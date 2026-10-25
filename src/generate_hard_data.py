"""
generate_hard_data.py  (Phase 3)

Builds a HARDER test set on top of the Phase 1 data, closer to messy real life.
Reads ./data, writes ./data_hard.

What it adds
1. New anomaly type R12: near-duplicate billing (same patient, provider,
   procedure, date and charge, but a different claim_id).
2. Overlapping anomalies: 10 claims that carry TWO problems at once.
3. Legitimate look-alikes that must NOT be flagged (to measure false positives):
     - same patient/provider/day, different procedure
     - repeat therapy visit a week later (same procedure, different date)
     - a payment split into two equal instalments on different dates
     - payment exactly equal to the charge
4. Formatting noise that is NOT an anomaly (to be cleaned, not flagged):
     - stray spaces and lower/upper case in codes, ids and status
     - US-style dates (MM/DD/YYYY) mixed with ISO dates
     - currency text such as "$1,234.50"

All data is SYNTHETIC.
"""
import random
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from generate_data import CPT_BAD_EXAMPLES, CPT_REF, ICD10_BAD_EXAMPLES

SRC_DIR = Path("data")
OUT_DIR = Path("data_hard")
SEED = 2026
rng = random.Random(SEED)

ISO = "%Y-%m-%d"
US = "%m/%d/%Y"


def add_days(iso_date, days):
    return (datetime.strptime(iso_date, ISO) + timedelta(days=days)).strftime(ISO)


