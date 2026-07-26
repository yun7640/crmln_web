# -*- coding: utf-8 -*-
"""스모크 검증 ① — 앱 기능 + HTTP 헤더 latin-1 안전성 (크로스 플랫폼).

배경: HTTP 응답 헤더는 latin-1만 허용한다. 헤더에 한글이 그대로 들어가면
      gunicorn(Railway)에서 500이 나지만 Flask 개발서버/test_client는 관대해서 그냥 통과한다.
      → 그래서 여기서는 **헤더 값을 직접 latin-1로 인코딩해보며 명시적으로 검사**한다.
      이 방식이면 Windows·개발서버에서도 동일한 버그를 잡을 수 있다.

실행:
    python tools/smoke_headers.py
종료코드 0=통과, 1=실패.

주의: 이 스크립트가 쓰는 측정 파일은 tools/make_fixture.py가 만든 **합성 데이터**이며
      실제 CRMLN 측정결과가 아니다. 판정·제출에 사용하지 말 것.
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

FAILS = []
CHECKS = [0]


def check(name, cond, detail=''):
    CHECKS[0] += 1
    if cond:
        print('  PASS  %s' % name)
    else:
        print('  FAIL  %s  %s' % (name, detail))
        FAILS.append(name)


def assert_latin1_headers(resp, where):
    """응답의 모든 헤더 이름·값이 latin-1로 인코딩 가능한지 검사(한글 헤더 500 재발 방지)."""
    bad = []
    for k, v in resp.headers.items():
        for part, kind in ((k, 'name'), (str(v), 'value')):
            try:
                part.encode('latin-1')
            except UnicodeEncodeError:
                bad.append('%s(%s)=%r' % (k, kind, part))
    check('%s: 헤더 latin-1 안전' % where, not bad, '위반: %s' % bad)


def main():
    tmp = tempfile.mkdtemp(prefix='crmln_smoke_')
    os.environ.update({
        'SECRET_KEY': 'smoke-test-key',
        'ADMIN_USERS': 'admin',
        'ADMIN_PASSWORD': 'smoke-pw',
        'USERS_FILE': os.path.join(tmp, 'users.json'),
        'ROUNDS_FILE': os.path.join(tmp, 'rounds.json'),
    })
    os.environ.pop('DATABASE_URL', None)  # 파일 폴백 경로로 검증

    import make_fixture  # noqa: E402  (tools/ 안)
    fx = os.path.join(tmp, 'fx')
    os.makedirs(fx, exist_ok=True)
    uc_path = make_fixture.build_uc(os.path.join(fx, 'fixture_UC.xlsx'))
    dcm_path = make_fixture.build_dcm(os.path.join(fx, 'fixture_DCM.xlsx'))

    import app as appmod  # noqa: E402
    appmod.app.config['TESTING'] = True
    c = appmod.app.test_client()

    print('[1] 기본 라우트')
    r = c.get('/healthz')
    check('/healthz 200', r.status_code == 200, r.status_code)
    check('/healthz ok=true', r.get_json(silent=True) == {'ok': True}, r.data[:80])
    r = c.get('/')
    check('비로그인 / → 로그인 리다이렉트', r.status_code in (301, 302), r.status_code)

    print('[2] 로그인')
    r = c.post('/login', data={'username': 'admin', 'password': 'wrong'})
    check('오답 비밀번호는 세션 미생성', b'/login' not in r.headers.get('Location', '').encode() or r.status_code == 200,
          r.status_code)
    r = c.post('/login', data={'username': 'admin', 'password': 'smoke-pw'}, follow_redirects=False)
    check('정답 비밀번호 → 리다이렉트', r.status_code in (301, 302), r.status_code)
    r = c.get('/')
    check('로그인 후 / 200', r.status_code == 200, r.status_code)

    print('[3] /review 단발 업로드 (한글 파일명)')
    with open(uc_path, 'rb') as f:
        r = c.post('/review', data={'file': (f, '2026.7 측정결과_한글이름.xlsx')},
                   content_type='multipart/form-data')
    check('/review 200', r.status_code == 200, r.data[:200])
    assert_latin1_headers(r, '/review')
    check('/review 엑셀 반환', r.data[:2] == b'PK', r.data[:8])
    xrs = r.headers.get('X-Review-Summary')
    check('X-Review-Summary 존재·JSON 파싱', bool(xrs) and isinstance(json.loads(xrs), dict), xrs)

    print('[4] /rounds/add 누적 저장 (한글 파일명 + 한글 메시지 헤더)')
    with open(uc_path, 'rb') as f:
        r = c.post('/rounds/add',
                   data={'file': (f, '2026.7 측정결과_한글이름.xlsx'), 'label': '2026-07'},
                   content_type='multipart/form-data')
    check('/rounds/add 200', r.status_code == 200, r.data[:300])
    assert_latin1_headers(r, '/rounds/add')
    xrr = r.headers.get('X-Round-Result')
    check('X-Round-Result 존재', bool(xrr), xrr)
    if xrr:
        d = json.loads(xrr)
        check('X-Round-Result stored=True', d.get('stored') is True, d)
        check('X-Round-Result 라벨 정규화 2026-07→2026.7', d.get('label') in ('2026-07', '2026.7'), d.get('label'))
        check('X-Round-Result 한글 메시지 복원됨',
              isinstance(d.get('message'), str) and any('가' <= ch <= '힣' for ch in d.get('message', '')),
              d.get('message'))

    with open(dcm_path, 'rb') as f:
        r = c.post('/rounds/add',
                   data={'file': (f, 'DCM_측정.xlsx'), 'label': '2026.07'},
                   content_type='multipart/form-data')
    check('/rounds/add DCM 200', r.status_code == 200, r.data[:300])
    assert_latin1_headers(r, '/rounds/add(DCM)')

    print('[5] 라벨 정규화(canon_label) — 중복 회차가 생기지 않아야 함')
    import rounds  # noqa: E402
    for raw, want in (('2026-07', '2026.7'), ('2026.07', '2026.7'), ('2026-07-01', '2026.7'),
                      ('2026.7', '2026.7'), ('2026-01', '2026.1'), ('2025.1', '2025.1')):
        check('canon_label(%s)=%s' % (raw, want), rounds.canon_label(raw) == want, rounds.canon_label(raw))
    labels = [x['label'] if isinstance(x, dict) else x for x in rounds.list_rounds()]
    check('업로드 2건이 단일 라벨 2026.7로 병합', labels.count('2026.7') == 1 and len(labels) == 1, labels)

    print('[6] /rounds/data payload')
    r = c.get('/rounds/data')
    check('/rounds/data 200', r.status_code == 200, r.status_code)
    assert_latin1_headers(r, '/rounds/data')
    p = r.get_json(silent=True) or {}
    check('is_admin 주입됨', p.get('is_admin') is True, p.get('is_admin'))
    for k in ('surveys', 'qc_bias', 'ps_eval', 'dcm_eval', 'uploaded', 'round_labels'):
        check('payload.%s 존재' % k, k in p, sorted(p)[:12])
    check('시드 회차(2023.1) 포함', '2023.1' in (p.get('surveys') or []), (p.get('surveys') or [])[:4])
    check('업로드 회차(2026.7) 포함', '2026.7' in (p.get('round_labels') or []), p.get('round_labels'))

    print('[6b] /rounds/stats 누적 통계')
    r = c.get('/rounds/stats')
    check('/rounds/stats 200', r.status_code == 200, r.status_code)
    assert_latin1_headers(r, '/rounds/stats')
    S = r.get_json(silent=True) or {}
    for k in ('backend', 'round_labels', 'n_rounds', 'bias_summary', 'precision',
              'drift', 'drop_pattern', 'limits', 'note'):
        check('stats.%s 존재' % k, k in S, sorted(S)[:12])
    check('stats.n_rounds=1', S.get('n_rounds') == 1, S.get('n_rounds'))
    bs = (S.get('bias_summary') or {}).get('2026.7') or {}
    check('bias_summary에 uc·dcm 둘 다', set(bs) == {'uc', 'dcm'}, sorted(bs))
    uc_bs = bs.get('uc') or {}
    check('UC bias_summary 분석물질 4종', set(uc_bs) == {'TC', 'BF', 'HDL', 'LDL'}, sorted(uc_bs))
    hdl = uc_bs.get('HDL') or {}
    check('HDL 한계는 mg/dL 기준 ±1', hdl.get('limit') == 1.0 and hdl.get('unit') == 'mg/dL', hdl)
    check('TC 한계는 % 기준 ±1', (uc_bs.get('TC') or {}).get('unit') == '%', uc_bs.get('TC'))
    check('margin = |mean|/limit 일관',
          abs((hdl.get('margin') or 0) - abs(hdl.get('mean') or 0) / 1.0) < 0.002, hdl)
    dr = S.get('drift') or {}
    check('drift는 UC/DCM 분리 저장', set(dr) <= {'uc', 'dcm'} and set(dr), sorted(dr))
    check('회차 1개 → 기울기 판단 보류(None)',
          all(v.get('slope_per_round') is None for m in dr.values() for v in m.values()), dr)
    pr = (S.get('precision') or {}).get('2026.7') or {}
    check('precision에 CV·Day차 계산됨',
          (pr.get('uc') or {}).get('n_cv', 0) > 0 and (pr.get('uc') or {}).get('n_pairs', 0) > 0, pr)
    dp = S.get('drop_pattern') or {}
    check('drop_pattern 합계 = R1+R2+R3',
          dp.get('total') == sum((dp.get('counts') or {}).values()), dp)
    check('통계 note에 방법론 경고 포함', '판정' in (S.get('note') or ''), S.get('note'))

    print('[6c] T1 과거 회차 소급 누적 — 라벨 추정·연도 제한·시드 병기')
    import rounds as R  # noqa: E402
    # (1) 라벨 자동 추정: 파일명·시트명에서만 추정하며 저장하지 않는다
    cands = R.infer_labels('2025.1_HDLC_UC_측정결과.xlsx', ['결과정리', '2025년 1월 검토'])
    labs = [x['label'] for x in cands]
    check('파일명에서 라벨 추정', '2025.1' in labs, cands)
    check('추정 근거(source)를 함께 반환', all(x.get('source') and x.get('matched') for x in cands), cands)
    check('상/하반기 표기도 추정', '2024.7' in [x['label'] for x in R.infer_labels('2024 하반기.xlsx')],
          R.infer_labels('2024 하반기.xlsx'))
    check('추정 불가 파일은 빈 목록', R.infer_labels('측정결과.xlsx', ['결과정리']) == [],
          R.infer_labels('측정결과.xlsx', ['결과정리']))
    check('13월 등 잘못된 월은 추정 안 함', R.infer_labels('2025.13_x.xlsx') == [],
          R.infer_labels('2025.13_x.xlsx'))
    check('숫자 오인 방지(2025.1234)', R.infer_labels('2025.1234.xlsx') == [],
          R.infer_labels('2025.1234.xlsx'))
    check('YYYY-MM-DD도 반기로 정규화',
          [x['label'] for x in R.infer_labels('2024-07-15.xlsx')] == ['2024.7'],
          R.infer_labels('2024-07-15.xlsx'))
    check('같은 라벨 여러 근거 → n_sources 집계',
          all(x['n_sources'] == 2 for x in R.infer_labels('2025.1.xlsx', ['2025년 1월'])),
          R.infer_labels('2025.1.xlsx', ['2025년 1월']))

    # Postgres 경로 재현 — db.rounds_load()는 레코드 최상위에 reference를 넣지 않고
    # 요약(data JSONB) 안에만 넣는다. 그 형태에서도 참고용 판정이 되어야 한다.
    import stats as _S
    pg_like = {'2024.1': {'label': '2024.1', 'by': {'uc': 'admin'}, 'uc': {
        'mode': 'uc', 'reference': True, 'n_qc': 1, 'n_exceed': 0, 'n_samples': 1,
        'qc': [{'analyte': 'TC', 'biaspct': 0.2, 'biasmgdl': None, 'name': 'NIST', 'day': 1, 'ok': True}],
        'samples': [{'name': 'CS01', 'day': 1, 'drop': 2, 'keep': [1, 3],
                     'BF': 1, 'HDL': 50, 'LDL': 1, 'cvL': 0.3}]}}}
    check('Postgres 형태(요약 안에만 reference)에서도 참고용 인식',
          R.is_reference(pg_like['2024.1']) is True)
    check('일반 회차는 참고용 아님', R.is_reference({'uc': {'mode': 'uc'}}) is False)
    _d = _S.drift(pg_like)
    check('Postgres 형태에서도 드리프트가 참고용 제외',
          _d.get('_excluded_reference') == ['2024.1/UC'], _d)
    check('참고용만 있으면 추세 계열이 비어야 함', set(_d) == {'_excluded_reference'}, sorted(_d))
    check('bias_summary 행에 reference 표시',
          _S.bias_summary(pg_like)['2024.1']['uc']['TC']['reference'] is True)

    # (2) 최근 3년 제한 — 시점 불확실 시 min_backfill_year 이전은 거부
    lo = R.min_backfill_year()
    check('최근 3년 하한 = 올해-2', lo == __import__('datetime').date.today().year - 2, lo)
    ok_old, msg_old = R.year_guard('%d.1' % (lo - 1), date_certain=False)
    check('시점 불확실 + 3년 초과 과거 → 거부', ok_old is False and str(lo) in msg_old, msg_old)
    ok_cert, _ = R.year_guard('%d.1' % (lo - 1), date_certain=True)
    check('시점 확인됨 체크 시 허용', ok_cert is True)
    check('범위 내 연도는 허용', R.year_guard('%d.7' % lo)[0] is True)
    check('미래 연도 거부', R.year_guard('2099.1')[0] is False)

    # (3) /rounds/preview — 저장하지 않는다
    before = set(R.load_store())
    with open(uc_path, 'rb') as f:
        r = c.post('/rounds/preview', data={'file': (f, '2025.1_과거측정.xlsx')},
                   content_type='multipart/form-data')
    check('/rounds/preview 200', r.status_code == 200, r.data[:200])
    assert_latin1_headers(r, '/rounds/preview')
    P = r.get_json(silent=True) or {}
    check('preview saved=False', P.get('saved') is False, P.get('saved'))
    check('preview는 저장하지 않음', set(R.load_store()) == before, sorted(set(R.load_store()) - before))
    check('preview 추정 라벨 제시', P.get('suggested_label') == '2025.1', P.get('suggested_label'))
    check('preview 기존 라벨 상태 포함', isinstance(P.get('status'), dict) and 'exists' in P['status'], P.get('status'))
    check('preview 시드 대조 포함', isinstance(P.get('seed_compare'), dict), P.get('seed_compare'))
    check('preview note에 사용자 확인 요구 명시', '확정' in (P.get('note') or ''), P.get('note'))

    # (4) 확인(confirm) 없이는 소급 저장 불가
    with open(uc_path, 'rb') as f:
        r = c.post('/rounds/add', data={'file': (f, 'a.xlsx'), 'label': '2025.1', 'reference': '1'},
                   content_type='multipart/form-data')
    check('confirm 없는 소급 저장 거부 400', r.status_code == 400, r.status_code)
    with open(uc_path, 'rb') as f:
        r = c.post('/rounds/add', data={'file': (f, 'a.xlsx'), 'label': '%d.1' % (lo - 1),
                                        'reference': '1', 'confirm': '1'},
                   content_type='multipart/form-data')
    check('3년 초과 과거 소급 거부 400', r.status_code == 400, r.data[:200])

    # (5) 정상 소급 저장 — 참고용 표시 + 검토 엑셀 미생성(JSON 응답)
    with open(uc_path, 'rb') as f:
        r = c.post('/rounds/add', data={'file': (f, 'a.xlsx'), 'label': '%d.1' % lo,
                                        'reference': '1', 'confirm': '1'},
                   content_type='multipart/form-data')
    check('소급 저장 200', r.status_code == 200, r.data[:200])
    assert_latin1_headers(r, '/rounds/add(소급)')
    J = r.get_json(silent=True) or {}
    check('소급 응답은 JSON(검토 엑셀 미생성)', J.get('stored') is True and J.get('reference') is True, J)
    st = R.load_store().get('%d.1' % lo) or {}
    check('저장 레코드에 reference 표시', R.is_reference(st) is True, st.get('reference'))

    # (6) 시드 값 보존 — 덮어쓰지 않고 병기
    P2 = R.dashboard_payload()
    seedpts = (P2['qc_bias']['NIST'] or {}).get('points_seed') or {}
    seed_raw = (R.load_seed()['qc_bias']['NIST'] or {}).get('points') or {}
    check('시드 points_seed가 원본과 동일(덮어쓰기 없음)',
          all(abs(seedpts[k] - seed_raw[k]) < 1e-9 for k in seed_raw), 'seed 변형됨')
    check('업로드 값은 points_upload에 별도 보관',
          isinstance(P2['qc_bias']['NIST'].get('points_upload'), dict), P2['qc_bias']['NIST'].keys())
    check('conflicts 목록 존재', isinstance(P2.get('conflicts'), list), type(P2.get('conflicts')))
    check('payload에 reference_labels', '%d.1' % lo in (P2.get('reference_labels') or []),
          P2.get('reference_labels'))
    check('payload note_seed에 병기 원칙 명시', '덮어쓰지' in (P2.get('note_seed') or ''), P2.get('note_seed'))
    for cf in (P2.get('conflicts') or []):
        check('conflict 항목에 시드·업로드 값 모두 포함',
              cf.get('seed') is not None and cf.get('upload') is not None, cf)
        break

    # (7) 참고용 소급은 드리프트(추세) 계산에서 제외
    S2 = json.loads(c.get('/rounds/stats').data.decode('utf-8'))
    check('stats에 reference_labels 노출', '%d.1' % lo in (S2.get('reference_labels') or []),
          S2.get('reference_labels'))
    ex = (S2.get('drift') or {}).get('_excluded_reference') or []
    check('드리프트에서 참고용 소급 제외', any(('%d.1' % lo) in e for e in ex), ex)
    check('stats note_reference에 참고용 경고', '참고용' in (S2.get('note_reference') or ''),
          S2.get('note_reference'))
    c.post('/rounds/delete', data={'label': '%d.1' % lo, 'ajax': '1'})

    print('[7] /rounds/delete (관리자, ajax)')
    r = c.post('/rounds/delete', data={'label': '2026.7', 'mode': 'dcm', 'ajax': '1'})
    check('/rounds/delete ajax 200', r.status_code == 200, r.data[:200])
    check('/rounds/delete ok=True', (r.get_json(silent=True) or {}).get('ok') is True, r.data[:200])
    assert_latin1_headers(r, '/rounds/delete')

    print('[8] 잘못된 입력 방어')
    r = c.post('/rounds/add', data={'file': (open(uc_path, 'rb'), 'x.txt')},
               content_type='multipart/form-data')
    check('비-xlsx 거부 400', r.status_code == 400, r.status_code)
    with open(uc_path, 'rb') as f:
        r = c.post('/rounds/add', data={'file': (f, 'a.xlsx'), 'label': ''},
                   content_type='multipart/form-data')
    check('라벨 누락 거부 400', r.status_code == 400, r.status_code)

    shutil.rmtree(tmp, ignore_errors=True)

    print('\n=== %d개 검사 중 실패 %d ===' % (CHECKS[0], len(FAILS)))
    if FAILS:
        for f in FAILS:
            print('  - %s' % f)
        return 1
    print('전부 통과')
    return 0


if __name__ == '__main__':
    sys.exit(main())
