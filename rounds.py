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


# ── 누적 추이 분석 컷오프 (★ 모드별로 다르다) ─────────────────────────
# 사용자 확정(2026-07-28, 2026-07-28 재확정):
#   · **HDLC-DCM** — 누적 추이는 **2025.7 회차부터**.
#     2025년 6월 이전 DCM 측정지는 구조가 다르다(순도보정 블록이 원자료와 별도로 쌓임,
#     NS01·NS02 검체 추가, Day1/Day2가 별도 파일, 반복 3개). 서로 다른 구조의 값을
#     한 추세선에 이으면 방법이 다른 값을 잇는 셈이 된다 → §0 위반.
#   · **HDLC-UC(BF·LDL-C·HDL-C)** — **컷오프 없음. 2023.1부터 전 회차 누적.**
#     ★ 위 구조 차이는 DCM 측정지에만 해당한다. UC는 형식이 이어져 있으므로 자르지 않는다.
#       (v19에서 UC까지 함께 잘랐던 것은 과적용이었고 v20에서 되돌렸다.)
#   ⇒ 컷오프가 적용되는 쪽도 **삭제하지 않고 분리 보관**해 '참고(구 형식)'으로 표시한다.
CUM_START_DCM = '2025.7'
CUM_START_UC = None            # None = 컷오프 없음(전 회차 누적)
CUM_START = CUM_START_DCM      # 하위 호환(구 이름). 기본은 DCM 기준이다.
CUM_NOTE = ('HDLC-DCM 누적 추이는 %s 회차부터 표시합니다. 이전 회차는 DCM 측정지 구조가 달라 '
            '동일한 추세선에 올리지 않으며, 삭제하지 않고 참고용으로 분리해 보관합니다. '
            'HDLC-UC(BF·LDL-C·HDL-C)는 컷오프 없이 전 회차를 누적합니다.')


def cum_start_for(mode='dcm'):
    """모드별 누적 시작 회차. UC는 None(전 회차), DCM은 '2025.7'."""
    return CUM_START_UC if str(mode or '').lower() == 'uc' else CUM_START_DCM


def in_cumulative(label, start=None, mode='dcm'):
    """누적 추이 분석에 포함할 회차인지 판정.

    ★ mode를 반드시 넘길 것 — UC는 컷오프가 없고 DCM만 2025.7~이다.
      (기본값이 'dcm'인 이유: 컷오프가 있는 쪽을 기본으로 두어 실수로 과거 DCM이 섞이지 않게 한다)
    start를 직접 주면 모드보다 우선한다."""
    s = start if start is not None else cum_start_for(mode)
    if not s:
        return True
    return _key(canon_label(label)) >= _key(s)


def split_by_cutoff(labels, start=None, mode='dcm'):
    """라벨 목록을 (누적 대상, 참고=컷오프 이전)으로 나눈다. 양쪽 다 회차순 정렬."""
    cum, legacy = [], []
    for lab in sorted({str(l) for l in (labels or [])}, key=_key):
        (cum if in_cumulative(lab, start, mode) else legacy).append(lab)
    return cum, legacy


def split_map_by_cutoff(mapping, start=None, mode='dcm'):
    """{라벨: 값} 딕셔너리를 (누적 대상, 참고) 두 딕셔너리로 나눈다."""
    cum, legacy = {}, {}
    for lab, val in (mapping or {}).items():
        (cum if in_cumulative(lab, start, mode) else legacy)[lab] = val
    return cum, legacy


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


# ── CRMLN 제출 결과 선택 기준(수기 기록) ─────────────────────────────
# 사용자 확정(2026-07-28): 제출에 쓸 반복(replicate) 선택은 **매 회차 사람이 수기로 결정**한다.
# 그 결정을 회차별로 남겨 **다음 회차 선택 시 참고**한다(⑦탭).
#
# ★ 이 기록은 '무엇을 골랐는지'에 대한 **기록일 뿐** 자동 채택 로직이 아니다(§0).
#   서버의 `_dcm_pick`/`combo_pick`은 이 값을 읽지 않으며, 여기 저장된 값 때문에
#   검토 결과가 달라지지 않는다. 화면에서 알고리즘 채택값과 **병기**해 보여 준다.
#
# 저장 위치: app_rounds 테이블의 **의사 모드 `'selection'`** 행 (스키마 변경 없음).
#   data = {'uc': {...}, 'dcm': {...}} 형태로 두 모드를 한 행에 담는다.
SEL_MODE = 'selection'
SEL_REPS = ('R1', 'R2', 'R3', 'R4')
SEL_KEEP_N = 2                      # CRMLN 제출은 채택 2반복(§4)
SEL_DAYS = ('1', '2')

