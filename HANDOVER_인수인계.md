# CRMLN 대시보드 프로젝트 · 인수인계 (HANDOVER)

> **새 세션 사용법 (★ 2026-07-26 갱신):**
>
> **이 프로젝트는 "내 컴퓨터에서 실행(On your computer)"으로 시작하세요.** 그래야 Claude가 커밋·푸시까지 처리합니다.
>
> 1. Claude **데스크톱 앱**에서 **새 Cowork 작업**을 시작합니다.
>    · 실행 위치는 **작업을 시작하는 시점에만** 정해집니다. 이미 돌아가는 세션은 옮길 수 없습니다.
>    · 우측 상단 **"Run this task" → "On your computer"**, 또는
>      **Settings → Cowork → "Run new tasks in the cloud" 를 꺼두면** 새 작업이 기본적으로 내 컴퓨터에서 실행됩니다.
>    · 웹·모바일에서 시작한 작업은 항상 클라우드입니다(데스크톱 앱 전용 기능).
> 2. 폴더는 **실제 git clone 경로**를 연결합니다: `C:\Users\yun76\Documents\GitHub\crmln_web`
> 3. 이렇게 요청합니다:
>    "이 폴더의 `HANDOVER_인수인계.md`를 읽고 지금까지 상태를 파악한 다음 이어서 진행해줘.
>     파일 수정은 이 폴더에 직접 반영하고 커밋·푸시까지 처리해줘."
> 4. Claude가 파일 수정 → `git commit` 까지 수행.
>
> **⚠️ 2026-07-26 실측 확인: on-computer 세션이어도 `git push` 는 Claude가 할 수 없습니다.**
> Claude의 셸은 폴더만 마운트된 별도 리눅스 샌드박스라 **Windows 자격증명 관리자의 GitHub 토큰이 보이지 않습니다**
> (`git push` → `could not read Username for 'https://github.com'`).
> `git ls-remote`(공개 읽기)와 `git commit`(로컬)은 정상 동작합니다.
> ⇒ **역할 분담: Claude = 수정 + 검증 + commit / 사용자 = GitHub Desktop에서 Push 버튼.**
> Push 후 Railway가 자동 재배포합니다.
>
> 참고: 이 샌드박스는 마운트 폴더의 **파일 삭제가 기본 차단**되어 있습니다
> (`rm` → `Operation not permitted`). git 이 남긴 `.git/index.lock`·`tmp_obj_*` 정리에 필요하므로,
> 그런 오류가 나면 Claude가 삭제 권한을 요청하고 사용자가 1회 승인하면 됩니다.
>
> **클라우드 세션으로 시작해버렸다면** (§11 아래쪽 참조)
> 클라우드 세션은 사용자 PC에서 셸(git)을 실행할 수 없어 **커밋·푸시를 대신할 수 없습니다.**
> 이때는 Claude가 `device_request_folder_access`로 위 clone 폴더 권한을 받아 파일만 직접 쓰고,
> **마지막 Commit + Push 는 사용자가 GitHub Desktop에서** 눌러야 합니다.

작성일: 2026-07-26 · 최신 버전: **v9** (문서 개정 v9.1)

---

## 0. 사용자 · 도메인

- 사용자: KDCA 진단검사의학 표준검사실(NMRL, **Lab 509**) 담당. 진단검사의학과 전문의(clinical pathologist, MD/PhD).
- 전문: laboratory medicine, clinical chemistry, TDM, mass spectrometry, 표준화·조화(standardization/harmonization).
- 목적: **CRMLN**(Cholesterol Reference Method Laboratory Network) 측정결과 검토 및 CRMLN member laboratory 수행능 평가 제출 지원. 평가는 **연 2회(반기)** 정기 시행.
- 사용자 선호: 관련 Skill이 있으면 사용하고, 사용 시 "Used Skills" 줄을 포함.

### ⚠️ 반드시 지켜야 할 방법론 원칙
- **결과를 유리하게 만들기 위한 선택은 절대 지양.** 반복 측정(R1/R2/R3) 중 채택은 오직 **정밀도/QC 기반**(median 이상치 제외)으로만 한다. 편향을 줄이거나 판정을 통과시키기 위한 선택 금지.
- 최종 제출·판정은 **CDC 참조법 회신 및 검토자 확인 후 확정**. 본 도구는 검토 보조용.

---

## 1. 제품 개요

Flask 웹앱. 로그인 후 (1) CRMLN 대시보드 열람, (2) 측정 엑셀 업로드 → 자동 검토파일 생성, (3) **회차 누적분석**(연 2회 경향 + 제출결과)을 제공.

- **소스(GitHub):** `yun7640/crmln_web`
- **배포(Railway):** GitHub push → 자동 재배포. 공개 URL 예: `https://web-production-8f1b1c.up.railway.app/`
- **저장소(Storage):** **Postgres**(Railway) 우선, 미설정 시 파일 폴백.
- 로컬 clone 경로(사용자 PC): `C:\Users\yun76\Documents\GitHub\crmln_web`

---

## 2. 저장소 파일 구조 (리포지토리 루트 = 앱 루트)

```
app.py                     Flask 라우트(로그인·세션·업로드·회차·관리자)
review_engine.py           엑셀 처리: UC(β-정량)·DCM 자동감지, 선택 로직, 검토시트 생성, summarize_round
rounds.py                  회차 누적 저장소(Postgres/파일) + 과거 시드 병합 + dashboard_payload + 라벨 정규화(canon_label)
                           + T1 소급 누적: infer_labels·label_status·seed_compare·year_guard·is_reference
db.py                      Postgres 계층(app_users, app_rounds) + 연결 실패 시 폴백
auth.py                    사용자 저장소·로그인(Postgres/파일, 관리자 CRUD)
templates/
  base.html                공통 레이아웃(상단 내비)
  login.html               로그인
  dashboard.html           로그인 후 화면(왼쪽 업로드 패널 + 오른쪽 iframe)
  cumulative.html          /rounds 전체페이지(회차 누적분석, 관리자 백업/삭제)
  manual.html              사용자 설명서
  admin.html               관리자(사용자 CRUD, 저장소 배지)
  message.html
private/
  dashboard.html           ★ iframe에 뜨는 6탭 CRMLN 대시보드(커스텀 SVG 차트). ⑥ 탭 = 회차 누적분석(Chart.js, /rounds/data fetch)
assets/
  select_template.xlsx     동적 선택 시트 템플릿(수식·조건부서식 보존, 값 주입 방식)
  history_seed.json        과거 이력 2023.1–2026.7(QC bias·PS평가·DCM평가·기준) 시드
stats.py                   ★ 누적 통계(bias 요약·정밀도·드리프트·제외 index 분포). 모니터링 전용
tools/                     ★ 배포 전 스모크 검증 (tools/README.md 참조)
  make_fixture.py          합성 측정지 생성(UC/DCM) — ⚠️ 가짜 데이터, 판정·제출 금지
  smoke_headers.py         앱 기능 + HTTP 헤더 latin-1 안전성 (63검사, Windows 포함 어디서나)
  smoke_gunicorn.sh        실제 gunicorn 기동 후 HTTP 레벨 재검증 (18검사, Linux/WSL 전용)
  smoke_tab6.py            Playwright headless로 ⑥탭 Chart.js·통계 섹션 렌더 검증 (17검사)
  stats_queries.sql        Postgres JSONB 직접 분석용 참조 쿼리 7종(읽기 전용)
  README.md                실행법·막는 버그 목록
requirements.txt  Procfile  railway.json  runtime.txt  README.md  make_user.py
.gitignore                 (tools/vendor/, tools/_fixtures/ 제외 포함)
HANDOVER_인수인계.md        (이 문서)
```

