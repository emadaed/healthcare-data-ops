"""
validate_data.py  (Phase 2)

Rule-based data quality engine for healthcare claims and payments.

    claims_raw.csv + billing_transactions.csv + ref_cpt_codes.csv
        -> run 11 documented rules
        -> findings.csv, dq_scorecard.xlsx
        -> precision / recall against anomaly_manifest.csv

Design notes
- Each rule is a small pure function: data in, findings out. Easy to test.
- Every rule is described in RULE_CATALOG (the single source of truth that also
  feeds the Excel "Rule Catalog" sheet).
- Findings are one row per bad record, with an estimated dollars-at-risk.
"""
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

DATA_DIR = Path("data")
REPORT_DIR = Path("reports")

# ICD-10-CM shape: letter, two digits, optional dot + up to 4 alphanumerics.
# This checks FORMAT only, not whether the code truly exists.
ICD10_PATTERN = r"^[A-Z][0-9]{2}(\.[A-Z0-9]{1,4})?$"

# Share of the checked population allowed to fail before a rule is "in breach".
TOLERANCE = {"Critical": 0.001, "Major": 0.005, "Minor": 0.01}


# ---------------------------------------------------------------------------
# Rule catalog
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Rule:
    rule_id: str
    name: str
    table: str
    severity: str
    logic: str
    business_impact: str


RULE_CATALOG = [
    Rule("R01", "Duplicate claim_id", "claims", "Critical",
         "claim_id appears on more than one row",
         "Double billing; inflated revenue and duplicate payment risk"),
    Rule("R02", "Negative charge amount", "claims", "Major",
         "charge_amount < 0",
         "Understated revenue; claim likely rejected by payer"),
    Rule("R03", "Missing service date", "claims", "Major",
         "service_date is blank or not a valid date",
         "Claim cannot be aged or submitted; breaks timely-filing checks"),
    Rule("R04", "Invalid procedure code", "claims", "Major",
         "cpt_code not found in reference table ref_cpt_codes",
         "Payer rejection; revenue delayed"),
    Rule("R05", "Malformed ICD-10 code", "claims", "Major",
         f"icd10_code does not match pattern {ICD10_PATTERN}",
         "Diagnosis denial (cf. denial code D04)"),
    Rule("R06", "Orphan payment", "payments", "Critical",
         "payment.claim_id has no matching claim",
         "Unallocated cash; cannot be applied to any account"),
    Rule("R07", "Overpayment", "payments", "Critical",
         "paid_amount > charge_amount for the matching claim",
         "Refund liability to payer; audit exposure"),
    Rule("R08", "Payment before service date", "payments", "Major",
         "payment_date < service_date",
         "Timeline impossible; indicates wrong claim match or bad dates"),
    Rule("R09", "Paid claim without payment", "claims", "Critical",
         "status = Paid but no payment record exists",
         "Revenue reported but cash not evidenced"),
    Rule("R10", "Denied claim without denial code", "claims", "Minor",
         "status = Denied and denial_code is blank",
         "Denial cannot be categorised or worked for appeal"),
    Rule("R11", "Duplicate payment", "payments", "Critical",
         "same claim_id, paid_amount and payment_date appear more than once",
         "Cash overstated; possible overpayment to recover"),
]
RULES = {r.rule_id: r for r in RULE_CATALOG}


# ---------------------------------------------------------------------------
# Loading and preparation
# ---------------------------------------------------------------------------
@dataclass
class Data:
    claims_raw: pd.DataFrame  # as received (may contain duplicate claim rows)
    claims: pd.DataFrame      # one row per claim_id (first occurrence kept)
    payments: pd.DataFrame
    valid_cpt: set


def prepare(claims, payments, cpt_ref) -> Data:
    """Fix data types. Bad values become NaN/NaT so rules can catch them."""
    claims = claims.copy()
    payments = payments.copy()
    claims["charge_amount"] = pd.to_numeric(claims["charge_amount"], errors="coerce")
    claims["service_date"] = pd.to_datetime(claims["service_date"], errors="coerce")
    payments["paid_amount"] = pd.to_numeric(payments["paid_amount"], errors="coerce")
    payments["payment_date"] = pd.to_datetime(payments["payment_date"], errors="coerce")
    return Data(
        claims_raw=claims,
        claims=claims.drop_duplicates("claim_id", keep="first"),
        payments=payments,
        valid_cpt=set(cpt_ref["cpt_code"].astype(str)),
    )


