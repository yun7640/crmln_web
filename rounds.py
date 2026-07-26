# -*- coding: utf-8 -*-
"""회차(반기) 측정결과 누적 저장소.
매 회차 업로드된 측정결과를 요약(summarize_round)해 서버에 회차별로 보관하고,
과거 이력(assets/history_seed.json)과 병합해 누적 경향·통계 분석 payload를 생성한다.

저장 위치: ROUNDS_FILE(기본 data/rounds.json). Railway 영구 저장은 Volume 마운트 권장.
민감(임상) 자료이므로 접근 권한 최소화 전제. export/import로 백업·복구 가능."""
import os, json, re, threading, datetime
import db

BASE = os.path.dirname(os.path.abspath(__file__))

# 소급(backfill) 정책 — 인수인계 §10 T1, 2026-07-26 사용자 확정
#   · 과거 측정 원본은 **참고용**으로만 누적한다(reference=True).
#   · 측정 시점이 불확실하면 **최근 3년**(올해 포함 3개 연도) 자료만 소급 적용한다.
#     시점이 문서로 확인된 경우에만(date_certain=True) 그 이전 연도도 허용한다.
BACKFILL_YEARS = 3
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
    s = str(label or '').strip()
    m = re.match(r'^(\d{4})\s*[.\-/]\s*(\d{1,2})', s)
    if not m:
        return s
    y = int(m.group(1)); mth = int(m.group(2))
    return '%d.%d' % (y, 7 if mth >= 7 else 1)


def label_year(label):
    """라벨에서 연도만 추출. 해석 불가면 None."""
    m = re.match(r'^(\d{4})', str(label or '').strip())
    return int(m.group(1)) if m else None


def min_backfill_year(today=None):
    """시점이 불확실할 때 허용하는 가장 오래된 연도(올해 포함 최근 BACKFILL_YEARS개 연도)."""
    y = (today or datetime.date.today()).year
    return y - (BACKFILL_YEARS - 1)


def year_guard(label, date_certain=False, today=None):
    """소급 라벨의 연도 허용 여부.

    측정 시점이 불확실하면(date_certain=False) 최근 3개 연도만 허용한다.
    문서로 시점이 확인된 경우에만 그 이전 연도를 허용하되, 호출부에서 사용자가
    명시적으로 확인 체크를 해야 한다(자동 추정만으로 통과시키지 않는다).
    반환: (ok, message)"""
    y = label_year(label)
    lo = min_backfill_year(today)
    if y is None:
        return False, "회차 라벨을 연도.반기 형식으로 입력하세요(예: 2025.1)."
    if y < lo and not date_certain:
        return False, ("측정 시점이 불확실한 자료는 최근 %d개 연도(%d년 이후)만 소급 적용합니다. "
                       "%d년 자료를 넣으려면 측정 시점이 문서로 확인되었음을 체크하십시오."
                       % (BACKFILL_YEARS, lo, y))
    if y > (today or datetime.date.today()).year:
        return False, "미래 연도(%d)는 저장할 수 없습니다." % y
    return True, ''


# ---------- 소급 누적(T1): 라벨 추정 ----------
# 자동 추정은 **참고 제시용**이다. 저장은 반드시 사용자가 라벨을 확인·확정해야 한다(§10 T1).
_LABEL_PATTERNS = [
    (re.compile(r'(20\d{2})\s*년\s*(0?[1-9]|1[0-2])\s*월'), 'ym'),
    (re.compile(r'(20\d{2})\s*[.\-_/]\s*(0?[1-9]|1[0-2])(?!\d)'), 'ym'),
    (re.compile(r'(20\d{2})\s*[.\-_/년]?\s*(상|하)\s*반기'), 'half'),
]


def _scan_labels(text, source, out, seen):
    if not text:
        return
    for pat, kind in _LABEL_PATTERNS:
        for m in pat.finditer(str(text)):
            y = int(m.group(1))
            if kind == 'half':
                mth = 1 if m.group(2) == '상' else 7
            else:
                mth = int(m.group(2))
            lab = canon_label('%d.%d' % (y, mth))
            key = (lab, source)
            if key in seen:
                continue
            seen.add(key)
            out.append({'label': lab, 'source': source, 'matched': m.group(0).strip()})


