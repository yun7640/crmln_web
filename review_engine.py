# -*- coding: utf-8 -*-
"""CRMLN 측정 엑셀 업로드 → 검토 파일 생성.
전략: 사용자 검토 템플릿(assets/select_template.xlsx)에 업로드 측정값을 '주입'하여
동적 선택 시트(제출결과_선택검토 → 2026.7_결과선택; 수식·조건부서식·드롭다운 100% 보존)를
그대로 재현하고, 정적 요약 시트(2026.7 측정결과 검토)를 추가한다."""
import io, os, openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.cell.cell import MergedCell

MEMBER = {'TC': ('±1%', 'pct', 1.0), 'BF': ('±2%', 'pct', 2.0),
          'HDL': ('±1 mg/dL', 'mgdl', 1.0), 'LDL': ('±2%', 'pct', 2.0)}
D1 = (5, 6, 7); D2 = (17, 18, 19)   # R1,R2,R3 열 (Day1 / Day2)
BASE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(BASE, 'assets', 'select_template.xlsx')
TMPL_MS = '2026-07_결과정리'          # 템플릿 측정 시트명
SEL_SRC = '제출결과_선택검토'          # 템플릿 선택 시트명
SEL_DST = '2026.7_결과선택'           # 출력 선택 시트명
DEFAULT_OPTION = '종합 (BF+HDL 상대편차) · 균형 [기본]'
UC_SHEET = 'HDLC UC 검토'      # (구)2026.7 측정결과 검토 — HDL-C UC / β-정량 검토
DCM_SHEET = 'HDLC DCM 검토'    # HDL-C DCM 검토
DCM_HDL_LIM = 1.0             # CRMLN member: HDL-C DCM bias ±1.0 mg/dL, imprecision SD ≤1.0 mg/dL (PS0126 참조)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _median(a):
    return sorted(a)[1]


def combo_pick(BF, HDL, LDL):
    mB, mH = _median(BF), _median(HDL)
    disc = [abs(BF[k] - mB) / mB * 100 + abs(HDL[k] - mH) / mH * 100 for k in range(3)]
    drop = disc.index(max(disc)); keep = [k for k in range(3) if k != drop]
    m = lambda a: (a[keep[0]] + a[keep[1]]) / 2
    cv = lambda a: (((a[keep[0]] - m(a)) ** 2 + (a[keep[1]] - m(a)) ** 2) / 2) ** 0.5 / m(a) * 100
    return drop, keep, m(BF), m(HDL), m(LDL), cv(LDL)


def _parse(ws):
    """측정 시트에서 CS 검체 행위치와 QC/Control bias(원자료 계산)를 추출."""
    rows = {}; qc = []; an = None; kind = None
    DAY = {1: (4, (5, 6, 7)), 2: (16, (17, 18, 19))}
    for r in range(1, ws.max_row + 1):
        b = ws.cell(r, 2).value
        if isinstance(b, str) and b.strip():
            s = b.strip()
            if s.startswith('BF Control'): an, kind = 'BF', 'ctl'
            elif s.startswith('BF Sample'): an, kind = 'BF', 'smp'
            elif s.startswith('HDL Control'): an, kind = 'HDL', 'ctl'
            elif s.startswith('HDL Sample'): an, kind = 'HDL', 'smp'
            elif s == 'LDL Control': an, kind = 'LDL', 'ctl'
            elif s == 'LDL': an, kind = 'LDL', 'smp'
            elif s == 'QC': an, kind = 'TC', 'qc'
        name = ws.cell(r, 3).value
        if isinstance(name, str): name = name.strip()
        if not name: continue
        if kind in ('qc', 'ctl'):
            analyte = 'TC' if kind == 'qc' else an
            for day, (av_col, rep_cols) in DAY.items():
                A = _num(ws.cell(r, av_col).value)
                reps = [_num(ws.cell(r, c).value) for c in rep_cols]
                if A is None or A == 0 or any(x is None for x in reps):
                    continue
                mean = sum(reps) / 3.0
                qc.append(dict(analyte=analyte, name=name, day=day,
                               biaspct=(mean - A) / A * 100,
                               biasmgdl=(mean - A) if analyte == 'HDL' else None))
        elif kind == 'smp' and name.startswith('CS'):
            rows.setdefault(name, {})[an] = r
    return rows, qc