def load_data(data_dir=DATA_DIR) -> Data:
    claims = pd.read_csv(data_dir / "claims_raw.csv", dtype=str)
    payments = pd.read_csv(data_dir / "billing_transactions.csv", dtype=str)
    cpt_ref = pd.read_csv(data_dir / "ref_cpt_codes.csv", dtype=str)
    return prepare(claims, payments, cpt_ref)


# ---------------------------------------------------------------------------
# Rule functions: each returns (findings, population_checked)
# ---------------------------------------------------------------------------
def _findings(rule_id, ids, detail, dollars):
    table = RULES[rule_id].table
    return pd.DataFrame(
        {
            "rule_id": rule_id,
            "anomaly_type": RULES[rule_id].name,
            "table": table,
            "record_id": list(ids),
            "detail": detail if isinstance(detail, str) else list(detail),
            "dollars_at_risk": [round(float(x), 2) if pd.notna(x) else 0.0 for x in dollars],
        }
    )


def r01_duplicate_claims(d: Data):
    extra = d.claims_raw[d.claims_raw.duplicated("claim_id", keep="first")]
    extra = extra.drop_duplicates("claim_id")
    return _findings("R01", extra.claim_id, "claim_id appears more than once",
                     extra.charge_amount), d.claims_raw["claim_id"].nunique()


def r02_negative_charge(d: Data):
    bad = d.claims[d.claims.charge_amount < 0]
    return _findings("R02", bad.claim_id, "charge_amount is negative",
                     bad.charge_amount.abs()), len(d.claims)


def r03_missing_service_date(d: Data):
    bad = d.claims[d.claims.service_date.isna()]
    return _findings("R03", bad.claim_id, "service_date missing or invalid",
                     bad.charge_amount), len(d.claims)


def r04_invalid_cpt(d: Data):
    bad = d.claims[~d.claims.cpt_code.isin(d.valid_cpt)]
    return _findings("R04", bad.claim_id, "cpt_code not in reference table: " + bad.cpt_code.astype(str),
                     bad.charge_amount), len(d.claims)


def r05_malformed_icd10(d: Data):
    ok = d.claims.icd10_code.fillna("").str.match(ICD10_PATTERN)
    bad = d.claims[~ok]
    return _findings("R05", bad.claim_id, "icd10_code malformed: " + bad.icd10_code.astype(str),
                     bad.charge_amount), len(d.claims)


def r06_orphan_payments(d: Data):
    bad = d.payments[~d.payments.claim_id.isin(d.claims.claim_id)]
    return _findings("R06", bad.payment_id, "claim_id has no matching claim",
                     bad.paid_amount), len(d.payments)


def _payments_with_claims(d: Data):
    return d.payments.merge(
        d.claims[["claim_id", "charge_amount", "service_date"]], on="claim_id", how="inner"
    )


def r07_overpayment(d: Data):
    m = _payments_with_claims(d)
    bad = m[m.paid_amount > m.charge_amount]
    return _findings("R07", bad.payment_id, "paid_amount exceeds charge_amount",
                     bad.paid_amount - bad.charge_amount), len(m)


def r08_payment_before_service(d: Data):
    m = _payments_with_claims(d)
    bad = m[m.payment_date < m.service_date]
    return _findings("R08", bad.payment_id, "payment_date is before service_date",
                     bad.paid_amount), len(m)


def r09_paid_without_payment(d: Data):
    paid = d.claims[d.claims.status == "Paid"]
    bad = paid[~paid.claim_id.isin(d.payments.claim_id)]
    return _findings("R09", bad.claim_id, "status is Paid but no payment record",
                     bad.charge_amount), len(paid)


def r10_denied_without_code(d: Data):
    denied = d.claims[d.claims.status == "Denied"]
    bad = denied[denied.denial_code.isna()]
    return _findings("R10", bad.claim_id, "status is Denied but denial_code is blank",
                     bad.charge_amount), len(denied)


def r11_duplicate_payments(d: Data):
    ordered = d.payments.sort_values("payment_id")
    dup = ordered.duplicated(["claim_id", "paid_amount", "payment_date"], keep="first")
    bad = ordered[dup]
    return _findings("R11", bad.payment_id, "same claim, amount and date already paid",
                     bad.paid_amount), len(d.payments)


RULE_FUNCTIONS = {
    "R01": r01_duplicate_claims,
    "R02": r02_negative_charge,
    "R03": r03_missing_service_date,
    "R04": r04_invalid_cpt,
    "R05": r05_malformed_icd10,
    "R06": r06_orphan_payments,
    "R07": r07_overpayment,
    "R08": r08_payment_before_service,
    "R09": r09_paid_without_payment,
    "R10": r10_denied_without_code,
    "R11": r11_duplicate_payments,
}