# ── 이상치 판정 기준(선택 옵션) ──────────────────────────────────────
# ★ 화면 ①탭(`#selCrit`, UC)·④탭(`#dcmSelCrit`, DCM) 드롭다운과 **같은 목록**이어야 한다.
#   여기가 정본이고 ⑦탭은 이 목록으로 드롭다운을 만든다.
#   ①·④탭은 인라인 <option>으로 갖고 있으므로, 값이 어긋나면 스모크가 잡는다.
# (value, 표시 문구, 그룹, 민감도 여부)
#   민감도(방향성) 옵션은 **결과를 유리하게 만들 수 있는 what-if 분석용**이다.
#   기본값이 아니며, 기록에 남으면 화면에 경고를 띄운다(§0).
SEL_CRITERIA = {
    'uc': [
        ('combo',    '종합 (BF+HDL 상대편차) · 균형 [기본]', '정밀도 기준 (권장)', False),
        ('LDL',      'LDL 결과 우선 (LDL 편차 최소)',        '정밀도 기준 (권장)', False),
        ('BF',       'BF(하부분획) 우선',                    '정밀도 기준 (권장)', False),
        ('HDL',      'HDL 우선',                             '정밀도 기준 (권장)', False),
        ('combo3',   '3항목 종합 (BF+HDL+LDL)',              '정밀도 기준 (권장)', False),
        ('minpair',  '최소분산 쌍 (가장 근접 2개 채택)',      '정밀도 기준 (권장)', False),
        ('hdl_high', 'HDL 높은값 우선 (상위 2개 채택)', '방향성 (민감도 분석 · what-if)', True),
        ('hdl_low',  'HDL 낮은값 우선 (하위 2개 채택)', '방향성 (민감도 분석 · what-if)', True),
        ('bf_high',  'BF 높은값 우선 (상위 2개 채택)',  '방향성 (민감도 분석 · what-if)', True),
        ('bf_low',   'BF 낮은값 우선 (하위 2개 채택)',  '방향성 (민감도 분석 · what-if)', True),
    ],
    'dcm': [
        ('median',   '정밀도(median 이상치 제외) [기본]', '정밀도 기준 (권장)', False),
        ('minpair',  '최소분산쌍 (민감도)',               '방향성 (민감도 분석)', True),
        ('hdl_high', 'HDL 높은값 우선 (민감도)',          '방향성 (민감도 분석)', True),
        ('hdl_low',  'HDL 낮은값 우선 (민감도)',          '방향성 (민감도 분석)', True),
    ],
}
SEL_DEFAULT_CRIT = {'uc': 'combo', 'dcm': 'median'}


def criteria_for(mode):
    """모드별 선택 기준 목록 → [{value, label, group, sensitivity}]."""
    return [{'value': v, 'label': t, 'group': g, 'sensitivity': s}
            for v, t, g, s in SEL_CRITERIA.get(str(mode or '').lower(), [])]


def criterion_label(mode, value):
    for v, t, _g, _s in SEL_CRITERIA.get(str(mode or '').lower(), []):
        if v == value:
            return t
    return value or ''


def is_sensitivity(mode, value):
    """민감도(방향성) 옵션인지 — 기록에 남으면 화면에 경고를 띄운다(§0)."""
    for v, _t, _g, s in SEL_CRITERIA.get(str(mode or '').lower(), []):
        if v == value:
            return bool(s)
    return False


def validate_selection(sel):
    """수기 선택 입력 검증. 반환 (ok, 정규화된 dict 또는 오류 메시지).

    형식: {검체: {Day: {'keep': ['R1','R3'], 'note': '...'}}}
    ★ 채택은 반드시 **정확히 2개**여야 한다 — 제출 규칙이 2반복이므로,
      1개나 3개가 저장되면 다음 회차 참고 자료로서 의미가 없다."""
    if not isinstance(sel, dict):
        return False, '선택 내용을 해석하지 못했습니다.'
    out = {}
    for sample, per_day in sel.items():
        name = str(sample).strip().upper().replace(' ', '')
        if not name or not isinstance(per_day, dict):
            continue
        block = {}
        for day, v in per_day.items():
            d = str(day).strip().lstrip('Dd').lstrip('ay').strip() or str(day)
            d = ''.join(ch for ch in str(day) if ch.isdigit()) or str(day)
            if d not in SEL_DAYS:
                return False, "Day는 1 또는 2여야 합니다(입력: %s)." % day
            v = v or {}
            keep = [str(x).strip().upper() for x in (v.get('keep') or []) if str(x).strip()]
            note = str(v.get('note') or '').strip()
            if not keep and not note:
                continue                      # 빈 칸은 저장하지 않음
            bad = [k for k in keep if k not in SEL_REPS]
            if bad:
                return False, '채택 반복은 R1–R4만 가능합니다(입력: %s).' % ', '.join(bad)
            if len(set(keep)) != len(keep):
                return False, '%s Day%s: 같은 반복을 중복 선택했습니다.' % (name, d)
            if keep and len(keep) != SEL_KEEP_N:
                return False, ('%s Day%s: 채택은 정확히 %d개여야 합니다(현재 %d개).'
                               % (name, d, SEL_KEEP_N, len(keep)))
            block[d] = {'keep': sorted(keep, key=lambda x: SEL_REPS.index(x)), 'note': note}
        if block:
            out[name] = block
    return True, out


