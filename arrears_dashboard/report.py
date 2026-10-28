"""Write the outputs: two CSVs and one self-contained HTML dashboard."""

from html import escape
from pathlib import Path

from .reconcile import BUCKETS

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#1c2430;--muted:#5d6b7c;--line:#e3e7ec;
--accent:#1f6feb;--warn:#b54708;--bad:#b42318;--ok:#067647;--b1:#93c5fd;--b2:#3b82f6;--b3:#f59e0b;--b4:#dc2626}
@media (prefers-color-scheme:dark){:root{--bg:#0f141a;--card:#171e26;--ink:#e6ebf1;--muted:#97a3b3;
--line:#283240;--accent:#58a6ff;--warn:#f0a35e;--bad:#f97066;--ok:#47cd89}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:22px;margin:0}h2{font-size:16px;margin:28px 0 10px}
.sub{color:var(--muted);margin:4px 0 20px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}
.kpi .v{font-size:24px;font-weight:650;font-variant-numeric:tabular-nums}
.kpi .l{color:var(--muted);font-size:13px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px}
.bar{display:flex;height:22px;border-radius:6px;overflow:hidden;margin:6px 0 10px}
.legend{display:flex;flex-wrap:wrap;gap:14px;font-size:13px;color:var(--muted)}
.dot{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px}
.tbl{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:13.5px}
th,td{text-align:left;padding:8px 7px;border-bottom:1px solid var(--line);white-space:nowrap}
th{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.03em}
td.n{text-align:right;font-variant-numeric:tabular-nums}td.wrap{white-space:normal;min-width:280px}
.tag{font-size:12px;padding:2px 8px;border-radius:99px;border:1px solid currentColor}
.action{color:var(--bad)}.review{color:var(--warn)}.info{color:var(--muted)}.zero{color:var(--muted)}
footer{margin-top:32px;color:var(--muted);font-size:13px}
"""

BUCKET_COLORS = ["var(--b1)", "var(--b2)", "var(--b3)", "var(--b4)"]


def _money(v) -> str:
    return f"${v:,.2f}"


def _cell(v) -> str:
    return f'<td class="n{" zero" if not v else ""}">{_money(v) if v else "–"}</td>'


def render_html(result, summary: dict) -> str:
    occ, tot = result.occupancy, result.totals
    kpis = [
        (f"{occ['occupancy_pct_units']}%", f"Occupancy by units ({occ['units_occupied']}/{occ['units_total']})"),
        (f"{occ['occupancy_pct_sqft']}%", f"Occupancy by sq ft ({occ['sqft_occupied']:,}/{occ['sqft_total']:,})"),
        (_money(tot["arrears_total"]), f"Arrears across {tot['tenants_in_arrears']} tenants"),
        (_money(tot["buckets"]["91+"]), "Older than 90 days"),
        (str(tot["issues_action"]), f"Data issues needing action ({tot['issues_total']} total)"),
    ]
    kpi_html = "".join(
        f'<div class="kpi"><div class="v">{escape(v)}</div><div class="l">{escape(label)}</div></div>'
        for v, label in kpis
    )

    total = tot["arrears_total"] or 1
    segs, legend = [], []
    for (label, _, _), color in zip(BUCKETS, BUCKET_COLORS, strict=True):
        amt = tot["buckets"][label]
        if amt:
            segs.append(f'<div style="width:{100 * amt / total:.2f}%;background:{color}" '
                        f'title="{label} days: {_money(amt)}"></div>')
        legend.append(f'<span><span class="dot" style="background:{color}"></span>'
                      f'{label} days: {_money(amt)}</span>')

    rows = []
    for _, t in result.tenants.iterrows():
        contact = escape(t["contact"]) if t["contact"] else '<span class="action">no CRM record</span>'
        last = f"{escape(t['last_contact'])} ({int(t['days_since_contact'])}d)" if t["last_contact"] else "–"
        buckets = "".join(_cell(t[label]) for label, _, _ in BUCKETS)
        rows.append(
            f"<tr><td>{escape(t['tenant'])}</td><td>{escape(t['unit_id'])}</td>"
            f"{_cell(t['arrears'])}{buckets}{_cell(t['credit'])}"
            f"<td>{contact}</td><td>{last}</td></tr>"
        )

    issue_rows = "".join(
        f'<tr><td><span class="tag {escape(i.severity)}">{escape(i.severity)}</span></td>'
        f"<td>{escape(i.type)}</td><td>{escape(str(i.ref))}</td><td class=\"wrap\">{escape(i.detail)}</td></tr>"
        for i in result.issues.itertuples()
    )

    note = f" · {escape(summary['note'])}" if summary.get("note") else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Occupancy and Arrears</title><style>{CSS}</style></head><body><main>
<h1>Occupancy and Arrears</h1>
<p class="sub">As of {result.as_of:%d %B %Y} · merged from rent roll, accounting export
and CRM export · sample data</p>
<div class="kpis">{kpi_html}</div>
<h2>Summary</h2><div class="card"><p style="margin:0">{escape(summary['text'])}</p>
<p class="sub" style="margin:8px 0 0;font-size:13px">Source: {escape(summary['source'])}{note}</p></div>
<h2>Arrears aging</h2><div class="card"><div class="bar">{''.join(segs)}</div>
<div class="legend">{''.join(legend)}</div></div>
<h2>By tenant</h2><div class="card tbl"><table><thead><tr><th>Tenant</th><th>Unit</th>
<th>Arrears</th><th>0-30</th><th>31-60</th><th>61-90</th><th>91+</th><th>Credit</th>
<th>Contact</th><th>Last contact</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<h2>Data issues to fix</h2><div class="card tbl"><table><thead><tr><th>Severity</th><th>Type</th>
<th>Ref</th><th>Detail</th></tr></thead><tbody>{issue_rows}</tbody></table></div>
<footer>Generated by property-arrears-dashboard. Rows the pipeline could not place are excluded
from the figures and listed above rather than guessed.</footer>
</main></body></html>"""


def write_outputs(result, summary: dict, out_dir) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {
        "dashboard": out / "dashboard.html",
        "arrears": out / "arrears_by_tenant.csv",
        "issues": out / "data_issues.csv",
    }
    paths["dashboard"].write_text(render_html(result, summary), encoding="utf-8")
    result.tenants.to_csv(paths["arrears"], index=False)
    result.issues.to_csv(paths["issues"], index=False)
    return paths
