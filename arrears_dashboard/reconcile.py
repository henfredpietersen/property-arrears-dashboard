"""The core merge: rent roll + accounting ledger + CRM -> occupancy, arrears
by tenant with aging buckets, and a list of data issues for a human to check.

Rules (kept simple and explicit so they can be argued with):
- The rent roll is the source of truth for which units exist and who leases them.
- Ledger rows are matched to the rent roll by unit, after cleaning the unit code.
- Payments and credits are applied to the oldest open charge first (FIFO).
- Anything the pipeline can't place confidently is excluded from the numbers and
  listed as an issue, instead of being guessed.
"""

from dataclasses import dataclass

import pandas as pd

from .normalize import company, is_blank, money, name_similarity, unit_id

BUCKETS = [("0-30", 0, 30), ("31-60", 31, 60), ("61-90", 61, 90), ("91+", 91, 10**9)]
CHARGE_TYPES = {"rent", "late_fee", "charge"}
CREDIT_TYPES = {"payment", "credit"}


@dataclass
class Result:
    as_of: pd.Timestamp
    occupancy: dict
    tenants: pd.DataFrame
    issues: pd.DataFrame
    totals: dict


def bucket_for(days: int) -> str:
    for label, low, high in BUCKETS:
        if low <= days <= high:
            return label
    return BUCKETS[0][0]  # future-dated charge: treat as current


def _issue(issues, kind, ref, detail, severity="review"):
    issues.append({"severity": severity, "type": kind, "ref": ref, "detail": detail})


def _clean_rent_roll(raw: pd.DataFrame) -> pd.DataFrame:
    rr = raw.copy()
    rr["unit_id"] = rr["unit_id"].map(unit_id)
    rr["status"] = rr["status"].str.strip().str.lower()
    rr["sqft"] = rr["sqft"].astype(int)
    rr["monthly_rent"] = rr["monthly_rent"].map(lambda v: 0.0 if is_blank(v) else money(v))
    rr["lease_end"] = pd.to_datetime(rr["lease_end"].replace("", None))
    return rr


def _occupancy(rr: pd.DataFrame) -> dict:
    occupied = rr[rr["status"] == "occupied"]
    return {
        "units_total": len(rr),
        "units_occupied": len(occupied),
        "occupancy_pct_units": round(100 * len(occupied) / len(rr), 1),
        "sqft_total": int(rr["sqft"].sum()),
        "sqft_occupied": int(occupied["sqft"].sum()),
        "occupancy_pct_sqft": round(100 * occupied["sqft"].sum() / rr["sqft"].sum(), 1),
    }


def _clean_ledger(raw: pd.DataFrame, rr: pd.DataFrame, issues, name_threshold) -> pd.DataFrame:
    # 1. exact duplicate rows (same date, unit, amount, reference...) are double-posts
    dup_mask = raw.duplicated(keep="first")
    for _, row in raw[dup_mask].iterrows():
        _issue(issues, "duplicate_transaction", row["reference"],
               f"Duplicate row in export ({row['txn_type']} ${money(row['amount']):,.2f}); counted once.")
    led = raw[~dup_mask].copy()

    led["unit"] = led["unit_ref"].map(unit_id)
    led["amount"] = led["amount"].map(money)
    led["txn_date"] = pd.to_datetime(led["txn_date"])
    led["txn_type"] = led["txn_type"].str.strip().str.lower()

    units = rr.set_index("unit_id")
    keep = []
    for idx, row in led.iterrows():
        ref = row["reference"]
        if row["unit"] is None or row["unit"] not in units.index:
            _issue(issues, "unmatched_transaction", ref,
                   f"Unit '{row['unit_ref']}' is not on the rent roll ({row['txn_type']} "
                   f"${row['amount']:,.2f} from '{row['customer']}'). Excluded.", "action")
            continue
        unit = units.loc[row["unit"]]
        if unit["status"] != "occupied":
            _issue(issues, "charge_on_vacant_unit", ref,
                   f"{row['txn_type']} ${row['amount']:,.2f} posted to vacant unit {row['unit']}. Excluded.",
                   "action")
            continue
        if row["txn_type"] not in CHARGE_TYPES | CREDIT_TYPES:
            _issue(issues, "unknown_txn_type", ref, f"Type '{row['txn_type']}' not recognised. Excluded.")
            continue
        if not is_blank(row["customer"]):
            score = name_similarity(row["customer"], unit["tenant_name"])
            if score < name_threshold:
                _issue(issues, "name_mismatch", ref,
                       f"Posted to {row['unit']} ({unit['tenant_name']}) but payer is "
                       f"'{row['customer']}'. Check for a mis-posting. Applied to the unit as recorded.")
        keep.append(idx)

    led = led.loc[keep].copy()
    led["tenant_id"] = led["unit"].map(units["tenant_id"])
    return led