def save_selection(label, mode, sel, user='', note='', criterion=''):
    """회차·모드별 수기 선택을 저장(덮어쓰기). 반환 (ok, 메시지).

    criterion = 이상치 판정 기준(①·④탭 드롭다운과 같은 값). 비우면 모드 기본값."""
    label = canon_label(label)
    if not label:
        return False, '회차 라벨(예: 2026.7)을 입력하세요.'
    mode = str(mode or '').lower()
    if mode not in ('uc', 'dcm'):
        return False, '모드는 uc 또는 dcm이어야 합니다.'
    crit = str(criterion or '').strip() or SEL_DEFAULT_CRIT[mode]
    if crit not in [c['value'] for c in criteria_for(mode)]:
        return False, ('선택 기준 값이 올바르지 않습니다: %s (%s 목록에 없음)'
                       % (crit, mode.upper()))
    ok, res = validate_selection(sel)
    if not ok:
        return False, res
    rec = {'samples': res, 'note': str(note or '').strip(), 'by': user,
           'criterion': crit, 'criterion_label': criterion_label(mode, crit),
           'sensitivity': is_sensitivity(mode, crit),
           'saved_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}
    cur = load_selections().get(label) or {}
    cur = {k: v for k, v in cur.items() if k in ('uc', 'dcm')}
    cur[mode] = rec
    if db.configured():
        if db.rounds_upsert(label, SEL_MODE, cur, date='', user=user):
            return True, '%s 회차 %s 선택 기준을 저장했습니다.' % (label, mode.upper())
    s = load_store()
    r = s.setdefault(label, {'label': label})
    r[SEL_MODE] = cur
    if _save(s):
        return True, '%s 회차 %s 선택 기준을 저장했습니다.' % (label, mode.upper())
    return False, '저장 실패 — Postgres(DATABASE_URL) 또는 Volume(ROUNDS_FILE)이 필요합니다.'


def load_selections():
    """{label: {'uc': {...}, 'dcm': {...}}} — 저장된 수기 선택 전체."""
    out = {}
    for label, r in (load_store() or {}).items():
        sel = (r or {}).get(SEL_MODE)
        if isinstance(sel, dict) and sel:
            out[label] = {k: v for k, v in sel.items() if k in ('uc', 'dcm')}
    return out


def selection_payload():
    """⑦탭 payload — 수기 선택 이력 + 직전 회차(참고 대상) 안내."""
    sels = load_selections()
    labels = sorted(sels, key=_key)
    store = load_store() or {}
    # 화면에서 '알고리즘 채택값'과 병기할 수 있도록 회차별 계산 결과도 함께 넘긴다.
    computed = {}
    for label, r in store.items():
        per = {}
        for mode in ('uc', 'dcm'):
            s = (r or {}).get(mode)
            if isinstance(s, dict) and s.get('samples'):
                per[mode] = s['samples']
        if per:
            computed[label] = per
    return {
        'labels': labels,
        'selections': sels,
        'computed': computed,
        'all_labels': sorted(set(list(store) + labels), key=_key),
        'reps': list(SEL_REPS),
        'keep_n': SEL_KEEP_N,
        'criteria': {'uc': criteria_for('uc'), 'dcm': criteria_for('dcm')},
        'criteria_default': dict(SEL_DEFAULT_CRIT),
        'note': ('이 표는 매 회차 사람이 수기로 결정한 제출 선택을 남긴 기록입니다. '
                 '다음 회차 선택 시 참고용이며, 서버의 채택 로직은 이 값을 읽지 않습니다. '
                 '최종 제출·판정은 CDC 참조법 회신 및 검토자 확인 후 확정합니다.'),
        'note_sensitivity': ('방향성(민감도) 기준은 what-if 분석용입니다. '
                             '결과를 유리하게 만들기 위한 선택은 지양하며(§0), '
                             '기록에 남은 경우 화면에 경고가 표시됩니다.'),
    }


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
                       'points_upload': {},
                       'points_cum': {}, 'points_legacy': {}}
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
    # 컷오프 분리 — 값은 그대로 두고 '누적 대상'과 '참고(구 형식)'로만 나눈다(§0: 삭제하지 않음).
    # ★ qc_bias(NIST·BF·HDL·LDL)는 **UC 계열**이므로 컷오프가 없다 → points_cum = 전 회차.
    for an in qc_bias:
        cum, legacy = split_map_by_cutoff(qc_bias[an]['points'], mode='uc')
        qc_bias[an]['points_cum'] = cum
        qc_bias[an]['points_legacy'] = legacy

    # 3) DCM QC HDL Control bias 트렌드(mg/dL)
    #    시드(측정지에서 확정한 과거 회차) + 업로드 회차. 시드는 별도로도 보존해 병기한다(§0).
    dcm_qc_seed = {}
    for label, meta in (seed.get('dcm_qc') or {}).items():
        v = (meta or {}).get('HDL_mgdl')
        if v is not None:
            dcm_qc_seed[label] = v
    dcm_qc = dict(dcm_qc_seed)
    dcm_qc_upload_only = {}
    for label, r in store.items():
        dcm = r.get('dcm')
        if not dcm:
            continue
        b = dcm.get('qc_bias', {}).get('HDL_mgdl')
        if b is not None:
            dcm_qc_upload_only[label] = b
            dcm_qc[label] = b       # 업로드가 있으면 최신 측정으로 갱신(시드는 아래에 그대로 보존)

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

    # ★ 모드별 컷오프 — UC는 전 회차, DCM만 2025.7~.
    surveys_uc, _ = split_by_cutoff(surveys, mode='uc')            # = 전 회차
    surveys_cum, surveys_legacy = split_by_cutoff(surveys, mode='dcm')
    ps_cum, ps_legacy = split_map_by_cutoff(seed.get('ps_eval', {}), mode='uc')      # PS 평가 = UC 계열
    dcm_ev_cum, dcm_ev_legacy = split_map_by_cutoff(seed.get('dcm_eval', {}), mode='dcm')
    dcm_qc_cum, dcm_qc_legacy = split_map_by_cutoff(dcm_qc, mode='dcm')

    return {
        'surveys': surveys,
        'seed_surveys': seed.get('surveys', []),
        'criteria': seed.get('criteria', {}),
        'qc_bias': qc_bias,
        'ps_eval': seed.get('ps_eval', {}),
        'dcm_eval': seed.get('dcm_eval', {}),
        'dcm_qc_upload': dcm_qc,
        'dcm_qc_seed': dcm_qc_seed,
        'dcm_qc_upload_only': dcm_qc_upload_only,
        'uploaded': uploaded,
        'round_labels': sorted(store, key=_key),
        'reference_labels': reference_labels,
        'conflicts': conflicts,
        'backfill': {'min_year': min_backfill_year(), 'years': BACKFILL_YEARS},
        # ── 누적 컷오프 (★ 모드별) ────────────────────────────────────
        # 값 자체는 위 계열에 그대로 남아 있고, 아래는 **표시 분리용** 이다.
        #   UC(BF·LDL·HDL, PS 평가) → 컷오프 없음(2023.1~ 전 회차)
        #   DCM                      → 2025.7~
        'cum_start': CUM_START_DCM,          # 하위 호환(구 소비처는 DCM 기준으로 읽었다)
        'cum_start_dcm': CUM_START_DCM,
        'cum_start_uc': CUM_START_UC,
        'cum_note': CUM_NOTE % CUM_START_DCM,
        'surveys_uc': surveys_uc,            # UC 그래프 축 = 전 회차
        'surveys_cum': surveys_cum,          # DCM 그래프 축 = 2025.7~
        'surveys_cum_dcm': surveys_cum,
        'surveys_legacy': surveys_legacy,
        'surveys_legacy_dcm': surveys_legacy,
        'ps_eval_cum': ps_cum, 'ps_eval_legacy': ps_legacy,
        'dcm_eval_cum': dcm_ev_cum, 'dcm_eval_legacy': dcm_ev_legacy,
        'dcm_qc_cum': dcm_qc_cum, 'dcm_qc_legacy': dcm_qc_legacy,
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