# ---------------------------------------------------------------------------
# Run everything
# ---------------------------------------------------------------------------
def run_all_rules(d: Data):
    all_findings, stats = [], []
    for rule in RULE_CATALOG:
        findings, population = RULE_FUNCTIONS[rule.rule_id](d)
        all_findings.append(findings)
        failures = len(findings)
        rate = failures / population if population else 0.0
        tolerance = TOLERANCE[rule.severity]
        stats.append(
            {
                "rule_id": rule.rule_id,
                "rule": rule.name,
                "severity": rule.severity,
                "table": rule.table,
                "records_checked": population,
                "failures": failures,
                "failure_rate": rate,
                "pass_rate": 1 - rate,
                "tolerance": tolerance,
                "status": "Threshold breach" if rate > tolerance else "Within tolerance",
                "dollars_at_risk": round(float(findings.dollars_at_risk.sum()), 2),
            }
        )
    return pd.concat(all_findings, ignore_index=True), pd.DataFrame(stats)


def evaluate_against_manifest(findings, manifest):
    """Score the validator against the ground truth (precision / recall / F1)."""
    found = set(zip(findings.rule_id, findings.record_id))
    truth = set(zip(manifest.rule_id, manifest.record_id))
    rows = []
    for rule in RULE_CATALOG:
        f = {k for k in found if k[0] == rule.rule_id}
        t = {k for k in truth if k[0] == rule.rule_id}
        tp, fp, fn = len(f & t), len(f - t), len(t - f)
        rows.append(_score_row(rule.rule_id, rule.name, tp, fp, fn))
    tp = len(found & truth)
    fp = len(found - truth)
    fn = len(truth - found)
    rows.append(_score_row("ALL", "All rules", tp, fp, fn))
    return pd.DataFrame(rows)


def _score_row(rule_id, name, tp, fp, fn):
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "rule_id": rule_id, "rule": name,
        "true_positives": tp, "false_positives": fp, "false_negatives": fn,
        "precision": precision, "recall": recall, "f1": f1,
    }


