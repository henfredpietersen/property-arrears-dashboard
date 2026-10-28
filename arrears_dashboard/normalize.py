"""Small cleaning helpers for the messy fields each export uses differently."""

import difflib
import re

import pandas as pd

UNIT_RE = re.compile(r"^([A-Z]+)-?(\d+)$")
COMPANY_SUFFIXES = {"llc", "inc", "co", "ltd", "corp", "company", "pty"}


def is_blank(value) -> bool:
    return value is None or (isinstance(value, float) and pd.isna(value)) or str(value).strip() == ""


def unit_id(raw):
    """'NG101', 'ng-101', 'NG 101' and 'Unit NG-101' all become 'NG-101'.
    Returns None when the value cannot be read as a unit."""
    if is_blank(raw):
        return None
    cleaned = str(raw).upper().replace("UNIT", "").replace(" ", "").strip()
    match = UNIT_RE.match(cleaned)
    if not match:
        return None
    return f"{match.group(1)}-{match.group(2)}"


def money(raw) -> float:
    """'$9,000.00', '9000' and '(250)' -> 9000.0, 9000.0, -250.0"""
    text = str(raw).replace("$", "").replace(",", "").strip()
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    return round(float(text), 2)


def company(name) -> str:
    """Lower-case, drop punctuation and legal suffixes, so
    'Blue Harbor Freight, Inc.' and 'BLUE HARBOR FREIGHT' compare equal."""
    if is_blank(name):
        return ""
    words = re.sub(r"[^a-z0-9 ]", " ", str(name).lower()).split()
    return " ".join(w for w in words if w not in COMPANY_SUFFIXES)


def name_similarity(a, b) -> float:
    """0.0 to 1.0. Used to match tenants across systems that have no shared ID."""
    return difflib.SequenceMatcher(None, company(a), company(b)).ratio()
