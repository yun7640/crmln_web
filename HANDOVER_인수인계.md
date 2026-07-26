# CRMLN 대시보드 프로젝트 · 인수인계 (HANDOVER)

> **새 세션 사용법 (★ 2026-07-26 갱신 · 실측 반영):**
>
> 이 계정에서는 **"Run this task → On your computer" 선택기가 제공되지 않습니다**(2026-07-26 확인).
> 따라서 모든 세션은 **클라우드**에서 실행되며, 아래 방식으로 작업합니다.
>
> 1. Claude 데스크톱 앱에서 **새 Cowork 작업**을 시작합니다. (데스크톱 앱이어야 로컬 파일 브리지가 동작)
> 2. 폴더는 `G:\내 드라이브\00_study\표준화과제\CRMLN` 을 연결한 뒤 이렇게 요청합니다:
>    "`HANDOVER_인수인계.md`를 읽고 지금까지 상태를 파악한 다음 이어서 진행해줘.
>     `C:\Users\yun76\Documents\GitHub\crmln_web` 폴더 접근 권한을 요청해서 거기에 직접 수정 반영해줘."
> 3. Claude가 폴더 접근 승인 요청을 띄우면 **승인**합니다. 이후 Claude가 **git 작업트리에 직접 파일을 씁니다.**
> 4. **커밋·푸시는 사용자가 GitHub Desktop에서 수행**합니다(변경분이 자동으로 표시됨) → Railway 자동 재배포.
>
> ⚠️ **클라우드 세션은 사용자 PC에서 셸(git)을 실행할 수 없습니다.** 파일 읽기/쓰기 브리지만 가능하므로
> `git commit` / `git push`는 Claude가 대신 할 수 없습니다. 마지막 커밋 버튼만 사용자가 눌러주세요.
> (참고: 선택기가 나타나는 계정이라면 Settings → Cowork → "Run new tasks in the cloud" 토글로 기본값 변경 가능.
>  웹·모바일에서 시작한 작업은 항상 클라우드입니다.)

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
requirements.txt  Procfile  railway.json  runtime.txt  README.md  make_user.py
HANDOVER_인수인계.md        (이 문서)
```

주의: `.gitignore`가 `*.xlsx`를 무시하되 `!assets/*.xlsx`로 템플릿만 포함. `data/`(로컬 저장), `users.json`은 커밋 제외. `assets/select_template.xlsx`와 `assets/history_seed.json`은 반드시 리포에 포함되어야 함(앱 동작 필수).

> **★ 실제 리포 추적 상태 확인(2026-07-26, `git ls-files` 기준):**
> 현재 GitHub `yun7640/crmln_web` main(`231ea36`)에 실제로 추적되는 파일은 위 목록 중
> `.gitignore`, `HANDOVER_인수인계.md`, `static/` **을 제외한** 나머지입니다.
> 즉 **이 인수인계 문서와 `.gitignore`는 아직 리포에 커밋되어 있지 않습니다.**
> → 다음 on-computer 세션에서 `.gitignore`와 `HANDOVER_인수인계.md`를 커밋할 것(할 일 T0).

---

## 3. 라우트(app.py)

- `/login` `/logout` — 세션 로그인.
- `/` — dashboard.html(업로드 패널 + iframe). `/view` — private/dashboard.html 제공.
- `/review` (POST) — 단발 업로드 → 검토파일 반환(누적 저장 안 함). 헤더 `X-Review-Summary`.
- `/rounds` — cumulative.html(전체 페이지). `/rounds/data` — 누적 payload JSON(+`is_admin`).
- `/rounds/add` (POST) — 업로드 → **summarize_round로 누적 저장 + process로 검토파일 반환**. 헤더 `X-Round-Result`.
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
- **DCM(_is_dcm):** 측정지 7행 2열이 'HDL Control'로 시작하면 DCM. 행 구성: 5=NIST(TC),6=CFS21-01(TC),7=HDL CFS21-01(HDL Control),8=HDL QC2(HDL),9–12=CS01–CS04. Day1 R열=(5,6,7)·A열=4, Day2 R열=(17,18,19)·A열=16. **동일검체 반복 CV>15%인 Day는 정렬오류로 제외(DCM_CV_GUARD=15).** _dcm_pick: median 이상치 1개 제외 → 2개 평균 채택.
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
- ①–⑤: 커스텀 인라인 SVG 차트(외부 라이브러리 없음). 데이터는 파일 내 인라인 JS 상수.
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

## 10. 다음 작업 계획 (2026-07-26 사용자 확정 · 우선순위 순)

> 아래 T0–T4는 **사용자가 직접 선택한 다음 작업 목록**입니다. on-computer 세션에서 위에서부터 진행하고,
> 각 항목 완료 시 §9 변경 이력에 추가한 뒤 커밋·푸시하세요.

- **T0. 리포 위생 (선착)** — `.gitignore`, `HANDOVER_인수인계.md`를 리포에 커밋(§2 확인 결과 누락 상태).
  이후 이 문서의 단일 원본은 GitHub 리포가 됩니다.
- **T1. 과거 회차 소급 누적** — 2023.1–2026.7은 현재 `assets/history_seed.json`의 **경향 시드만** 있고 상세 제출표가 없음.
  과거 측정 원본 엑셀을 업로드하면 `summarize_round`로 상세 제출표까지 소급 누적되도록 지원.
  · 회차 라벨은 파일명/시트명에서 추정하되 **반드시 사용자 확인 후 확정**(자동 추정만으로 저장 금지).
  · `canon_label`로 정규화되므로 중복 생성 위험은 낮으나, 저장 전 기존 라벨 존재 여부를 표시할 것.
  · 시드 값과 소급 계산 값이 다를 경우 **덮어쓰지 말고 병기·차이 표시**(§0 원칙: 유리한 값 선택 금지).
- **T2. `app_rounds.data`(JSONB) 통계 분석** — Postgres `app_rounds.data` 기반 추가 통계.
  후보 지표: 회차간 bias 추이(NIST/BF/HDL/LDL), 반복측정 CV·재현성, QC bias와 평가결과 상관, 판정 마진 분포.
  · 읽기 전용 SQL(집계)만 사용, 화면은 ⑥ 탭 하위 섹션 또는 `/rounds/stats` 신설 검토.
- **T3. Drive `crmln-app` 사본 최신화** — Google Drive `…\CRMLN\crmln-app` 은 **v8 시점 스냅샷**(`rounds.py`에 `canon_label` 없음,
  `app.py`에 `is_admin` 주입·`ajax` 분기 없음, `private/dashboard.html` 구버전). GitHub main(v9)으로 동기화하거나,
  혼동 방지를 위해 사본을 폐기하고 리포 단일 원본만 유지할지 결정할 것. (§12 참조)
- **T4. 검증 스모크 정비** — 재발 버그 방지용 스크립트를 리포에 추가.
  · `tools/smoke_gunicorn.sh`: 실제 gunicorn 기동 후 `/healthz`, 업로드 응답 헤더 latin-1 검증(한글 헤더 500 재발 방지).
  · `tools/smoke_tab6.py`: Chart.js 로컬 vendoring + Playwright headless로 ⑥ 탭 캔버스/표 행수 확인.
  · CI 없이도 `python -m pytest` 또는 셸 한 줄로 돌아가게 할 것.

### 진행 중/기타
- 중복 회차 라벨(2026-07 / 2026.07 / 2026-07-01) 정리는 사용자가 ⑥ 탭 삭제표에서 수행, `2026.7`만 유지.

---

## 11. 실제 작업 워크플로 (클라우드 세션 + 폴더 접근 권한)

이 계정은 on-computer 실행이 불가하므로 **클라우드 세션 + 로컬 폴더 쓰기 권한** 조합으로 작업합니다.

**표준 절차**

1. Claude가 `device_request_folder_access` 로 `C:\Users\yun76\Documents\GitHub\crmln_web` 접근 요청 → 사용자 승인.
   (승인은 **세션 단위**입니다. 새 세션마다 다시 승인해야 합니다.)
2. Claude가 클라우드 컨테이너에 `git clone https://github.com/yun7640/crmln_web.git` 으로 정본을 받아
   그 안에서 코드 수정 + **검증**(gunicorn 헤더 검증, Playwright ⑥탭 렌더, Postgres 경로).
3. 검증 통과한 파일만 `device_commit_files` 로 **로컬 git 작업트리에 직접 기록**.
4. 사용자가 **GitHub Desktop에서 변경분 확인 → Commit → Push** → Railway 자동 재배포.
5. 배포 후 공개 URL에서 실제 동작 확인.

**주의**

- 로컬 작업트리 파일은 **CRLF**, GitHub 정본은 LF입니다. 내용 비교 시 `tr -d '\r'` 로 정규화해서 비교할 것
  (그냥 diff하면 전 파일이 바뀐 것처럼 보임). 커밋 시에는 git의 autocrlf가 처리합니다.
- git 원격은 **HTTPS**여야 함(`git remote -v` 확인, SSH면 `git remote set-url origin https://github.com/yun7640/crmln_web.git`).
- Claude는 사용자 PC에서 파일 **삭제 불가**. 삭제가 필요하면 `_to_delete/` 하위로 옮기고 사용자에게 알릴 것.
- 수정 후 반드시 gunicorn/Playwright 검증 습관 유지, 방법론 원칙(§0) 준수.

---

## 12. 폴더 3곳 구분 (혼동 주의)

| 위치 | 경로 | 성격 |
|---|---|---|
| **정본(source of truth)** | GitHub `yun7640/crmln_web` main | 배포 원본. Railway가 여기서 빌드 |
| **로컬 clone** | `C:\Users\yun76\Documents\GitHub\crmln_web` | 실제 git 저장소. **작업은 여기서** |
| 참고 사본 | `G:\내 드라이브\00_study\표준화과제\CRMLN\crmln-app` | git 아님. **v8 시점 스냅샷(구버전)** — 코드 기준으로 삼지 말 것 |

`G:\…\CRMLN\` 루트에는 이 `HANDOVER_인수인계.md`와 `회차누적분석_미리보기.html`(정적 미리보기)도 있습니다.