def infer_labels(filename='', sheetnames=None):
    """파일명·시트명에서 회차 라벨 후보를 추정한다.

    ⚠️ 추정 결과만으로 저장하지 않는다. 화면에 후보로 제시하고 사용자가 확정한다.
    반환: [{'label','source','matched'}] — 파일명 후보를 앞에 둔다."""
    out, seen = [], set()
    _scan_labels(filename, '파일명', out, seen)
    for sn in (sheetnames or []):
        _scan_labels(sn, "시트명 '%s'" % sn, out, seen)
    # 같은 라벨이 여러 곳에서 나오면 근거 수만큼 신뢰도를 올린다(표시용).
    tally = {}
    for c in out:
        tally[c['label']] = tally.get(c['label'], 0) + 1
    for c in out:
        c['n_sources'] = tally[c['label']]
    return out


def label_status(label):
    """저장 전 확인용 — 이 라벨이 이미 있는지, 시드에 있는지."""
    lab = canon_label(label)
    store = load_store()
    r = store.get(lab) or {}
    seed = load_seed()
    return {
        'label': lab,
        'exists': bool(r),
        'has_uc': bool(r.get('uc')),
        'has_dcm': bool(r.get('dcm')),
        'date': r.get('date', ''),
        'reference': bool(r.get('reference')),
        'in_seed': lab in (seed.get('surveys') or []),
        'known_labels': sorted(store, key=_key),
    }


# ---------- 소급 누적(T1): 시드 ↔ 소급계산 대조 ----------
# ⚠️ 어느 쪽도 덮어쓰지 않는다. 차이는 그대로 병기해 검토자가 판단한다(§0).
_SEED_DIFF_TOL = 0.005      # 시드 값이 소수 3자리로 반올림되어 있으므로 그보다 작은 차이는 동일 취급


def seed_compare(label, summary):
    """시드(assets/history_seed.json)에 이미 있는 값과 업로드 파일에서 소급 계산한 값을 비교.

    UC의 QC bias 트렌드 점(NIST/BF/HDL/LDL, %)은 같은 방식으로 산출되므로 직접 비교 가능하다.
    DCM의 공식 평가 bias(dcm_eval)는 **CDC 회신 값**이고 업로드 값은 내부 HDL Control bias라
    서로 다른 지표이므로 comparable=False로 두고 참고 표시만 한다."""
    lab = canon_label(label)
    seed = load_seed()
    rows = []
    if not isinstance(summary, dict):
        return {'label': lab, 'mode': None, 'rows': rows, 'n_diff': 0, 'in_seed': False}
    mode = summary.get('mode')
    if mode == 'uc':
        pt = _uc_trend_point(summary)
        for an in ('NIST', 'BF', 'HDL', 'LDL'):
            meta = (seed.get('qc_bias') or {}).get(an) or {}
            sv = (meta.get('points') or {}).get(lab)
            rv = pt.get(an)
            diff = None if (sv is None or rv is None) else round(rv - sv, 3)
            rows.append({'key': an, 'label': meta.get('label', an), 'unit': meta.get('unit', '%'),
                         'limit': meta.get('lim'), 'seed': sv, 'retro': rv, 'diff': diff,
                         'comparable': True,
                         'differs': bool(diff is not None and abs(diff) > _SEED_DIFF_TOL)})
    elif mode == 'dcm':
        ev = (seed.get('dcm_eval') or {}).get(lab) or {}
        rv = (summary.get('qc_bias') or {}).get('HDL_mgdl')
        rows.append({'key': 'DCM_HDL', 'label': 'HDL bias (공식 평가 vs 내부 HDL Control)',
                     'unit': 'mg/dL', 'limit': 1.0, 'seed': ev.get('bias'), 'retro': rv,
                     'diff': None, 'comparable': False, 'differs': False,
                     'note': '공식 DCM 평가 bias(CDC 회신)와 업로드 측정지의 내부 HDL Control bias는 '
                             '서로 다른 지표입니다. 차이를 계산하지 않고 참고로만 병기합니다.'})
    return {'label': lab, 'mode': mode, 'rows': rows,
            'n_diff': sum(1 for r in rows if r.get('differs')),
            'in_seed': lab in (seed.get('surveys') or [])}


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