주의: `.gitignore`가 `*.xlsx`를 무시하되 `!assets/*.xlsx`로 템플릿만 포함. `data/`(로컬 저장), `users.json`은 커밋 제외. `assets/select_template.xlsx`와 `assets/history_seed.json`은 반드시 리포에 포함되어야 함(앱 동작 필수).

> **★ 리포 추적 상태(2026-07-26 갱신):** T0 완료 — `.gitignore`, `HANDOVER_인수인계.md` 커밋됨(`17b6602`).
> `static/`은 여전히 리포에 없으며 앱 동작에도 불필요(Drive 사본에만 존재).

---

## 3. 라우트(app.py)

- `/login` `/logout` — 세션 로그인.
- `/` — dashboard.html(업로드 패널 + iframe). `/view` — private/dashboard.html 제공.
- `/review` (POST) — 단발 업로드 → 검토파일 반환(누적 저장 안 함). 헤더 `X-Review-Summary`.
- `/rounds` — cumulative.html(전체 페이지). `/rounds/data` — 누적 payload JSON(+`is_admin`).
- `/rounds/stats` — 누적 통계 JSON(stats.py). 모니터링·진단용, 채택 로직 비관여.
- `/rounds/preview` (POST) — **과거 회차 소급 1단계. 저장하지 않음.** 라벨 후보(추정 근거 포함)·기존 라벨 상태·
  시드↔소급 대조·연도 제한 판정을 JSON으로 반환. 저장은 사용자가 라벨 확정 후 `/rounds/add`로.
- `/rounds/add` (POST) — 업로드 → **summarize_round로 누적 저장 + process로 검토파일 반환**. 헤더 `X-Round-Result`.
  `reference=1`(소급)이면 `confirm=1` 필수, 연도 제한 적용, 검토 엑셀 없이 JSON만 반환.
- `/rounds/delete` (POST, admin) — 회차/모드 삭제. `ajax=1`이면 JSON 반환, 아니면 redirect.
- `/rounds/export` `/rounds/import` (admin) — 누적 백업 JSON.
- `/admin/*` (admin) — 사용자 CRUD.
- `/healthz`.

### ★ 과거에 겪은 버그(재발 주의)
- **HTTP 응답 헤더에 한글 금지.** 헤더는 latin-1만 허용 → gunicorn(Railway)에서 500. `X-Round-Result` 등 헤더 JSON은 반드시 `json.dumps(..., ensure_ascii=True)` (본문 JSON은 UTF-8 OK). 로컬 `test_client`는 관대해서 통과하므로 **gunicorn으로 검증**할 것.
- openpyxl 주입 시 `MergedCell` 쓰기 금지(가드 필요).
- DCM 파일 bias는 수식이 아닌 **원자료(A.value + R1/R2/R3)로 계산**.

---

## 4. 측정 처리(review_engine.py) 핵심

- **판정 기준(MEMBER):** TC ±1%, BF ±2%(LDL 준용), HDL ±1 mg/dL, LDL ±2%.
- **β-정량:** BF(하부분획)=LDL+HDL; LDL-C=BF−HDL.
- **UC 선택 로직(combo_pick):** CS 검체 Day별 R1/R2/R3 중 BF·HDL median 상대편차 합이 최대인 1개 제외 → 2개 채택. **BF·HDL·LDL 동일 R index 잠금**(LDL=BF−HDL 정합). QC·Control은 제출 안 함(전체 3반복 사용, batch 정확도 확인용).
- **DCM(_is_dcm):** 측정지 7행 2열이 'HDL Control'로 시작하면 DCM. 행 구성: 5=NIST(TC),6=CFS21-01(TC),7=HDL CFS21-01(HDL Control),8=HDL QC2(HDL),9–12=CS01–CS04.
  · **★ 열은 하드코딩하지 않는다.** `_dcm_day_cols()`가 헤더 행(`DCM_HEADER_ROW=4`)의 `A.value`·`R1…Rn`을
    찾아 Day1/Day2 블록 열을 자동 탐지한다(구 3반복 레이아웃 = Day1 D/E,F,G · Day2 P/Q,R,S,
    2026.7 4반복 레이아웃 = Day1 D/E,F,G,H · Day2 Q/R,S,T,U). 헤더가 없으면 구 하드코딩으로 폴백.
  · **동일검체 반복 CV>15%인 Day는 정렬오류로 제외(DCM_CV_GUARD=15).**
  · **_dcm_pick(2/n):** median 편차가 큰 순으로 **n−2개** 제외 → 2개 평균 채택(3반복=1개, 4반복=2개 제외).
    편차 동점 시 **정렬 순위가 중앙에서 먼 쪽을 먼저 제외** — 중복 측정값 때문에 CV가 인위적으로 0이 되는 것을 막는다.
    반환하는 `drop`은 **리스트**다(구 데이터는 정수이므로 소비처에서 양쪽 처리).
- **시트명:** UC 검토 시트 = `HDLC UC 검토`(구 "2026.7 측정결과 검토"), DCM = `HDLC DCM 검토`. 동적 선택 시트 = `2026.7_결과선택`(템플릿 `제출결과_선택검토` 리네임).
- **summarize_round(bytes):** UC/DCM 자동감지 → 누적 저장용 compact dict(qc, qc_bias, samples, n_* 등) 반환.
- HDLC-DCM 참조값(PS0126): CS01=55.66, CS02=46.50, CS03=35.98, CS04=60.08 mg/dL. Lab 509는 2026.1 DCM 미인증(bias −1.50).

---

## 5. 회차 누적(rounds.py, db.py)

