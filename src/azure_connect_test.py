"""
azure_connect_test.py  (Phase 5, step 1)

Checks that your machine can reach your Azure SQL database.
Reads connection details from ENVIRONMENT VARIABLES so no password is ever
written into code or committed to Git.

PowerShell, for the current window only:
    $env:AZURE_SQL_SERVER   = "yourserver.database.windows.net"
    $env:AZURE_SQL_DATABASE = "claims_dq"
    $env:AZURE_SQL_USER     = "your_admin_login"
    $env:AZURE_SQL_PASSWORD = "your_password"
    python src\azure_connect_test.py
"""
import os
import sys
import time

import pyodbc

DRIVER = "ODBC Driver 18 for SQL Server"
RETRIES = 4          # a paused serverless database needs a minute to wake up
WAIT_SECONDS = 20


def connection_string() -> str:
    missing = [k for k in ("AZURE_SQL_SERVER", "AZURE_SQL_DATABASE",
                           "AZURE_SQL_USER", "AZURE_SQL_PASSWORD") if not os.environ.get(k)]
    if missing:
        sys.exit(f"Missing environment variables: {', '.join(missing)}")
    return (
        f"Driver={{{DRIVER}}};"
        f"Server=tcp:{os.environ['AZURE_SQL_SERVER']},1433;"
        f"Database={os.environ['AZURE_SQL_DATABASE']};"
        f"Uid={os.environ['AZURE_SQL_USER']};Pwd={os.environ['AZURE_SQL_PASSWORD']};"     
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=60;"
    )


def main():
    if DRIVER not in pyodbc.drivers():
        sys.exit(f"'{DRIVER}' not found. Installed drivers: {pyodbc.drivers()}")

    for attempt in range(1, RETRIES + 1):
        try:
            with pyodbc.connect(connection_string()) as conn:
                row = conn.cursor().execute(
                    "SELECT DB_NAME(), SYSDATETIME(), LEFT(@@VERSION, 60)").fetchone()
            print("Connected.")
            print(f"  database : {row[0]}")
            print(f"  server time : {row[1]}")
            print(f"  version : {row[2]}")
            return
        except pyodbc.Error as err:
            print(f"Attempt {attempt}/{RETRIES} failed: {err}")
            if attempt < RETRIES:
                print(f"  (a paused database can take a minute to resume) waiting {WAIT_SECONDS}s...")
                time.sleep(WAIT_SECONDS)
    sys.exit("Could not connect. Send me the error text above (without your password).")


if __name__ == "__main__":
    main()