def add_round(label, summary, user='', date='', reference=False, date_certain=False):
    """회차 라벨에 업로드 요약(mode=uc/dcm)을 병합 저장.

    reference=True 는 과거 자료 소급 누적(T1)을 뜻하며 **참고용** 표시가 함께 저장된다.
    소급인 경우 연도 제한(year_guard)을 적용한다."""
    label = canon_label(label)
    if not label:
        return False, '회차 라벨(예: 2026.7)을 입력하세요.'
    if not isinstance(summary, dict) or summary.get('mode') not in ('uc', 'dcm'):
        return False, '측정 요약을 해석하지 못했습니다.'
    if reference:
        ok, msg = year_guard(label, date_certain=date_certain)
        if not ok:
            return False, msg
    mode = summary['mode']
    summary = dict(summary)
    summary['reference'] = bool(reference)
    summary['date_certain'] = bool(date_certain)
    tag = ' (참고용 소급)' if reference else ''
    # Postgres 경로
    if db.configured():
        if db.rounds_upsert(label, mode, summary, date=date, user=user):
            return True, '%s 회차 %s 결과를 Postgres에 저장했습니다.%s' % (label, mode.upper(), tag)
        # 폴백(연결 실패): 파일 시도
    s = load_store()
    r = s.setdefault(label, {'label': label})
    if date:
        r['date'] = date
    r[mode] = summary
    if reference:
        r['reference'] = True
    r.setdefault('by', {})[mode] = user
    ok = _save(s)
    return ok, ('%s 회차 %s 결과를 저장했습니다.%s' % (label, mode.upper(), tag) if ok
                else '저장 실패 — Postgres(DATABASE_URL) 또는 Railway Volume(ROUNDS_FILE)이 필요합니다.')


def is_reference(r):
    """회차 레코드(또는 uc/dcm 요약)가 참고용 소급 자료인지."""
    if not isinstance(r, dict):
        return False
    if r.get('reference'):
        return True
    return any(isinstance(r.get(m), dict) and r[m].get('reference') for m in ('uc', 'dcm'))


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

    # 2) QC bias 트렌드
    #    ⚠️ 시드 값과 업로드(소급 계산) 값은 **서로 덮어쓰지 않는다**(§0: 유리한 값 선택 금지).
    #    points        = 시드 값 그대로 (과거 이력 원본)
    #    points_upload = 업로드/소급 계산 값 (별도 계열로 병기)
    #    conflicts     = 같은 회차에 두 값이 모두 있고 서로 다른 경우 목록
    qc_bias = {}
    for an, meta in seed.get('qc_bias', {}).items():
        qc_bias[an] = {'lim': meta['lim'], 'unit': meta['unit'], 'label': meta.get('label', an),
                       'points': dict(meta.get('points', {})),
                       'points_seed': dict(meta.get('points', {})),
                       'points_upload': {}}
    conflicts = []
    for label, r in store.items():
        uc = r.get('uc')
        if not uc:
            continue
        pt = _uc_trend_point(uc)
        for an, val in pt.items():
            if an not in qc_bias or val is None:
                continue
            qc_bias[an]['points_upload'][label] = val
            sv = qc_bias[an]['points_seed'].get(label)
            if sv is None:
                # 시드에 없는 회차 → 병기 충돌 아님. 경향선이 끊기지 않도록 points에도 채운다.
                qc_bias[an]['points'][label] = val
            elif abs(val - sv) > _SEED_DIFF_TOL:
                conflicts.append({'label': label, 'analyte': an,
                                  'analyte_label': qc_bias[an]['label'],
                                  'unit': qc_bias[an]['unit'], 'limit': qc_bias[an]['lim'],
                                  'seed': sv, 'upload': round(val, 3),
                                  'diff': round(val - sv, 3),
                                  'reference': is_reference(r)})
    conflicts.sort(key=lambda c: (_key(c['label']), c['analyte']))

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
    reference_labels = []
    for label in sorted(store, key=_key):
        r = store[label]
        ref = is_reference(r)
        if ref:
            reference_labels.append(label)
        uploaded[label] = {'label': label, 'date': r.get('date', ''),
                           'uc': r.get('uc'), 'dcm': r.get('dcm'), 'reference': ref}

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
        'reference_labels': reference_labels,
        'conflicts': conflicts,
        'backfill': {'min_year': min_backfill_year(), 'years': BACKFILL_YEARS},
        'note_seed': ('시드(과거 이력)와 업로드 소급 계산 값은 서로 덮어쓰지 않고 병기합니다. '
                      '차이가 있으면 아래 대조표에 그대로 표시되며, 어느 쪽도 자동으로 채택하지 않습니다.'),
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