def _extract_samples(ws, rows):
    out = {}
    for name, amap in rows.items():
        d = {}
        for an in ('BF', 'HDL', 'LDL'):
            rr = amap.get(an)
            if not rr: continue
            per = {}
            for day, cols in ((1, D1), (2, D2)):
                vals = [_num(ws.cell(rr, c).value) for c in cols]
                if all(v is not None for v in vals): per[day] = vals
            d[an] = per
        out[name] = d
    return out


def _verdict(an, biaspct, biasmgdl):
    lbl, mode, lim = MEMBER[an]
    val = biasmgdl if mode == 'mgdl' else biaspct
    if val is None: return ('–', None, lbl)
    ok = abs(val) <= lim + 1e-9
    return ('적합' if ok else '초과', ok, lbl)


def _inject(src_ws, dst_ws, force=False):
    """src → dst 셀값 복사. 병합 부셀·(force=False 시)dst 수식·src 수식은 건너뜀."""
    n = 0
    for row in src_ws.iter_rows():
        for c in row:
            dc = dst_ws.cell(c.row, c.column)
            if isinstance(dc, MergedCell):
                continue
            if not force:
                dv = dc.value
                if isinstance(dv, str) and dv.startswith('='):
                    continue
            v = c.value
            if isinstance(v, str) and v.startswith('='):
                continue
            if v is None:
                continue
            if dc.value != v:
                dc.value = v; n += 1
    return n


def process(in_bytes):
    """입력 xlsx 바이트 → (출력 xlsx 바이트, 요약 dict)."""
    up = openpyxl.load_workbook(io.BytesIO(in_bytes))
    up_do = openpyxl.load_workbook(io.BytesIO(in_bytes), data_only=True)
    ms_name = '결과정리' if '결과정리' in up.sheetnames else (TMPL_MS if TMPL_MS in up.sheetnames else None)
    if ms_name is None:
        raise ValueError("'결과정리' 시트를 찾을 수 없습니다. 표준 CRMLN 측정지 형식이 필요합니다.")
    up_ms = up[ms_name]
    if _is_dcm(up_ms):
        return _process_dcm(up, up_ms)
    rows, qc = _parse(up_ms)
    if not rows:
        raise ValueError("CS 검체(BF/HDL/LDL Sample) 데이터를 찾지 못했습니다. 레이아웃을 확인하세요.")
    samples = _extract_samples(up_ms, rows)

    # 검토 템플릿을 base로 로드
    wb = openpyxl.load_workbook(TEMPLATE)

    # 1) 측정값 주입: 업로드 결과정리 → 템플릿 2026-07_결과정리 (템플릿 수식 보존)
    _inject(up_ms, wb[TMPL_MS], force=False)
    # RESULT 원자료도 이번 회차 값으로 갱신(계산값 스냅샷)
    for sn in ('RESULT(Conc)_DAY1', 'RESULT(Conc)_DAY2'):
        if sn in up_do.sheetnames and sn in wb.sheetnames:
            _inject(up_do[sn], wb[sn], force=True)

    # 2) 선택 시트: 기본 옵션으로 초기화 후 이름 변경
    if SEL_SRC in wb.sheetnames:
        sel = wb[SEL_SRC]
        try:
            sel['C4'] = DEFAULT_OPTION
        except Exception:
            pass
        sel.title = SEL_DST

    # 3) 가이드 시트 텍스트의 옛 시트명 갱신
    if '검토_가이드' in wb.sheetnames:
        g = wb['검토_가이드']
        for row in g.iter_rows():
            for c in row:
                if isinstance(c.value, str) and SEL_SRC in c.value:
                    c.value = c.value.replace(SEL_SRC, SEL_DST)

    # 4) 정적 요약 시트 추가
    _build_review_sheet(wb, samples, qc)

    # 5) Excel 열 때 자동 재계산
    try:
        wb.calculation.fullCalcOnLoad = True
    except Exception:
        pass

    # 6) 시트 순서
    order = ['검토_가이드', 'RESULT(Conc)_DAY1', 'RESULT(Conc)_DAY2',
             TMPL_MS, SEL_DST, UC_SHEET]
    wb._sheets.sort(key=lambda s: order.index(s.title) if s.title in order else 999)

    out = io.BytesIO(); wb.save(out); out.seek(0)
    n_exc = sum(1 for q in qc if _verdict(q['analyte'], q['biaspct'], q['biasmgdl'])[1] is False)
    summary = {'samples': len(rows), 'qc_rows': len(qc), 'member_exceed': n_exc, 'mode': 'dynamic'}
    return out.read(), summary


