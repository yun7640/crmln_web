# -*- coding: utf-8 -*-
"""스모크 검증 ③ — ⑥ 회차 누적분석 탭이 실제로 렌더되는지 (Playwright headless).

검사 항목:
  · 로그인 → /view (private/dashboard.html) 로드
  · ⑥ 탭 클릭 → initCum()이 /rounds/data fetch → Chart.js 4개 캔버스 렌더
  · 캔버스가 '빈 화면'이 아닌지(픽셀 분산으로 확인)
  · 회차 제출표에 행이 생기는지
  · 관리자 삭제표(#cumManage)가 is_admin일 때 렌더되는지
  · 콘솔 에러가 없는지

Chart.js는 CDN(cdnjs)에서 로드되므로, 오프라인/차단 환경 대비로 한 번 받아
tools/vendor/chart.umd.min.js 에 캐시한 뒤 page.route로 가로채 주입한다.

실행:
    pip install playwright && python -m playwright install chromium
    python tools/smoke_tab6.py
종료코드 0=통과, 1=실패.

⚠️ 사용하는 측정 파일은 tools/make_fixture.py 가 만든 합성 데이터이며 실제 CRMLN 결과가 아니다.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
VENDOR = os.path.join(HERE, 'vendor')
CDN = 'https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js'
CHART_LOCAL = os.path.join(VENDOR, 'chart.umd.min.js')
PORT = int(os.environ.get('PORT', '8932'))
BASE = 'http://127.0.0.1:%d' % PORT

fails, n = [], [0]


def check(name, cond, detail=''):
    n[0] += 1
    print(('  PASS  ' if cond else '  FAIL  ') + name + ('' if cond else '  %s' % (detail,)))
    if not cond:
        fails.append(name)


def ensure_chartjs():
    """Chart.js를 로컬에 캐시(최초 1회만 네트워크 사용).

    1순위: cdnjs 직접 다운로드.
    2순위: npm 레지스트리(`npm pack chart.js@4.4.1`) — CDN이 막힌 샌드박스/사내망 대비.
    둘 다 실패하면 False를 반환하고 브라우저가 CDN을 직접 로드하도록 둔다."""
    if os.path.exists(CHART_LOCAL) and os.path.getsize(CHART_LOCAL) > 50000:
        return True
    os.makedirs(VENDOR, exist_ok=True)
    try:
        with urllib.request.urlopen(CDN, timeout=20) as r:
            data = r.read()
        if len(data) >= 50000:
            with open(CHART_LOCAL, 'wb') as f:
                f.write(data)
            return True
    except Exception as e:
        print('  (cdnjs 실패: %s — npm 레지스트리로 재시도)' % e)
    try:
        work = tempfile.mkdtemp(prefix='chartjs_')
        subprocess.run(['npm', 'pack', 'chart.js@4.4.1', '--silent'],
                       cwd=work, check=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=180)
        import tarfile
        tgz = [f for f in os.listdir(work) if f.endswith('.tgz')][0]
        with tarfile.open(os.path.join(work, tgz)) as t:
            src = t.extractfile('package/dist/chart.umd.js').read()
        with open(CHART_LOCAL, 'wb') as f:
            f.write(src)
        shutil.rmtree(work, ignore_errors=True)
        print('  (Chart.js를 npm 레지스트리에서 받아 %s 에 캐시)' % os.path.relpath(CHART_LOCAL, ROOT))
        return True
    except Exception as e:
        print('  (Chart.js 캐시 실패: %s — CDN 직접 로드로 진행)' % e)
        return False


def start_server(tmp):
    env = dict(os.environ)
    env.update({
        'SECRET_KEY': 'smoke-test-key',
        'ADMIN_USERS': 'admin',
        'ADMIN_PASSWORD': 'smoke-pw',
        'USERS_FILE': os.path.join(tmp, 'users.json'),
        'ROUNDS_FILE': os.path.join(tmp, 'rounds.json'),
        'PORT': str(PORT),
    })
    env.pop('DATABASE_URL', None)
    try:
        import gunicorn  # noqa: F401
        cmd = [sys.executable, '-m', 'gunicorn', 'app:app', '--bind', '127.0.0.1:%d' % PORT,
               '--workers', '1', '--timeout', '60', '--access-logfile', os.devnull]
    except ImportError:  # Windows 등
        cmd = [sys.executable, '-c',
               'import app; app.app.run(host="127.0.0.1", port=%d, debug=False, use_reloader=False)' % PORT]
    p = subprocess.Popen(cmd, cwd=ROOT, env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    for _ in range(80):
        try:
            urllib.request.urlopen(BASE + '/healthz', timeout=1)
            return p
        except Exception:
            time.sleep(0.25)
    p.kill()
    raise RuntimeError('서버 기동 실패')


def seed_round(tmp):
    """합성 측정파일 1건을 업로드해 ⑥ 탭에 표시할 회차를 만든다."""
    sys.path.insert(0, HERE)
    import make_fixture
    fx = os.path.join(tmp, 'fx')
    os.makedirs(fx, exist_ok=True)
    uc = make_fixture.build_uc(os.path.join(fx, 'uc.xlsx'))
    import http.cookiejar
    import uuid
    op = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    b = uuid.uuid4().hex
    body = b''
    for k, v in (('username', 'admin'), ('password', 'smoke-pw')):
        body += ('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (b, k, v)).encode()
    body += ('--%s--\r\n' % b).encode()
    op.open(urllib.request.Request(BASE + '/login', data=body,
            headers={'Content-Type': 'multipart/form-data; boundary=%s' % b}), timeout=30)
    b = uuid.uuid4().hex
    body = ('--%s\r\nContent-Disposition: form-data; name="label"\r\n\r\n2026.7\r\n' % b).encode()
    body += ('--%s\r\nContent-Disposition: form-data; name="file"; filename="uc.xlsx"\r\n'
             'Content-Type: application/octet-stream\r\n\r\n' % b).encode()
    body += open(uc, 'rb').read() + ('\r\n--%s--\r\n' % b).encode()
    op.open(urllib.request.Request(BASE + '/rounds/add', data=body,
            headers={'Content-Type': 'multipart/form-data; boundary=%s' % b}), timeout=120)


def run_browser(have_local_chart):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        exe = os.environ.get('CHROMIUM_PATH', '/opt/pw-browsers/chromium')
        launch = {'headless': True}
        if os.path.exists(exe):
            launch['executable_path'] = exe
        try:
            browser = pw.chromium.launch(**launch)
        except Exception:
            browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})

        errors = []
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
        page.on('pageerror', lambda e: errors.append(str(e)))

        if have_local_chart:
            body = open(CHART_LOCAL, 'rb').read()
            page.route('**/cdnjs.cloudflare.com/**',
                       lambda route: route.fulfill(status=200, body=body,
                                                   content_type='application/javascript'))

        page.goto(BASE + '/login', wait_until='domcontentloaded')
        page.fill('input[name="username"]', 'admin')
        page.fill('input[name="password"]', 'smoke-pw')
        page.click('button[type="submit"], input[type="submit"]')
        page.wait_for_load_state('networkidle')

        page.goto(BASE + '/view', wait_until='networkidle')
        check('대시보드 로드 (탭 6개)', page.locator('#tabs button').count() == 6,
              page.locator('#tabs button').count())
        check('탭① 명칭 "HDL-C UC 측정결과 검토"',
              'HDL-C UC 측정결과 검토' in (page.locator('#tabs button').first.inner_text()),
              page.locator('#tabs button').first.inner_text())

        check('Chart.js 로드됨', page.evaluate('typeof window.Chart') == 'function',
              page.evaluate('typeof window.Chart'))

        page.click('#tabs button[data-tab="t6"]')
        page.wait_for_selector('#t6.active', timeout=10000)
        try:
            page.wait_for_function(
                "() => { const c = document.getElementById('cum_tcbf');"
                " return c && c.width > 10 && window.Chart && Chart.getChart(c); }",
                timeout=20000)
        except Exception as e:
            check('⑥ 탭 Chart 인스턴스 생성', False, e)

        for cid, title in (('cum_tcbf', 'NIST(TC)·BF'), ('cum_hdlldl', 'HDL·LDL'),
                           ('cum_ps', 'PS 평가'), ('cum_dcm', 'HDLC-DCM')):
            info = page.evaluate("""(id) => {
              const c = document.getElementById(id);
              if (!c) return {ok:false, why:'no canvas'};
              const ch = window.Chart && Chart.getChart(c);
              const g = c.getContext('2d');
              const d = g.getImageData(0, 0, c.width, c.height).data;
              let ink = 0;
              for (let i = 3; i < d.length; i += 4) if (d[i] > 0) ink++;
              return {ok:true, w:c.width, h:c.height, ink:ink,
                      pts: ch ? (ch.data.datasets||[]).reduce((a,s)=>a+(s.data||[]).length,0) : 0};
            }""", cid)
            check('캔버스 %s 그려짐(%s)' % (cid, title),
                  bool(info.get('ok')) and info.get('ink', 0) > 500 and info.get('pts', 0) > 0, info)

        rows = page.evaluate("() => document.querySelectorAll('#cumBody table tr').length")
        check('회차 제출표에 행 존재', rows > 1, rows)
        # 회차 서브탭은 <button>이 아니라 <span class="cum-subtab">로 생성된다.
        tabs = page.evaluate("() => document.querySelectorAll('#cumTabs .cum-subtab').length")
        check('회차 서브탭 존재', tabs >= 1, tabs)
        manage = page.evaluate("() => (document.getElementById('cumManage')||{}).innerHTML || ''")
        check('관리자 삭제표 렌더(is_admin)', len(manage.strip()) > 0, len(manage))

        # ── 누적 통계 분석 섹션 (/rounds/stats) ──
        page.wait_for_function(
            "() => { const e = document.getElementById('cumStats');"
            " return e && e.querySelectorAll('table').length >= 3; }", timeout=20000)
        st = page.evaluate("""() => {
          const e = document.getElementById('cumStats');
          const b = document.getElementById('cumStatsBackend');
          return {tables: e.querySelectorAll('table').length,
                  bars: e.querySelectorAll('.cum-bar').length,
                  rows: e.querySelectorAll('tbody tr').length,
                  badge: (b && b.textContent) || '',
                  text: e.innerText};
        }""")
        check('통계 표 3개 이상 렌더', st['tables'] >= 3, st['tables'])
        check('마진 바 렌더', st['bars'] > 0, st['bars'])
        check('통계 표에 데이터 행 존재', st['rows'] >= 4, st['rows'])
        check('저장 백엔드 배지 표시', '회차' in st['badge'], st['badge'])
        check('방법론 경고문 노출(채택에 관여하지 않음)',
              '판정' in st['text'] and '채택' in st['text'], st['text'][:120])
        check('회차 1개 → 드리프트 판단 보류 표기', '판단 보류' in st['text'], st['text'][:200])

        check('콘솔 에러 없음', not errors, errors[:3])

        browser.close()


def main():
    have = ensure_chartjs()
    tmp = tempfile.mkdtemp(prefix='crmln_tab6_')
    p = None
    try:
        p = start_server(tmp)
        seed_round(tmp)
        run_browser(have)
    finally:
        if p:
            p.kill()
        shutil.rmtree(tmp, ignore_errors=True)
    print('\n=== %d개 검사 중 실패 %d ===' % (n[0], len(fails)))
    if fails:
        for f in fails:
            print('  - %s' % f)
        return 1
    print('전부 통과')
    return 0


if __name__ == '__main__':
    sys.exit(main())
