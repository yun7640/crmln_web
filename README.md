# CRMLN 측정결과 검토 대시보드 (로그인 · 업로드 검토)

KDCA 진단검사의학 표준검사실(NMRL, Lab 509)용 웹 앱입니다.
**사용자별 아이디·비밀번호 로그인** 뒤에 CRMLN 측정결과 검토·평가경향 대시보드를 보여주고,
표준 CRMLN 측정 엑셀(`결과정리` 시트)을 업로드하면 **선택(채택 2반복) 하이라이트 + `2026.7 측정결과 검토` 시트**가 자동 생성된 파일을 내려받습니다.

GitHub(소스) + Railway(배포) 조합으로 무료/저비용 호스팅할 수 있도록 구성했습니다.

---

## 구성

```
app.py              Flask 앱 (로그인·세션·라우트)
review_engine.py    업로드 엑셀 처리(선택 로직·member 판정·검토 시트) — openpyxl
templates/
  login.html        로그인 화면
  dashboard.html    로그인 후 화면(대시보드 iframe + 업로드 패널)
private/
  dashboard.html    CRMLN 대시보드(HTML) — 로그인 사용자에게만 제공
requirements.txt    의존성
Procfile            Railway/일반 PaaS 실행 명령
railway.json        Railway 빌드·헬스체크 설정
make_user.py        사용자 비밀번호 해시 생성기
users.example.json  사용자 목록 예시
```

로그인 판정 기준(member): NIST/TC ±1%, BF·LDL ±2%, HDL ±1 mg/dL.
선택: 종합(BF+HDL 상대편차·균형), BF·HDL·LDL 동일 R index 잠금, QC·Control 미제출.

---

## 1) 로컬 실행 (선택)

```bash
pip install -r requirements.txt
# 사용자 만들기 (아이디 yeomin, 비밀번호 원하는 값)
python make_user.py yeomin "원하는비밀번호"      # 출력된 JSON을 users.json 으로 저장
export SECRET_KEY="아무_긴_랜덤_문자열"
python app.py            # http://localhost:8000
```

## 2) 사용자 추가/관리

두 가지 방법 중 하나:

- **환경변수 `USERS_JSON`** (권장, Railway에서 사용): `{"아이디":"해시", ...}` 형태의 JSON 한 줄.
- **`users.json` 파일**: 같은 형식의 파일(리포지토리에 커밋하지 말 것 — `.gitignore`에 포함됨).

해시는 반드시 `make_user.py`로 생성합니다(평문 비밀번호를 저장하지 않음):

```bash
python make_user.py 아이디 "비밀번호"
# → {"아이디": "pbkdf2:sha256:600000$....."}
```

여러 명이면 각 출력의 `{}` 안 항목을 하나의 JSON으로 합칩니다:
```json
{"yeomin":"pbkdf2:sha256:...","reviewer1":"pbkdf2:sha256:..."}
```

---

## 3) GitHub에 올리기

```bash
cd crmln-app
git init
git add .
git commit -m "CRMLN review dashboard"
# GitHub에서 빈 리포지토리 생성 후:
git remote add origin https://github.com/<사용자>/<리포>.git
git branch -M main
git push -u origin main
```
> `users.json`, `.env`, `*.xlsx`는 `.gitignore`로 제외됩니다(비밀정보·업로드 파일 커밋 방지).

## 4) Railway 배포

1. https://railway.app 로그인 → **New Project** → **Deploy from GitHub repo** → 위 리포 선택.
2. Railway가 `requirements.txt`+`Procfile`을 감지해 자동 빌드합니다(Nixpacks).
3. **Variables** 탭에서 환경변수 추가:
   - `SECRET_KEY` = 아무 긴 랜덤 문자열(세션 서명용, 필수)
   - `USERS_JSON` = 위에서 만든 사용자 JSON 한 줄(최초 시드·영구 백업용)
   - `ADMIN_USERS` = 관리자 아이디(콤마 구분, 예: `yeomin`)
   - (권장) `USERS_FILE` = `/data/users.json` — 관리자 화면에서 등록한 사용자를 **영구 저장**하려면 아래 Volume과 함께 설정
4. (권장) **Settings → Volumes → New Volume**, 마운트 경로 `/data` — 이러면 관리자 화면에서 추가/변경한 사용자가 재배포 후에도 유지됩니다. Volume 없이도 동작하지만, 재배포·재시작 시 관리자 화면에서 추가한 사용자는 초기화될 수 있으니 `USERS_JSON` 백업을 병행하세요.
5. **Settings → Networking → Generate Domain** 으로 공개 주소(`https://...up.railway.app`) 생성.
6. 해당 주소로 접속 → 로그인 → 사용.

### 관리자 · 사용자 설명서
- 로그인 후 상단 **관리자** 메뉴(관리자 계정만)에서 사용자 아이디·비밀번호 등록·변경·삭제, 관리자 권한 지정이 가능합니다. 화면의 **USERS_JSON 백업**을 복사해 Railway `USERS_JSON`에 저장하면 영구 보존됩니다.
- 상단 **사용자 설명서** 메뉴에 대시보드·업로드·판정기준·선택로직 사용법이 있습니다.
- 관리자 지정: `ADMIN_USERS` 환경변수(콤마 목록). 관리자가 하나도 없으면 첫 사용자가 자동 관리자가 됩니다.

헬스체크 경로는 `/healthz`로 설정되어 있습니다. 재배포는 GitHub에 push하면 자동 반영됩니다.

---

## 사용법

1. 로그인(아이디·비밀번호).
2. 오른쪽 대시보드에서 검토·평가경향 확인.
3. 왼쪽 패널에 **CRMLN 측정 .xlsx**(‘결과정리’ 시트 포함)를 끌어놓고 **검토 파일 생성·다운로드**.
   - 결과정리의 채택 2반복이 노란색으로 표시되고, `2026.7 측정결과 검토` 시트(QC 정확도 판정·제출 선택·종합 고찰)가 추가된 파일이 내려받아집니다.

---

## 보안·규제 유의

- Railway 도메인은 HTTPS가 자동 적용됩니다.
- 비밀번호는 해시(pbkdf2)로만 저장하며 평문을 두지 마십시오. `SECRET_KEY`는 반드시 설정하십시오.
- 업로드 파일은 메모리에서 처리 후 응답으로만 반환하며 서버에 저장하지 않습니다.
- 임상·규제 대상 자료인 만큼, 접근 권한은 최소화하고 **최종 제출·판정은 CDC 회신 및 검토자 확인 후 확정**하십시오. 필요 시 기관 정보보안 정책에 따른 접근통제(IP 제한 등)를 추가 적용하십시오.
