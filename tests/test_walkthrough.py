"""The walkthrough page replays this export, so the export must agree with the pipeline."""

import json
from pathlib import Path

import pytest

from arrears_dashboard.walkthrough import build

DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture(scope="module")
def wt():
    return build(DATA, "2026-10-31")


def test_every_accounting_row_has_one_decision(wt):
    rows = [e["row"] for e in wt["ledger_log"]]
    assert len(rows) == len(wt["inputs"]["accounting"]) == len(set(rows))
    counts = {s: sum(e["status"] == s for e in wt["ledger_log"]) for s in ("kept", "excluded", "duplicate")}
    assert counts == {"kept": 38, "excluded": 2, "duplicate": 1}


def test_fifo_lines_add_up_to_reported_buckets(wt):
    for tenant in wt["tenants"]:
        lines = wt["allocations"][tenant["tenant_id"]]["lines"]
        for bucket in wt["buckets"]:
            assert round(sum(x["open"] for x in lines if x["bucket"] == bucket), 2) == tenant[bucket]


def test_copperline_partial_payment_trace(wt):
    lines = wt["allocations"]["T003"]["lines"]
    assert wt["allocations"]["T003"]["paid"] == 12500.0
    assert [(x["applied"], x["open"], x["bucket"]) for x in lines] == [
        (7500.0, 0.0, ""), (5000.0, 2500.0, "31-60"), (0.0, 7500.0, "0-30")]


def test_without_duplicate_check_acme_shows_false_credit(wt):
    w = wt["whatif_no_dedupe"]
    assert w["balance_with_check"] == 0.0
    assert w["balance_without_check"] == -9000.0
    assert w["credit_total_without"] == 9200.0


def test_name_matching_display_agrees_with_pipeline(wt):
    matched = {m["tenant"] for m in wt["cleaning"]["names"] if m["matched"]}
    with_contact = {t["tenant"] for t in wt["tenants"] if t["contact"]}
    assert matched == with_contact


def test_sample_summaries_verdicts(wt):
    s = wt["summary"]["samples"]
    assert s["faithful"]["unsupported"] == []
    assert s["invented"]["unsupported"] == ["78500", "12"]


def test_export_is_json_and_has_no_contact_details(wt):
    text = json.dumps(wt, default=str)
    for private in ["@", "555-", "Promised payment"]:
        assert private not in text