def _age_tenant(rows: pd.DataFrame, as_of: pd.Timestamp) -> dict:
    charges = rows[rows["txn_type"].isin(CHARGE_TYPES)].sort_values("txn_date")
    paid = rows[rows["txn_type"].isin(CREDIT_TYPES)]["amount"].sum()
    out = {label: 0.0 for label, _, _ in BUCKETS}
    remaining = paid
    for _, charge in charges.iterrows():
        applied = min(charge["amount"], remaining)
        remaining -= applied
        open_amount = round(charge["amount"] - applied, 2)
        if open_amount > 0:
            days = (as_of - charge["txn_date"]).days
            out[bucket_for(days)] += open_amount
    balance = round(charges["amount"].sum() - paid, 2)
    out["balance"] = balance
    out["arrears"] = max(0.0, balance)
    out["credit"] = max(0.0, -balance)
    return out


def _match_crm(rr_tenants: pd.DataFrame, crm: pd.DataFrame, issues, threshold) -> dict:
    """Return {tenant_id: crm row}. The CRM has no tenant ID, so match on name."""
    matches, used = {}, set()
    for _, tenant in rr_tenants.iterrows():
        best, best_score = None, 0.0
        for idx, rec in crm.iterrows():
            score = name_similarity(tenant["tenant_name"], rec["company"])
            if score > best_score:
                best, best_score = idx, score
        if best is not None and best_score >= threshold:
            matches[tenant["tenant_id"]] = crm.loc[best]
            used.add(best)
        else:
            _issue(issues, "no_crm_record", tenant["tenant_id"],
                   f"{tenant['tenant_name']} ({tenant['unit_id']}) has no matching CRM contact.")
    for idx, rec in crm.iterrows():
        if idx not in used:
            _issue(issues, "crm_record_not_in_rent_roll", rec["company"],
                   f"CRM company '{rec['company']}' is not a current tenant (prospect or former tenant?).",
                   "info")
    return matches


def run(frames: dict, as_of, name_threshold: float = 0.75, contact_days: int = 30) -> Result:
    as_of = pd.Timestamp(as_of)
    issues = []

    rr = _clean_rent_roll(frames["rent_roll"])
    occupancy = _occupancy(rr)
    tenants_rr = rr[rr["status"] == "occupied"].copy()

    for _, t in tenants_rr.iterrows():
        if pd.notna(t["lease_end"]) and t["lease_end"] < as_of:
            _issue(issues, "lease_expired_still_occupied", t["unit_id"],
                   f"{t['tenant_name']} lease ended {t['lease_end']:%Y-%m-%d} but unit is marked occupied.",
                   "action")

    ledger = _clean_ledger(frames["accounting"], rr, issues, name_threshold)
    crm = frames["crm"].copy()
    crm["last_contact"] = pd.to_datetime(crm["last_contact"].replace("", None))
    crm_by_tenant = _match_crm(tenants_rr, crm, issues, name_threshold)

    rows = []
    for _, t in tenants_rr.iterrows():
        aged = _age_tenant(ledger[ledger["tenant_id"] == t["tenant_id"]], as_of)
        contact = crm_by_tenant.get(t["tenant_id"])
        last = contact["last_contact"] if contact is not None else pd.NaT
        days_since = (as_of - last).days if pd.notna(last) else None
        if aged["arrears"] > 0 and (days_since is None or days_since > contact_days):
            when = "never" if days_since is None else f"{days_since} days ago"
            _issue(issues, "arrears_no_recent_contact", t["tenant_id"],
                   f"{t['tenant_name']} owes ${aged['arrears']:,.2f}; last CRM contact {when}.", "action")
        rows.append({
            "tenant_id": t["tenant_id"],
            "tenant": t["tenant_name"],
            "unit_id": t["unit_id"],
            "property": t["property"],
            "monthly_rent": t["monthly_rent"],
            "lease_end": t["lease_end"].strftime("%Y-%m-%d") if pd.notna(t["lease_end"]) else "",
            **{k: round(v, 2) for k, v in aged.items()},
            "contact": "" if contact is None else contact["contact_name"],
            "email": "" if contact is None else contact["email"],
            "last_contact": last.strftime("%Y-%m-%d") if pd.notna(last) else "",
            "days_since_contact": days_since,
        })

    tenants = pd.DataFrame(rows).sort_values("arrears", ascending=False).reset_index(drop=True)
    issues_df = pd.DataFrame(issues, columns=["severity", "type", "ref", "detail"])
    order = {"action": 0, "review": 1, "info": 2}
    issues_df = issues_df.sort_values("severity", key=lambda s: s.map(order), kind="stable").reset_index(drop=True)

    totals = {
        "arrears_total": round(tenants["arrears"].sum(), 2),
        "tenants_in_arrears": int((tenants["arrears"] > 0).sum()),
        "credit_total": round(tenants["credit"].sum(), 2),
        "buckets": {label: round(tenants[label].sum(), 2) for label, _, _ in BUCKETS},
        "issues_total": len(issues_df),
        "issues_action": int((issues_df["severity"] == "action").sum()),
    }
    return Result(as_of=as_of, occupancy=occupancy, tenants=tenants, issues=issues_df, totals=totals)


__all__ = ["run", "Result", "BUCKETS", "bucket_for", "company"]