def _build_review_sheet(wb, samples, qc):
    if UC_SHEET in wb.sheetnames:
        del wb[UC_SHEET]
    ws = wb.create_sheet(UC_SHEET)
    NAVY, BLUE, GREEN, RED2 = '1F3A5F', '2C6E9B', '1B7F4B', 'C0392B'
    thin = Side(style='thin', color='BBBBBB'); box = Border(thin, thin, thin, thin)

    def C(r, c, v, bold=False, size=10, color='222222', fill=None, align='left', border=False, wrap=False, italic=False):
        x = ws.cell(r, c, v); x.font = Font(name='맑은 고딕', bold=bold, size=size, color=color, italic=italic)
        x.alignment = Alignment(horizontal=align, vertical='center', wrap_text=wrap)
        if fill: x.fill = PatternFill('solid', fgColor=fill)
        if border: x.border = box
        return x

    def M(r, c1, c2, v, **k):
        ws.merge_cells(start_row=r, start_column=c1, end_row=r, end_column=c2); return C(r, c1, v, **k)

    NC = 8; R = 1
    M(R, 1, NC, 'CRMLN 2026년 7월 HDL-C UC 측정결과 검토', bold=True, size=15, color='FFFFFF', fill=NAVY, align='center'); ws.row_dimensions[R].height = 26; R += 1
    M(R, 1, NC, 'KDCA 진단검사의학 표준검사실(NMRL) · CRMLN member laboratory (Lab 509) · HDL-C / LDL-C(β-quantification)', size=10, color='FFFFFF', fill=BLUE, align='center'); R += 2

    def section(t, sub=''):
        nonlocal R
        M(R, 1, NC, t, bold=True, size=11.5, color='FFFFFF', fill=BLUE); R += 1
        if sub:
            M(R, 1, NC, sub, size=9, color='555555', italic=True, wrap=True); ws.row_dimensions[R].height = 26; R += 1

    # ① QC/Control 정확도
    section('① QC · Control 정확도 판정 (CRMLN member laboratory 기준)',
            '기준: NIST/TC ±1%, BF ±2%, HDL ±1 mg/dL, LDL ±2%. QC·Control은 제출 대상 아님(batch 정확도 확인용).')
    for i, t in enumerate(['항목', '관리물질', 'Day', 'bias(%)', 'bias(mg/dL)', '기준', '판정', '']):
        C(R, i + 1, t, bold=True, size=9.5, color='FFFFFF', fill=NAVY, align='center', border=True)
    ws.merge_cells(start_row=R, start_column=7, end_row=R, end_column=8); R += 1
    lbl = {'TC': 'NIST(TC)', 'BF': 'BF Control', 'HDL': 'HDL Control', 'LDL': 'LDL Control'}
    for an in ['TC', 'BF', 'HDL', 'LDL']:
        for q in [x for x in qc if x['analyte'] == an]:
            v, ok, lm = _verdict(an, q['biaspct'], q['biasmgdl'])
            col = GREEN if ok else (RED2 if ok is False else '888888')
            C(R, 1, lbl[an], size=9.5, border=True); C(R, 2, q['name'], size=9.5, border=True)
            C(R, 3, 'Day%d' % q['day'], size=9.5, align='center', border=True)
            C(R, 4, '' if q['biaspct'] is None else round(q['biaspct'], 2), size=9.5, align='center', border=True)
            C(R, 5, '' if q['biasmgdl'] is None else round(q['biasmgdl'], 2), size=9.5, align='center', border=True)
            C(R, 6, lm, size=9.5, align='center', border=True)
            C(R, 7, ('✓ ' if ok else ('⚠ ' if ok is False else '')) + v, bold=True, size=9.5, color=col, align='center', border=True)
            ws.merge_cells(start_row=R, start_column=7, end_row=R, end_column=8); ws.cell(R, 8).border = box; R += 1
    R += 1

    # ② 제출 선택 (종합·균형)
    section('② CRMLN 제출 결과 선택 (CS 검체 R1/R2/R3 → 채택 2반복, 기본: 종합 BF+HDL 균형)',
            '동적 선택·옵션 비교는 [2026.7_결과선택] 시트 참조. QC/Control 미제출 · BF·HDL·LDL 동일 R index 잠금.')
    for i, t in enumerate(['검체', 'Day', '제외R', '채택R', 'BF채택', 'HDL채택', 'LDL채택', 'LDL cv%']):
        C(R, i + 1, t, bold=True, size=9.5, color='FFFFFF', fill=NAVY, align='center', border=True)
    R += 1
    for name in sorted(samples):
        d = samples[name]
        for day in (1, 2):
            BF = d.get('BF', {}).get(day); HDL = d.get('HDL', {}).get(day); LDL = d.get('LDL', {}).get(day)
            if not (BF and HDL and LDL): continue
            drop, keep, sB, sH, sL, cvL = combo_pick(BF, HDL, LDL)
            C(R, 1, name, size=9, border=True); C(R, 2, 'Day%d' % day, size=9, align='center', border=True)
            C(R, 3, 'R%d' % (drop + 1), size=9, align='center', color=RED2, border=True)
            C(R, 4, 'R%d·R%d' % (keep[0] + 1, keep[1] + 1), size=9, align='center', color=GREEN, border=True)
            C(R, 5, round(sB, 2), bold=True, size=9, align='center', border=True)
            C(R, 6, round(sH, 2), bold=True, size=9, align='center', border=True)
            C(R, 7, round(sL, 2), bold=True, size=9, align='center', border=True)
            C(R, 8, round(cvL, 2), size=9, align='center', border=True); R += 1
    R += 1

    # ③ 종합 고찰
    exc = [q for q in qc if _verdict(q['analyte'], q['biaspct'], q['biasmgdl'])[1] is False]
    exc_txt = ', '.join('%s %s' % (q['analyte'], q['name']) for q in exc) or '없음'
    section('③ 종합 고찰')
    for t in [
        '· CS 검체는 정밀도 기반(median 이상치 제외)으로 2반복 채택 → 제출(QC·Control 미제출).',
        '· QC·Control member 기준 초과 항목: %s.' % exc_txt,
        '· 제출값은 CDC 참조법 회신 전 잠정이며, 최종 판정은 검토자 확인 후 확정.',
        '· 선택 기준을 바꿔 비교하려면 [2026.7_결과선택] 시트의 C4 옵션(드롭다운)을 사용하십시오.',
    ]:
        M(R, 1, NC, t, size=10, wrap=True, color='333333'); R += 1
    M(R, 1, NC, '※ 본 시트는 업로드 파일로부터 자동 생성됨. 공식 CRMLN 인증 판정은 CDC 평가보고서(PS)에 따름.', size=8.5, color='888888', italic=True); R += 1

    for i, w in enumerate([13, 13, 7, 12, 12, 10, 10, 10]): ws.column_dimensions[get_column_letter(i + 1)].width = w
    ws.sheet_view.showGridLines = False
    from openpyxl.worksheet.properties import PageSetupProperties
    ws.page_setup.orientation = 'landscape'; ws.page_setup.fitToWidth = 1; ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)


