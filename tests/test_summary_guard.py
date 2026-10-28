"""The LLM summary is optional. These tests use a fake LLM (no network, no key)
to prove the safeguard: a summary with a made-up number is rejected."""

from pathlib import Path

import pytest

from arrears_dashboard.load import load_all
from arrears_dashboard.reconcile import run
from arrears_dashboard.report import render_html
from arrears_dashboard.summary import build_facts, build_prompt, check_numbers, summarize

DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture(scope="module")
def result():
    return run(load_all(DATA), "2026-10-31")


def test_template_summary_uses_computed_numbers(result):
    s = summarize(result, "template")
    assert s["source"] == "template"
    assert "$74,200.00" in s["text"] and "70.0%" in s["text"]
    assert check_numbers(s["text"], build_facts(result)) == []


def test_faithful_llm_summary_is_accepted(result):
    def fake(prompt):
        return ("Occupancy is 70.0% by units. Four tenants owe $74,200 in total, "
                "with $16,000 over 90 days. Delta Cold Storage owes the most at $48,800.")

    s = summarize(result, "llm", call=fake)
    assert s["source"] == "llm"


def test_llm_summary_with_invented_number_is_rejected(result):
    def fake(prompt):
        return "Tenants owe $78,500 in total and occupancy is 70.0%."

    s = summarize(result, "llm", call=fake)
    assert s["source"] == "template"
    assert "78500" in s["note"]


def test_llm_failure_falls_back_to_template(result):
    def broken(prompt):
        raise ConnectionError("no network")
    s = summarize(result, "llm", call=broken)
    assert s["source"] == "template"
    assert "ConnectionError" in s["note"]


def test_prompt_contains_no_contact_details(result):
    prompt = build_prompt(build_facts(result))
    for private in ["@", "555", "Marco Bianchi", "Promised payment"]:
        assert private not in prompt


def test_dashboard_escapes_html(result):
    html = render_html(result, {"text": "<script>alert(1)</script>", "source": "template", "note": ""})
    assert "<script>alert(1)</script>" not in html
    assert "$74,200.00" in html
