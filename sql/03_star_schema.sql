-- 03_star_schema.sql
-- Layer 3: CURATED star schema for reporting (Power BI / Excel).
--   dim_payer, dim_procedure, dim_provider, dim_date
--   fact_claim   (one row per claim_id)
--   fact_payment (one row per payment that matches a claim)
-- Rows with data quality findings are KEPT and marked with dq_flag so reports can
-- show or exclude them. Orphan payments cannot join to a claim, so they are not in
-- fact_payment; see dq_findings (rule R06).

CREATE TABLE dim_payer AS
SELECT ROW_NUMBER() OVER (ORDER BY payer_name) AS payer_key, payer_name
FROM (SELECT DISTINCT payer_name FROM stg_claims WHERE payer_name IS NOT NULL);

CREATE TABLE dim_procedure AS
SELECT cpt_code, description, min_charge, max_charge,
       -- grouping defined by this project for reporting, not an official code set
       CASE WHEN cpt_code LIKE 'E%' OR cpt_code LIKE 'K%'           THEN 'DME'
            WHEN cpt_code IN ('11042', '97597', '97606')            THEN 'Wound care'
            WHEN cpt_code IN ('93000', '71046', '80053', '85025')   THEN 'Diagnostics'
            WHEN cpt_code = '97110'                                 THEN 'Therapy'
            ELSE 'Evaluation & management' END AS procedure_group
FROM stg_ref_cpt;

CREATE TABLE dim_provider AS
SELECT DISTINCT provider_id FROM stg_claims WHERE provider_id IS NOT NULL;

-- Calendar covering all service and payment dates in the data
CREATE TABLE dim_date AS
WITH RECURSIVE d(dt) AS (
    SELECT '2025-01-01' UNION ALL SELECT date(dt, '+1 day') FROM d WHERE dt < '2026-12-31'
)
SELECT CAST(strftime('%Y%m%d', dt) AS INTEGER)  AS date_key,
       dt                                       AS full_date,
       CAST(strftime('%Y', dt) AS INTEGER)      AS year,
       'Q' || ((CAST(strftime('%m', dt) AS INTEGER) + 2) / 3) AS quarter,
       CAST(strftime('%m', dt) AS INTEGER)      AS month_num,
       CASE strftime('%m', dt)
         WHEN '01' THEN 'January'   WHEN '02' THEN 'February' WHEN '03' THEN 'March'
         WHEN '04' THEN 'April'     WHEN '05' THEN 'May'      WHEN '06' THEN 'June'
         WHEN '07' THEN 'July'      WHEN '08' THEN 'August'   WHEN '09' THEN 'September'
         WHEN '10' THEN 'October'   WHEN '11' THEN 'November' ELSE 'December' END AS month_name,
       strftime('%Y-%m', dt)                    AS year_month,
       CASE strftime('%w', dt)
         WHEN '0' THEN 'Sunday' WHEN '1' THEN 'Monday' WHEN '2' THEN 'Tuesday' WHEN '3' THEN 'Wednesday'
         WHEN '4' THEN 'Thursday' WHEN '5' THEN 'Friday' ELSE 'Saturday' END AS day_name,
       CASE WHEN strftime('%w', dt) IN ('0', '6') THEN 1 ELSE 0 END AS is_weekend
FROM d;

CREATE TABLE fact_payment AS
SELECT p.payment_id,
       p.claim_id,
       CAST(strftime('%Y%m%d', p.payment_date) AS INTEGER) AS payment_date_key,
       p.payment_date,
       p.payment_method,
       p.paid_amount,
       CASE WHEN d11.record_id IS NULL THEN 0 ELSE 1 END   AS is_duplicate,
       CASE WHEN fl.record_id  IS NULL THEN 0 ELSE 1 END   AS dq_flag
FROM stg_payments p
LEFT JOIN (SELECT record_id FROM dq_findings WHERE rule_id = 'R11') d11 ON d11.record_id = p.payment_id
LEFT JOIN (SELECT DISTINCT record_id FROM dq_findings WHERE source_table = 'payments') fl ON fl.record_id = p.payment_id
WHERE EXISTS (SELECT 1 FROM stg_claims c WHERE c.claim_id = p.claim_id);

CREATE TABLE fact_claim AS
SELECT c.claim_id,
       c.patient_id,
       c.provider_id,
       py.payer_key,
       c.cpt_code,
       c.icd10_code,
       CAST(strftime('%Y%m%d', c.service_date)    AS INTEGER) AS service_date_key,
       CAST(strftime('%Y%m%d', c.submission_date) AS INTEGER) AS submission_date_key,
       c.status,
       c.denial_code,
       c.charge_amount,
       COALESCE(pm.paid_amount, 0)                            AS paid_amount,
       CAST(julianday(pm.first_payment_date) - julianday(c.service_date) AS INTEGER) AS days_to_pay,
       CASE WHEN dq.claim_id IS NULL THEN 0 ELSE 1 END        AS dq_flag
FROM stg_claims c
LEFT JOIN dim_payer py ON py.payer_name = c.payer_name
LEFT JOIN (SELECT claim_id, SUM(paid_amount) AS paid_amount, MIN(payment_date) AS first_payment_date
           FROM fact_payment WHERE is_duplicate = 0 GROUP BY claim_id) pm ON pm.claim_id = c.claim_id
LEFT JOIN (SELECT DISTINCT record_id AS claim_id FROM dq_findings WHERE source_table = 'claims'
           UNION
           SELECT DISTINCT claim_id FROM fact_payment WHERE dq_flag = 1) dq ON dq.claim_id = c.claim_id;