# ============================================================
#  HDL-C DCM (Designated Comparison Method) — 자동 감지·검토
#  β-정량과 열 위치(R1/R2/R3 = E/F/G, Q/R/S) 동일, 행 구성·단일 항목만 다름.
#  측정지 5–12행: NIST(5)·CFS21-01(6)=TC / HDL CFS21-01(7)·HDL QC2(8)=HDL /
#                 HDL Sample CS01–CS04(9–12).  판정: TC ±1%, HDL ±1 mg/dL.
# ============================================================
DCM_CV_GUARD = 15.0  # 동일 검체 반복 CV(%)가 이보다 크면 데이터 정렬 오류로 보고 해당 Day 제외

def _is_dcm(ws):
    return str(ws.cell(7, 2).value or '').strip().startswith('HDL Control')

def _cv3(reps):
    m = sum(reps) / 3.0
    return (sum((x - m) ** 2 for x in reps) / 3.0) ** 0.5 / m * 100 if m else 999

def _dcm_pick(reps):
    m = _median(reps); dev = [abs(x - m) for x in reps]
    drop = dev.index(max(dev)); keep = [k for k in range(3) if k != drop]
    sel = (reps[keep[0]] + reps[keep[1]]) / 2.0
    cv = (((reps[keep[0]] - sel) ** 2 + (reps[keep[1]] - sel) ** 2) / 2.0) ** 0.5 / sel * 100 if sel else 0
    return drop, keep, sel, cv

