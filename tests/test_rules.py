"""Unit tests for the validation rules, using tiny hand-made datasets."""
from pathlib import Path

import pandas as pd
import pytest

import validate_data as v

CPT = pd.DataFrame({"cpt_code": ["99213", "97597"]})


def claim(claim_id="C1", cpt="99213", icd="I10", charge="100.00", status="Paid",
          service="2025-03-01", denial=None):
    return {"claim_id": claim_id, "cpt_code": cpt, "icd10_code": icd,
            "charge_amount": charge, "status": status,
            "service_date": service, "denial_code": denial}


def pay(payment_id="P1", claim_id="C1", amount="90.00", date="2025-04-01"):
    return {"payment_id": payment_id, "claim_id": claim_id,
            "paid_amount": amount, "payment_date": date}


def run(rule_fn, claims, payments=None):
    payments = payments if payments is not None else [pay()]
    pay_df = pd.DataFrame(payments, columns=list(pay().keys()))  # keeps columns when empty
    data = v.prepare(pd.DataFrame(claims), pay_df, CPT)
    findings, _ = rule_fn(data)
    return findings


def test_clean_data_produces_no_findings():
    data = v.prepare(pd.DataFrame([claim()]), pd.DataFrame([pay()]), CPT)
    findings, _ = v.run_all_rules(data)
    assert findings.empty


def test_duplicate_claim_is_flagged_once_even_if_repeated_three_times():
    f = run(v.r01_duplicate_claims, [claim(), claim(), claim()])
    assert list(f.record_id) == ["C1"]


def test_negative_charge_dollars_use_absolute_value():
    f = run(v.r02_negative_charge, [claim(charge="-250.00", status="Pending")], [])
    assert list(f.record_id) == ["C1"] and f.dollars_at_risk.iloc[0] == 250.0


def test_unparseable_service_date_counts_as_missing():
    f = run(v.r03_missing_service_date, [claim(service="not-a-date")])
    assert len(f) == 1


@pytest.mark.parametrize("icd,ok", [("E11.9", True), ("I10", True), ("L97.509", True),
                                    ("E119", False), ("99.9", False), ("I1O", False)])
def test_icd10_format(icd, ok):
    f = run(v.r05_malformed_icd10, [claim(icd=icd)])
    assert (len(f) == 0) == ok


def test_unknown_cpt_flagged():
    assert len(run(v.r04_invalid_cpt, [claim(cpt="99999")])) == 1


def test_orphan_payment():
    f = run(v.r06_orphan_payments, [claim()], [pay(), pay("P2", "C-MISSING")])
    assert list(f.record_id) == ["P2"]


def test_overpayment_amount_is_the_excess():
    f = run(v.r07_overpayment, [claim(charge="100.00")], [pay(amount="130.00")])
    assert f.dollars_at_risk.iloc[0] == 30.0


def test_payment_before_service():
    f = run(v.r08_payment_before_service, [claim(service="2025-03-01")],
            [pay(date="2025-02-15")])
    assert len(f) == 1


def test_paid_claim_without_payment():
    f = run(v.r09_paid_without_payment, [claim()], [])
    assert list(f.record_id) == ["C1"]


def test_denied_without_code_but_pending_is_ignored():
    f = run(v.r10_denied_without_code,
            [claim("C1", status="Denied"), claim("C2", status="Pending")], [])
    assert list(f.record_id) == ["C1"]


def test_duplicate_payment_keeps_the_first_one():
    f = run(v.r11_duplicate_payments, [claim()], [pay("P1"), pay("P2")])
    assert list(f.record_id) == ["P2"]


@pytest.mark.skipif(not Path("data/anomaly_manifest.csv").exists(),
                    reason="run generate_data.py first")
def test_full_dataset_matches_ground_truth():
    data = v.load_data()
    findings, _ = v.run_all_rules(data)
    manifest = pd.read_csv("data/anomaly_manifest.csv", dtype=str)
    result = v.evaluate_against_manifest(findings, manifest)
    overall = result[result.rule_id == "ALL"].iloc[0]
    assert overall.precision == 1.0 and overall.recall == 1.0