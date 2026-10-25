"""Unit tests for the validation rules, using tiny hand-made datasets."""
from pathlib import Path

import pandas as pd
import pytest

import validate_data as v

CPT = pd.DataFrame({"cpt_code": ["99213", "97597"]})


def claim(claim_id="C1", cpt="99213", icd="I10", charge="100.00", status="Paid",
          service="2025-03-01", denial=None, patient="PAT-1", provider="PRV-1"):
    return {"claim_id": claim_id, "patient_id": patient, "provider_id": provider,
            "cpt_code": cpt, "icd10_code": icd,
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


# ---------------------------------------------------------------------------
# Phase 3: cleaning layer, R12, and look-alikes that must NOT be flagged
# ---------------------------------------------------------------------------
def test_formatting_noise_is_cleaned_not_flagged():
    rows = [claim(cpt=" 99213 ", icd="i10", status="paid", service="03/01/2025",
                  charge="$1,234.50")]
    data = v.prepare(pd.DataFrame(rows), pd.DataFrame([pay(claim_id="c1 ", date="04/01/2025")]), CPT)
    findings, _ = v.run_all_rules(data)
    assert findings.empty
    assert data.claims.charge_amount.iloc[0] == 1234.50


def test_garbage_date_is_still_flagged_after_cleaning():
    assert len(run(v.r03_missing_service_date, [claim(service="31/31/2025")])) == 1


def test_near_duplicate_billing_flags_only_the_later_claim():
    f = run(v.r12_possible_duplicate_billing, [claim("C1"), claim("C2")], [])
    assert list(f.record_id) == ["C2"]


def test_same_day_different_procedure_is_not_near_duplicate():
    f = run(v.r12_possible_duplicate_billing, [claim("C1"), claim("C2", cpt="97597")], [])
    assert f.empty


def test_repeat_visit_a_week_later_is_not_near_duplicate():
    f = run(v.r12_possible_duplicate_billing, [claim("C1"), claim("C2", service="2025-03-08")], [])
    assert f.empty


def test_exact_duplicate_rows_are_left_to_r01_not_r12():
    f = run(v.r12_possible_duplicate_billing, [claim("C1"), claim("C1")], [])
    assert f.empty


def test_equal_instalments_on_different_dates_are_not_duplicate_payments():
    f = run(v.r11_duplicate_payments, [claim()],
            [pay("P1", amount="45.00", date="2025-04-01"), pay("P2", amount="45.00", date="2025-04-15")])
    assert f.empty


def test_payment_equal_to_charge_is_not_an_overpayment():
    assert run(v.r07_overpayment, [claim(charge="100.00")], [pay(amount="100.00")]).empty


@pytest.mark.skipif(not Path("data_hard/anomaly_manifest.csv").exists(),
                    reason="run generate_hard_data.py first")
def test_hard_dataset_matches_ground_truth():
    data = v.load_data(Path("data_hard"))
    findings, _ = v.run_all_rules(data)
    manifest = pd.read_csv("data_hard/anomaly_manifest.csv", dtype=str)
    overall = v.evaluate_against_manifest(findings, manifest).query("rule_id == 'ALL'").iloc[0]
    assert overall.false_positives == 0 and overall.false_negatives == 0
