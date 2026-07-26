# -*- coding: utf-8 -*-
"""회차(반기) 측정결과 누적 저장소.
매 회차 업로드된 측정결과를 요약(summarize_round)해 서버에 회차별로 보관하고,
과거 이력(assets/history_seed.json)과 병합해 누적 경향·통계 분석 payload를 생성한다.

저장 위치: ROUNDS_FILE(기본 data/rounds.json). Railway 영구 저장은 Volume 마운트 권장.
민감(임상) 자료이므로 접근 권한 최소화 전제. export/import로 백업·복구 가능."""
import os, json, threading
import db

BASE = os.path.dirname(os.path.abspath(__file__))
ROUNDS_FILE = os.environ.get('ROUNDS_FILE', os.path.join(BASE, 'data', 'rounds.json'))
SEED_FILE = os.path.join(BASE, 'assets', 'history_seed.json')
_lock = threading.RLock()

# 회차 라벨 정렬용: "2026.7" → 2026.35 (7월=하반기)
def _key(label):
    try:
        y, h = str(label).replace('-', '.').split('.')[:2]
        y = int(y); h = int(''.join(ch for ch in h if ch.isdigit()) or '0')
        return (y, 7 if h >= 7 else (h if h > 1 else 1))
    except Exception:
        return (9999, 9)


def canon_label(label):
    """회차 라벨을 반기 표준(YYYY.1=상반기, YYYY.7=하반기)으로 정규화.
    예: '2026-07','2026.07','2026-07-01','2026.7' → '2026.7'; '2026-01' → '2026.1'.
    형식을 알 수 없으면 공백만 정리해 원문 유지."""
    import re
    s = str(label or '').strip()
    m = re.match(r'^(\d{4})\s*[.\-/]\s*(\d{1,2})', s)
    if not m:
        return s
    y = int(m.group(1)); mth = int(m.group(2))
    return '%d.%d' % (y, 7 if mth >= 7 else 1)


