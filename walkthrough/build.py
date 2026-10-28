"""Build the interactive walkthrough from a real pipeline run.

    python walkthrough/build.py

Writes:
  docs/walkthrough.js    the page script with the pipeline results embedded (what the live page loads)
  docs/walkthrough.html  standalone page with the same script inlined (open it in a browser)

To show it on any web page, add a container and load the script:
  <div id="ov-arrears-walkthrough"></div>
  <script defer
    src="https://cdn.jsdelivr.net/gh/henfredpietersen/property-arrears-dashboard@<commit>/docs/walkthrough.js">
  </script>
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from arrears_dashboard.walkthrough import build  # noqa: E402

STANDALONE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Three messy exports in, one arrears view out</title>
<style>html,body{margin:0;background:#05070d}</style></head>
<body>
<div id="ov-arrears-walkthrough"></div>
<script>
{script}</script>
</body></html>
"""


def main() -> int:
    data = build(ROOT / "data", "2026-10-31")
    # ensure_ascii keeps it plain ASCII; escaping "</" keeps it safe when inlined in <script>.
    payload = json.dumps(data, separators=(",", ":"), default=str).replace("</", "<\\/")
    script = (ROOT / "walkthrough" / "walkthrough.js").read_text(encoding="utf-8").replace("__DATA__", payload)
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "walkthrough.js").write_text(script, encoding="utf-8")
    (docs / "walkthrough.html").write_text(STANDALONE.replace("{script}", script), encoding="utf-8")
    print(f"Wrote docs/walkthrough.js ({len(script):,} bytes) and docs/walkthrough.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
