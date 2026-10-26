-- 02_dq_rules.sql  (T-SQL / Azure SQL)
-- Same 12 rules as the Python engine and the SQLite version.
-- Every view returns: rule_id, source_table, record_id, dollars_at_risk.

CREATE VIEW dbo.dq_r01 AS   -- Duplicate claim_id (flag once per claim_id)
SELECT 'R01' AS rule_id, 'claims' AS source_table, claim_id AS record_id, charge_amount AS dollars_at_risk
FROM (SELECT claim_id, charge_amount,
             ROW_NUMBER() OVER (PARTITION BY claim_id ORDER BY row_id) AS rn
      FROM dbo.stg_claims_all) AS t
WHERE rn = 2;
GO

CREATE VIEW dbo.dq_r02 AS   -- Negative charge amount
SELECT 'R02' AS rule_id, 'claims' AS source_table, claim_id AS record_id, ABS(charge_amount) AS dollars_at_risk
FROM dbo.stg_claims WHERE charge_amount < 0;
GO

CREATE VIEW dbo.dq_r03 AS   -- Missing or invalid service date
SELECT 'R03' AS rule_id, 'claims' AS source_table, claim_id AS record_id, charge_amount AS dollars_at_risk
FROM dbo.stg_claims WHERE service_date IS NULL;
GO

CREATE VIEW dbo.dq_r04 AS   -- Procedure code not in reference table
SELECT 'R04' AS rule_id, 'claims' AS source_table, claim_id AS record_id, charge_amount AS dollars_at_risk
FROM dbo.stg_claims
WHERE cpt_code IS NULL OR cpt_code NOT IN (SELECT cpt_code FROM dbo.stg_ref_cpt);
GO

CREATE VIEW dbo.dq_r05 AS   -- ICD-10 format: letter, 2 digits, optional .[1-4 alphanumerics]
SELECT 'R05' AS rule_id, 'claims' AS source_table, claim_id AS record_id, charge_amount AS dollars_at_risk
FROM dbo.stg_claims
WHERE icd10_code IS NULL OR NOT (
       icd10_code LIKE '[A-Z][0-9][0-9]'
    OR icd10_code LIKE '[A-Z][0-9][0-9].[A-Z0-9]'
    OR icd10_code LIKE '[A-Z][0-9][0-9].[A-Z0-9][A-Z0-9]'
    OR icd10_code LIKE '[A-Z][0-9][0-9].[A-Z0-9][A-Z0-9][A-Z0-9]'
    OR icd10_code LIKE '[A-Z][0-9][0-9].[A-Z0-9][A-Z0-9][A-Z0-9][A-Z0-9]');
GO

CREATE VIEW dbo.dq_r06 AS   -- Orphan payment
SELECT 'R06' AS rule_id, 'payments' AS source_table, p.payment_id AS record_id, p.paid_amount AS dollars_at_risk
FROM dbo.stg_payments p
WHERE NOT EXISTS (SELECT 1 FROM dbo.stg_claims c WHERE c.claim_id = p.claim_id);
GO

CREATE VIEW dbo.dq_r07 AS   -- Overpayment
SELECT 'R07' AS rule_id, 'payments' AS source_table, p.payment_id AS record_id,
       p.paid_amount - c.charge_amount AS dollars_at_risk
FROM dbo.stg_payments p JOIN dbo.stg_claims c ON c.claim_id = p.claim_id
WHERE p.paid_amount > c.charge_amount;
GO

CREATE VIEW dbo.dq_r08 AS   -- Payment dated before service
SELECT 'R08' AS rule_id, 'payments' AS source_table, p.payment_id AS record_id, p.paid_amount AS dollars_at_risk
FROM dbo.stg_payments p JOIN dbo.stg_claims c ON c.claim_id = p.claim_id
WHERE p.payment_date < c.service_date;
GO

CREATE VIEW dbo.dq_r09 AS   -- Paid claim with no payment record
SELECT 'R09' AS rule_id, 'claims' AS source_table, c.claim_id AS record_id, c.charge_amount AS dollars_at_risk
FROM dbo.stg_claims c
WHERE c.status = 'Paid'
  AND NOT EXISTS (SELECT 1 FROM dbo.stg_payments p WHERE p.claim_id = c.claim_id);
GO

CREATE VIEW dbo.dq_r10 AS   -- Denied claim without denial code
SELECT 'R10' AS rule_id, 'claims' AS source_table, claim_id AS record_id, charge_amount AS dollars_at_risk
FROM dbo.stg_claims WHERE status = 'Denied' AND denial_code IS NULL;
GO

CREATE VIEW dbo.dq_r11 AS   -- Duplicate payment (keep the lowest payment_id as the original)
SELECT 'R11' AS rule_id, 'payments' AS source_table, payment_id AS record_id, paid_amount AS dollars_at_risk
FROM (SELECT payment_id, paid_amount,
             ROW_NUMBER() OVER (PARTITION BY claim_id, paid_amount, payment_date
                                ORDER BY payment_id COLLATE Latin1_General_BIN2) AS rn
      FROM dbo.stg_payments) AS t
WHERE rn > 1;
GO

CREATE VIEW dbo.dq_r12 AS   -- Possible duplicate billing under a new claim_id
SELECT 'R12' AS rule_id, 'claims' AS source_table, claim_id AS record_id, charge_amount AS dollars_at_risk
FROM (SELECT claim_id, charge_amount,
             ROW_NUMBER() OVER (PARTITION BY patient_id, provider_id, cpt_code, service_date, charge_amount
                                ORDER BY claim_id COLLATE Latin1_General_BIN2) AS rn
      FROM dbo.stg_claims WHERE service_date IS NOT NULL) AS t
WHERE rn > 1;
GO

CREATE VIEW dbo.dq_findings AS
SELECT rule_id, source_table, record_id,
       CAST(COALESCE(dollars_at_risk, 0) AS DECIMAL(14,2)) AS dollars_at_risk
FROM (
    SELECT * FROM dbo.dq_r01 UNION ALL SELECT * FROM dbo.dq_r02 UNION ALL SELECT * FROM dbo.dq_r03
    UNION ALL SELECT * FROM dbo.dq_r04 UNION ALL SELECT * FROM dbo.dq_r05 UNION ALL SELECT * FROM dbo.dq_r06
    UNION ALL SELECT * FROM dbo.dq_r07 UNION ALL SELECT * FROM dbo.dq_r08 UNION ALL SELECT * FROM dbo.dq_r09
    UNION ALL SELECT * FROM dbo.dq_r10 UNION ALL SELECT * FROM dbo.dq_r11 UNION ALL SELECT * FROM dbo.dq_r12
) AS u;
GO

-- dq_rule_catalog is loaded from the Python RULE_CATALOG by build_azure.py
CREATE VIEW dbo.dq_rule_summary AS
SELECT c.rule_id, c.name AS rule_name, c.severity, c.source_table,
       COUNT(f.record_id)                                         AS failures,
       CAST(COALESCE(SUM(f.dollars_at_risk), 0) AS DECIMAL(14,2)) AS dollars_at_risk
FROM dbo.dq_rule_catalog c
LEFT JOIN dbo.dq_findings f ON f.rule_id = c.rule_id
GROUP BY c.rule_id, c.name, c.severity, c.source_table;
GO