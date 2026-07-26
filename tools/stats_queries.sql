-- CRMLN 회차 누적 데이터(app_rounds.data JSONB) 직접 분석용 참조 쿼리
--
-- ⚠️ 방법론 원칙 (인수인계 §0)
--    아래 쿼리는 **모니터링·진단용**입니다. 반복측정(R1/R2/R3) 채택은 이미
--    review_engine의 정밀도/QC 기반 로직으로만 결정되며, 여기서 얻은 값을
--    판정을 통과시키기 위한 선택 근거로 사용해서는 안 됩니다.
--    최종 제출·판정은 CDC 참조법 회신 및 검토자 확인 후 확정합니다.
--
-- ⚠️ 전부 읽기 전용(SELECT)입니다. UPDATE/DELETE를 추가하지 마십시오.
--    회차 삭제는 앱의 ⑥ 탭 관리자 UI(/rounds/delete)를 사용하세요.
--
-- 접속: Railway → Postgres → Connect → psql
--   psql "$DATABASE_URL" -f tools/stats_queries.sql
--
-- ℹ️ 반올림 주의: Postgres round()는 0.5를 절대값이 커지는 쪽으로, Python round()는
--    가까운 짝수로 반올림합니다(banker's rounding). 3째 자리에서 ±0.001 차이가 날 수 있으니
--    앱 화면(/rounds/stats)과 아래 쿼리 결과를 비교할 때 참고하세요. 판정에 영향을 줄 수준은 아닙니다.
--
-- 테이블: app_rounds(label text, mode text, data jsonb, meta jsonb, updated_at timestamptz)
--   data 구조 — summarize_round() 출력:
--     {mode, qc:[{analyte,name,day,biaspct,biasmgdl,ok,limit}], qc_bias:{...},
--      samples:[{name,day,drop,keep,HDL,(BF,LDL,cvL|cv),reps}], n_qc,n_exceed,n_samples}


-- ── 0. 저장된 회차 목록 ────────────────────────────────────────────────
SELECT label, mode, data->>'n_samples' AS n_samples, data->>'n_qc' AS n_qc,
       data->>'n_exceed' AS n_exceed, meta->>'date' AS meas_date,
       meta->>'by' AS uploaded_by, updated_at
FROM app_rounds
ORDER BY label, mode;


-- ── 1. 회차·모드·분석물질별 QC/Control bias 요약 ───────────────────────
-- HDL은 mg/dL(biasmgdl), 나머지는 %(biaspct) 기준으로 판정한다.
WITH q AS (
  SELECT r.label, r.mode,
         e->>'analyte'                        AS analyte,
         e->>'name'                           AS qc_name,
         (e->>'day')::int                     AS day,
         CASE WHEN e->>'analyte' = 'HDL'
              THEN (e->>'biasmgdl')::numeric
              ELSE (e->>'biaspct')::numeric END AS bias,
         CASE WHEN e->>'analyte' = 'HDL' THEN 'mg/dL' ELSE '%' END AS unit
  FROM app_rounds r, jsonb_array_elements(r.data->'qc') e
)
SELECT label, mode, analyte, unit,
       count(*)                       AS n,
       round(avg(bias), 3)            AS mean_bias,
       round(stddev_samp(bias), 3)    AS sd_bias,
       round(min(bias), 3)            AS min_bias,
       round(max(bias), 3)            AS max_bias
FROM q
GROUP BY label, mode, analyte, unit
ORDER BY label, mode, analyte;


-- ── 2. 허용한계 대비 마진 (1.0 초과 = 한계 초과) ───────────────────────
-- MEMBER 기준: TC ±1%, BF ±2%, LDL ±2%, HDL ±1 mg/dL
WITH lim(analyte, lim) AS (
  VALUES ('TC', 1.0), ('BF', 2.0), ('LDL', 2.0), ('HDL', 1.0)
), q AS (
  SELECT r.label, r.mode, e->>'analyte' AS analyte,
         CASE WHEN e->>'analyte' = 'HDL'
              THEN (e->>'biasmgdl')::numeric
              ELSE (e->>'biaspct')::numeric END AS bias
  FROM app_rounds r, jsonb_array_elements(r.data->'qc') e
)
SELECT q.label, q.mode, q.analyte,
       round(avg(q.bias), 3)                          AS mean_bias,
       l.lim                                          AS limit_val,
       round(abs(avg(q.bias)) / l.lim, 3)             AS margin_ratio,
       (abs(avg(q.bias)) > l.lim)                     AS exceeds
FROM q JOIN lim l USING (analyte)
GROUP BY q.label, q.mode, q.analyte, l.lim
ORDER BY margin_ratio DESC;


-- ── 3. 검체 반복측정 정밀도 (채택 2개의 CV) ────────────────────────────
-- UC는 cvL(LDL 기준), DCM은 cv 키를 쓴다.
SELECT r.label, r.mode,
       count(*)                                                   AS n_sample_day,
       round(avg(COALESCE((s->>'cv')::numeric,
                          (s->>'cvL')::numeric)), 4)              AS mean_cv_pct,
       round(max(COALESCE((s->>'cv')::numeric,
                          (s->>'cvL')::numeric)), 4)              AS max_cv_pct
FROM app_rounds r, jsonb_array_elements(r.data->'samples') s
GROUP BY r.label, r.mode
ORDER BY r.label, r.mode;


-- ── 4. Day1 vs Day2 재현성 (같은 검체의 채택값 차이) ───────────────────
WITH d AS (
  SELECT r.label, r.mode, s->>'name' AS sample,
         max(CASE WHEN (s->>'day')::int = 1 THEN (s->>'HDL')::numeric END) AS day1,
         max(CASE WHEN (s->>'day')::int = 2 THEN (s->>'HDL')::numeric END) AS day2
  FROM app_rounds r, jsonb_array_elements(r.data->'samples') s
  GROUP BY r.label, r.mode, s->>'name'
)
SELECT label, mode, sample, day1, day2,
       round(abs(day1 - day2), 3) AS abs_diff
FROM d
WHERE day1 IS NOT NULL AND day2 IS NOT NULL
ORDER BY abs_diff DESC;


-- ── 5. 제외된 반복 index(R1/R2/R3) 분포 ────────────────────────────────
-- 특정 index가 유독 자주 제외되면 측정 순서·장비 안정화 등 계통 오류를 의심할 근거.
-- (채택 로직 자체를 바꾸는 용도가 아니라, 원인을 찾기 위한 진단 정보)
SELECT r.label, r.mode,
       count(*) FILTER (WHERE (s->>'drop')::int = 1) AS dropped_R1,
       count(*) FILTER (WHERE (s->>'drop')::int = 2) AS dropped_R2,
       count(*) FILTER (WHERE (s->>'drop')::int = 3) AS dropped_R3,
       count(*)                                      AS total
FROM app_rounds r, jsonb_array_elements(r.data->'samples') s
GROUP BY r.label, r.mode
ORDER BY r.label, r.mode;


-- ── 6. 회차 간 bias 변화 (직전 회차 대비) ──────────────────────────────
-- 지속적인 한 방향 이동은 드리프트 신호. 단, 회차가 3개 이상일 때만 추세로 해석할 것.
WITH q AS (
  SELECT r.label, r.mode, e->>'analyte' AS analyte,
         CASE WHEN e->>'analyte' = 'HDL'
              THEN (e->>'biasmgdl')::numeric
              ELSE (e->>'biaspct')::numeric END AS bias
  FROM app_rounds r, jsonb_array_elements(r.data->'qc') e
), m AS (
  SELECT label, mode, analyte, avg(bias) AS mean_bias
  FROM q GROUP BY label, mode, analyte
)
SELECT label, mode, analyte,
       round(mean_bias, 3) AS mean_bias,
       round(mean_bias - lag(mean_bias) OVER (PARTITION BY mode, analyte ORDER BY label), 3)
         AS delta_vs_prev
FROM m
ORDER BY mode, analyte, label;
-- 주의: ORDER BY label 은 문자열 정렬이라 '2026.1' < '2026.7' 은 맞지만
--       회차 라벨 체계가 바뀌면 정렬이 어긋날 수 있다. 앱의 rounds._key()가 정본 정렬 기준이다.


-- ── 7. 한계를 초과한 QC 항목만 추출 ────────────────────────────────────
SELECT r.label, r.mode, e->>'analyte' AS analyte, e->>'name' AS qc_name,
       (e->>'day')::int AS day, e->>'limit' AS limit_label,
       (e->>'biaspct')::numeric AS bias_pct, (e->>'biasmgdl')::numeric AS bias_mgdl
FROM app_rounds r, jsonb_array_elements(r.data->'qc') e
WHERE (e->>'ok') = 'false'
ORDER BY r.label, r.mode, analyte;
