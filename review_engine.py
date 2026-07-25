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
             TMPL_MS, SEL_DST, '2026.7 측정결과 검토']
    wb._sheets.sort(key=lambda s: order.index(s.title) if s.title in order else 999)

    out = io.BytesIO(); wb.save(out); out.seek(0)
    n_exc = sum(1 for q in qc if _verdict(q['analyte'], q['biaspct'], q['biasmgdl'])[1] is False)
    summary = {'samples': len(rows), 'qc_rows': len(qc), 'member_exceed': n_exc, 'mode': 'dynamic'}
    return out.read(), summary


def _build_review_sheet(wb, samples, qc):
    if '2026.7 측정결과 검토' in wb.sheetnames:
        del wb['2026.7 측정결과 검토']
    ws = wb.create_sheet('2026.7 측정결과 검토')
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
    M(R, 1, NC, 'CRMLN 2026년 7월 측정결과 검토', bold=True, size=15, color='FFFFFF', fill=NAVY, align='center'); ws.row_dimensions[R].height = 26; R += 1
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