def main():
    kw = dict(dtype=str, keep_default_na=False)  # keep everything as plain text
    claims = pd.read_csv(SRC_DIR / "claims_raw.csv", **kw).to_dict("records")
    payments = pd.read_csv(SRC_DIR / "billing_transactions.csv", **kw).to_dict("records")
    manifest = pd.read_csv(SRC_DIR / "anomaly_manifest.csv", **kw).to_dict("records")
    bad_ids = {m["record_id"] for m in manifest}

    pays_by_claim = defaultdict(list)
    for p in payments:
        pays_by_claim[p["claim_id"]].append(p)

    # Claims with no known problem, and no problem on their payment either
    clean = [
        c for c in claims
        if c["claim_id"] not in bad_ids
        and all(p["payment_id"] not in bad_ids for p in pays_by_claim[c["claim_id"]])
        and len(pays_by_claim[c["claim_id"]]) <= 1
    ]
    used = set()

    def pick(pool, k):
        candidates = [c for c in pool if c["claim_id"] not in used]
        chosen = rng.sample(candidates, k)
        used.update(c["claim_id"] for c in chosen)
        return chosen

    next_num = [105001]

    def new_claim_id():
        cid = f"CLM-{next_num[0]}"
        next_num[0] += 1
        return cid

    def log(rule, name, record_id, detail):
        manifest.append({"rule_id": rule, "anomaly_type": name, "table": "claims",
                         "record_id": record_id, "detail": detail})

    pending = [c for c in clean if c["status"] == "Pending"]
    paid_one_payment = [c for c in clean if c["status"] == "Paid"
                        and len(pays_by_claim[c["claim_id"]]) == 1]

    # --- 1. R12 near-duplicate billing -------------------------------------
    for src in pick([c for c in clean if c["status"] in ("Paid", "Pending")], 12):
        dup = dict(src)
        dup.update(claim_id=new_claim_id(), status="Pending", denial_code="",
                   submission_date=add_days(src["submission_date"], rng.randint(3, 20)))
        claims.append(dup)
        log("R12", "Possible duplicate billing", dup["claim_id"],
            f"Same patient, provider, procedure, date and charge as {src['claim_id']}")

    # --- 2. Overlapping anomalies (two problems on one claim) --------------
    for c in pick(pending, 5):
        c["charge_amount"] = f"{-float(c['charge_amount']):.2f}"
        c["cpt_code"] = rng.choice(CPT_BAD_EXAMPLES)
        log("R02", "Negative charge amount", c["claim_id"], "overlap: also invalid CPT")
        log("R04", "Invalid procedure code", c["claim_id"], "overlap: also negative charge")
    for c in pick(pending, 5):
        c["service_date"] = ""
        c["icd10_code"] = rng.choice(ICD10_BAD_EXAMPLES)
        log("R03", "Missing service date", c["claim_id"], "overlap: also malformed ICD-10")
        log("R05", "Malformed ICD-10 code", c["claim_id"], "overlap: also missing date")

    # --- 3. Legitimate look-alikes (NOT anomalies) -------------------------
    for src in pick(clean, 20):  # same patient and day, different procedure
        other = rng.choice([x for x in CPT_REF if x[0] != src["cpt_code"]])
        c = dict(src)
        c.update(claim_id=new_claim_id(), cpt_code=other[0], status="Pending", denial_code="",
                 charge_amount=f"{rng.uniform(other[2], other[3]):.2f}")
        claims.append(c)
    for src in pick(clean, 20):  # repeat therapy visit a week later
        c = dict(src)
        c.update(claim_id=new_claim_id(), status="Pending", denial_code="",
                 service_date=add_days(src["service_date"], 7),
                 submission_date=add_days(src["submission_date"], 7))
        claims.append(c)
    for src in pick(paid_one_payment, 15):  # instalments: two equal payments, different dates
        p = pays_by_claim[src["claim_id"]][0]
        half = f"{float(p['paid_amount']) / 2:.2f}"
        p["paid_amount"] = half
        second = dict(p)
        second.update(payment_id=f"PAY-INST-{src['claim_id'][-5:]}", paid_amount=half,
                      payment_date=add_days(p["payment_date"], 14))
        payments.append(second)
    for src in pick(paid_one_payment, 15):  # payment exactly equals the charge
        pays_by_claim[src["claim_id"]][0]["paid_amount"] = src["charge_amount"]

    # --- 4. Formatting noise (cleaning, not anomalies) ---------------------
    noise = defaultdict(int)

    def chance(p):
        return rng.random() < p

    def pad_or_case(value, label, case_fn):
        noise[label] += 1
        return rng.choice([f" {value}", f"{value} ", case_fn(value)])

    for c in claims:
        if chance(0.04):
            c["cpt_code"] = pad_or_case(c["cpt_code"], "cpt_code spacing/case", str.lower)
        if c["icd10_code"] and chance(0.04):
            c["icd10_code"] = pad_or_case(c["icd10_code"], "icd10_code spacing/case", str.lower)
        if chance(0.03):
            c["status"] = pad_or_case(c["status"], "status spacing/case", str.upper)
        if c["service_date"] and chance(0.06):
            c["service_date"] = datetime.strptime(c["service_date"], ISO).strftime(US)
            noise["service_date US format"] += 1
        if c["charge_amount"] and not c["charge_amount"].startswith("-") and chance(0.02):
            c["charge_amount"] = f"${float(c['charge_amount']):,.2f}"
            noise["charge_amount currency text"] += 1
    for p in payments:
        if chance(0.04):
            p["claim_id"] = pad_or_case(p["claim_id"], "payment claim_id spacing/case", str.lower)
        if p["payment_date"] and chance(0.06):
            p["payment_date"] = datetime.strptime(p["payment_date"], ISO).strftime(US)
            noise["payment_date US format"] += 1

    # --- 5. Save -----------------------------------------------------------
    rng.shuffle(claims)
    rng.shuffle(payments)
    OUT_DIR.mkdir(exist_ok=True)
    pd.DataFrame(claims).to_csv(OUT_DIR / "claims_raw.csv", index=False)
    pd.DataFrame(payments).to_csv(OUT_DIR / "billing_transactions.csv", index=False)
    pd.read_csv(SRC_DIR / "ref_cpt_codes.csv").to_csv(OUT_DIR / "ref_cpt_codes.csv", index=False)
    man = pd.DataFrame(manifest).drop(columns="anomaly_id")  # renumber below
    man.insert(0, "anomaly_id", [f"A{i:04d}" for i in range(1, len(man) + 1)])
    man.to_csv(OUT_DIR / "anomaly_manifest.csv", index=False)

    print(f"claims_raw.csv           : {len(claims):>6} rows")
    print(f"billing_transactions.csv : {len(payments):>6} rows")
    print(f"anomaly_manifest.csv     : {len(man):>6} injected anomalies")
    print("\nFormatting noise added (not anomalies):")
    for label, n in sorted(noise.items()):
        print(f"  {label:<34}{n:>5}")


if __name__ == "__main__":
    main()