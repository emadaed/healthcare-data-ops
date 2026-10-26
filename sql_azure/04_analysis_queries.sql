-- 04_analysis_queries.sql  (T-SQL / Azure SQL). Each query ends with a semicolon.

-- Q1. Denial rate by payer (decided claims only)
SELECT p.payer_name,
       COUNT(*)                                                              AS decided_claims,
       SUM(CASE WHEN f.status = 'Denied' THEN 1 ELSE 0 END)                  AS denied,
       ROUND(100.0 * SUM(CASE WHEN f.status = 'Denied' THEN 1 ELSE 0 END) / COUNT(*), 1) AS denial_rate_pct
FROM dbo.fact_claim f JOIN dbo.dim_payer p ON p.payer_key = f.payer_key
WHERE f.status IN ('Paid', 'Denied')
GROUP BY p.payer_name
ORDER BY denial_rate_pct DESC;

-- Q2. Average days to pay by payer (clean paid claims only)
SELECT p.payer_name, ROUND(AVG(CAST(f.days_to_pay AS FLOAT)), 1) AS avg_days_to_pay, COUNT(*) AS claims
FROM dbo.fact_claim f JOIN dbo.dim_payer p ON p.payer_key = f.payer_key
WHERE f.status = 'Paid' AND f.dq_flag = 0 AND f.days_to_pay IS NOT NULL
GROUP BY p.payer_name
ORDER BY avg_days_to_pay;

-- Q3. AR aging of pending claims, as of 2025-12-31 (fixed date so results are repeatable)
SELECT age_bucket, COUNT(*) AS claims, SUM(charge_amount) AS outstanding
FROM (SELECT f.charge_amount,
             DATEDIFF(day, d.full_date, CAST('2025-12-31' AS date)) AS age,
             CASE WHEN DATEDIFF(day, d.full_date, CAST('2025-12-31' AS date)) <= 30 THEN '0-30'
                  WHEN DATEDIFF(day, d.full_date, CAST('2025-12-31' AS date)) <= 60 THEN '31-60'
                  WHEN DATEDIFF(day, d.full_date, CAST('2025-12-31' AS date)) <= 90 THEN '61-90'
                  ELSE '90+' END AS age_bucket
      FROM dbo.fact_claim f JOIN dbo.dim_date d ON d.date_key = f.service_date_key
      WHERE f.status = 'Pending' AND f.charge_amount > 0) AS t
GROUP BY age_bucket
ORDER BY MIN(age);

-- Q4. Data quality exposure by rule
SELECT rule_id, rule_name, severity, failures, dollars_at_risk
FROM dbo.dq_rule_summary
ORDER BY dollars_at_risk DESC;