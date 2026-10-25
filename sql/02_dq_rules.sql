-- 02_dq_rules.sql
-- Layer 2: DATA QUALITY RULES as SQL views. Same 12 rules as the Python engine.
-- Every view returns: rule_id, source_table, record_id, dollars_at_risk.

CREATE VIEW dq_r01 AS   -- Duplicate claim_id (flag once per claim_id)
SELECT 'R01' AS rule_id, 'claims' AS source_table, claim_id AS record_id, charge_amount AS dollars_at_risk
FROM (SELECT claim_id, charge_amount,
             ROW_NUMBER() OVER (PARTITION BY claim_id ORDER BY row_id) AS rn
      FROM stg_claims_all)
WHERE rn = 2;

CREATE VIEW dq_r02 AS   -- Negative charge amount
SELECT 'R02', 'claims', claim_id, ABS(charge_amount)
FROM stg_claims WHERE charge_amount < 0;

CREATE VIEW dq_r03 AS   -- Missing or invalid service date
SELECT 'R03', 'claims', claim_id, charge_amount
FROM stg_claims WHERE service_date IS NULL;

CREATE VIEW dq_r04 AS   -- Procedure code not in reference table
SELECT 'R04', 'claims', claim_id, charge_amount
FROM stg_claims
WHERE cpt_code IS NULL OR cpt_code NOT IN (SELECT cpt_code FROM stg_ref_cpt);

CREATE VIEW dq_r05 AS   -- ICD-10 format: letter, 2 digits, optional .[1-4 alphanumerics]
SELECT 'R05', 'claims', claim_id, charge_amount
FROM stg_claims
WHERE icd10_code IS NULL OR NOT (
       icd10_code GLOB '[A-Z][0-9][0-9]'
    OR icd10_code GLOB '[A-Z][0-9][0-9].[A-Z0-9]'
    OR icd10_code GLOB '[A-Z][0-9][0-9].[A-Z0-9][A-Z0-9]'
    OR icd10_code GLOB '[A-Z][0-9][0-9].[A-Z0-9][A-Z0-9][A-Z0-9]'
    OR icd10_code GLOB '[A-Z][0-9][0-9].[A-Z0-9][A-Z0-9][A-Z0-9][A-Z0-9]');

CREATE VIEW dq_r06 AS   -- Orphan payment
SELECT 'R06', 'payments', p.payment_id, p.paid_amount
FROM stg_payments p
WHERE NOT EXISTS (SELECT 1 FROM stg_claims c WHERE c.claim_id = p.claim_id);

CREATE VIEW dq_r07 AS   -- Overpayment
SELECT 'R07', 'payments', p.payment_id, p.paid_amount - c.charge_amount
FROM stg_payments p JOIN stg_claims c ON c.claim_id = p.claim_id
WHERE p.paid_amount > c.charge_amount;

CREATE VIEW dq_r08 AS   -- Payment dated before service
SELECT 'R08', 'payments', p.payment_id, p.paid_amount
FROM stg_payments p JOIN stg_claims c ON c.claim_id = p.claim_id
WHERE p.payment_date < c.service_date;

CREATE VIEW dq_r09 AS   -- Paid claim with no payment record
SELECT 'R09', 'claims', c.claim_id, c.charge_amount
FROM stg_claims c
WHERE c.status = 'Paid'
  AND NOT EXISTS (SELECT 1 FROM stg_payments p WHERE p.claim_id = c.claim_id);

CREATE VIEW dq_r10 AS   -- Denied claim without denial code
SELECT 'R10', 'claims', claim_id, charge_amount
FROM stg_claims WHERE status = 'Denied' AND denial_code IS NULL;

CREATE VIEW dq_r11 AS   -- Duplicate payment (keep the lowest payment_id as the original)
SELECT 'R11', 'payments', payment_id, paid_amount
FROM (SELECT payment_id, paid_amount,
             ROW_NUMBER() OVER (PARTITION BY claim_id, paid_amount, payment_date
                                ORDER BY payment_id) AS rn
      FROM stg_payments)
WHERE rn > 1;

CREATE VIEW dq_r12 AS   -- Possible duplicate billing under a new claim_id
SELECT 'R12', 'claims', claim_id, charge_amount
FROM (SELECT claim_id, charge_amount,
             ROW_NUMBER() OVER (PARTITION BY patient_id, provider_id, cpt_code, service_date, charge_amount
                                ORDER BY claim_id) AS rn
      FROM stg_claims WHERE service_date IS NOT NULL)
WHERE rn > 1;

CREATE VIEW dq_findings AS
SELECT rule_id, source_table, record_id, ROUND(COALESCE(dollars_at_risk, 0), 2) AS dollars_at_risk
FROM (
    SELECT * FROM dq_r01 UNION ALL SELECT * FROM dq_r02 UNION ALL SELECT * FROM dq_r03
    UNION ALL SELECT * FROM dq_r04 UNION ALL SELECT * FROM dq_r05 UNION ALL SELECT * FROM dq_r06
    UNION ALL SELECT * FROM dq_r07 UNION ALL SELECT * FROM dq_r08 UNION ALL SELECT * FROM dq_r09
    UNION ALL SELECT * FROM dq_r10 UNION ALL SELECT * FROM dq_r11 UNION ALL SELECT * FROM dq_r12
);

-- dq_rule_catalog is loaded from the Python RULE_CATALOG by build_database.py
CREATE VIEW dq_rule_summary AS
SELECT c.rule_id, c.name AS rule_name, c.severity, c.source_table,
       COUNT(f.record_id)                           AS failures,
       ROUND(COALESCE(SUM(f.dollars_at_risk), 0), 2) AS dollars_at_risk
FROM dq_rule_catalog c
LEFT JOIN dq_findings f ON f.rule_id = c.rule_id
GROUP BY c.rule_id, c.name, c.severity, c.source_table;