# ---------------------------------------------------------------------------
# Excel scorecard
# ---------------------------------------------------------------------------
def write_scorecard(path, stats, findings, evaluation, n_claims, n_payments):
    catalog = pd.DataFrame(
        [r.__dict__ for r in RULE_CATALOG]
    ).rename(columns={"rule_id": "Rule ID", "name": "Rule", "table": "Table",
                      "severity": "Severity", "logic": "Logic",
                      "business_impact": "Business impact"})

    with pd.ExcelWriter(path, engine="xlsxwriter") as xw:
        wb = xw.book
        title = wb.add_format({"bold": True, "font_size": 16, "font_color": "#1F3864"})
        sub = wb.add_format({"italic": True, "font_color": "#595959"})
        head = wb.add_format({"bold": True, "bg_color": "#1F3864", "font_color": "white",
                              "border": 1, "text_wrap": True, "valign": "vcenter"})
        kpi_label = wb.add_format({"bold": True, "bg_color": "#D9E2F3", "border": 1})
        kpi_int = wb.add_format({"border": 1, "num_format": "#,##0"})
        kpi_usd = wb.add_format({"border": 1, "num_format": "$#,##0"})
        pct = wb.add_format({"num_format": "0.00%"})
        usd = wb.add_format({"num_format": "$#,##0.00"})
        wrap = wb.add_format({"text_wrap": True, "valign": "top"})
        red = wb.add_format({"bg_color": "#F8CBAD", "font_color": "#9C0006"})
        green = wb.add_format({"bg_color": "#C6EFCE", "font_color": "#006100"})

        # --- Scorecard sheet -------------------------------------------------
        stats.to_excel(xw, sheet_name="Scorecard", index=False, startrow=5)
        ws = xw.sheets["Scorecard"]
        ws.write("A1", "Healthcare Claims Data Quality Scorecard", title)
        ws.write("A2", "Synthetic data. Generated by validate_data.py", sub)
        breaches = int((stats.status == "Threshold breach").sum())
        ws.write("A3", "Claims checked", kpi_label); ws.write("B3", n_claims, kpi_int)
        ws.write("C3", "Payments checked", kpi_label); ws.write("D3", n_payments, kpi_int)
        ws.write("E3", "Rules in breach", kpi_label); ws.write("F3", f"{breaches} of {len(stats)}", kpi_int)
        ws.write("G3", "Total findings", kpi_label); ws.write("H3", len(findings), kpi_int)
        ws.write("I3", "$ at risk", kpi_label); ws.write("J3", stats.dollars_at_risk.sum(), kpi_usd)
        for col, name in enumerate(stats.columns):
            ws.write(5, col, name.replace("_", " ").title(), head)
        ws.set_row(5, 30)
        ws.set_column("A:A", 8); ws.set_column("B:B", 32); ws.set_column("C:D", 11)
        ws.set_column("E:F", 14, kpi_int)
        ws.set_column("G:I", 13, pct); ws.set_column("J:J", 18)
        ws.set_column("K:K", 16, usd)
        last = len(stats) + 5
        ws.conditional_format(6, 9, last, 9, {"type": "text", "criteria": "containing",
                                              "value": "breach", "format": red})
        ws.conditional_format(6, 9, last, 9, {"type": "text", "criteria": "containing",
                                              "value": "Within", "format": green})
        chart = wb.add_chart({"type": "column"})
        chart.add_series({"name": "Failures", "categories": ["Scorecard", 6, 0, last, 0],
                          "values": ["Scorecard", 6, 5, last, 5], "fill": {"color": "#2F5597"},
                          "data_labels": {"value": True}})
        chart.set_title({"name": "Failures by rule"})
        chart.set_legend({"none": True})
        chart.set_size({"width": 720, "height": 300})
        ws.insert_chart(last + 3, 0, chart)

        # --- Findings sheet ---------------------------------------------------
        findings.to_excel(xw, sheet_name="Findings", index=False)
        wf = xw.sheets["Findings"]
        for col, name in enumerate(findings.columns):
            wf.write(0, col, name, head)
        wf.set_column("A:A", 9); wf.set_column("B:B", 32); wf.set_column("C:C", 10)
        wf.set_column("D:D", 18); wf.set_column("E:E", 48); wf.set_column("F:F", 16, usd)
        wf.autofilter(0, 0, len(findings), len(findings.columns) - 1)
        wf.freeze_panes(1, 0)

        # --- Validator vs ground truth ---------------------------------------
        evaluation.to_excel(xw, sheet_name="Validator vs Truth", index=False)
        we = xw.sheets["Validator vs Truth"]
        for col, name in enumerate(evaluation.columns):
            we.write(0, col, name.replace("_", " ").title(), head)
        we.set_column("A:A", 8); we.set_column("B:B", 32); we.set_column("C:E", 14)
        we.set_column("F:H", 12, pct)

        # --- Rule catalog -----------------------------------------------------
        catalog.to_excel(xw, sheet_name="Rule Catalog", index=False)
        wc = xw.sheets["Rule Catalog"]
        for col, name in enumerate(catalog.columns):
            wc.write(0, col, name, head)
        wc.set_column("A:A", 8); wc.set_column("B:B", 30); wc.set_column("C:D", 11)
        wc.set_column("E:E", 55, wrap); wc.set_column("F:F", 55, wrap)


# ---------------------------------------------------------------------------
def main():
    REPORT_DIR.mkdir(exist_ok=True)
    d = load_data()
    findings, stats = run_all_rules(d)
    manifest = pd.read_csv(DATA_DIR / "anomaly_manifest.csv", dtype=str)
    evaluation = evaluate_against_manifest(findings, manifest)

    findings.to_csv(REPORT_DIR / "findings.csv", index=False)
    write_scorecard(REPORT_DIR / "dq_scorecard.xlsx", stats, findings, evaluation,
                    n_claims=len(d.claims), n_payments=len(d.payments))

    pd.set_option("display.width", 160)
    print("DATA QUALITY SCORECARD")
    print(stats[["rule_id", "rule", "severity", "records_checked", "failures",
                 "failure_rate", "status", "dollars_at_risk"]]
          .to_string(index=False, formatters={"failure_rate": "{:.2%}".format,
                                              "dollars_at_risk": "${:,.2f}".format}))
    print(f"\nTotal findings: {len(findings)}   "
          f"Total $ at risk: ${stats.dollars_at_risk.sum():,.2f}")
    print("\nVALIDATOR vs GROUND TRUTH")
    print(evaluation.to_string(index=False, formatters={
        "precision": "{:.0%}".format, "recall": "{:.0%}".format, "f1": "{:.0%}".format}))
    print(f"\nSaved: {REPORT_DIR / 'dq_scorecard.xlsx'} and {REPORT_DIR / 'findings.csv'}")


if __name__ == "__main__":
    main()