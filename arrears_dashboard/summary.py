"""A short plain-English summary for leadership.

Two modes:
- template (default): built from the computed numbers, no AI involved.
- llm: an LLM rewrites the same facts more naturally. Its output is checked:
  every number it writes must already be in the facts. If it invents or
  changes a number, the template summary is used instead.

Only aggregate figures and company names are sent to the LLM. Contact names,
emails, phone numbers and CRM notes are never included in the prompt.
"""

import os
import re

NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def build_facts(result) -> dict:
    occ, tot = result.occupancy, result.totals
    top = result.tenants[result.tenants["arrears"] > 0][["tenant", "arrears"]].head(3)
    return {
        "as_of": result.as_of.strftime("%Y-%m-%d"),
        "units_occupied": occ["units_occupied"],
        "units_total": occ["units_total"],
        "occupancy_pct_units": occ["occupancy_pct_units"],
        "occupancy_pct_sqft": occ["occupancy_pct_sqft"],
        "arrears_total": tot["arrears_total"],
        "tenants_in_arrears": tot["tenants_in_arrears"],
        "arrears_91_plus": tot["buckets"]["91+"],
        "issues_action": tot["issues_action"],
        "top_arrears": [(r.tenant, r.arrears) for r in top.itertuples()],
    }


def template_summary(f: dict) -> str:
    top = "; ".join(f"{name} ${amt:,.2f}" for name, amt in f["top_arrears"]) or "none"
    return (
        f"As of {f['as_of']}, {f['units_occupied']} of {f['units_total']} units are occupied "
        f"({f['occupancy_pct_units']}% by units, {f['occupancy_pct_sqft']}% by square feet). "
        f"{f['tenants_in_arrears']} tenants owe ${f['arrears_total']:,.2f} in total, "
        f"of which ${f['arrears_91_plus']:,.2f} is more than 90 days old. "
        f"Largest balances: {top}. "
        f"{f['issues_action']} data issues need action before these numbers are final."
    )


def _allowed_numbers(f: dict) -> set:
    allowed = set()

    def add(value):
        if isinstance(value, (int, float)):
            for text in (f"{value}", f"{value:,.2f}", f"{value:,.0f}", f"{value:.2f}", f"{value:.0f}"):
                allowed.add(text.replace(",", ""))
        elif isinstance(value, str):
            for n in NUMBER_RE.findall(value):
                allowed.add(n.replace(",", ""))

    for key, value in f.items():
        if key == "top_arrears":
            for name, amt in value:
                add(name)
                add(amt)
        else:
            add(value)
    allowed.update({"30", "60", "90", "91", "0", "31", "61"})  # bucket labels
    return allowed


def check_numbers(text: str, facts: dict) -> list:
    """Return the numbers in `text` that are not supported by `facts`."""
    allowed = _allowed_numbers(facts)
    found = [n.replace(",", "") for n in NUMBER_RE.findall(text)]
    bad = []
    for n in found:
        stripped = n[:-3] if n.endswith(".00") else n
        if n not in allowed and stripped not in allowed:
            bad.append(n)
    return bad


def build_prompt(f: dict) -> str:
    return (
        "Rewrite these property facts as a 3-sentence update for a busy operations lead. "
        "Use only the numbers given, exactly as given. Do not add advice or new figures.\n\n"
        f"FACTS:\n{f}"
    )


def anthropic_call(prompt: str) -> str:  # pragma: no cover - needs a live key
    import anthropic

    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=os.environ.get("LLM_MODEL", "claude-haiku-5-5"),
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


def summarize(result, mode: str = "template", call=None) -> dict:
    """Returns {'text', 'source', 'note'}. `call` lets tests inject a fake LLM."""
    facts = build_facts(result)
    fallback = template_summary(facts)
    if mode != "llm":
        return {"text": fallback, "source": "template", "note": ""}
    try:
        text = (call or anthropic_call)(build_prompt(facts))
    except Exception as exc:  # no key, no package, network error
        return {"text": fallback, "source": "template", "note": f"LLM unavailable ({type(exc).__name__})"}
    bad = check_numbers(text, facts)
    if bad:
        return {"text": fallback, "source": "template",
                "note": f"LLM output rejected: unsupported number(s) {', '.join(bad)}"}
    return {"text": text, "source": "llm", "note": "numbers checked against computed facts"}
