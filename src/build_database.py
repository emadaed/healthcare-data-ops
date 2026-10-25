"""
build_database.py  (Phase 4)

Builds a SQLite warehouse from the CSV files and proves that the SQL rules give
the same answers as the Python rules.

    raw_*  tables  ->  stg_*  views  ->  dq_*  views  ->  dim_* / fact_*  tables
    (as received)      (cleaned)         (12 rules)        (star schema)

Usage:
    python src\\build_database.py --data-dir data_hard
Outputs:
    warehouse\\claims_dq.db            the database
    warehouse\\export\\*.csv           star schema tables, ready for Power BI / Excel
"""
import argparse
import sqlite3
from pathlib import Path

import pandas as pd

import validate_data as v

SQL_DIR = Path("sql")
SQL_FILES = ["01_staging.sql", "02_dq_rules.sql", "03_star_schema.sql"]
STAR_TABLES = ["dim_payer", "dim_procedure", "dim_provider", "dim_date", "fact_claim", "fact_payment"]


def build_database(data_dir: Path, db_path: Path, sql_dir: Path = SQL_DIR) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)

    # Raw layer: everything stored as text, exactly as received
    raw_files = {"raw_claims": "claims_raw.csv",
                 "raw_payments": "billing_transactions.csv",
                 "raw_ref_cpt": "ref_cpt_codes.csv"}
    for table, filename in raw_files.items():
        pd.read_csv(data_dir / filename, dtype=str, keep_default_na=False).to_sql(
            table, conn, index=False)

    # Rule catalog table (same source of truth as the Python engine)
    catalog = pd.DataFrame([r.__dict__ for r in v.RULE_CATALOG]).rename(columns={"table": "source_table"})
    catalog.to_sql("dq_rule_catalog", conn, index=False)

    for name in SQL_FILES:
        conn.executescript((sql_dir / name).read_text(encoding="utf-8"))
    conn.commit()
    return conn


def compare_with_python(conn: sqlite3.Connection, data_dir: Path) -> pd.DataFrame:
    """Rule by rule: do the SQL views and the Python engine flag the same records?"""
    py, _ = v.run_all_rules(v.load_data(data_dir))
    sql = pd.read_sql_query("SELECT rule_id, record_id, dollars_at_risk FROM dq_findings", conn)
    rows = []
    for rule in v.RULE_CATALOG:
        p = py[py.rule_id == rule.rule_id]
        s = sql[sql.rule_id == rule.rule_id]
        p_ids, s_ids = set(p.record_id), set(s.record_id)
        rows.append({
            "rule_id": rule.rule_id,
            "python_findings": len(p_ids),
            "sql_findings": len(s_ids),
            "only_in_python": len(p_ids - s_ids),
            "only_in_sql": len(s_ids - p_ids),
            "python_dollars": round(p.dollars_at_risk.sum(), 2),
            "sql_dollars": round(s.dollars_at_risk.sum(), 2),
        })
    out = pd.DataFrame(rows)
    out["match"] = ((out.only_in_python == 0) & (out.only_in_sql == 0)
                    & ((out.python_dollars - out.sql_dollars).abs() < 0.01))
    return out


def export_star_schema(conn: sqlite3.Connection, export_dir: Path) -> None:
    export_dir.mkdir(parents=True, exist_ok=True)
    for table in STAR_TABLES:
        pd.read_sql_query(f"SELECT * FROM {table}", conn).to_csv(export_dir / f"{table}.csv", index=False)


def main():
    parser = argparse.ArgumentParser(description="Build the SQLite warehouse.")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--db", type=Path, default=Path("warehouse/claims_dq.db"))
    args = parser.parse_args()

    conn = build_database(args.data_dir, args.db)
    print(f"Built {args.db} from {args.data_dir}\n")

    print("ROW COUNTS")
    for table in ["raw_claims", "raw_payments"] + STAR_TABLES:
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table:<14}{n:>8}")

    parity = compare_with_python(conn, args.data_dir)
    print("\nSQL vs PYTHON PARITY")
    print(parity.to_string(index=False))
    print("\nAll rules match." if parity.match.all() else "\nMISMATCH: investigate the rows above.")

    export_dir = args.db.parent / "export"
    export_star_schema(conn, export_dir)
    print(f"\nStar schema CSVs written to {export_dir}")
    conn.close()


if __name__ == "__main__":
    main()
