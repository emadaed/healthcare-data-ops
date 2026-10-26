-- 03_star_schema.sql  (T-SQL / Azure SQL)
-- Curated star schema for Power BI. Flagged rows are KEPT with dq_flag = 1.
-- Orphan payments cannot join to a claim, so they are not in fact_payment (see rule R06).

SELECT ROW_NUMBER() OVER (ORDER BY payer_name) AS payer_key, payer_name
INTO dbo.dim_payer
FROM (SELECT DISTINCT payer_name FROM dbo.stg_claims WHERE payer_name IS NOT NULL) AS x;
GO

SELECT cpt_code, description, min_charge, max_charge,
       -- grouping defined by this project for reporting, not an official code set
       CASE WHEN cpt_code LIKE 'E%' OR cpt_code LIKE 'K%'           THEN 'DME'
            WHEN cpt_code IN ('11042', '97597', '97606')            THEN 'Wound care'
            WHEN cpt_code IN ('93000', '71046', '80053', '85025')   THEN 'Diagnostics'
            WHEN cpt_code = '97110'                                 THEN 'Therapy'
            ELSE 'Evaluation & management' END AS procedure_group
INTO dbo.dim_procedure
FROM dbo.stg_ref_cpt;
GO

SELECT DISTINCT provider_id
INTO dbo.dim_provider
FROM dbo.stg_claims WHERE provider_id IS NOT NULL;
GO

-- Calendar covering all service and payment dates in the data
WITH d AS (
    SELECT CAST('2025-01-01' AS date) AS dt
    UNION ALL
    SELECT DATEADD(day, 1, dt) FROM d WHERE dt < '2026-12-31'
)
SELECT CAST(CONVERT(char(8), dt, 112) AS INT)                 AS date_key,
       dt                                                     AS full_date,
       YEAR(dt)                                               AS [year],
       'Q' + CAST(DATEPART(quarter, dt) AS varchar(1))        AS [quarter],
       MONTH(dt)                                              AS month_num,
       DATENAME(month, dt)                                    AS month_name,
       CONVERT(char(7), dt, 120)                              AS year_month,
       DATENAME(weekday, dt)                                  AS day_name,
       CASE WHEN DATENAME(weekday, dt) IN ('Saturday', 'Sunday') THEN 1 ELSE 0 END AS is_weekend
INTO dbo.dim_date
FROM d
OPTION (MAXRECURSION 1000);
GO

SELECT p.payment_id,
       p.claim_id,
       CAST(CONVERT(char(8), p.payment_date, 112) AS INT)  AS payment_date_key,
       p.payment_date,
       p.payment_method,
       p.paid_amount,
       CASE WHEN d11.record_id IS NULL THEN 0 ELSE 1 END   AS is_duplicate,
       CASE WHEN fl.record_id  IS NULL THEN 0 ELSE 1 END   AS dq_flag
INTO dbo.fact_payment
FROM dbo.stg_payments p
LEFT JOIN (SELECT record_id FROM dbo.dq_findings WHERE rule_id = 'R11') AS d11
       ON d11.record_id = p.payment_id
LEFT JOIN (SELECT DISTINCT record_id FROM dbo.dq_findings WHERE source_table = 'payments') AS fl
       ON fl.record_id = p.payment_id
WHERE EXISTS (SELECT 1 FROM dbo.stg_claims c WHERE c.claim_id = p.claim_id);
GO

SELECT c.claim_id,
       c.patient_id,
       c.provider_id,
       py.payer_key,
       c.cpt_code,
       c.icd10_code,
       CAST(CONVERT(char(8), c.service_date, 112)    AS INT) AS service_date_key,
       CAST(CONVERT(char(8), c.submission_date, 112) AS INT) AS submission_date_key,
       c.status,
       c.denial_code,
       c.charge_amount,
       CAST(COALESCE(pm.paid_amount, 0) AS DECIMAL(14,2))    AS paid_amount,
       DATEDIFF(day, c.service_date, pm.first_payment_date)  AS days_to_pay,
       CASE WHEN dq.claim_id IS NULL THEN 0 ELSE 1 END       AS dq_flag
INTO dbo.fact_claim
FROM dbo.stg_claims c
LEFT JOIN dbo.dim_payer py ON py.payer_name = c.payer_name
LEFT JOIN (SELECT claim_id, SUM(paid_amount) AS paid_amount, MIN(payment_date) AS first_payment_date
           FROM dbo.fact_payment WHERE is_duplicate = 0 GROUP BY claim_id) AS pm
       ON pm.claim_id = c.claim_id
LEFT JOIN (SELECT record_id AS claim_id FROM dbo.dq_findings WHERE source_table = 'claims'
           UNION
           SELECT claim_id FROM dbo.fact_payment WHERE dq_flag = 1) AS dq
       ON dq.claim_id = c.claim_id;
GO