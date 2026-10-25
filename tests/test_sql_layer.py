"""Tests for the SQL layer: parity with Python rules, star schema integrity, queries run."""
from pathlib import Path

import pandas as pd
import pytest

import build_database as bd

DATA_DIR = Path("data_hard")
pytestmark = pytest.mark.skipif(not (DATA_DIR / "claims_raw.csv").exists(),
                                reason="run generate_hard_data.py first")


@pytest.fixture(scope="module")
def conn(tmp_path_factory):
    db = tmp_path_factory.mktemp("wh") / "test.db"
    c = bd.build_database(DATA_DIR, db)
    yield c
    c.close()


def scalar(conn, sql):
    return conn.execute(sql).fetchone()[0]


def test_sql_rules_match_python_rules_exactly(conn):
    parity = bd.compare_with_python(conn, DATA_DIR)
    assert parity.match.all(), parity[~parity.match]


def test_one_fact_row_per_unique_claim(conn):
    assert scalar(conn, "SELECT COUNT(*) FROM fact_claim") == \
           scalar(conn, "SELECT COUNT(DISTINCT claim_id) FROM fact_claim")
    assert scalar(conn, "SELECT COUNT(*) FROM fact_claim") == 5052


def test_fact_claim_keys_resolve_to_dimensions(conn):
    assert scalar(conn, """SELECT COUNT(*) FROM fact_claim f
                           LEFT JOIN dim_payer p ON p.payer_key = f.payer_key
                           WHERE p.payer_key IS NULL""") == 0
    assert scalar(conn, """SELECT COUNT(*) FROM fact_claim f
                           LEFT JOIN dim_date d ON d.date_key = f.service_date_key
                           WHERE f.service_date_key IS NOT NULL AND d.date_key IS NULL""") == 0
    assert scalar(conn, """SELECT COUNT(*) FROM fact_claim f
                           LEFT JOIN dim_procedure p ON p.cpt_code = f.cpt_code
                           WHERE p.cpt_code IS NULL AND f.cpt_code IN (SELECT cpt_code FROM dim_procedure)""") == 0


def test_every_fact_payment_belongs_to_a_fact_claim(conn):
    assert scalar(conn, """SELECT COUNT(*) FROM fact_payment p
                           LEFT JOIN fact_claim c ON c.claim_id = p.claim_id
                           WHERE c.claim_id IS NULL""") == 0


def test_orphan_payments_are_kept_out_of_the_fact_table(conn):
    raw = scalar(conn, "SELECT COUNT(*) FROM raw_payments")
    orphans = scalar(conn, "SELECT COUNT(*) FROM dq_findings WHERE rule_id = 'R06'")
    assert scalar(conn, "SELECT COUNT(*) FROM fact_payment") == raw - orphans


def test_duplicate_payments_do_not_inflate_paid_amount(conn):
    fact_total = scalar(conn, "SELECT ROUND(SUM(paid_amount), 2) FROM fact_claim")
    clean_total = scalar(conn, """SELECT ROUND(SUM(paid_amount), 2) FROM fact_payment
                                  WHERE is_duplicate = 0""")
    assert fact_total == clean_total


def test_analysis_queries_all_run_and_return_rows(conn):
    text = Path("sql/04_analysis_queries.sql").read_text(encoding="utf-8")
    queries = [q.strip() for q in text.split(";") if "SELECT" in q.upper()]
    assert len(queries) == 4
    for q in queries:
        assert len(pd.read_sql_query(q, conn)) > 0