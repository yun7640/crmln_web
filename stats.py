# -*- coding: utf-8 -*-
"""회차 누적 데이터(app_rounds.data JSONB / 파일 폴백) 기반 추가 통계.

⚠️ 방법론 원칙 (인수인계 §0)
    여기서 계산하는 값은 **모니터링·진단용**입니다.
    반복측정(R1/R2/R3) 중 무엇을 채택할지는 이미 review_engine의 정밀도/QC 기반 로직
    (median 이상치 1개 제외)으로만 결정되며, 이 모듈은 그 결정에 관여하지 않습니다.
    **어떤 통계값도 판정을 통과시키기 위한 선택 근거로 사용해서는 안 됩니다.**
    최종 제출·판정은 CDC 참조법 회신 및 검토자 확인 후 확정합니다.

계산 항목
  1) bias_summary   회차·분석물질별 QC/Control bias 평균·SD·한계 대비 마진
  2) precision      검체 반복측정 정밀도 — 채택 2개의 CV, Day1/Day2 차이(재현성)
  3) drift          회차에 대한 bias 선형 추세(최소제곱 기울기) — 지속적 이동 감지
  4) drop_pattern   median 이상치로 제외된 반복 index(R1/R2/R3) 분포 — 계통 오류 탐지
  5) margin         |bias| / 허용한계 비율 분포 — 한계에 얼마나 근접했는지

저장 백엔드(Postgres/파일)와 무관하게 rounds.load_store()에서 읽으므로 둘 다 동작합니다.
Postgres에서 직접 임시 분석하려면 tools/stats_queries.sql 참조.
"""
import rounds

# CRMLN member 허용 한계 (review_engine.MEMBER와 동일 기준)
LIMITS = {
    'TC': (1.0, '%'),
    'BF': (2.0, '%'),
    'LDL': (2.0, '%'),
    'HDL': (1.0, 'mg/dL'),   # HDL은 mg/dL 절대값 기준
}


def _mean(v):
    v = [x for x in v if x is not None]
    return sum(v) / len(v) if v else None


def _sd(v):
    """표본표준편차(n-1). 값이 2개 미만이면 None."""
    v = [x for x in v if x is not None]
    if len(v) < 2:
        return None
    m = sum(v) / len(v)
    return (sum((x - m) ** 2 for x in v) / (len(v) - 1)) ** 0.5


def _r(x, n=3):
    return None if x is None else round(x, n)


def _bias_value(q):
    """분석물질별 판정에 쓰는 bias 값과 단위를 고른다(HDL은 mg/dL)."""
    an = q.get('analyte')
    if an == 'HDL':
        return q.get('biasmgdl'), 'mg/dL'
    return q.get('biaspct'), '%'


# ---------- 1) 회차·분석물질별 bias 요약 ----------
def bias_summary(store):
    """{label: {mode: {analyte: {n, mean, sd, min, max, limit, unit, margin, exceed}}}}

    margin = |mean| / limit  (1.0을 넘으면 한계 초과)
    """
    out = {}
    for label in sorted(store, key=rounds._key):
        r = store[label]
        for mode in ('uc', 'dcm'):
            s = r.get(mode)
            if not s:
                continue
            per = {}
            for q in s.get('qc', []):
                an = q.get('analyte')
                if an not in LIMITS:
                    continue
                val, unit = _bias_value(q)
                if val is None:
                    continue
                per.setdefault(an, []).append(val)
            block = {}
            for an, vals in per.items():
                lim, unit = LIMITS[an]
                m = _mean(vals)
                block[an] = {
                    'n': len(vals),
                    'mean': _r(m),
                    'sd': _r(_sd(vals)),
                    'min': _r(min(vals)),
                    'max': _r(max(vals)),
                    'limit': lim,
                    'unit': unit,
                    'margin': _r(abs(m) / lim, 3) if m is not None and lim else None,
                    'exceed': bool(m is not None and abs(m) > lim),
                }
            if block:
                for b in block.values():
                    b['reference'] = bool(s.get('reference'))
                out.setdefault(label, {})[mode] = block
    return out


# ---------- 2) 검체 반복측정 정밀도 ----------
def precision(store):
    """회차별 정밀도 요약.

    within_cv : 채택된 2개 반복의 CV(%) — review_engine이 이미 계산해 저장한 값
    day_diff  : 같은 검체의 Day1 vs Day2 채택값 차이(절대값, mg/dL) — 재현성 지표
    """
    out = {}
    for label in sorted(store, key=rounds._key):
        r = store[label]
        for mode in ('uc', 'dcm'):
            s = r.get(mode)
            if not s:
                continue
            cvs, per_sample = [], {}
            for smp in s.get('samples', []):
                cv = smp.get('cv') if mode == 'dcm' else smp.get('cvL')
                if cv is not None:
                    cvs.append(cv)
                hdl = smp.get('HDL')
                if hdl is not None:
                    per_sample.setdefault(smp.get('name'), {})[smp.get('day')] = hdl
            diffs = []
            for nm, days in per_sample.items():
                if 1 in days and 2 in days:
                    diffs.append(abs(days[1] - days[2]))
            block = {
                'n_cv': len(cvs),
                'within_cv_mean': _r(_mean(cvs)),
                'within_cv_max': _r(max(cvs)) if cvs else None,
                'n_pairs': len(diffs),
                'day_diff_mean': _r(_mean(diffs)),
                'day_diff_max': _r(max(diffs)) if diffs else None,
                'reference': bool(s.get('reference')),
            }
            out.setdefault(label, {})[mode] = block
    return out