- `add_round(label, summary, ...)` — 라벨을 **canon_label로 정규화**(2026-07/2026.07/2026-07-01/2026.7 → `2026.7`, 2026-01 → `2026.1`; 반기 표준 YYYY.1/YYYY.7) 후 (label, mode) 업서트. **중복 방지 목적.**
- `dashboard_payload()` — history_seed(2023.1–2026.7) + 업로드 회차 병합. surveys 축, qc_bias 트렌드(NIST/BF/HDL/LDL %), ps_eval, dcm_eval, dcm_qc_upload, uploaded(회차별 제출표), round_labels.
- Postgres 테이블: `app_users(username, pw, admin)`, `app_rounds(label, mode, data jsonb, meta jsonb, updated_at)`. `data`는 회차 요약 → **SQL로 추가 통계 분석 가능**.
- 저장 백엔드 판별 `backend()` → 'postgres'/'file'. 화면 상단 배지(🟢 Postgres / 📁 파일)로 표시.

---

## 6. private/dashboard.html (6탭 대시보드)

- 탭: ① **HDL-C UC 측정결과 검토** ② 평가보고서 경향분석 ③ QC–평가 관련성 ④ HDL-C DCM ⑤ BF 하부분획 ⑥ **회차 누적분석**.
- ④ HDL-C DCM 탭 하단에 **CRMLN 제출 결과 선택(R1–R4 → 2개)** 표가 있음(①탭 ③ 선택 표와 동일 방식).
  원자료는 파일 내 `const DCM_SEL` 상수. **채택 JS(`dcmPick`)는 서버 `review_engine._dcm_pick`과 반드시 동일하게 유지할 것**
  (수정 시 Python↔JS 교차 검증 필요 — v13에서 616건 일치 확인).
- ①–⑤: 커스텀 인라인 SVG 차트(외부 라이브러리 없음). 데이터는 파일 내 인라인 JS 상수.
- ④ 탭에는 **'DCM QC bias vs CRMLN 평가 bias 대응'** 그래프도 있음(내부 QC 실선 / CDC 평가 점선, 공통 mg/dL 축).
  내부 QC 과거값은 `/rounds/data`의 `dcm_qc_upload`에서 비동기로 채우며, **없는 회차는 추정하지 않고 선을 끊는다.**
- ⑥ 회차 누적분석: 별도 `#t6` 패널 + `cum-` 접두 스코프 CSS. **Chart.js(CDN)** 로드, 탭 첫 클릭 시 `initCum()`이 `/rounds/data`를 fetch해서 렌더. 경향 4그래프 + 회차 제출표(UC/DCM 선택 2/3) + **관리자용 중복 삭제표**(is_admin일 때만, `/rounds/delete` ajax). 업로드(회차 추가)도 이 탭에서 가능.
- 탭 전환 JS 배열에 't6' 포함되어야 함. 다크모드 전환 시 ⑥ 차트 색 갱신 로직 있음.

---

## 7. 배포 · 환경변수 (Railway)

1. GitHub `yun7640/crmln_web`에 push → Railway 자동 재배포(Nixpacks, `Procfile`: `gunicorn app:app`).
2. Variables:
   - `SECRET_KEY` (필수, 세션 서명)
   - `ADMIN_USERS` = `yeomin`(콤마 목록) — 관리자 지정
   - `ADMIN_PASSWORD` 또는 `USERS_JSON` — 최초 관리자 시드
   - `DATABASE_URL` = `${{Postgres.DATABASE_URL}}` (참조변수) — **Postgres 저장(권장).** 있으면 테이블 자동 생성, 재배포에도 사용자·회차 유지. 없으면 파일/Volume 필요.
3. 확인: 로그인 후 관리자/회차 화면 상단 `🟢 Postgres` 배지.

로컬 실행: `pip install -r requirements.txt` → `python app.py`(포트 8000). psycopg2-binary 포함.

---

## 8. 검증 방법(권장 습관)

- Flask `app.test_client()`로 기능 스모크(백그라운드 서버는 이 샌드박스에서 불안정했음).
- 헤더/응답은 **실제 gunicorn**으로도 확인(한글 헤더 버그 재발 방지).
- **★ 조건부 서식 색상은 렌더링해서 눈으로 확인할 것.** dxf는 `bgColor`로 렌더되므로 `fgColor`만 넣으면
  파일은 정상이지만 색이 안 보인다. PDF→PNG로 뽑아 확인하면 확실하다:
  `soffice --headless --convert-to pdf ...` → `pdftoppm -png -r 130 x.pdf out` → 색상 픽셀 카운트/육안 확인.
  (숨김 시트로 만들어도 LibreOffice는 PDF에 포함하므로 페이지 번호로 찾을 것. 참조 시트를 **삭제하면 `#NAME?`** 이 된다)
- **★ 엑셀 수식 시트는 반드시 실제 재계산해서 검증할 것.** openpyxl은 수식을 계산하지 않으므로
  수식이 틀려도 파일은 정상으로 보인다. LibreOffice headless로 변환하면 계산된 값을 읽을 수 있다:
  `soffice --headless --norestore -env:UserInstallation=file:///tmp/lo --convert-to xlsx --outdir OUT IN.xlsx`
  → `openpyxl.load_workbook(..., data_only=True)`로 값 확인 → 서버 계산값과 대조.
  (v14에서 이 방법으로 헬퍼 열 충돌·부동소수 동점 두 건을 잡았음)
- **화면 JS와 서버 Python이 같은 로직을 구현하면 교차 검증할 것.** 실제 데이터 + 무작위 케이스를
  Python으로 계산해 JSON으로 떨어뜨리고 `node`로 JS 함수를 돌려 비교(v13에서 616건, v14에서 40건).
- ⑥ 탭 렌더는 Chart.js를 로컬 vendoring 후 Playwright headless로 캔버스 픽셀/표 행수 확인(오프라인 CDN 차단 대비).
- Postgres 경로는 로컬 Postgres 띄워 저장·조회·정규화·삭제까지 확인.

---

## 9. 최근 변경 이력

- v6: Postgres 계층(db.py) 도입, auth·rounds DB 연동, 파일 폴백.
- v7: private/dashboard.html에 ⑥ 회차 누적분석 탭 통합.
- v8: 업로드 500 수정(`X-Round-Result` 헤더 `ensure_ascii=True`).
- **v9(현재):** ⑥ 탭 회차 **중복 삭제 UI(관리자)** + **라벨 자동 정규화(canon_label)** + 탭① 명칭 "HDL-C UC 측정결과 검토".
  - 2026-07-26 확인: GitHub main `231ea36` = v9. `rounds.py`에 `canon_label`, `app.py` `/rounds/data`에 `is_admin` 주입,
    `/rounds/delete`에 `ajax` 분기, `private/dashboard.html`에 `initCum`·삭제표 모두 반영되어 있음.
