# tools/ — 배포 전 스모크 검증

과거에 실제로 터졌던 버그(§인수인계 §3)가 다시 나오지 않게 막는 최소 검증 세트입니다.
**수정 후 배포(push) 전에 돌리는 것을 습관화하세요.**

## 무엇을 막는가

| 스크립트 | 막는 것 |
|---|---|
| `smoke_headers.py` | **HTTP 헤더에 한글이 들어가 gunicorn에서 500** — 헤더 값을 직접 latin-1 인코딩해 검사. 라벨 정규화(`canon_label`)로 중복 회차가 안 생기는지, `/rounds/data`에 `is_admin`이 실리는지도 확인. **T1 소급 누적**: 라벨 자동추정 경계값, 최근 3년 연도 제한, `/rounds/preview`가 저장하지 않는지, 확인(confirm) 없이는 소급 저장이 거부되는지, **시드 값이 덮어써지지 않는지**, 참고용 소급이 드리프트에서 제외되는지 |
| `smoke_gunicorn.sh` | 같은 검사를 **실제 gunicorn(Railway와 동일 환경)** 위에서 HTTP로 재확인. Flask 개발서버는 한글 헤더를 관대하게 통과시키므로 이 단계가 필요 |
| `smoke_tab6.py` | **⑥ 회차 누적분석 탭이 실제로 렌더되는지** — Chart.js 4개 캔버스가 빈 화면이 아닌지(픽셀 검사), 제출표 행·회차 서브탭·관리자 삭제표가 생기는지, 콘솔 에러가 없는지 |
| `make_fixture.py` | 위 검사들이 쓰는 **합성 측정지** 생성. `build_dcm()`=3반복(구 레이아웃), `build_dcm4()`=**4반복·Day2 열 밀림·중복값 포함**(2026.7 실제 측정지에서 Day2가 조용히 누락됐던 버그의 회귀 fixture) |

`stats_queries.sql` 은 검증 스크립트가 아니라 **참조용 SQL 모음**입니다.
Postgres에서 `app_rounds.data`(JSONB)를 직접 임시 분석할 때 씁니다 — 전부 읽기 전용(SELECT)입니다.

```bash
psql "$DATABASE_URL" -f tools/stats_queries.sql
```

## 실행

```bash
python tools/smoke_headers.py     # 어디서나 (Windows 포함)
bash   tools/smoke_gunicorn.sh    # Linux/macOS/WSL 전용 (gunicorn 미지원 환경은 SKIP 처리)
python tools/smoke_tab6.py        # Playwright 필요
```

전부 종료코드 `0`이면 통과입니다.

준비물:

```bash
pip install -r requirements.txt
pip install playwright && python -m playwright install chromium   # smoke_tab6.py 용 (운영에는 불필요)
```

`smoke_tab6.py`는 Chart.js를 `tools/vendor/`에 한 번 캐시합니다.
cdnjs가 막힌 망에서는 npm 레지스트리(`npm pack chart.js@4.4.1`)로 자동 대체하고,
둘 다 막히면 브라우저가 CDN을 직접 로드하도록 둡니다.
`tools/vendor/`와 `tools/_fixtures/`는 `.gitignore` 대상입니다.

## ⚠️ 합성 데이터 경고

`make_fixture.py`가 만드는 숫자는 **레이아웃 검증용으로 지어낸 가짜 값**입니다.
실제 CRMLN 측정결과가 아니며, **판정·제출·보고에 절대 사용하지 마십시오.**
스모크 통과는 "코드가 죽지 않는다"는 뜻일 뿐, 측정 결과의 타당성과는 무관합니다.
최종 제출·판정은 CDC 참조법 회신 및 검토자 확인 후 확정합니다.
