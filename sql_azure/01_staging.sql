-- 01_staging.sql  (T-SQL / Azure SQL)
-- Cleans formatting noise in the raw tables. Raw tables are never modified.
-- Differences from the SQLite version: GLOB -> LIKE, date() -> TRY_CONVERT, CAST -> TRY_CAST.

CREATE VIEW dbo.stg_ref_cpt AS
SELECT UPPER(TRIM(cpt_code))                    AS cpt_code,
       description,
       TRY_CAST(min_charge AS DECIMAL(12,2))    AS min_charge,
       TRY_CAST(max_charge AS DECIMAL(12,2))    AS max_charge
FROM dbo.raw_ref_cpt;
GO

CREATE VIEW dbo.stg_claims_all AS
SELECT
    row_id,
    UPPER(TRIM(claim_id))                       AS claim_id,
    NULLIF(TRIM(patient_id), '')                AS patient_id,
    NULLIF(TRIM(provider_id), '')               AS provider_id,
    NULLIF(TRIM(payer_name), '')                AS payer_name,
    -- accepts YYYY-MM-DD and MM/DD/YYYY; anything else (or an impossible date) becomes NULL
    CASE
      WHEN TRIM(service_date) LIKE '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' THEN TRY_CONVERT(date, TRIM(service_date), 23)
      WHEN TRIM(service_date) LIKE '[0-9][0-9]/[0-9][0-9]/[0-9][0-9][0-9][0-9]' THEN TRY_CONVERT(date, TRIM(service_date), 101)
    END                                         AS service_date,
    CASE
      WHEN TRIM(submission_date) LIKE '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' THEN TRY_CONVERT(date, TRIM(submission_date), 23)
      WHEN TRIM(submission_date) LIKE '[0-9][0-9]/[0-9][0-9]/[0-9][0-9][0-9][0-9]' THEN TRY_CONVERT(date, TRIM(submission_date), 101)
    END                                         AS submission_date,
    NULLIF(UPPER(TRIM(cpt_code)), '')           AS cpt_code,
    NULLIF(UPPER(TRIM(icd10_code)), '')         AS icd10_code,
    -- strips $ and thousands commas; unreadable text becomes NULL
    CASE
      WHEN TRIM(charge_amount) = '' THEN NULL
      WHEN REPLACE(REPLACE(TRIM(charge_amount), '$', ''), ',', '') LIKE '%[^0-9.-]%' THEN NULL
      ELSE TRY_CAST(REPLACE(REPLACE(TRIM(charge_amount), '$', ''), ',', '') AS DECIMAL(12,2))
    END                                         AS charge_amount,
    CASE UPPER(TRIM(status))
      WHEN 'PAID' THEN 'Paid' WHEN 'PENDING' THEN 'Pending' WHEN 'DENIED' THEN 'Denied'
      ELSE NULLIF(TRIM(status), '')
    END                                         AS status,
    NULLIF(TRIM(denial_code), '')               AS denial_code
FROM dbo.raw_claims;
GO

CREATE VIEW dbo.stg_claims AS
SELECT row_id, claim_id, patient_id, provider_id, payer_name, service_date, submission_date,
       cpt_code, icd10_code, charge_amount, status, denial_code
FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY claim_id ORDER BY row_id) AS rn
      FROM dbo.stg_claims_all) AS t
WHERE rn = 1;
GO

CREATE VIEW dbo.stg_payments AS
SELECT
    row_id,
    TRIM(payment_id)                            AS payment_id,
    UPPER(TRIM(claim_id))                       AS claim_id,
    CASE
      WHEN TRIM(paid_amount) = '' THEN NULL
      WHEN REPLACE(REPLACE(TRIM(paid_amount), '$', ''), ',', '') LIKE '%[^0-9.-]%' THEN NULL
      ELSE TRY_CAST(REPLACE(REPLACE(TRIM(paid_amount), '$', ''), ',', '') AS DECIMAL(12,2))
    END                                         AS paid_amount,
    CASE
      WHEN TRIM(payment_date) LIKE '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' THEN TRY_CONVERT(date, TRIM(payment_date), 23)
      WHEN TRIM(payment_date) LIKE '[0-9][0-9]/[0-9][0-9]/[0-9][0-9][0-9][0-9]' THEN TRY_CONVERT(date, TRIM(payment_date), 101)
    END                                         AS payment_date,
    NULLIF(TRIM(payment_method), '')            AS payment_method
FROM dbo.raw_payments;
GO