def load_seed():
    try:
        with open(SEED_FILE, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {'surveys': [], 'criteria': {}, 'qc_bias': {}, 'ps_eval': {}, 'dcm_eval': {}}


def _write(store):
    try:
        d = os.path.dirname(ROUNDS_FILE)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(ROUNDS_FILE, 'w', encoding='utf-8') as f:
            json.dump(store, f, ensure_ascii=False, indent=1)
        return True
    except Exception:
        return False


def backend():
    """현재 저장 백엔드: 'postgres' | 'file'."""
    return 'postgres' if (db.configured() and db.available()) else 'file'


def persistent():
    if db.configured():
        return db.available()
    return os.path.exists(ROUNDS_FILE) or bool(os.environ.get('ROUNDS_FILE'))


def load_store():
    """업로드 회차 저장소 {label: {'label','date','uc':{...},'dcm':{...},'by':user}}."""
    if db.configured():
        d = db.rounds_load()
        if d is not None:
            return d
    with _lock:
        if os.path.exists(ROUNDS_FILE):
            try:
                with open(ROUNDS_FILE, encoding='utf-8') as f:
                    d = json.load(f)
                    if isinstance(d, dict):
                        return d.get('rounds', d) if 'rounds' in d else d
            except Exception:
                pass
        return {}


def _save(store):
    with _lock:
        return _write({'version': 1, 'rounds': store})


def add_round(label, summary, user='', date=''):
    """회차 라벨에 업로드 요약(mode=uc/dcm)을 병합 저장."""
    label = canon_label(label)
    if not label:
        return False, '회차 라벨(예: 2026.7)을 입력하세요.'
    if not isinstance(summary, dict) or summary.get('mode') not in ('uc', 'dcm'):
        return False, '측정 요약을 해석하지 못했습니다.'
    mode = summary['mode']
    # Postgres 경로
    if db.configured():
        if db.rounds_upsert(label, mode, summary, date=date, user=user):
            return True, '%s 회차 %s 결과를 Postgres에 저장했습니다.' % (label, mode.upper())
        # 폴백(연결 실패): 파일 시도
    s = load_store()
    r = s.setdefault(label, {'label': label})
    if date:
        r['date'] = date
    r[mode] = summary
    r.setdefault('by', {})[mode] = user
    ok = _save(s)
    return ok, ('%s 회차 %s 결과를 저장했습니다.' % (label, mode.upper()) if ok
                else '저장 실패 — Postgres(DATABASE_URL) 또는 Railway Volume(ROUNDS_FILE)이 필요합니다.')


def delete_round(label, mode=None):
    if db.configured():
        if db.rounds_delete(label, mode):
            return True, '삭제되었습니다.'
    s = load_store()
    if label not in s:
        return False, '없는 회차.'
    if mode and mode in s[label]:
        del s[label][mode]
        if not (s[label].get('uc') or s[label].get('dcm')):
            del s[label]
    else:
        del s[label]
    ok = _save(s)
    return ok, ('삭제되었습니다.' if ok else '저장 실패.')


def list_rounds():
    s = load_store()
    out = []
    for label in sorted(s, key=_key):
        r = s[label]
        out.append({'label': label, 'date': r.get('date', ''),
                    'has_uc': bool(r.get('uc')), 'has_dcm': bool(r.get('dcm'))})
    return out


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


def _uc_trend_point(uc):
    """UC 회차 → 트렌드 점(NIST/BF/HDL/LDL, % bias)."""
    qc = uc.get('qc', [])
    return {
        'NIST': _mean([q['biaspct'] for q in qc if q['analyte'] == 'TC']),
        'BF': _mean([q['biaspct'] for q in qc if q['analyte'] == 'BF']),
        'HDL': _mean([q['biaspct'] for q in qc if q['analyte'] == 'HDL']),
        'LDL': _mean([q['biaspct'] for q in qc if q['analyte'] == 'LDL']),
    }


def dashboard_payload():
    """과거 시드 + 업로드 회차를 병합한 누적 대시보드용 payload."""
    seed = load_seed()
    store = load_store()

    # 1) 설문(회차) 축: 시드 + 업로드 라벨
    surveys = list(seed.get('surveys', []))
    for label in sorted(store, key=_key):
        if label not in surveys:
            surveys.append(label)
    surveys = sorted(set(surveys), key=_key)

    # 2) QC bias 트렌드: 시드 점 + 업로드 UC 회차 점
    qc_bias = {}
    for an, meta in seed.get('qc_bias', {}).items():
        qc_bias[an] = {'lim': meta['lim'], 'unit': meta['unit'], 'label': meta.get('label', an),
                       'points': dict(meta.get('points', {}))}
    for label, r in store.items():
        uc = r.get('uc')
        if not uc:
            continue
        pt = _uc_trend_point(uc)
        for an, val in pt.items():
            if an in qc_bias and val is not None:
                qc_bias[an]['points'][label] = val

    # 3) DCM QC HDL Control bias 트렌드(업로드 DCM 회차; mg/dL)
    dcm_qc = {}
    for label, r in store.items():
        dcm = r.get('dcm')
        if not dcm:
            continue
        b = dcm.get('qc_bias', {}).get('HDL_mgdl')
        if b is not None:
            dcm_qc[label] = b

    # 4) 업로드 회차 상세(제출 선택표·QC 판정)
    uploaded = {}
    for label in sorted(store, key=_key):
        r = store[label]
        uploaded[label] = {'label': label, 'date': r.get('date', ''),
                           'uc': r.get('uc'), 'dcm': r.get('dcm')}

    return {
        'surveys': surveys,
        'seed_surveys': seed.get('surveys', []),
        'criteria': seed.get('criteria', {}),
        'qc_bias': qc_bias,
        'ps_eval': seed.get('ps_eval', {}),
        'dcm_eval': seed.get('dcm_eval', {}),
        'dcm_qc_upload': dcm_qc,
        'uploaded': uploaded,
        'round_labels': sorted(store, key=_key),
    }


def export_json():
    return json.dumps({'version': 1, 'rounds': load_store()}, ensure_ascii=False)


def import_json(raw):
    try:
        d = json.loads(raw)
        rounds = d.get('rounds', d) if isinstance(d, dict) else {}
        if not isinstance(rounds, dict):
            return False, 'JSON 형식이 올바르지 않습니다.'
        if db.configured() and db.available():
            n = 0
            for label, r in rounds.items():
                date = r.get('date', '') if isinstance(r, dict) else ''
                by = r.get('by', {}) if isinstance(r, dict) else {}
                for mode in ('uc', 'dcm'):
                    if isinstance(r, dict) and r.get(mode):
                        db.rounds_upsert(label, mode, r[mode], date=date,
                                         user=(by.get(mode, '') if isinstance(by, dict) else ''))
                        n += 1
            return True, '%d개 회차(모드)를 Postgres로 가져왔습니다.' % n
        cur = load_store()
        cur.update(rounds)
        ok = _save(cur)
        return ok, ('%d개 회차를 가져왔습니다.' % len(rounds) if ok else '저장 실패.')
    except Exception as e:
        return False, '가져오기 실패: %s' % e
