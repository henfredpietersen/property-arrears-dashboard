"""Command line entry point:  python -m arrears_dashboard --as-of 2026-10-31"""

import argparse
import os
import sys

from .load import load_all
from .reconcile import run
from .report import write_outputs
from .summary import summarize


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build the occupancy and arrears dashboard.")
    parser.add_argument("--data", default=os.environ.get("DATA_DIR", "data"))
    parser.add_argument("--out", default=os.environ.get("OUTPUT_DIR", "output"))
    parser.add_argument("--as-of", default=os.environ.get("AS_OF_DATE", "2026-10-31"))
    parser.add_argument("--summary", choices=["template", "llm"],
                        default=os.environ.get("SUMMARY_MODE", "template"))
    args = parser.parse_args(argv)

    try:
        frames = load_all(args.data)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Input problem: {exc}", file=sys.stderr)
        return 2

    result = run(frames, args.as_of)
    summary = summarize(result, args.summary)
    paths = write_outputs(result, summary, args.out)

    t, o = result.totals, result.occupancy
    print(f"Occupancy: {o['occupancy_pct_units']}% of units, {o['occupancy_pct_sqft']}% of sq ft")
    print(f"Arrears:   ${t['arrears_total']:,.2f} across {t['tenants_in_arrears']} tenants")
    print(f"Issues:    {t['issues_total']} ({t['issues_action']} need action)")
    print(f"Summary:   {summary['source']}{' - ' + summary['note'] if summary['note'] else ''}")
    for name, path in paths.items():
        print(f"Wrote {name}: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
