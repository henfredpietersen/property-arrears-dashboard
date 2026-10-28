"""Export everything the interactive walkthrough page shows, straight from a real
pipeline run, so the page replays the Python results instead of re-calculating them.

    python -m arrears_dashboard.walkthrough --out docs/walkthrough.json
"""

import argparse
import json
from pathlib import Path

from .load import load_all
from .normalize import company, money, name_similarity, unit_id
from .reconcile import BUCKETS, run
from .summary import _allowed_numbers, build_facts, check_numbers, summarize, template_summary

# Two example AI summaries the page offers as buttons. Their verdicts are computed
# here by the real Python check, and the page's own checker is tested against them.
SAMPLE_SUMMARIES = {
    "faithful": ("Occupancy is 70.0% by units. Four tenants owe $74,200 in total, with $16,000 "
                 "more than 90 days old. Delta Cold Storage owes the most at $48,800."),
    "invented": ("Occupancy is 70.0% by units. Tenants owe $78,500 in total, and arrears "
                 "fell 12% since last month."),
}


def _records(frame):
    return frame.to_dict(orient="records")


def build(data_dir, as_of) -> dict:
    frames = load_all(data_dir)
    result = run(frames, as_of)
    no_dedupe = run(frames, as_of, dedupe=False)

    rr = frames["rent_roll"]
    tenant_names = dict(zip(rr["tenant_id"], rr["tenant_name"], strict=True))

    # Cleaning examples: every distinct raw form seen in the exports.
    acc = frames["accounting"]
    unit_examples = sorted({(r, unit_id(r)) for r in acc["unit_ref"]}, key=lambda p: (str(p[1]), p[0]))
    amount_examples = sorted({(a, money(a)) for a in acc["amount"] if not a.replace(".", "").isdigit()})

    # Name matching shown on the page (same similarity function the pipeline uses).
    crm = frames["crm"]
    occupied = rr[rr["status"].str.lower() == "occupied"]
    name_matches = []
    for _, t in occupied.iterrows():
        scored = sorted(((name_similarity(t["tenant_name"], c), c) for c in crm["company"]), reverse=True)
        score, best = scored[0]
        name_matches.append({"tenant": t["tenant_name"], "crm": best, "score": round(score, 2),
                             "matched": score >= 0.75, "clean_a": company(t["tenant_name"]),
                             "clean_b": company(best)})

    tenants = result.tenants.drop(columns=["email"]).copy()
    tenants["days_since_contact"] = tenants["days_since_contact"].astype("object")
    tenants = tenants.where(tenants.notna(), None)

    acme_with = float(result.tenants.set_index("tenant_id").loc["T001", "balance"])
    acme_without = float(no_dedupe.tenants.set_index("tenant_id").loc["T001", "balance"])

    facts = build_facts(result)
    return {
        "as_of": f"{result.as_of:%Y-%m-%d}",
        "inputs": {
            "rent_roll": _records(rr),
            "accounting": _records(acc),
            "crm": _records(crm[["company", "contact_name", "account_manager", "last_contact"]]),
        },
        "cleaning": {
            "units": [{"raw": r, "clean": c} for r, c in unit_examples],
            "amounts": [{"raw": r, "clean": c} for r, c in amount_examples],
            "names": name_matches,
        },
        "ledger_log": result.ledger_log,
        "allocations": {tid: {"tenant": tenant_names[tid], **a} for tid, a in result.allocations.items()},
        "whatif_no_dedupe": {
            "tenant": tenant_names["T001"],
            "balance_with_check": acme_with,
            "balance_without_check": acme_without,
            "credit_total_with": result.totals["credit_total"],
            "credit_total_without": no_dedupe.totals["credit_total"],
        },
        "occupancy": result.occupancy,
        "totals": result.totals,
        "buckets": [b[0] for b in BUCKETS],
        "tenants": _records(tenants),
        "issues": _records(result.issues),
        "summary": {
            "template": template_summary(facts),
            "facts": {k: v for k, v in facts.items() if k != "top_arrears"},
            "top_arrears": facts["top_arrears"],
            "allowed_numbers": sorted(_allowed_numbers(facts)),
            "samples": {name: {"text": text, "unsupported": check_numbers(text, facts)}
                        for name, text in SAMPLE_SUMMARIES.items()},
        },
        "dashboard_summary_source": summarize(result, "template")["source"],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Export data for the interactive walkthrough page.")
    parser.add_argument("--data", default="data")
    parser.add_argument("--as-of", default="2026-10-31")
    parser.add_argument("--out", default="docs/walkthrough.json")
    args = parser.parse_args(argv)
    payload = build(args.data, args.as_of)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