def _parse_dcm(ws):
    """DCM 측정지(5–12행) → (qc, samples). CV>가드 인 Day는 정렬오류로 제외."""
    DAY = {1: (4, (5, 6, 7)), 2: (16, (17, 18, 19))}
    qc = []
    for r, an in [(5, 'TC'), (6, 'TC'), (7, 'HDL'), (8, 'HDL')]:
        name = str(ws.cell(r, 3).value or '').strip()
        if not name:
            continue
        for day, (av, rc) in DAY.items():
            A = _num(ws.cell(r, av).value); reps = [_num(ws.cell(r, c).value) for c in rc]
            if A is None or A == 0 or any(x is None for x in reps):
                continue
            if _cv3(reps) > DCM_CV_GUARD:
                continue
            mean = sum(reps) / 3.0
            qc.append(dict(analyte=an, name=name, day=day,
                           biaspct=(mean - A) / A * 100,
                           biasmgdl=(mean - A) if an == 'HDL' else None))
    samples = {}
    for r in range(9, 13):
        name = str(ws.cell(r, 3).value or '').strip()
        if not name.upper().replace(' ', '').startswith('CS'):
            continue
        per = {}
        for day, rc in {1: (5, 6, 7), 2: (17, 18, 19)}.items():
            reps = [_num(ws.cell(r, c).value) for c in rc]
            if all(x is not None for x in reps) and _cv3(reps) <= DCM_CV_GUARD:
                per[day] = reps
        if per:
            samples[name] = per
    return qc, samples


def _extract_dcm_rows(ws):
    """DCM 측정지(5–12행) → Day별 원자료 행(Excel-mirror 표시용).
    반환: {day: [ {label, name, analyte, is_sample, A, reps[3], mean3, cv3} ]}"""
    DAY = {1: (2, 3, 4, (5, 6, 7)), 2: (14, 15, 16, (17, 18, 19))}  # (label열, name열, 지정값열, R열)
    SPEC = [(5, 'TC', False), (6, 'TC', False), (7, 'HDL', False), (8, 'HDL', False),
            (9, 'HDL', True), (10, 'HDL', True), (11, 'HDL', True), (12, 'HDL', True)]
    out = {1: [], 2: []}
    for r, an, is_s in SPEC:
        label = str(ws.cell(r, 2).value or '').strip()
        name = str(ws.cell(r, 3).value or '').strip()
        if not (label or name):
            continue
        if is_s and not name.upper().replace(' ', '').startswith('CS'):
            continue
        for day, (lc, nc, av, rc) in DAY.items():
            reps = [_num(ws.cell(r, c).value) for c in rc]
            if any(x is None for x in reps):
                continue
            if _cv3(reps) > DCM_CV_GUARD:
                continue
            A = _num(ws.cell(r, av).value)
            mean3 = sum(reps) / 3.0
            disp = (name or label) if is_s else (label or name)
            out[day].append(dict(label=disp, name=name, analyte=an, is_sample=is_s,
                                 A=A, reps=reps, mean3=mean3, cv3=_cv3(reps)))
    return out