- v9.1(문서만): 리포 추적 상태 확인, 다음 작업 T0–T4 확정, §12 폴더 구분표 추가.
- v9.2(문서만, 2026-07-26): on-computer 실행 옵션이 **이 계정에서 제공되지 않음**을 확인 →
  §11을 "클라우드 세션 + 로컬 폴더 쓰기 권한" 워크플로로 교체. CRLF/LF 비교 주의사항 추가.
  로컬 작업트리(`C:\Users\yun76\Documents\GitHub\crmln_web`)가 GitHub main `231ea36`과 **내용 동일**(줄바꿈 차이만) 확인.
  T0 착수: `.gitignore`, `HANDOVER_인수인계.md`를 리포 폴더에 배치.
- **v10 (2026-07-26): T0 + T4 완료.** `.gitignore`·`HANDOVER` 커밋(`17b6602`), `tools/` 스모크 검증 세트 추가(66검사 통과).
  검증 중 확인된 사실: `/review`·`/rounds/add` 모두 헤더 latin-1 안전, canon_label 정상,
  ⑥탭 Chart.js 4개 캔버스 정상 렌더, 콘솔 에러 없음. **현재 코드에서 재발 버그 없음.**
  origin/main `a2d2ee8`에 반영 확인, Railway 배포 정상(`/healthz` → `{"ok":true}`).
- **v11.1 (2026-07-26, 문서만):** 사용자가 Cowork 설정에서 on-computer 실행을 활성화 →
  문서 맨 위 사용법과 §11을 (A) on-computer 권장 / (B) 클라우드 폴백 2단 구조로 재작성.
- **v11.2 (2026-07-26): T2 변경분 커밋.** 미커밋 상태였던 `stats.py`·`/rounds/stats`·⑥탭 통계 섹션·
  `tools/stats_queries.sql` 및 스모크 확장분을 검증 후 커밋(9개 파일, +662/−35).
  · 검증: `smoke_headers.py` **63/63 통과**, `smoke_gunicorn.sh` **18/18 통과**(실 gunicorn, 한글 헤더 latin-1 안전 재확인).
  · `smoke_tab6.py`는 샌드박스 네트워크 allowlist가 Chromium 바이너리 다운로드를 차단해 **실행 불가 → SKIP**.
    대체 정적 검증 수행: `node --check`로 `private/dashboard.html` 인라인 `<script>` 2블록 문법 통과,
    ⑥탭 통계 DOM(`#cumStats`·`#cumStatsBackend`·`loadStats`·`statsHTML`·`/rounds/stats` fetch)과
    방법론 경고 문구 10종 존재 확인, `stats_queries.sql` 전량 SELECT 전용 확인.
    ⚠️ **브라우저 실제 렌더 검증은 미수행** — 배포 후 공개 URL ⑥탭에서 눈으로 확인 필요.
  · **줄바꿈 문제 해소:** 리포 로컬에 `core.autocrlf=input` 설정. 이제 CRLF 잡음 없이 실제 변경 파일만 스테이징됨
    (설정 전에는 25개 파일이 전부 수정된 것처럼 보였음). 이 설정은 `.git/config`에 남겨둠.
- **v10.1 (2026-07-26): T3 완료.** Drive `crmln-app` 사본 전수 대조 후 폐기 결정(고유 파일 0개).
  경고 파일 배치, §12 폴더표 정리. 폴더 실제 삭제는 사용자 조치 대기.
