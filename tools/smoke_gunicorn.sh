#!/usr/bin/env bash
# 스모크 검증 ② — 실제 gunicorn으로 기동해 HTTP 레벨 검증.
#
# 왜 필요한가: Flask 개발서버/test_client는 한글 헤더를 관대하게 통과시키지만
# gunicorn(Railway 운영 환경)은 latin-1 위반 시 500을 낸다. 배포 전 반드시 여기서 확인한다.
#
# 실행:  bash tools/smoke_gunicorn.sh
# 종료코드 0=통과, 1=실패.
#
# ⚠️ gunicorn은 Linux/macOS 전용이다. Windows에서는 실행되지 않으므로
#    클라우드 세션(Linux 컨테이너) 또는 WSL에서 돌릴 것.
#    Windows에서는 tools/smoke_headers.py 로 대체 검증한다.
#
# ⚠️ 사용하는 측정 파일은 tools/make_fixture.py 가 만든 합성 데이터이며 실제 CRMLN 결과가 아니다.
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

if ! python3 -c 'import gunicorn' 2>/dev/null; then
  echo "SKIP: gunicorn 미설치/미지원 환경입니다. (Windows라면 정상)"
  echo "      대신 'python tools/smoke_headers.py' 를 실행하세요."
  exit 0
fi

PORT="${PORT:-8931}"
TMP="$(mktemp -d)"
LOG="$TMP/gunicorn.log"

export SECRET_KEY='smoke-test-key'
export ADMIN_USERS='admin'
export ADMIN_PASSWORD='smoke-pw'
export USERS_FILE="$TMP/users.json"
export ROUNDS_FILE="$TMP/rounds.json"
unset DATABASE_URL

python3 tools/make_fixture.py --out "$TMP/fx" >/dev/null || { echo "FAIL: fixture 생성 실패"; exit 1; }

python3 -m gunicorn app:app --bind "127.0.0.1:$PORT" --workers 1 --timeout 60 \
  --log-file "$LOG" --access-logfile /dev/null >/dev/null 2>&1 &
PID=$!

cleanup() { kill "$PID" 2>/dev/null; wait "$PID" 2>/dev/null; rm -rf "$TMP"; }
trap cleanup EXIT

# 기동 대기
for _ in $(seq 1 60); do
  if python3 -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:$PORT/healthz',timeout=1)" 2>/dev/null; then
    break
  fi
  sleep 0.5
done

PORT="$PORT" FX="$TMP/fx" python3 - <<'PY'
import http.cookiejar, json, os, sys, urllib.request, uuid

PORT = os.environ['PORT']; FX = os.environ['FX']
BASE = 'http://127.0.0.1:%s' % PORT
opener = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

fails, n = [], [0]


def check(name, cond, detail=''):
    n[0] += 1
    print(('  PASS  ' if cond else '  FAIL  ') + name + ('' if cond else '  %s' % (detail,)))
    if not cond:
        fails.append(name)


def latin1_ok(resp, where):
    bad = []
    for k, v in resp.getheaders():
        for part in (k, v):
            try:
                part.encode('latin-1')
            except UnicodeEncodeError:
                bad.append('%s=%r' % (k, part))
    check('%s: 헤더 latin-1 안전(실 HTTP)' % where, not bad, bad)