def _process_dcm(up, ms):
    qc, samples = _parse_dcm(ms)
    rows = _extract_dcm_rows(ms)
    if not samples:
        raise ValueError('HDL-C DCM 검체(CS01–CS04)를 찾지 못했습니다. DCM 측정지 형식(5–12행)을 확인하세요.')
    for nm in ('2026.7_결과선택', '2026.7 측정결과 검토', UC_SHEET, '검토_가이드'):
        if nm in up.sheetnames:
            del up[nm]
    _build_dcm_review(up, qc, samples, rows)
    # 순서: 측정/RESULT 뒤에 검토 시트
    order = ['검토_가이드', 'RESULT(Conc)_DAY1', 'RESULT(Conc)_DAY2', '결과정리', TMPL_MS, DCM_SHEET]
    up._sheets.sort(key=lambda s: order.index(s.title) if s.title in order else 500)
    try:
        up.calculation.fullCalcOnLoad = True
    except Exception:
        pass
    out = io.BytesIO(); up.save(out); out.seek(0)
    n_exc = sum(1 for q in qc if _verdict(q['analyte'], q['biaspct'], q['biasmgdl'])[1] is False)
    days = sorted({d for v in samples.values() for d in v})
    return out.read(), {'mode': 'dcm', 'samples': len(samples), 'qc_rows': len(qc),
                        'member_exceed': n_exc, 'days': days}