# ---------- 3) 회차에 대한 bias 드리프트 ----------
def _slope(xs, ys):
    """최소제곱 기울기. 점이 3개 미만이면 None(추세 판단 불가)."""
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den


def drift(store):
    """모드(UC/DCM)·분석물질별 '회차당 bias 변화량' 기울기.

    ★ UC와 DCM은 서로 다른 측정절차이므로 **절대 합치지 않는다.**
      (같은 HDL이라도 UC의 β-정량 HDL과 DCM의 HDL은 다른 값이다)
    ★ 참고용 소급 자료(reference=True)는 **추세 계산에서 제외한다.**
      과거 자료는 참고용이며 측정 시점·조건 확인이 불완전할 수 있어 추세 판단 근거로 쓰지 않는다
      (인수인계 §10 T1, 사용자 확정 사항). 제외 후 회차가 3개 미만이면 slope=None.
    x축은 회차 순서(0,1,2…). 회차 3개 미만이면 slope=None으로 두고 추세를 판단하지 않는다.
    |slope| 가 허용한계의 25%/회차를 넘으면 flag — **임의 임계값이며 경고용일 뿐 판정 기준이 아니다.**
    """
    series = {}   # {mode: {analyte: {label: mean_bias}}}
    excluded = []
    for label in sorted(store, key=rounds._key):
        r = store[label]
        for mode in ('uc', 'dcm'):
            s = r.get(mode)
            if not s:
                continue
            if s.get('reference') or r.get('reference'):
                excluded.append('%s/%s' % (label, mode.upper()))
                continue
            per = {}
            for q in s.get('qc', []):
                an = q.get('analyte')
                if an not in LIMITS:
                    continue
                val, _u = _bias_value(q)
                if val is not None:
                    per.setdefault(an, []).append(val)
            for an, vals in per.items():
                m = _mean(vals)
                if m is not None:
                    series.setdefault(mode, {}).setdefault(an, {})[label] = m

    out = {}
    for mode, per_an in series.items():
        for an, by_label in per_an.items():
            labels = sorted(by_label, key=rounds._key)
            ys = [by_label[l] for l in labels]
            lim, unit = LIMITS[an]
            sl = _slope(list(range(len(labels))), ys)
            out.setdefault(mode, {})[an] = {
                'labels': labels,
                'values': [_r(v) for v in ys],
                'n': len(labels),
                'slope_per_round': _r(sl),
                'limit': lim,
                'unit': unit,
                'flag': bool(sl is not None and abs(sl) > 0.25 * lim),
            }
    if excluded:
        out['_excluded_reference'] = sorted(set(excluded))
    return out


# ---------- 4) 제외된 반복 index 분포 ----------
def drop_pattern(store):
    """median 이상치로 제외된 반복 index(R1/R2/R3) 빈도.

    특정 index가 유독 자주 제외되면 측정 순서·장비 안정화 등 **계통 오류**를 의심할 근거가 된다.
    (채택 로직 자체는 바꾸지 않는다 — 진단 정보일 뿐)
    """
    counts = {1: 0, 2: 0, 3: 0}
    total = 0
    per_round = {}
    for label in sorted(store, key=rounds._key):
        r = store[label]
        local = {1: 0, 2: 0, 3: 0}
        for mode in ('uc', 'dcm'):
            s = r.get(mode)
            if not s:
                continue
            for smp in s.get('samples', []):
                d = smp.get('drop')
                if d in (1, 2, 3):
                    counts[d] += 1
                    local[d] += 1
                    total += 1
        if sum(local.values()):
            per_round[label] = {'R%d' % k: v for k, v in local.items()}
    expected = total / 3.0 if total else 0
    skew = None
    if total >= 9:  # 표본이 너무 적으면 판단하지 않음
        skew = max(abs(counts[k] - expected) for k in counts) / expected if expected else None
    return {
        'total': total,
        'counts': {'R%d' % k: v for k, v in counts.items()},
        'per_round': per_round,
        'expected_each': _r(expected, 2),
        'max_rel_dev': _r(skew),
        'flag': bool(skew is not None and skew > 0.5),
    }


# ---------- 통합 ----------
def payload():
    """/rounds/stats 응답."""
    store = rounds.load_store()
    labels = sorted(store, key=rounds._key)
    bs = bias_summary(store)
    ref = [l for l in labels if rounds.is_reference(store.get(l) or {})]
    return {
        'backend': rounds.backend(),
        'round_labels': labels,
        'n_rounds': len(labels),
        'reference_labels': ref,
        'bias_summary': bs,
        'precision': precision(store),
        'drift': drift(store),
        'drop_pattern': drop_pattern(store),
        'limits': {k: {'limit': v[0], 'unit': v[1]} for k, v in LIMITS.items()},
        'note': ('모니터링·진단용 통계입니다. 반복측정 채택은 정밀도/QC 기반 로직으로만 결정되며 '
                 '이 통계는 채택에 관여하지 않습니다. 최종 판정은 CDC 참조법 회신 및 검토자 확인 후 확정합니다.'),
        'note_reference': ('참고(소급) 표시가 붙은 회차는 과거 자료를 소급 누적한 것으로 참고용입니다. '
                           '드리프트(추세) 계산에서는 제외되며, 제출·판정 근거로 사용하지 마십시오.'),
    }
