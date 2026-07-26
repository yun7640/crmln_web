# -*- coding: utf-8 -*-
"""검증용 합성(synthetic) 측정지 생성기 — UC / DCM.

⚠️ 여기서 만드는 값은 **전부 인위적으로 만든 가짜 숫자**입니다.
   실제 CRMLN 측정결과가 아니며, 판정·제출에 절대 사용하지 마십시오.
   목적은 오직 업로드 경로(파싱→검토파일 생성→회차요약)가 죽지 않는지 확인하는 것입니다.

레이아웃 근거(review_engine.py):
  · 측정 시트명: '결과정리'
  · B열=구분 라벨, C열=검체명
  · Day1: 지정값 D열(4), R1~R3 = E,F,G(5,6,7)
  · Day2: 지정값 P열(16), R1~R3 = Q,R,S(17,18,19)
  · DCM 판별: 7행 2열이 'HDL Control'로 시작
  · DCM 행 구성: 5=NIST(TC), 6=CFS21-01(TC), 7=HDL CFS(HDL), 8=HDL QC2(HDL), 9~12=CS01~CS04

사용:
  python tools/make_fixture.py            # tools/_fixtures/ 에 2개 생성
  python tools/make_fixture.py --out DIR
"""
import argparse
import os

from openpyxl import Workbook

SHEET = '결과정리'


def _put(ws, row, label, name, a1, reps1, a2, reps2):
    """한 행에 Day1/Day2 지정값·3반복을 채운다."""
    if label is not None:
        ws.cell(row, 2, label)
    ws.cell(row, 3, name)
    if a1 is not None:
        ws.cell(row, 4, a1)
    for i, v in enumerate(reps1):
        ws.cell(row, 5 + i, v)
    if a2 is not None:
        ws.cell(row, 16, a2)
    for i, v in enumerate(reps2):
        ws.cell(row, 17 + i, v)


def build_uc(path):
    """UC(β-정량) 합성 측정지. BF/HDL Sample CS01~CS04 + QC/Control 포함."""
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET
    ws.cell(1, 1, '합성 검증용 파일 — 실제 측정결과 아님 (synthetic fixture, NOT real data)')

    # QC (TC) : 지정값 대비 약 +0.4% 편향
    _put(ws, 3, 'QC', 'NIST SRM1951', 200.0, [200.6, 200.9, 201.1], 200.0, [200.4, 200.8, 201.2])
    # BF Control
    _put(ws, 5, 'BF Control', 'CFS21-01 BF', 120.0, [120.9, 121.2, 121.5], 120.0, [120.7, 121.0, 121.4])
    # HDL Control — ★ 7행에 두면 _is_dcm()이 DCM으로 오인하므로 반드시 6행에 둔다.
    _put(ws, 6, 'HDL Control', 'HDL QC2', 50.0, [50.3, 50.5, 50.6], 50.0, [50.2, 50.4, 50.7])

    # BF Sample CS01~CS04 (지정값 없음 — 검체)
    ws.cell(9, 2, 'BF Sample')
    bf = {'CS01': ([95.2, 95.6, 97.9], [95.4, 95.7, 95.9]),
          'CS02': ([88.1, 88.4, 88.6], [88.0, 88.5, 90.2]),
          'CS03': ([76.5, 76.8, 77.0], [76.6, 76.9, 77.1]),
          'CS04': ([102.3, 102.7, 102.9], [102.4, 102.8, 103.0])}
    for i, (nm, (r1, r2)) in enumerate(bf.items()):
        _put(ws, 9 + i, None, nm, None, r1, None, r2)

    # HDL Sample CS01~CS04
    ws.cell(14, 2, 'HDL Sample')
    hdl = {'CS01': ([55.4, 55.7, 55.9], [55.5, 55.8, 56.0]),
           'CS02': ([46.2, 46.5, 46.7], [46.3, 46.6, 47.9]),
           'CS03': ([35.8, 36.0, 36.2], [35.9, 36.1, 36.3]),
           'CS04': ([59.9, 60.2, 60.4], [60.0, 60.3, 60.5])}
    for i, (nm, (r1, r2)) in enumerate(hdl.items()):
        _put(ws, 14 + i, None, nm, None, r1, None, r2)

    # LDL Control (B열이 정확히 'LDL Control')
    _put(ws, 19, 'LDL Control', 'LDL QC', 70.0, [70.4, 70.7, 70.9], 70.0, [70.3, 70.6, 71.0])

    # LDL Sample CS01~CS04 — B열이 정확히 'LDL'.
    # β-정량 정합(§4): LDL-C = BF − HDL 이므로 반복별로 그대로 차감해 만든다.
    ws.cell(21, 2, 'LDL')
    for i, nm in enumerate(bf):
        l1 = [round(b - h, 2) for b, h in zip(bf[nm][0], hdl[nm][0])]
        l2 = [round(b - h, 2) for b, h in zip(bf[nm][1], hdl[nm][1])]
        _put(ws, 21 + i, None, nm, None, l1, None, l2)

    wb.save(path)
    return path


def build_dcm(path):
    """DCM 합성 측정지. 7행 B열이 'HDL Control'로 시작해야 DCM으로 인식된다."""
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET
    ws.cell(1, 1, '합성 검증용 파일 — 실제 측정결과 아님 (synthetic fixture, NOT real data)')

    _put(ws, 5, 'QC', 'NIST SRM1951', 200.0, [200.5, 200.8, 201.0], 200.0, [200.4, 200.7, 201.1])
    _put(ws, 6, 'QC', 'CFS21-01', 190.0, [190.4, 190.7, 190.9], 190.0, [190.3, 190.6, 191.0])
    _put(ws, 7, 'HDL Control', 'HDL CFS21-01', 50.0, [50.2, 50.4, 50.5], 50.0, [50.1, 50.3, 50.6])
    _put(ws, 8, 'HDL QC2', 'HDL QC2', 40.0, [40.1, 40.3, 40.4], 40.0, [40.2, 40.3, 40.5])

    # CS01~CS04 (9~12행) — PS0126 참조값 근처의 임의값
    cs = {'CS01': ([55.4, 55.7, 55.9], [55.5, 55.8, 56.0]),
          'CS02': ([46.2, 46.5, 46.7], [46.3, 46.6, 46.8]),
          'CS03': ([35.8, 36.0, 36.2], [35.9, 36.1, 36.3]),
          'CS04': ([59.9, 60.2, 60.4], [60.0, 60.3, 60.5])}
    for i, (nm, (r1, r2)) in enumerate(cs.items()):
        _put(ws, 9 + i, 'HDL Sample', nm, None, r1, None, r2)

    wb.save(path)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), '_fixtures'))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    u = build_uc(os.path.join(a.out, 'fixture_UC_합성.xlsx'))
    d = build_dcm(os.path.join(a.out, 'fixture_DCM_합성.xlsx'))
    print(u)
    print(d)


if __name__ == '__main__':
    main()