def _build_dcm_review(wb, qc, samples, rows=None):
    if DCM_SHEET in wb.sheetnames:
        del wb[DCM_SHEET]
    ws = wb.create_sheet(DCM_SHEET)
    NAVY, BLUE, GREEN, RED2 = '1F3A5F', '2C6E9B', '1B7F4B', 'C0392B'
    thin = Side(style='thin', color='BBBBBB'); box = Border(thin, thin, thin, thin)

    def C(r, c, v, bold=False, size=10, color='222222', fill=None, align='left', border=False, wrap=False, italic=False):
        x = ws.cell(r, c, v); x.font = Font(name='맑은 고딕', bold=bold, size=size, color=color, italic=italic)
        x.alignment = Alignment(horizontal=align, vertical='center', wrap_text=wrap)
        if fill: x.fill = PatternFill('solid', fgColor=fill)
        if border: x.border = box
        return x

    def M(r, c1, c2, v, **k):
        ws.merge_cells(start_row=r, start_column=c1, end_row=r, end_column=c2); return C(r, c1, v, **k)

    STRIKE = Font(name='맑은 고딕', size=9, color='C0392B', strike=True)
    NC = 8; R = 1
    M(R, 1, NC, 'CRMLN 2026년 7월 HDL-C DCM 측정결과 검토', bold=True, size=15, color='FFFFFF', fill=NAVY, align='center'); ws.row_dimensions[R].height = 26; R += 1
    M(R, 1, NC, 'KDCA 진단검사의학 표준검사실(NMRL) · CRMLN member laboratory (Lab 509) · HDL-C Designated Comparison Method(DCM)', size=10, color='FFFFFF', fill=BLUE, align='center'); R += 2

    def section(t, sub=''):
        nonlocal R
        M(R, 1, NC, t, bold=True, size=11.5, color='FFFFFF', fill=BLUE); R += 1
        if sub:
            M(R, 1, NC, sub, size=9, color='555555', italic=True, wrap=True); ws.row_dimensions[R].height = 26; R += 1

    # ① QC·Control 정확도
    section('① QC · Control 정확도 판정 (CRMLN member laboratory 기준)',
            '기준: NIST/CFS(TC) ±1%, HDL Control ±1 mg/dL. QC·Control은 제출 대상 아님(batch 정확도 확인용).')
    for i, t in enumerate(['항목', '관리물질', 'Day', 'bias(%)', 'bias(mg/dL)', '기준', '판정', '']):
        C(R, i + 1, t, bold=True, size=9.5, color='FFFFFF', fill=NAVY, align='center', border=True)
    ws.merge_cells(start_row=R, start_column=7, end_row=R, end_column=8); R += 1
    lbl = {'TC': 'TC(SRM/CFS)', 'HDL': 'HDL Control'}
    for an in ['TC', 'HDL']:
        for q in [x for x in qc if x['analyte'] == an]:
            v, ok, lm = _verdict(an, q['biaspct'], q['biasmgdl'])
            col = GREEN if ok else (RED2 if ok is False else '888888')
            C(R, 1, lbl[an], size=9.5, border=True); C(R, 2, q['name'], size=9.5, border=True)
            C(R, 3, 'Day%d' % q['day'], size=9.5, align='center', border=True)
            C(R, 4, '' if q['biaspct'] is None else round(q['biaspct'], 2), size=9.5, align='center', border=True)
            C(R, 5, '' if q['biasmgdl'] is None else round(q['biasmgdl'], 2), size=9.5, align='center', border=True)
            C(R, 6, lm, size=9.5, align='center', border=True)
            C(R, 7, ('✓ ' if ok else ('⚠ ' if ok is False else '')) + v, bold=True, size=9.5, color=col, align='center', border=True)
            ws.merge_cells(start_row=R, start_column=7, end_row=R, end_column=8); ws.cell(R, 8).border = box; R += 1
    R += 1

    # ② 제출 결과 선택 (측정지 재현 Day1/Day2 — HDL-C UC 검토와 동일 방식)
    section('② CRMLN 제출 결과 선택 (HDL-C DCM 측정지 재현 · R1/R2/R3 → 채택 2반복)',
            '정밀도 기반: median 대비 편차가 가장 큰 replicate 1개 제외(취소선) → 나머지 2개 평균 채택. QC/Control은 제출 대상 아님(미제출).')
    hdr = ['구분 · 검체', '지정값', 'R1', 'R2', 'R3', 'mean(3)', 'cv%(3)', '채택(2/3)']
    rows = rows or {1: [], 2: []}
    days_present = [d for d in (1, 2) if rows.get(d)]
    if not days_present:  # 폴백: rows 미제공 시 samples로 최소 구성
        days_present = sorted({d for v in samples.values() for d in v})
    for day in days_present:
        M(R, 1, NC, 'Day %d' % day, bold=True, size=10, color='FFFFFF', fill='6B7683', align='center'); R += 1
        for i, t in enumerate(hdr):
            C(R, i + 1, t, bold=True, size=9.5, color='FFFFFF', fill=NAVY, align='center', border=True)
        R += 1
        drow = rows.get(day) or []
        for rr in drow:
            reps = rr['reps']
            C(R, 1, rr['label'], size=9, border=True)
            C(R, 2, '' if rr['A'] in (None, 0) else round(rr['A'], 2), size=9, align='center', border=True)
            if rr['is_sample']:
                drop, keep, sel, cv = _dcm_pick(reps)
                for k in range(3):
                    cell = C(R, 3 + k, round(reps[k], 2), size=9, align='center', border=True,
                             color=(GREEN if k in keep else RED2))
                    if k == drop:
                        cell.font = STRIKE
                C(R, 6, round(rr['mean3'], 2), size=9, align='center', color='888888', border=True)
                C(R, 7, round(rr['cv3'], 2), size=9, align='center', color='888888', border=True)
                C(R, 8, round(sel, 2), bold=True, size=9.5, color=GREEN, align='center', border=True)
            else:
                for k in range(3):
                    C(R, 3 + k, round(reps[k], 2), size=9, align='center', border=True)
                C(R, 6, round(rr['mean3'], 2), size=9, align='center', border=True)
                C(R, 7, round(rr['cv3'], 2), size=9, align='center', border=True)
                C(R, 8, '미제출', size=8.5, italic=True, color='888888', align='center', border=True)
            R += 1
        R += 1

    # ③ 종합 고찰
    exc = [q for q in qc if _verdict(q['analyte'], q['biaspct'], q['biasmgdl'])[1] is False]
    exc_txt = ', '.join('%s %s(Day%d)' % (q['analyte'], q['name'], q['day']) for q in exc) or '없음'
    section('③ 종합 고찰')
    for t in [
        '· HDL-C DCM 검체는 정밀도 기반(median 이상치 제외)으로 2반복 채택 → 제출(QC·Control 미제출).',
        '· QC·Control member 기준 초과 항목: %s.' % exc_txt,
        '· HDL Control 판정은 ±1 mg/dL(절대값), NIST·CFS(TC)는 ±1%.',
        '· 제출값은 CDC 참조법 회신 전 잠정이며, 최종 판정은 검토자 확인 후 확정.',
        '· 동일 검체 반복 CV가 %g%% 초과인 Day는 데이터 정렬 오류로 보고 검토에서 제외했습니다(측정지 확인 권장).' % DCM_CV_GUARD,
    ]:
        M(R, 1, NC, t, size=10, wrap=True, color='333333'); R += 1
    M(R, 1, NC, '※ 본 시트는 업로드 파일로부터 자동 생성됨. 공식 CRMLN 인증 판정은 CDC 평가보고서(PS)에 따름.', size=8.5, color='888888', italic=True); R += 1

    for i, w in enumerate([20, 9, 9, 9, 9, 9, 8, 11]): ws.column_dimensions[get_column_letter(i + 1)].width = w
    ws.sheet_view.showGridLines = False
    from openpyxl.worksheet.properties import PageSetupProperties
    ws.page_setup.orientation = 'landscape'; ws.page_setup.fitToWidth = 1; ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)


