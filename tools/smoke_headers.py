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
