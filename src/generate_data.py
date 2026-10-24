"""
generate_data.py  (Phase 1)

Creates a synthetic healthcare revenue-cycle dataset and deliberately injects
data quality problems. Every injected problem is written to a ground-truth
file (anomaly_manifest.csv) so the Phase 2 validator can be scored on
precision and recall.

All data is SYNTHETIC. No real patients, payers' contracts or prices.

Outputs (in ./data):
    claims_raw.csv
    billing_transactions.csv
    ref_cpt_codes.csv
    anomaly_manifest.csv
"""
import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

SEED = 42
N_CLAIMS = 5000
DATA_DIR = Path("data")

rng = random.Random(SEED)

# ---------------------------------------------------------------------------
# Reference data (invented for demonstration; not real fee schedules)
# ---------------------------------------------------------------------------
PAYERS = [
    ("Blue Cross Blue Shield", 0.22),
    ("UnitedHealth Group", 0.22),
    ("Aetna", 0.14),
    ("Cigna", 0.12),
    ("Medicare", 0.20),
    ("Medicaid", 0.10),
]

# (code, short description, min charge, max charge)
CPT_REF = [
    ("99213", "Office visit, established patient", 120, 260),
    ("99214", "Office visit, established patient (higher complexity)", 180, 380),
    ("99203", "Office visit, new patient", 150, 320),
    ("93000", "Electrocardiogram", 60, 150),
    ("71046", "Chest X-ray, 2 views", 90, 220),
    ("80053", "Comprehensive metabolic panel", 40, 110),
    ("85025", "Complete blood count", 25, 80),
    ("97110", "Therapeutic exercise, 15 min", 70, 160),
    ("11042", "Debridement, subcutaneous tissue", 250, 700),
    ("97597", "Debridement, open wound", 200, 600),
    ("97606", "Negative pressure wound therapy", 300, 900),
    ("E0601", "CPAP device (DME)", 600, 1800),
    ("E1390", "Oxygen concentrator (DME)", 900, 2600),
    ("K0001", "Standard wheelchair (DME)", 700, 2200),
]
VALID_CPT = {c[0] for c in CPT_REF}

ICD10_VALID = [
    "E11.9", "I10", "J45.909", "M54.50", "L97.509",
    "L89.159", "E11.621", "J44.9", "G47.33", "Z00.00",
]
ICD10_BAD_EXAMPLES = ["E119", "99.9", "ICD10-E11", "E11.99999", "I1O"]
CPT_BAD_EXAMPLES = ["99999", "00000", "ABCDE", "9921", "1234567"]

DENIAL_CODES = [
    "D01_EligExpired",
    "D02_PriorAuthReq",
    "D03_DuplicateClaim",
    "D04_InvalidICD10",
]

# How many of each anomaly to inject (150 of 5,000 claims = 3.0%)
ANOMALY_PLAN = {
    "R01": 12,  # duplicate claim_id
    "R02": 12,  # negative charge amount
    "R03": 14,  # missing service date
    "R04": 14,  # invalid CPT/HCPCS code
    "R05": 14,  # malformed ICD-10 code
    "R06": 14,  # orphan payment (claim does not exist)
    "R07": 14,  # overpayment (paid > charge)
    "R08": 14,  # payment dated before service
    "R09": 14,  # Paid claim with no payment record
    "R10": 14,  # Denied claim with no denial code
    "R11": 14,  # duplicate payment for one claim
}

RULE_NAMES = {
    "R01": "Duplicate claim_id",
    "R02": "Negative charge amount",
    "R03": "Missing service date",
    "R04": "Invalid procedure code",
    "R05": "Malformed ICD-10 code",
    "R06": "Orphan payment",
    "R07": "Overpayment",
    "R08": "Payment before service date",
    "R09": "Paid claim without payment",
    "R10": "Denied claim without denial code",
    "R11": "Duplicate payment",
}