- **v11 (2026-07-26): T2 완료.** `stats.py` 신설, `/rounds/stats` 라우트, ⑥탭 통계 섹션,
  `tools/stats_queries.sql`(7종). 스모크 **98검사**(63+18+17) 전부 통과.
  로컬 Postgres 16을 띄워 **Postgres 백엔드 경로와 SQL 쿼리 전량을 실제 실행 검증**.
  · 검증 중 확인: `drift`를 UC/DCM 합산하면 같은 라벨이 중복되어 기울기가 왜곡됨 → **모드별 분리**로 수정.
  · Postgres `round()`와 Python `round()`(banker's)의 3째 자리 ±0.001 차이는 SQL 파일에 주석으로 명시.

- **v12 (2026-07-26): T1 완료 — 과거 회차 소급 누적 + 시드 덮어쓰기 버그 수정.**
  `rounds.py`에 `infer_labels`·`label_status`·`seed_compare`·`year_guard`·`min_backfill_year`·`is_reference` 신설,
  `add_round(reference=, date_certain=)` 확장, `dashboard_payload`가 시드를 덮어쓰지 않도록 수정
  (`points_seed`/`points_upload`/`conflicts` 분리). `app.py`에 `/rounds/preview` 추가.
  `stats.py`는 참고용 소급을 드리프트에서 제외하고 각 행에 `reference` 표시.
  ⑥탭에 소급 누적 패널 + 시드↔소급 대조표 + 경향 그래프 두 계열 병기.
  · **사용자 확정 정책:** 과거 자료는 **참고용**으로만 누적. 측정 시점이 불확실하면 **최근 3년만** 소급 적용.
  · 검증: `smoke_headers.py` **104/104**, `smoke_gunicorn.sh` **25/25** 통과(실 gunicorn).
    Postgres 저장 형태(레코드 최상위에 `reference`가 없고 요약 JSONB 안에만 있는 형태)를 재현해
    참고용 판정·드리프트 제외가 동작함을 확인. `smoke_tab6.py`는 여전히 SKIP(아래 §11 참조) —
    `node --check` 문법 검증 + ⑥탭 DOM·문구 12종 정적 확인으로 대체.

- **v13 (2026-07-26): HDL-C DCM 제출 선택(2/4) + Day2 누락 버그 수정.** ★ 중요
  · **[버그] DCM Day2가 조용히 누락되고 있었음.** `_parse_dcm`이 Day2를 P/Q/R/S열로 하드코딩했는데,
    2026.7 측정지는 CS 검체 반복이 4개(R1–R4)로 늘어 Day2 블록이 **한 칸 밀린 Q/R/S/T/U**였음.
    그 결과 `summarize_round`가 **Day1만 4건, Day2는 0건**을 반환하고도 오류를 내지 않았음.
    → `_dcm_day_cols()`가 헤더 행(4행)의 `A.value`·`R1…Rn`을 찾아 **열을 자동 탐지**하도록 교체.
      헤더가 없으면 종전 하드코딩으로 폴백하므로 과거 파일도 그대로 읽힘.
    → 관리물질 이름도 Day 블록별 열에서 읽음(Day1 NIST1 / Day2 NIST2 구분).
  · **[버그] `_median(a)`가 `sorted(a)[1]` 하드코딩**이었음. n=3에서는 맞지만 4반복에서는
    "2번째 작은 값"이 median이 되어 이상치 판정이 왜곡됨 → 일반 median으로 교체(n=3 결과는 동일, 회귀 검증함).
  · **채택 규칙 2/n (사용자 확정):** CS 검체 반복이 4개이므로 **median 편차가 큰 순으로 n−2개 제외**.
    ★ 동점 처리 주의 — 같은 값이 중복 측정되면 편차 동점이 생기고, 단순 index 순으로 자르면
    **동일한 두 값이 채택되어 CV가 0**으로 나옴(정밀도가 실제보다 좋아 보임 → §0 위반).
    그래서 편차 동점 시 **정렬 순위가 중앙에서 먼 쪽을 먼저 제외**한다(= 짝수 n에서 "순위 중앙 2개 채택").
    실제 2026.7 데이터에서 CS03 Day2·CS04 Day1이 이 경우에 해당했음.
  · `samples[].drop`이 **정수 → 리스트**로 변경됨(4반복은 2개 제외). `stats.drop_pattern`·⑥탭은
    구 정수 형식도 함께 처리하며, 균등 기대치는 실제 반복 개수(3 또는 4)로 계산.
  · **④ HDL-C DCM 탭에 "CRMLN 제출 결과 선택" 표 추가** — ③ UC 탭과 동일 방식.
    Day1·Day2 병렬 표(측정지 배열 재현), 채택=굵게/제외=취소선, HDL Control ±1 mg/dL 유효성 게이트,
    검체별 제출 요약(Day1·Day2 채택값·Day차·평균). 기본은 정밀도(median) 고정이고
    민감도 옵션(최소분산쌍·높은값/낮은값 우선)은 선택 시 **경고 배너**가 뜸.
    DCM은 HDL-C 단일 항목이라 UC의 BF·HDL·LDL index 잠금은 적용하지 않음.
  · 화면의 JS 채택 로직과 서버 `_dcm_pick`이 어긋나면 안 되므로, 실제 데이터 16건 + 무작위 600건
    **총 616건을 Python↔JS 교차 실행해 채택 index·채택값이 완전히 일치함을 확인**.
  · 검증: `smoke_headers.py` **132/132**, `smoke_gunicorn.sh` **25/25**.
    `tools/make_fixture.py`에 `build_dcm4()`(4반복·Day2 밀림·중복값 포함) 추가 — 이 버그의 회귀 fixture.

- **v14 (2026-07-26): DCM 검토파일에 [검토_가이드]·[결과선택] 시트 추가 + ④탭 QC↔평가 대응 그래프.**
  · **DCM 검토파일이 UC와 동일한 구성이 되었음** — 종전에는 `HDLC DCM 검토` 한 장뿐이었고
    `_process_dcm`이 `검토_가이드`를 **지우기만** 했음. 이제 `_build_dcm_select()`·`_build_dcm_guide()`로 생성.
    출력 시트 순서: 검토_가이드 → RESULT_DAY1/2 → 결과정리 → **2026.7_결과선택** → HDLC DCM 검토.
  · **[결과선택] 시트는 UC와 같은 수식 기반 동적 시트.** 측정 시트를 참조하므로 값만 바꿔도 재계산되고,
    C4 드롭다운(6종: 정밀도 기본 / 최소분산쌍 / 높은값·낮은값 우선 / 전체평균 / 수동지정)으로 채택이 즉시 바뀜.
    채택=노란색, 제외=회색 취소선, bias 한계 초과=빨강. ② 제출용 요약, ③ 수동 지정 부록 포함.
  · **★ 검증 열(자기대조).** 시트 수식과 서버 `_dcm_pick` 결과가 어긋나면 안 되므로,
    서버 계산값을 같은 행에 적어 두고 `일치/불일치`를 자동 표시한다. **"불일치"가 보이면 시트 수식을 신뢰하지 말 것.**
  · 개발 중 이 검증 열이 실제로 두 건의 오류를 잡았음:
    ① **헬퍼 열 충돌** — Day1 헬퍼(44~58)와 Day2 헬퍼(56~)가 겹쳐 Day2의 `n` 수식이 Day1의 '기본 drop2'를
       덮어써 8건 중 7건이 오답이었음 → `H_DCM_SEL=(44,60,15,90)` 상수로 분리하고 스모크에서 겹침을 검사.
    ② **최소분산쌍 동점** — 인접 간격이 1e-13 수준으로 같아 엑셀과 JS가 다른 쌍을 골랐음 →
       양쪽 모두 **9자리 반올림 비교 + 동점 시 중앙 쌍 우선**으로 규칙을 명시·통일.
  · 검증 방법: **LibreOffice headless로 실제 재계산**한 뒤 서버 값과 대조. 옵션 5종 × 8행 = **40건 전부 일치**.
    (openpyxl은 수식을 계산하지 않으므로 수식 시트는 반드시 이렇게 검증할 것)
  · **④탭에 'DCM QC bias vs CRMLN 평가 bias 대응' 그래프 추가** — 내부 HDL Control QC bias(실선)와
    CDC 평가 bias(점선)를 공통 y축(mg/dL)에 겹치고 ±1.0 member 밴드를 표시. 회차별 대조표 포함.
    ⚠️ **현재 짝 데이터 0건** — 내부 DCM QC는 2026.7만 있고 2026.7은 아직 평가 대기, 2023.1–2026.1은 평가만 있음.
    없는 회차는 **점을 찍지 않고 선을 끊어** 표시하며 추정값으로 채우지 않는다(§0).
    과거 회차 측정 엑셀을 ⑥탭 소급 누적으로 올리면 `/rounds/data`의 `dcm_qc_upload`로 채워진다.
  · 검증: `smoke_headers.py` **146/146**, `smoke_gunicorn.sh` **25/25**.

- **v15 (2026-07-26): 2025.7·2026.1 HDL-C DCM QC 결과 반영.**
  · 사용자 제공 측정지 2건에서 QC·Control 원자료를 추출해 대시보드에 반영.
    `private/dashboard.html`의 `DCM_QC_HIST` 상수(회차·Day별 관리물질 원자료 + bias),
    `assets/history_seed.json`의 `dcm_qc`(회차별 HDL Control bias mg/dL 평균).
  · **★ 이 두 파일은 자동 파서로 읽히지 않는다.** Day2가 옆이 아니라 **세로로 쌓여** 있고
    시트명도 다르다(2026.1=`결과 취합` Day1 5–12행·Day2 17–24행, 2025.7=`Sheet2` Day1 5–12행·Day2 18–25행).
    `_parse_dcm`은 Day1/Day2가 **가로로 나란한** 배열만 지원하므로 값을 확정해 상수로 넣었다.
    2025.7 원본에는 요약 시트 자체가 없어 `Sheet2`(수기 정리본)에서 읽었다.
    → 이 회차들을 ⑥탭 소급 누적으로 업로드하려면 세로 배열 지원이 먼저 필요하다(§10 잔여 과제).
  · **주요 소견 — QC↔평가 대응이 처음으로 확인됨:**

    | 회차 | 내부 HDL Control bias (mg/dL) | CDC 평가 bias | 평가 판정 |
    |---|---|---|---|
    | 2025.7 | **+0.082** (−0.225·−0.053·+0.428·+0.179) | −0.10 | 인증 |
    | 2026.1 | **−1.010** (−0.659·−0.612·**−1.624**·**−1.145**) | −1.50 | **미인증** |
    | 2026.7 | **+0.037** (+0.047·+0.474·−0.122·−0.253) | 평가 대기 | — |

    2026.1은 **Day2 HDL Control 2건이 모두 ±1 mg/dL를 초과**(−1.624, −1.145)했고 평가도 −1.50 미인증으로,
    내부 QC가 평가 결과와 같은 방향·비슷한 크기를 보였다. 2026.7 내부 QC는 +0.037로 안정적이나
    **평가 회신 전이므로 판정은 확정할 수 없다.**
  · 짝 데이터가 2개(2025.7·2026.1)가 되었으나 **3개 미만이라 상관 r은 계속 보류**한다.
  · ④탭에 **회차별 QC·Control 상세표** 추가(Day별 관리물질·A.value·반복 수·mean·bias·판정).
    판정 단위는 TC=±1%, HDL Control=±1 mg/dL로 행마다 다르게 적용한다.
  · `dashboard_payload`에 `dcm_qc_seed`·`dcm_qc_upload_only`를 분리 제공 — 업로드가 시드를 덮어쓰지 않는다(§0).
  · 검증: `smoke_headers.py` **152/152**, `smoke_gunicorn.sh` **25/25**.

- **v16 (2026-07-26): DCM [결과선택] 시트 채택 셀 노란색 표시 수정.** ★ 재발 주의
  · 증상: 채택 replicate가 굵게만 나오고 **노란색 배경이 전혀 보이지 않음**(UC 시트와 다름).
  · 원인: **조건부 서식(dxf)은 `fgColor`가 아니라 `bgColor`로 배경을 렌더링한다.**
    `PatternFill('solid', fgColor='FFF2A8')`로 쓰면 openpyxl이 `<patternFill><fgColor rgb="00FFF2A8"/></patternFill>`만
    기록해 Excel에서 **색이 안 보인다**. 게다가 6자리 RGB를 주면 알파가 `00`(완전 투명)으로 저장된다.
    UC 템플릿은 `<fgColor indexed="64"/><bgColor rgb="FFFFF2CC"/>` 형태다.
  · 조치: `_dxf_fill()` / `_dxf_font()` 헬퍼를 만들어 **bgColor + 8자리 ARGB**로 통일.
    채택 셀·채택 평균(mean) = 노란색, 제외 셀 = 회색+취소선, 검증 불일치 = 빨강.
  · **일반 셀 스타일은 fgColor가 정상 동작**하므로 헷갈리기 쉽다 — 조건부 서식에만 해당한다.
  · 회귀 방지: 스모크에서 `xl/styles.xml`의 dxf를 직접 파싱해 bgColor 사용·ARGB 8자리·노란색/회색 등록·취소선을 검사.
  · 검증: LibreOffice로 PDF 렌더 → PNG 변환 후 **노란색 픽셀 존재를 실제로 확인**(육안 + 픽셀 카운트).
    부수 수정: 옵션 설명 행 높이(6·7행), '구분'·'검체' 열 너비(라벨 잘림 해소).
  · 검증: `smoke_headers.py` **158/158**, `smoke_gunicorn.sh` **25/25**.

## 10. 다음 작업 계획 (2026-07-26 사용자 확정 · 우선순위 순)

> 아래 T0–T4는 **사용자가 직접 선택한 다음 작업 목록**입니다. on-computer 세션에서 위에서부터 진행하고,
> 각 항목 완료 시 §9 변경 이력에 추가한 뒤 커밋·푸시하세요.

- ~~**T0. 리포 위생**~~ — **완료(2026-07-26, `17b6602`).** `.gitignore` + `HANDOVER_인수인계.md` 커밋.
  이 문서의 단일 원본은 이제 GitHub 리포입니다.
- ~~**T1. 과거 회차 소급 누적**~~ — **완료(2026-07-26).** ⑥탭 "과거 회차 소급 누적" 패널 + `/rounds/preview`.
  · **2단계 확정 절차** — ① 파일 업로드 → `/rounds/preview`가 **저장하지 않고** 라벨 후보·기존 라벨 존재 여부·
    시드 대조를 반환 → ② 사용자가 라벨을 확정하고 확인 체크 → `/rounds/add?reference=1&confirm=1`로 저장.
    `confirm` 없이는 서버가 400으로 거부하므로 **자동 추정만으로는 절대 저장되지 않음**.
  · **라벨 자동 추정**(`rounds.infer_labels`) — 파일명·시트명에서 `YYYY.M` / `YYYY년 M월` / `YYYY 상·하반기` 패턴을
    찾아 **근거(어느 파일명·시트명의 어느 문자열)와 함께** 제시. 13월·`2025.1234` 같은 오인은 걸러냄. 추정 실패 시 직접 입력.
  · **참고용 원칙**(2026-07-26 사용자 확정) — 소급 저장분은 `reference=True`로 표시되고 화면에 "참고용 소급" 배지가 붙음.
    **`stats.drift`(추세) 계산에서 자동 제외**되며 `bias_summary`·`precision` 행에도 참고 표시가 실림.
  · **최근 3년 제한**(사용자 확정) — 측정 시점이 불확실하면 `min_backfill_year()`(올해−2년) 이후 자료만 소급 가능.
    그 이전은 "측정 시점이 문서로 확인됨" 체크(`date_certain`)를 해야 통과. 미래 연도는 거부.
  · **시드 덮어쓰기 버그 수정** — 기존 `dashboard_payload()`는 업로드 값으로 시드 `qc_bias` 점을 **덮어쓰고 있었음**(§0 위반).
    이제 `points_seed`(시드 원본)와 `points_upload`(소급 계산)를 분리 보관하고, 차이가 나면 `conflicts`에 담아
    ⑥탭 "시드 ↔ 소급 계산값 대조" 표에 **병기**. 경향 그래프도 실선(시드)·점선△(소급) 두 계열로 표시.
    어느 쪽도 자동 채택하지 않음.
  · 소급 업로드는 검토 엑셀을 만들지 않고 JSON만 반환(사용자 확정) — 여러 회차를 연속으로 넣기 쉬움.
- ~~**T2. `app_rounds.data`(JSONB) 통계 분석**~~ — **완료(2026-07-26).** `stats.py` + `/rounds/stats` + ⑥탭 하위 섹션.
  · **`stats.py`** — `rounds.load_store()`에서 읽으므로 **Postgres·파일 폴백 양쪽에서 동작**.
    ① `bias_summary` 회차·모드·분석물질별 평균/SD/범위 + **한계 대비 마진**(=|평균bias|÷한계, 1.0 초과 시 초과)
    ② `precision` 채택 2개 반복의 CV, Day1↔Day2 채택값 절대차(재현성)
    ③ `drift` 회차당 bias 변화 최소제곱 기울기 — **UC·DCM은 다른 측정절차라 절대 합치지 않음**.
       회차 3개 미만이면 `slope=None`(판단 보류). flag 임계(한계의 25%/회차)는 **임의값이며 경고용**
    ④ `drop_pattern` 제외된 반복 index(R1/R2/R3) 분포 — 치우치면 측정 순서·장비 안정화 등 **계통 오류** 의심 근거
  · **`tools/stats_queries.sql`** — Postgres 직접 분석용 참조 쿼리 7종(전부 SELECT).
    실제 Postgres 16에서 전 쿼리 실행 검증 완료.
  · **⑥탭 UI** — 표 4종 + 마진 바. 상단·하단에 §0 방법론 경고문 고정 노출.
  · **⚠️ 설계 원칙:** 이 통계는 **모니터링·진단 전용**이며 반복측정 채택 로직에 관여하지 않음.
    코드 주석·SQL 헤더·UI·API `note` 필드 4곳에 "판정 통과 목적의 선택 금지"를 명시.
- ~~**T3. Drive `crmln-app` 사본 정리**~~ — **폐기 결정(2026-07-26).**
  22개 파일을 GitHub main과 전수 대조: **19개 동일, 3개 구버전(`app.py`·`rounds.py`·`private/dashboard.html`),
  이 폴더에만 있는 파일 0개**(`static/`은 빈 폴더). 즉 잃을 내용이 없음.
  폴더 안에 `⚠️_이_폴더는_폐기대상입니다.md` 경고 파일을 넣어둠.
  · **남은 조치: 사용자가 탐색기에서 `G:\내 드라이브\00_study\표준화과제\CRMLN\crmln-app` 폴더 삭제.**
    (Claude는 사용자 PC 파일을 삭제할 수 없음)
- ~~**T4. 검증 스모크 정비**~~ — **완료(2026-07-26).** `tools/` 4개 스크립트 + README 추가, 총 **66개 검사 전부 통과**.
  · `tools/smoke_headers.py` (41) — 헤더 latin-1 안전성을 **직접 인코딩해 검사**하므로 Windows/개발서버에서도 동일 버그를 잡음.
    부가로 canon_label 6종, 중복 회차 병합, `/rounds/data`의 `is_admin`, 삭제 ajax, 잘못된 입력 400까지 검증.
  · `tools/smoke_gunicorn.sh` (14) — 실제 gunicorn 위에서 한글 파일명 업로드 → 200 + 헤더 latin-1 재확인.
  · `tools/smoke_tab6.py` (11) — Playwright headless. Chart.js 4개 캔버스 **픽셀 검사**(빈 캔버스면 실패),
    제출표 행/회차 서브탭/관리자 삭제표/콘솔 에러 확인.
  · `tools/make_fixture.py` — 합성 측정지 생성. ⚠️ **가짜 데이터**이므로 판정·제출 금지(README에 경고 명시).
  · **배포 전 습관:** `python tools/smoke_headers.py && bash tools/smoke_gunicorn.sh && python tools/smoke_tab6.py`

- **T5. DCM 측정지 세로(Day2 stacked) 배열 지원** — 2025.7·2026.1 측정지는 Day2가 Day1 아래에 세로로 쌓여 있고
  시트명도 `결과 취합`/`Sheet2`로 다르다. 현행 `_parse_dcm`은 가로 배열만 읽으므로 이 회차들은 업로드가 불가하고,
  v15에서는 값을 확정해 상수로 넣었다. 세로 배열·대체 시트명을 지원하면 과거 회차도 ⑥탭 소급 누적으로 처리 가능.
  · 구현 시 `_dcm_day_cols`처럼 **헤더(`A.value`/`R1…`) 위치를 세로로도 탐색**하는 방식 권장.
  · ⚠️ 지원 후에는 상수(`DCM_QC_HIST`)와 업로드 계산값이 **다를 수 있으므로 병기·대조**할 것(§0).

### 진행 중/기타
- 중복 회차 라벨(2026-07 / 2026.07 / 2026-07-01) 정리는 사용자가 ⑥ 탭 삭제표에서 수행, `2026.7`만 유지.
- **T0–T4 전부 완료.** 남은 사용자 조치: ① GitHub Desktop에서 Push, ② Drive `crmln-app` 폴더 삭제(T3),
  ③ 배포 후 ⑥탭 소급 패널·대조표 실제 렌더 확인(Playwright 미검증 구간).
- 소급 누적 실제 사용 시: 과거 측정 원본 엑셀에 `결과정리` 시트가 있어야 `summarize_round`가 읽습니다.
  시트명이 다르면 파일을 열어 시트명을 `결과정리`로 맞춘 뒤 올리십시오.

---

## 11. 작업 워크플로

### (A) 권장 — on-computer 세션

폴더 `C:\Users\yun76\Documents\GitHub\crmln_web` 를 연결한 상태로 시작하면 Claude가 전 과정을 처리합니다.

1. Claude가 파일 직접 수정 (GitHub Desktop에 변경분 자동 표시)
2. 배포 전 스모크 검증 — Claude의 리눅스 샌드박스에서 실행 가능:
   `python3 tools/smoke_headers.py` (63) · `bash tools/smoke_gunicorn.sh` (18) 는 **정상 실행됨**.
   `python3 tools/smoke_tab6.py` (17) 은 **Chromium 다운로드가 네트워크 allowlist에 막혀 실행 불가** →
   `node --check`로 인라인 JS 문법 + DOM/문구 grep 정적 검증으로 대체하고, 브라우저 렌더는 배포 후 공개 URL에서 확인.
3. Claude가 `git commit` (첫 `git add` 전에 `git config core.autocrlf input` — 이미 설정됨)
4. **사용자가 GitHub Desktop에서 Push** (§상단 ⚠️ 참조: Claude 셸에 GitHub 자격증명 없음)
5. Railway 자동 재배포 → 공개 URL에서 동작 확인 (특히 ⑥탭 "누적 통계 분석" 섹션)

### (B) 클라우드 세션으로 시작해버린 경우

1. Claude가 `device_request_folder_access` 로 위 clone 폴더 접근 요청 → 사용자 승인.
   (승인은 **세션 단위**. 새 세션마다 다시 승인 필요)
2. Claude가 컨테이너에 `git clone https://github.com/yun7640/crmln_web.git` 후 그 안에서 수정 + **전체 검증**
   (여기서는 gunicorn·Playwright·Postgres 전부 실행 가능 — Windows보다 검증 범위가 넓습니다)
3. 검증 통과한 파일만 `device_commit_files` 로 로컬 git 작업트리에 기록
4. **사용자가 GitHub Desktop에서 Commit + Push** → Railway 자동 재배포

### 공통 주의

- 로컬 작업트리 파일은 **CRLF**, GitHub 정본은 LF입니다. 내용 비교 시 `tr -d '\r'` 로 정규화할 것
  (그냥 diff하면 전 파일이 바뀐 것처럼 보임). 커밋 시에는 git의 autocrlf가 처리합니다.
- git 원격은 **HTTPS**여야 함(`git remote -v` 확인, SSH면 `git remote set-url origin https://github.com/yun7640/crmln_web.git`).
- 클라우드 세션의 Claude는 사용자 PC 파일을 **삭제할 수 없습니다.** 삭제가 필요하면 안내만 남기고 사용자가 처리.
- 수정 후 반드시 스모크 검증 습관 유지, 방법론 원칙(§0) 준수.

---

## 12. 폴더 3곳 구분 (혼동 주의)

| 위치 | 경로 | 성격 |
|---|---|---|
| **정본(source of truth)** | GitHub `yun7640/crmln_web` main | 배포 원본. Railway가 여기서 빌드 |
| **로컬 clone** | `C:\Users\yun76\Documents\GitHub\crmln_web` | 실제 git 저장소. **작업은 여기서** |
| ~~참고 사본~~ | ~~`G:\내 드라이브\00_study\표준화과제\CRMLN\crmln-app`~~ | **폐기 대상(T3).** git 아님, v8 스냅샷. 전수 대조 결과 고유 파일 0개 → 삭제해도 무방 |

`G:\…\CRMLN\` 루트에는 이 `HANDOVER_인수인계.md`와 `회차누적분석_미리보기.html`(정적 미리보기)도 있습니다.
`crmln-app` 폴더를 삭제하고 나면 **정본은 GitHub 리포, 작업은 로컬 clone** — 두 곳으로 단순해집니다.

---

## 13. 두 대의 PC에서 번갈아 작업하기 (직장 PC2 ↔ 집 PC1)

동일 사용자·동일 계정(GitHub / Railway / GitHub Desktop). **동기화 통로는 GitHub 하나뿐입니다.**
Google Drive나 Cowork 대화는 동기화 수단이 아닙니다.

### 한 번만 (각 PC에서 1회)

GitHub Desktop → File → Clone repository → `yun7640/crmln_web`
→ `C:\Users\<사용자>\Documents\GitHub\crmln_web`
(경로 확인: GitHub Desktop → **Repository → Show in Explorer** `Ctrl+Shift+F`)

### 매번 (양쪽 공통 3단계)

| 순서 | 할 일 |
|---|---|
| **① 시작 전** | GitHub Desktop에서 **Fetch origin → Pull origin** |
| **② 작업** | Cowork 새 작업 → **On your computer** → 폴더 = `crmln_web` → 아래 프롬프트 |
| **③ 끝낼 때** | Claude가 commit까지 수행 → **사용자가 Push 버튼** |

②의 프롬프트(고정 문구):

> 이 폴더의 `HANDOVER_인수인계.md`를 읽고 지금까지 상태를 파악한 다음 이어서 작업해줘.
> 파일 수정은 이 폴더에 직접 반영하고, 검증 후 커밋까지 처리해줘.

### 반드시 지킬 규칙 2개

1. **자리를 뜨기 전 반드시 Push.** 커밋만 하고 Push하지 않으면 다른 PC에서 보이지 않습니다.
   작업트리에만 있는 파일도 마찬가지입니다.
2. **두 PC에서 동시에 작업하지 않기.** 한쪽에서 Push를 끝낸 뒤 다른 쪽에서 Pull하고 시작하세요.
   동시 작업은 병합 충돌을 만듭니다.

> 실제 사례(2026-07-27): PC1에서 이 §13을 작성해 두고 Push하지 않은 채 자리를 옮겼더니,
> PC2의 GitHub Desktop에는 "No local changes"로만 보였다. 파일이 사라진 것이 아니라
> **푸시되지 않아 건너오지 않은 것.** 규칙 1을 어기면 정확히 이렇게 된다.

### 세션 종료 전 체크리스트

- [ ] 스모크 검증 통과 (`python3 tools/smoke_headers.py`, `bash tools/smoke_gunicorn.sh`)
- [ ] **이 문서(§9 변경 이력, §10 다음 작업) 갱신** ← 다음 PC로 넘기는 바통
- [ ] commit (Claude) → **Push (사용자)**
- [ ] Railway 재배포 확인 → 공개 URL 동작 확인

### 왜 이 방식인가

- **Cowork 대화는 PC 간 이어지지 않습니다.** on-computer 세션은 그 PC의 폴더에 묶여 있습니다.
  그래서 **이 인수인계 문서가 대화 기록을 대신하는 바통**입니다. 반드시 갱신하고 커밋하세요.
- **Railway는 신경 쓸 것이 없습니다.** GitHub main에서 자동 배포하므로 어느 PC에서 Push하든 동일합니다.
- ⚠️ **git 리포를 Google Drive 안에 두지 마십시오.** Drive 동기화가 `.git` 내부를 건드려 저장소가
  깨질 수 있고, 두 PC가 동시에 열면 특히 위험합니다. Drive는 측정 원본 엑셀 등 **비-코드 자료 전용**.

### 충돌이 났을 때

Pull 시 충돌이 나면 대개 ①(Pull) 을 건너뛰고 작업한 경우입니다.
GitHub Desktop → **Branch → Update from main** 으로 병합하거나,
로컬 변경이 이미 다른 PC에서 더 진전된 형태로 반영돼 있다면 **Discard changes 후 Pull** 하십시오.
버리기 전 반드시 History에서 origin 쪽에 해당 내용이 있는지 확인할 것.

### Claude가 남긴 `.git/index.lock` 오류

클라우드 세션의 Claude가 마운트된 리포에서 git 명령을 실행하면 `.git/index.lock` 이 생기는데,
샌드박스가 파일 삭제를 차단해 스스로 치우지 못합니다. 이 lock이 남아 있으면
**GitHub Desktop이 인덱스를 못 읽어 변경이 없는 것처럼 보입니다.**

```
del "C:\Users\yun76\Documents\GitHub\crmln_web\.git\index.lock"
```

삭제 후 GitHub Desktop → **Repository → Refresh**.
`_to_delete\` 폴더가 생겨 있으면 함께 지우십시오.
⇒ 클라우드 세션에서는 마운트 리포에 **git 명령을 실행하지 말고 파일 쓰기만** 할 것.

