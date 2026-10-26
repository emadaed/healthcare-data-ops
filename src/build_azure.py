"""
build_azure.py  (Phase 5, step 2)

Builds the same warehouse in Azure SQL Database:
    1. drops previous objects (so you can re-run safely)
    2. loads the CSV files as raw tables (all text) + the rule catalog
    3. runs the T-SQL files in sql_azure\\ in order (batches separated by GO)
    4. checks the Azure SQL rules against the Python rules, rule by rule
    5. runs the example analysis queries

Needs the same four AZURE_SQL_* environment variables as azure_connect_test.py.

Usage:
    python src\\build_azure.py --data-dir data_hard
"""
import argparse
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote_plus

import pandas as pd
import pyodbc
from sqlalchemy import create_engine
from sqlalchemy.types import Integer, NVARCHAR

import azure_connect_test as az
import build_database as bd
import validate_data as v

SQL_DIR = Path("sql_azure")
SQL_FILES = ["00_drop_all.sql", "01_staging.sql", "02_dq_rules.sql", "03_star_schema.sql"]
RAW_FILES = {"raw_claims": "claims_raw.csv",
             "raw_payments": "billing_transactions.csv",
             "raw_ref_cpt": "ref_cpt_codes.csv"}


def make_engine():
    url = "mssql+pyodbc:///?odbc_connect=" + quote_plus(az.connection_string())
    return create_engine(url, fast_executemany=True)


def run_sql_file(path: Path) -> None:
    """Run each GO-separated batch; on failure show exactly which one broke."""
    batches = re.split(r"^\s*GO\s*$", path.read_text(encoding="utf-8"), flags=re.M | re.I)
    with pyodbc.connect(az.connection_string(), autocommit=True) as conn:
        cur = conn.cursor()
        for number, batch in enumerate(batches, start=1):
            if not re.sub(r"--.*", "", batch).strip():
                continue
            try:
                cur.execute(batch)
                while cur.nextset():      # consume any extra result sets
                    pass
            except pyodbc.Error as err:
                first_lines = "\n".join(batch.strip().splitlines()[:6])
                print(f"\nFAILED in {path.name}, batch {number}:\n{first_lines}\n...\n{err}")
                sys.exit(1)
    print(f"  ran {path.name}")


def load_raw(engine, data_dir: Path) -> None:
    for table, filename in RAW_FILES.items():
        df = pd.read_csv(data_dir / filename, dtype=str, keep_default_na=False)
        df.insert(0, "row_id", range(1, len(df) + 1))   # keeps file order, like SQLite's rowid
        types = {c: NVARCHAR(400) for c in df.columns if c != "row_id"}
        types["row_id"] = Integer()
        df.to_sql(table, engine, index=False, if_exists="replace", dtype=types, chunksize=1000)
        print(f"  loaded {table}: {len(df)} rows")
    catalog = pd.DataFrame([r.__dict__ for r in v.RULE_CATALOG]).rename(columns={"table": "source_table"})
    catalog.to_sql("dq_rule_catalog", engine, index=False, if_exists="replace",
                   dtype={c: NVARCHAR(400) for c in catalog.columns})
    print(f"  loaded dq_rule_catalog: {len(catalog)} rules")


def main():
    parser = argparse.ArgumentParser(description="Build the warehouse in Azure SQL Database.")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args()

    started = time.time()
    engine = make_engine()
    print("1. Dropping previous objects")
    run_sql_file(SQL_DIR / SQL_FILES[0])
    print("2. Loading raw data")
    load_raw(engine, args.data_dir)
    print("3. Building staging views, rule views and star schema")
    for name in SQL_FILES[1:]:
        run_sql_file(SQL_DIR / name)

    print("\nROW COUNTS")
    for table in ["raw_claims", "raw_payments"] + bd.STAR_TABLES:
        n = pd.read_sql_query(f"SELECT COUNT(*) AS n FROM dbo.{table}", engine).iloc[0, 0]
        print(f"  {table:<14}{n:>8}")

    parity = bd.compare_with_python(engine, args.data_dir)
    print("\nAZURE SQL vs PYTHON PARITY")
    print(parity.to_string(index=False))
    print("\nAll rules match." if parity.match.all() else "\nMISMATCH: send me the table above.")

    print("\nEXAMPLE ANALYSES")
    text = (SQL_DIR / "04_analysis_queries.sql").read_text(encoding="utf-8")
    for q in [q.strip() for q in text.split(";") if "SELECT" in q.upper()]:
        print(pd.read_sql_query(q, engine).to_string(index=False), "\n")
    print(f"Done in {time.time() - started:.0f}s")


if __name__ == "__main__":
    main()