# ---------------------------------------------------------------------------
# Step 1: clean data
# ---------------------------------------------------------------------------
def build_clean_data(n_claims):
    claims, payments = [], []
    start = date(2025, 1, 1)
    payer_names = [p[0] for p in PAYERS]
    payer_weights = [p[1] for p in PAYERS]
    pay_counter = 1

    for i in range(1, n_claims + 1):
        claim_id = f"CLM-{100000 + i}"
        cpt, _, lo, hi = rng.choice(CPT_REF)
        service_date = start + timedelta(days=rng.randint(0, 364))
        submission_date = service_date + timedelta(days=rng.randint(1, 10))
        charge = round(rng.uniform(lo, hi), 2)
        status = rng.choices(["Paid", "Pending", "Denied"], weights=[68, 20, 12])[0]
        denial = rng.choice(DENIAL_CODES) if status == "Denied" else None

        claims.append(
            {
                "claim_id": claim_id,
                "patient_id": f"PAT-{rng.randint(1000, 9999)}",
                "provider_id": f"PRV-{rng.randint(1, 25):03d}",
                "payer_name": rng.choices(payer_names, weights=payer_weights)[0],
                "service_date": service_date,
                "submission_date": submission_date,
                "cpt_code": cpt,
                "icd10_code": rng.choice(ICD10_VALID),
                "charge_amount": charge,
                "status": status,
                "denial_code": denial,
            }
        )

        if status in ("Paid", "Denied"):
            paid = round(charge * rng.uniform(0.70, 1.00), 2) if status == "Paid" else 0.00
            payments.append(
                {
                    "payment_id": f"PAY-{200000 + pay_counter}",
                    "claim_id": claim_id,
                    "paid_amount": paid,
                    "payment_date": service_date + timedelta(days=rng.randint(14, 60)),
                    "payment_method": rng.choice(["EFT", "Check", "Credit Card"]),
                }
            )
            pay_counter += 1

    return claims, payments, pay_counter


