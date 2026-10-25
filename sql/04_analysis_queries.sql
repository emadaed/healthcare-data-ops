-- 04_analysis_queries.sql
-- Example analyses on the star schema. Run any of them in a SQLite browser or
-- through build_database.py. Each query ends with a semicolon.

-- Q1. Denial rate by payer (decided claims only)
SELECT p.payer_name,
       COUNT(*)                                                AS decided_claims,
       SUM(f.status = 'Denied')                                AS denied,
       ROUND(100.0 * SUM(f.status = 'Denied') / COUNT(*), 1)   AS denial_rate_pct
FROM fact_claim f JOIN dim_payer p ON p.payer_key = f.payer_key
WHERE f.status IN ('Paid', 'Denied')
GROUP BY p.payer_name
ORDER BY denial_rate_pct DESC;

-- Q2. Average days to pay by payer (clean paid claims only)
SELECT p.payer_name, ROUND(AVG(f.days_to_pay), 1) AS avg_days_to_pay, COUNT(*) AS claims
FROM fact_claim f JOIN dim_payer p ON p.payer_key = f.payer_key
WHERE f.status = 'Paid' AND f.dq_flag = 0 AND f.days_to_pay IS NOT NULL
GROUP BY p.payer_name
ORDER BY avg_days_to_pay;

-- Q3. AR aging of pending claims, as of 2025-12-31 (fixed date so results are repeatable)
SELECT CASE WHEN age <= 30 THEN '0-30'  WHEN age <= 60 THEN '31-60'
            WHEN age <= 90 THEN '61-90' ELSE '90+' END AS age_bucket,
       COUNT(*)                         AS claims,
       ROUND(SUM(charge_amount), 2)     AS outstanding
FROM (SELECT f.charge_amount,
             CAST(julianday('2025-12-31') - julianday(d.full_date) AS INTEGER) AS age
      FROM fact_claim f JOIN dim_date d ON d.date_key = f.service_date_key
      WHERE f.status = 'Pending' AND f.charge_amount > 0)
GROUP BY age_bucket
ORDER BY MIN(age);

-- Q4. Data quality exposure by rule
SELECT rule_id, rule_name, severity, failures, dollars_at_risk
FROM dq_rule_summary
ORDER BY dollars_at_risk DESC;