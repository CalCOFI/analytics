"""Server-side request counts, for the products GA4 structurally cannot measure.

erddap and storage are used mostly by machines — curl, R, Python fetching
.csv / .nc / parquet — none of which executes JavaScript. A gtag on their HTML
pages counts the humans browsing and nothing else; `calcofi4r::cc_get_db()`
reads parquet straight from the bucket and never appears at all.

So the CalCOFI server aggregates its own Caddy access logs nightly
(CalCOFI/server `scripts/caddy_usage.py`) into a public summary — counts and
top paths, with no addresses or user agents — and this reads it.

These numbers are kept in their own CSVs and rendered as a SEPARATE figure from
page views. Adding them together would be meaningless: one counts people, the
other counts requests, and a single parquet read can be either.
"""

from __future__ import annotations

import json
import urllib.request

from common import DATA, upsert_csv

SUMMARY_URL = "https://file.calcofi.io/_usage/requests.json"
FIELDS = ["date", "requests", "bytes", "clients", "browser", "tool", "errors"]


def fetch(url: str = SUMMARY_URL) -> dict:
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read().decode())


def fetch_and_store(reg: dict, url: str = SUMMARY_URL) -> int:
    """Write one CSV per product that has a `request_host` in the registry."""
    doc = fetch(url)
    by_host: dict[str, list[dict]] = {}
    for row in doc.get("rows", []):
        by_host.setdefault(row.get("host", ""), []).append(row)

    written = 0
    for prod in reg["products"]:
        host = prod.get("request_host")
        if not host or host not in by_host:
            continue
        rows = [{k: r.get(k, 0) for k in FIELDS} for r in by_host[host]]
        upsert_csv(DATA / "requests" / f"{prod['slug']}.csv", rows, ["date"], FIELDS)
        written += len(rows)

    # keep the top-paths detail for the most recent day, per host — useful for
    # "what are people actually downloading" without publishing a request log
    latest = {}
    for host, rows in by_host.items():
        newest = max(rows, key=lambda r: r.get("date", ""))
        latest[host] = {"date": newest.get("date"), "top_paths": newest.get("top_paths", [])}
    (DATA / "requests").mkdir(parents=True, exist_ok=True)
    (DATA / "requests" / "_top_paths.json").write_text(json.dumps(latest, indent=1))
    return written
