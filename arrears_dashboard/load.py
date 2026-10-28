"""Read the three exports and fail early, with a clear message, if a column is missing."""

from pathlib import Path

import pandas as pd

REQUIRED = {
    "rent_roll": ["unit_id", "property", "sqft", "tenant_id", "tenant_name",
                  "lease_start", "lease_end", "monthly_rent", "status"],
    "accounting": ["txn_date", "unit_ref", "customer", "txn_type", "amount", "reference"],
    "crm": ["company", "contact_name", "email", "last_contact"],
}

FILES = {
    "rent_roll": "rent_roll.csv",
    "accounting": "accounting_export.csv",
    "crm": "crm_export.csv",
}


def read_csv(path: Path, kind: str) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    frame.columns = [c.strip().lower() for c in frame.columns]
    missing = [c for c in REQUIRED[kind] if c not in frame.columns]
    if missing:
        raise ValueError(f"{path.name} is missing required column(s): {', '.join(missing)}")
    return frame


def load_all(data_dir) -> dict:
    data_dir = Path(data_dir)
    return {kind: read_csv(data_dir / name, kind) for kind, name in FILES.items()}
