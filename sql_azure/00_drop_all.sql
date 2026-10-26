-- 00_drop_all.sql : makes the build repeatable. Safe to run on an empty database.
DROP TABLE IF EXISTS dbo.fact_claim;
DROP TABLE IF EXISTS dbo.fact_payment;
DROP TABLE IF EXISTS dbo.dim_payer;
DROP TABLE IF EXISTS dbo.dim_procedure;
DROP TABLE IF EXISTS dbo.dim_provider;
DROP TABLE IF EXISTS dbo.dim_date;
GO
DROP VIEW IF EXISTS dbo.dq_rule_summary;
DROP VIEW IF EXISTS dbo.dq_findings;
DROP VIEW IF EXISTS dbo.dq_r12;
DROP VIEW IF EXISTS dbo.dq_r11;
DROP VIEW IF EXISTS dbo.dq_r10;
DROP VIEW IF EXISTS dbo.dq_r09;
DROP VIEW IF EXISTS dbo.dq_r08;
DROP VIEW IF EXISTS dbo.dq_r07;
DROP VIEW IF EXISTS dbo.dq_r06;
DROP VIEW IF EXISTS dbo.dq_r05;
DROP VIEW IF EXISTS dbo.dq_r04;
DROP VIEW IF EXISTS dbo.dq_r03;
DROP VIEW IF EXISTS dbo.dq_r02;
DROP VIEW IF EXISTS dbo.dq_r01;
DROP VIEW IF EXISTS dbo.stg_payments;
DROP VIEW IF EXISTS dbo.stg_claims;
DROP VIEW IF EXISTS dbo.stg_claims_all;
DROP VIEW IF EXISTS dbo.stg_ref_cpt;
GO