def post_form(path, fields):
    b = uuid.uuid4().hex
    body = b''
    for k, v in fields.items():
        body += ('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (b, k, v)).encode()
    body += ('--%s--\r\n' % b).encode()
    req = urllib.request.Request(BASE + path, data=body,
                                 headers={'Content-Type': 'multipart/form-data; boundary=%s' % b})
    return opener.open(req, timeout=60)


def post_file(path, filename, data, fields):
    b = uuid.uuid4().hex
    body = b''
    for k, v in fields.items():
        body += ('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (b, k, v)).encode()
    body += ('--%s\r\nContent-Disposition: form-data; name="file"; filename="%s"\r\n'
             'Content-Type: application/octet-stream\r\n\r\n' % (b, filename)).encode()
    body += data + ('\r\n--%s--\r\n' % b).encode()
    req = urllib.request.Request(BASE + path, data=body,
                                 headers={'Content-Type': 'multipart/form-data; boundary=%s' % b})
    return opener.open(req, timeout=120)


print('[G1] gunicorn 기동 확인')
r = opener.open(BASE + '/healthz', timeout=10)
check('/healthz 200', r.status == 200, r.status)
check('/healthz ok=true', json.loads(r.read()) == {'ok': True})

print('[G2] 로그인')
r = post_form('/login', {'username': 'admin', 'password': 'smoke-pw'})
check('로그인 후 200', r.status == 200, r.status)
latin1_ok(r, '/login')

print('[G3] 업로드 — 한글 파일명 + 한글 응답 메시지 (500 재발 감시 지점)')
uc = open(os.path.join(FX, 'fixture_UC_합성.xlsx'), 'rb').read()
try:
    r = post_file('/rounds/add', '2026.7 측정결과_한글이름.xlsx', uc, {'label': '2026-07'})
except urllib.error.HTTPError as e:
    check('/rounds/add 200 (한글 헤더 500 아님)', False, 'HTTP %s: %s' % (e.code, e.read()[:300]))
else:
    check('/rounds/add 200 (한글 헤더 500 아님)', r.status == 200, r.status)
    latin1_ok(r, '/rounds/add')
    body = r.read()
    # ★ 2026-07-28: /rounds/add 는 누적 저장만 하고 **JSON**을 돌려준다.
    #   검토 엑셀 생성은 왼쪽 자동검토(/review) 전용이다. 예전처럼 zip(PK)이 오면 회귀다.
    check('JSON 반환(검토 엑셀 아님)', body[:1] == b'{' and body[:2] != b'PK', body[:16])
    jb = json.loads(body.decode('utf-8'))
    check('review_file=False 명시', jb.get('review_file') is False, jb)
    check('본문 stored=True', jb.get('stored') is True, jb)
    check('본문에 자동검토 안내', '자동 검토' in str(jb.get('note','')), jb.get('note'))
    xrr = r.getheader('X-Round-Result')
    check('X-Round-Result 존재', bool(xrr))
    if xrr:
        d = json.loads(xrr)
        check('stored=True', d.get('stored') is True, d)
        check('한글 메시지 복원', any('가' <= c <= '힣' for c in str(d.get('message', ''))), d.get('message'))

print('[G4] /rounds/data')
r = opener.open(BASE + '/rounds/data', timeout=30)
check('/rounds/data 200', r.status == 200, r.status)
latin1_ok(r, '/rounds/data')
p = json.loads(r.read().decode('utf-8'))
check('is_admin 주입', p.get('is_admin') is True, p.get('is_admin'))
check('2026.7 누적됨', '2026.7' in (p.get('round_labels') or []), p.get('round_labels'))

print('[G5] /rounds/stats 누적 통계')
r = opener.open(BASE + '/rounds/stats', timeout=30)
check('/rounds/stats 200', r.status == 200, r.status)
latin1_ok(r, '/rounds/stats')
S = json.loads(r.read().decode('utf-8'))
check('통계 payload 키 완비',
      all(k in S for k in ('backend', 'bias_summary', 'precision', 'drift', 'drop_pattern', 'note')),
      sorted(S))
check('방법론 경고문 포함', '판정' in (S.get('note') or ''), S.get('note'))

print('[G6] T1 소급 미리보기 — 실 gunicorn에서 한글 파일명 + 한글 응답')
r = post_file('/rounds/preview', '2025.1_과거_측정결과.xlsx', uc, {})
check('/rounds/preview 200', r.status == 200, r.status)
latin1_ok(r, '/rounds/preview')
P = json.loads(r.read().decode('utf-8'))
check('저장하지 않음(saved=False)', P.get('saved') is False, P.get('saved'))
check('한글 파일명에서 라벨 추정', P.get('suggested_label') == '2025.1', P.get('suggested_label'))
check('한글 안내문 복원', '확정' in (P.get('note') or ''), P.get('note'))

try:
    post_file('/rounds/add', 'a.xlsx', uc, {'label': '2025.1', 'reference': '1'})
    check('confirm 없는 소급 저장 거부', False, '400이어야 함')
except urllib.error.HTTPError as e:
    check('confirm 없는 소급 저장 거부 400', e.code == 400, e.code)
    check('거부 응답도 헤더 latin-1 안전', all(
        (str(v).encode('latin-1', 'strict') or True) for _k, v in e.headers.items()), '')

print('\n=== %d개 검사 중 실패 %d ===' % (n[0], len(fails)))
sys.exit(1 if fails else 0)
PY
RC=$?

if [ "$RC" -ne 0 ]; then
  echo "--- gunicorn 로그(마지막 30줄) ---"
  tail -30 "$LOG" 2>/dev/null
fi
exit "$RC"
