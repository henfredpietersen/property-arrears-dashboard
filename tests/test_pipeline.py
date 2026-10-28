"""The eval: every expected number below was worked out by hand from the
sample CSVs (see README, 'How the expected answers were derived')."""

from pathlib import Path

import pandas as pd
import pytest

from arrears_dashboard.load import load_all, read_csv
from arrears_dashboard.normalize import money, name_similarity, unit_id
from arrears_dashboard.reconcile import bucket_for, run

DATA = Path(__file__).resolve().parent.parent / "data"
AS_OF = "2026-10-31"


@pytest.fixture(scope="module")
def result():
    return run(load_all(DATA), AS_OF)


def tenant(result, tenant_id):
    return result.tenants.set_index("tenant_id").loc[tenant_id]


# --- cleaning helpers -------------------------------------------------------

@pytest.mark.parametrize("raw", ["NG101", "ng-101", "NG 101", "Unit NG-101", " ng 101 "])
def test_unit_codes_normalise(raw):
    assert unit_id(raw) == "NG-101"


@pytest.mark.parametrize("raw", ["", None, "Bay #3", "101"])
def test_unreadable_unit_codes_return_none(raw):
    assert unit_id(raw) is None


def test_well_formed_but_unknown_code_is_caught_by_rent_roll_lookup():
    # The parser is deliberately permissive ('Dock 3' -> 'DOCK-3'); the safety net is
    # that any unit not on the rent roll becomes an 'unmatched_transaction' issue.
    assert unit_id("Dock 3") == "DOCK-3"


@pytest.mark.parametrize("raw,expected", [("$9,000.00", 9000.0), ("16,000.00", 16000.0), ("(250)", -250.0)])
def test_money_parsing(raw, expected):
    assert money(raw) == expected


def test_name_variants_match_but_different_companies_do_not():
    assert name_similarity("Blue Harbor Freight, Inc.", "BLUE HARBOR FREIGHT") == 1.0
    assert name_similarity("Blue Harbour Freight", "Blue Harbor Freight Inc") > 0.9
    assert name_similarity("Granite Tool Rental", "Falcon Parts Supply") < 0.5
    assert name_similarity("Ironwood Storage", "Delta Cold Storage") < 0.75


@pytest.mark.parametrize("days,label", [(0, "0-30"), (30, "0-30"), (31, "31-60"), (60, "31-60"),
                                        (77, "61-90"), (90, "61-90"), (91, "91+")])
def test_aging_bucket_edges(days, label):
    assert bucket_for(days) == label


# --- occupancy --------------------------------------------------------------

def test_occupancy(result):
    occ = result.occupancy
    assert (occ["units_occupied"], occ["units_total"]) == (7, 10)
    assert occ["occupancy_pct_units"] == 70.0
    assert (occ["sqft_occupied"], occ["sqft_total"]) == (74000, 110000)
    assert occ["occupancy_pct_sqft"] == 67.3


# --- arrears ----------------------------------------------------------------

def test_total_arrears_and_buckets(result):
    t = result.totals
    assert t["arrears_total"] == 74200.0
    assert t["tenants_in_arrears"] == 4
    assert t["buckets"] == {"0-30": 32500.0, "31-60": 24900.0, "61-90": 800.0, "91+": 16000.0}
    assert sum(t["buckets"].values()) == t["arrears_total"]


@pytest.mark.parametrize("tid,arrears,b030,b3160,b6190,b91", [
    ("T002", 12800.0, 6400.0, 6400.0, 0.0, 0.0),       # paid Aug only
    ("T003", 10000.0, 7500.0, 2500.0, 0.0, 0.0),       # partial Sep payment applied FIFO
    ("T004", 48800.0, 16000.0, 16000.0, 800.0, 16000.0),  # nothing paid + late fee
    ("T007", 2600.0, 2600.0, 0.0, 0.0, 0.0),           # short-paid Oct
])
def test_tenant_aging(result, tid, arrears, b030, b3160, b6190, b91):
    row = tenant(result, tid)
    assert row["arrears"] == arrears
    assert (row["0-30"], row["31-60"], row["61-90"], row["91+"]) == (b030, b3160, b6190, b91)


def test_duplicate_payment_is_counted_once(result):
    # Acme's October payment appears twice. Counted twice, Acme would show a $9,000 credit.
    acme = tenant(result, "T001")
    assert acme["balance"] == 0.0
    assert acme["credit"] == 0.0


def test_credit_memo_creates_credit_not_arrears(result):
    evergreen = tenant(result, "T005")
    assert evergreen["arrears"] == 0.0
    assert evergreen["credit"] == 200.0
    assert result.totals["credit_total"] == 200.0


def test_excluded_rows_do_not_leak_into_totals(result):
    # $1,500 on a unit that doesn't exist and $4,000 on a vacant unit must not be counted.
    assert "NG-109" not in set(result.tenants["unit_id"])
    assert "RB-203" not in set(result.tenants["unit_id"])
    assert result.totals["arrears_total"] == 74200.0


# --- data issues ------------------------------------------------------------

def test_issue_list(result):
    found = sorted(zip(result.issues["type"], result.issues["ref"].astype(str), strict=True))
    assert found == sorted([
        ("arrears_no_recent_contact", "T003"),
        ("arrears_no_recent_contact", "T004"),
        ("charge_on_vacant_unit", "INV-1001-203"),
        ("crm_record_not_in_rent_roll", "Ironwood Storage"),
        ("duplicate_transaction", "PAY-1004-101"),
        ("lease_expired_still_occupied", "NG-102"),
        ("name_mismatch", "PAY-1029-204"),
        ("no_crm_record", "T006"),
        ("unmatched_transaction", "PAY-1012-109"),
    ])
    assert result.totals["issues_action"] == 5


def test_action_items_listed_first(result):
    sev = list(result.issues["severity"])
    assert sev == sorted(sev, key={"action": 0, "review": 1, "info": 2}.get)


def test_missing_column_fails_with_clear_message(tmp_path):
    bad = tmp_path / "rent_roll.csv"
    pd.read_csv(DATA / "rent_roll.csv").drop(columns=["monthly_rent"]).to_csv(bad, index=False)
    with pytest.raises(ValueError, match="monthly_rent"):
        read_csv(bad, "rent_roll")
