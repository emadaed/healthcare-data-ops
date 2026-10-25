-- 01_staging.sql
-- Layer 1: STAGING. Cleans formatting noise in the raw tables (all text).
-- Raw tables are never modified; staging views read from them.
-- Dialect: SQLite. T-SQL equivalents are noted for the Azure SQL port.

CREATE VIEW stg_ref_cpt AS
SELECT UPPER(TRIM(cpt_code))      AS cpt_code,
       description,
       CAST(min_charge AS REAL)   AS min_charge,
       CAST(max_charge AS REAL)   AS max_charge
FROM raw_ref_cpt;

-- One row per RAW row (duplicates still present)
CREATE VIEW stg_claims_all AS
SELECT
    rowid                                   AS row_id,
    UPPER(TRIM(claim_id))                   AS claim_id,
    NULLIF(TRIM(patient_id), '')            AS patient_id,
    NULLIF(TRIM(provider_id), '')           AS provider_id,
    NULLIF(TRIM(payer_name), '')            AS payer_name,
    -- accepts YYYY-MM-DD and MM/DD/YYYY; anything else (or an impossible date) becomes NULL
    date(CASE
           WHEN TRIM(service_date) GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' THEN TRIM(service_date)
           WHEN TRIM(service_date) GLOB '[0-9][0-9]/[0-9][0-9]/[0-9][0-9][0-9][0-9]'
                THEN substr(TRIM(service_date),7,4) || '-' || substr(TRIM(service_date),1,2) || '-' || substr(TRIM(service_date),4,2)
         END)                               AS service_date,
    date(CASE
           WHEN TRIM(submission_date) GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' THEN TRIM(submission_date)
           WHEN TRIM(submission_date) GLOB '[0-9][0-9]/[0-9][0-9]/[0-9][0-9][0-9][0-9]'
                THEN substr(TRIM(submission_date),7,4) || '-' || substr(TRIM(submission_date),1,2) || '-' || substr(TRIM(submission_date),4,2)
         END)                               AS submission_date,
    NULLIF(UPPER(TRIM(cpt_code)), '')       AS cpt_code,
    NULLIF(UPPER(TRIM(icd10_code)), '')     AS icd10_code,
    -- strips $ and thousands commas; unreadable text becomes NULL
    CASE
      WHEN TRIM(charge_amount) = '' THEN NULL
      WHEN REPLACE(REPLACE(TRIM(charge_amount), '$', ''), ',', '') GLOB '*[^0-9.-]*' THEN NULL
      ELSE CAST(REPLACE(REPLACE(TRIM(charge_amount), '$', ''), ',', '') AS REAL)
    END                                     AS charge_amount,
    CASE UPPER(TRIM(status))
      WHEN 'PAID' THEN 'Paid' WHEN 'PENDING' THEN 'Pending' WHEN 'DENIED' THEN 'Denied'
      ELSE NULLIF(TRIM(status), '')
    END                                     AS status,
    NULLIF(TRIM(denial_code), '')           AS denial_code
FROM raw_claims;

-- One row per claim_id (first occurrence in file order kept)
CREATE VIEW stg_claims AS
SELECT row_id, claim_id, patient_id, provider_id, payer_name, service_date, submission_date,
       cpt_code, icd10_code, charge_amount, status, denial_code
FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY claim_id ORDER BY row_id) AS rn
      FROM stg_claims_all)
WHERE rn = 1;

CREATE VIEW stg_payments AS
SELECT
    rowid                                   AS row_id,
    TRIM(payment_id)                        AS payment_id,
    UPPER(TRIM(claim_id))                   AS claim_id,
    CASE
      WHEN TRIM(paid_amount) = '' THEN NULL
      WHEN REPLACE(REPLACE(TRIM(paid_amount), '$', ''), ',', '') GLOB '*[^0-9.-]*' THEN NULL
      ELSE CAST(REPLACE(REPLACE(TRIM(paid_amount), '$', ''), ',', '') AS REAL)
    END                                     AS paid_amount,
    date(CASE
           WHEN TRIM(payment_date) GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' THEN TRIM(payment_date)
           WHEN TRIM(payment_date) GLOB '[0-9][0-9]/[0-9][0-9]/[0-9][0-9][0-9][0-9]'
                THEN substr(TRIM(payment_date),7,4) || '-' || substr(TRIM(payment_date),1,2) || '-' || substr(TRIM(payment_date),4,2)
         END)                               AS payment_date,
    NULLIF(TRIM(payment_method), '')        AS payment_method
FROM raw_payments;