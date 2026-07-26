# tools/ — 배포 전 스모크 검증

과거에 실제로 터졌던 버그(§인수인계 §3)가 다시 나오지 않게 막는 최소 검증 세트입니다.
**수정 후 배포(push) 전에 돌리는 것을 습관화하세요.**

## 무엇을 막는가

| 스크립트 | 막는 것 |
|---|---|
| `smoke_headers.py` | **HTTP 헤더에 한글이 들어가 gunicorn에서 500** — 헤더 값을 직접 latin-1 인코딩해 검사. 라벨 정규화(`canon_label`)로 중복 회차가 안 생기는지, `/rounds/data`에 `is_admin`이 실리는지도 확인 |
| `smoke_gunicorn.sh` | 같은 검사를 **실제 gunicorn(Railway와 동일 환경)** 위에서 HTTP로 재확인. Flask 개발서버는 한글 헤더를 관대하게 통과시키므로 이 단계가 필요 |
| `smoke_tab6.py` | **⑥ 회차 누적분석 탭이 실제로 렌더되는지** — Chart.js 4개 캔버스가 빈 화면이 아닌지(픽셀 검사), 제출표 행·회차 서브탭·관리자 삭제표가 생기는지, 콘솔 에러가 없는지 |
| `make_fixture.py` | 위 검사들이 쓰는 **합성 측정지** 생성 |

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
