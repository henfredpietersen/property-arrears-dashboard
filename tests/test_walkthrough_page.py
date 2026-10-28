"""Browser test for the interactive page: it loads without errors, and its in-page
number check gives exactly the same verdicts as the Python check.

Skipped automatically where Playwright/Chromium isn't installed (e.g. plain CI).
"""

from pathlib import Path

import pytest

from arrears_dashboard.load import load_all
from arrears_dashboard.reconcile import run
from arrears_dashboard.summary import build_facts, check_numbers

playwright = pytest.importorskip("playwright.sync_api")

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "docs" / "walkthrough.html"

CASES = [
    "Occupancy is 70.0% by units. Four tenants owe $74,200 in total.",
    "Tenants owe $78,500 in total, and arrears fell 12% since last month.",
    "Delta Cold Storage owes $48,800.00 and $16,000 is over 90 days old.",
    "As of 2026-10-31, 7 of 10 units are occupied.",
    "Occupancy is 71% and 5 data issues need action.",
    "Owed: 74,200.50 across 4 tenants",
    "",
]


@pytest.fixture(scope="module")
def page():
    if not PAGE.exists():
        pytest.skip("run walkthrough/build.py first")
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001 - browser not installed
            pytest.skip(f"Chromium not available: {exc}")
        pg = browser.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(PAGE.as_uri())
        pg.wait_for_timeout(200)
        yield pg, errors
        browser.close()


def test_page_loads_without_errors(page):
    pg, errors = page
    assert errors == []
    assert pg.locator("#ov-arrears-walkthrough").evaluate("h => !!h.shadowRoot")


def test_in_page_guard_matches_python(page):
    pg, _ = page
    facts = build_facts(run(load_all(ROOT / "data"), "2026-10-31"))
    for text in CASES:
        js = pg.locator("#ov-arrears-walkthrough").evaluate("(h, t) => h.__checkNumbers(t)", text)
        assert js == check_numbers(text, facts), text


def test_page_shows_pipeline_totals(page):
    pg, _ = page
    text = pg.locator("#ov-arrears-walkthrough").evaluate("h => h.shadowRoot.textContent")
    for expected in ["$74,200", "70.0%", "67.3%", "$16,000", "$2,500.00"]:
        assert expected in text