# ---------------------------------------------------------------------------
# Step 2: inject anomalies, recording each one in the manifest
# ---------------------------------------------------------------------------
def inject_anomalies(claims, payments, pay_counter):
    manifest = []
    claim_by_id = {c["claim_id"]: c for c in claims}
    pay_by_claim = {p["claim_id"]: p for p in payments}

    all_ids = [c["claim_id"] for c in claims]
    paid_ids = [c["claim_id"] for c in claims if c["status"] == "Paid"]
    pending_ids = [c["claim_id"] for c in claims if c["status"] == "Pending"]
    denied_ids = [c["claim_id"] for c in claims if c["status"] == "Denied"]

    used = set()  # a claim is only ever corrupted once, so ground truth stays clean

    def pick(pool, k):
        candidates = [x for x in pool if x not in used]
        chosen = rng.sample(candidates, k)
        used.update(chosen)
        return chosen

    def log(rule, table, record_id, detail):
        manifest.append(
            {
                "rule_id": rule,
                "anomaly_type": RULE_NAMES[rule],
                "table": table,
                "record_id": record_id,
                "detail": detail,
            }
        )

    # R01 duplicate claim rows (exact copy, same claim_id)
    for cid in pick(all_ids, ANOMALY_PLAN["R01"]):
        claims.append(dict(claim_by_id[cid]))
        log("R01", "claims", cid, "Claim row appears twice")

    # R02 to R05: corrupt pending claims (they have no payments, so no side effects)
    for cid in pick(pending_ids, ANOMALY_PLAN["R02"]):
        c = claim_by_id[cid]
        c["charge_amount"] = -c["charge_amount"]
        log("R02", "claims", cid, f"charge_amount set to {c['charge_amount']}")

    for cid in pick(pending_ids, ANOMALY_PLAN["R03"]):
        claim_by_id[cid]["service_date"] = None
        log("R03", "claims", cid, "service_date blanked")

    for cid in pick(pending_ids, ANOMALY_PLAN["R04"]):
        bad = rng.choice(CPT_BAD_EXAMPLES)
        claim_by_id[cid]["cpt_code"] = bad
        log("R04", "claims", cid, f"cpt_code set to {bad}")

    for cid in pick(pending_ids, ANOMALY_PLAN["R05"]):
        bad = rng.choice(ICD10_BAD_EXAMPLES)
        claim_by_id[cid]["icd10_code"] = bad
        log("R05", "claims", cid, f"icd10_code set to {bad}")

    # R06 orphan payments (claim ids that do not exist)
    for i in range(1, ANOMALY_PLAN["R06"] + 1):
        pid = f"PAY-ORPH-{i:03d}"
        payments.append(
            {
                "payment_id": pid,
                "claim_id": f"CLM-{900000 + i}",
                "paid_amount": round(rng.uniform(100, 2000), 2),
                "payment_date": date(2025, 1, 1) + timedelta(days=rng.randint(30, 400)),
                "payment_method": rng.choice(["EFT", "Check"]),
            }
        )
        log("R06", "payments", pid, "Payment references a claim_id that does not exist")

    # R07 overpayment
    for cid in pick(paid_ids, ANOMALY_PLAN["R07"]):
        p = pay_by_claim[cid]
        p["paid_amount"] = round(claim_by_id[cid]["charge_amount"] * rng.uniform(1.05, 1.50), 2)
        log("R07", "payments", p["payment_id"], f"paid {p['paid_amount']} exceeds charge")

    # R08 payment dated before service
    for cid in pick(paid_ids, ANOMALY_PLAN["R08"]):
        p = pay_by_claim[cid]
        p["payment_date"] = claim_by_id[cid]["service_date"] - timedelta(days=rng.randint(1, 30))
        log("R08", "payments", p["payment_id"], "payment_date earlier than service_date")

    # R09 Paid claim whose payment record is missing
    r09_claims = pick(paid_ids, ANOMALY_PLAN["R09"])
    r09_payment_ids = {pay_by_claim[cid]["payment_id"] for cid in r09_claims}
    payments[:] = [p for p in payments if p["payment_id"] not in r09_payment_ids]
    for cid in r09_claims:
        log("R09", "claims", cid, "Status is Paid but no payment record exists")

    # R10 Denied claim without denial code
    for cid in pick(denied_ids, ANOMALY_PLAN["R10"]):
        claim_by_id[cid]["denial_code"] = None
        log("R10", "claims", cid, "Status is Denied but denial_code is blank")

    # R11 duplicate payment (same claim, same amount, same date, new payment_id)
    for cid in pick(paid_ids, ANOMALY_PLAN["R11"]):
        original = pay_by_claim[cid]
        dup = dict(original)
        dup["payment_id"] = f"PAY-{200000 + pay_counter}"
        pay_counter += 1
        payments.append(dup)
        log("R11", "payments", dup["payment_id"], f"Duplicate of {original['payment_id']}")

    return manifest


# ---------------------------------------------------------------------------
# Step 3: save
# ---------------------------------------------------------------------------
def main():
    claims, payments, pay_counter = build_clean_data(N_CLAIMS)
    manifest = inject_anomalies(claims, payments, pay_counter)

    rng.shuffle(claims)
    rng.shuffle(payments)

    DATA_DIR.mkdir(exist_ok=True)
    pd.DataFrame(claims).to_csv(DATA_DIR / "claims_raw.csv", index=False)
    pd.DataFrame(payments).to_csv(DATA_DIR / "billing_transactions.csv", index=False)

    ref = pd.DataFrame(CPT_REF, columns=["cpt_code", "description", "min_charge", "max_charge"])
    ref.to_csv(DATA_DIR / "ref_cpt_codes.csv", index=False)

    man = pd.DataFrame(manifest)
    man.insert(0, "anomaly_id", [f"A{i:04d}" for i in range(1, len(man) + 1)])
    man.to_csv(DATA_DIR / "anomaly_manifest.csv", index=False)

    print(f"claims_raw.csv           : {len(claims):>6} rows")
    print(f"billing_transactions.csv : {len(payments):>6} rows")
    print(f"anomaly_manifest.csv     : {len(man):>6} injected anomalies "
          f"({len(man) / N_CLAIMS:.1%} of {N_CLAIMS} claims)")
    print()
    print(man.groupby(["rule_id", "anomaly_type"]).size().to_string())


if __name__ == "__main__":
    main()