# ============================================================
#  회차 누적용 요약 추출 — summarize_round(in_bytes) → compact dict
#  서버에 회차별 저장 후 추가 통계 분석(경향·제출값 추이)에 활용.
# ============================================================
def _agg_bias(qc, an, key):
    vals = [q[key] for q in qc if q['analyte'] == an and q.get(key) is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


def _qc_list(qc):
    out = []
    for q in qc:
        _, ok, lm = _verdict(q['analyte'], q['biaspct'], q['biasmgdl'])
        out.append(dict(analyte=q['analyte'], name=q['name'], day=q['day'],
                        biaspct=None if q['biaspct'] is None else round(q['biaspct'], 3),
                        biasmgdl=None if q['biasmgdl'] is None else round(q['biasmgdl'], 3),
                        ok=ok, limit=lm))
    return out


def _summarize_uc(ws):
    rows, qc = _parse(ws)
    samples = _extract_samples(ws, rows)
    subs = []
    for name in sorted(samples):
        d = samples[name]
        for day in (1, 2):
            BF = d.get('BF', {}).get(day); HDL = d.get('HDL', {}).get(day); LDL = d.get('LDL', {}).get(day)
            if not (BF and HDL and LDL):
                continue
            drop, keep, sB, sH, sL, cvL = combo_pick(BF, HDL, LDL)
            subs.append(dict(name=name, day=day, drop=drop + 1, keep=[k + 1 for k in keep],
                             BF=round(sB, 2), HDL=round(sH, 2), LDL=round(sL, 2), cvL=round(cvL, 3),
                             reps=dict(BF=BF, HDL=HDL, LDL=LDL)))
    n_exc = sum(1 for q in qc if _verdict(q['analyte'], q['biaspct'], q['biasmgdl'])[1] is False)
    return dict(mode='uc', qc=_qc_list(qc),
                qc_bias={'TC': _agg_bias(qc, 'TC', 'biaspct'), 'BF': _agg_bias(qc, 'BF', 'biaspct'),
                         'HDL_mgdl': _agg_bias(qc, 'HDL', 'biasmgdl'), 'LDL': _agg_bias(qc, 'LDL', 'biaspct')},
                samples=subs, n_qc=len(qc), n_exceed=n_exc,
                n_samples=len({s['name'] for s in subs}))


def _summarize_dcm(ws):
    qc, samples = _parse_dcm(ws)
    subs = []
    for name in sorted(samples):
        for day in (1, 2):
            reps = samples[name].get(day)
            if not reps:
                continue
            drop, keep, sel, cv = _dcm_pick(reps)
            subs.append(dict(name=name, day=day, drop=drop + 1, keep=[k + 1 for k in keep],
                             HDL=round(sel, 2), cv=round(cv, 3), reps=reps))
    n_exc = sum(1 for q in qc if _verdict(q['analyte'], q['biaspct'], q['biasmgdl'])[1] is False)
    return dict(mode='dcm', qc=_qc_list(qc),
                qc_bias={'TC': _agg_bias(qc, 'TC', 'biaspct'), 'HDL_mgdl': _agg_bias(qc, 'HDL', 'biasmgdl')},
                samples=subs, n_qc=len(qc), n_exceed=n_exc,
                n_samples=len({s['name'] for s in subs}))


def summarize_round(in_bytes):
    """업로드 xlsx → 회차 누적 저장용 compact dict(UC/DCM 자동 감지)."""
    up = openpyxl.load_workbook(io.BytesIO(in_bytes), data_only=False)
    ms = '결과정리' if '결과정리' in up.sheetnames else (TMPL_MS if TMPL_MS in up.sheetnames else None)
    if ms is None:
        raise ValueError("'결과정리' 측정 시트를 찾을 수 없습니다.")
    ws = up[ms]
    return _summarize_dcm(ws) if _is_dcm(ws) else _summarize_uc(ws)
