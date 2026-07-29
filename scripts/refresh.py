"""Daily entry point: GA4 → CSVs → (Sheet → CSVs) → Hugo data → page stubs.

    GCP_SA_KEY=... USAGE_SHEET_ID=... python3 scripts/refresh.py [--backfill]

Attribution happens here, once, so the site never has to reason about it: each
GA4 row is assigned to a product by content group, else by host + path prefix
(see data/registry.yml). A row that matches nothing is ignored rather than
guessed at.
"""

from __future__ import annotations

import os
import sys

import ga4
from common import DATA, load_registry, upsert_csv

DAILY_FIELDS = ["date"] + ga4.METRICS
GEO_FIELDS = ["country", "countryId", "region", "activeUsers", "sessions"]
EVENT_FIELDS = ["eventName", "eventCount", "activeUsers"]

# below this many active users a region row is folded into "Other": GA4 already
# thresholds small cells, and a named region with a handful of users says more
# about one person than about usage
MIN_REGION_USERS = 10


def matches(prod: dict, row: dict) -> bool:
    cg = row.get("contentGroup", "")
    if cg and cg in (prod.get("content_groups") or []):
        return True
    host, path = row.get("hostName", ""), row.get("pagePath", "")
    if not path:
        return False
    if prod.get("host") and host and host != prod["host"]:
        return False
    return any(path.startswith(pfx) for pfx in (prod.get("path_prefixes") or []))


def collapse(rows: list[dict], keys: list[str], metrics: list[str]) -> list[dict]:
    """Sum metrics over duplicate key tuples (many paths → one product-day)."""
    acc: dict[tuple, dict] = {}
    for r in rows:
        k = tuple(r.get(x, "") for x in keys)
        cur = acc.setdefault(k, {**{x: r.get(x, "") for x in keys},
                                 **{m: 0.0 for m in metrics}})
        for m in metrics:
            try:
                cur[m] += float(r.get(m) or 0)
            except ValueError:
                pass
    for v in acc.values():
        for m in metrics:
            v[m] = int(v[m]) if float(v[m]).is_integer() else round(v[m], 2)
    return list(acc.values())


def main() -> int:
    backfill = "--backfill" in sys.argv
    reg = load_registry()
    props = reg["properties"]

    cli = ga4.client()
    pulled, failed = {}, []
    for name, pid in props.items():
        if not pid:
            print(f"! property '{name}' has no id in registry.yml — skipped. "
                  f"Its products will show no data; see OPERATIONS.md step 1.",
                  file=sys.stderr)
            failed.append(name)
            continue
        try:
            pulled[name] = ga4.fetch_all(cli, pid, backfill)
        except Exception as e:
            # one property being misconfigured (wrong id, Viewer not granted)
            # must not cost the other its daily pull — carry on and go red at
            # the end, with the commit step still running on failure
            print(f"! property '{name}' ({pid}) failed: {e}", file=sys.stderr)
            # the overwhelmingly common cause: GA4 shows three numbers and only
            # one of them is the property id
            print(f"  NOTE: '{pid}' must be the numeric PROPERTY id — not the "
                  f"Stream ID, and not the G-… Measurement ID. Run the "
                  f"'List GA4 properties' workflow to see the ids this service "
                  f"account can read.", file=sys.stderr)
            failed.append(name)
            continue
        print(f"  {name}: " + ", ".join(f"{k}={len(v)}" for k, v in pulled[name].items()),
              file=sys.stderr)

    for prod in reg["products"]:
        slug, pname = prod["slug"], prod.get("property")
        rep = pulled.get(pname)
        if not rep:
            continue

        # Time series: content group is authoritative; page paths fill in only
        # the dates it does not cover (history from before the product was
        # tagged, and Quarto/pkgdown pages that emit no group of ours).
        #
        # These must NOT be summed. A tagged product matches its own content
        # group AND its own path prefix, so adding them double-counts every
        # day — which looks plausible on a chart and is wrong by 2x.
        grp = collapse([r for r in rep["daily_group"] if matches(prod, r)],
                       ["date"], ga4.METRICS)
        pth = collapse([r for r in rep["daily_path"] if matches(prod, r)],
                       ["date"], ga4.METRICS)
        covered = {r["date"] for r in grp}
        daily = grp + [r for r in pth if r["date"] not in covered]
        if daily:
            upsert_csv(DATA / "daily" / f"{slug}.csv", daily, ["date"], DAILY_FIELDS)

        geo = collapse([r for r in rep["geo"] if matches(prod, r)],
                       ["country", "countryId", "region"], ["activeUsers", "sessions"])
        # small-cell suppression, on top of GA4's own: a named region carrying a
        # handful of users describes a person more than it describes usage
        for g in geo:
            if g.get("region") and float(g.get("activeUsers") or 0) < MIN_REGION_USERS:
                g["region"] = "Other"
        geo = collapse(geo, ["country", "countryId", "region"], ["activeUsers", "sessions"])
        if geo:
            upsert_csv(DATA / "geo" / f"{slug}.csv", geo,
                       ["country", "countryId", "region"], GEO_FIELDS)

        ev = collapse([r for r in rep["events"] if matches(prod, r)],
                      ["eventName"], ["eventCount", "activeUsers"])
        if ev:
            upsert_csv(DATA / "events" / f"{slug}.csv", ev, ["eventName"], EVENT_FIELDS)

    # ── request counts from the Caddy access logs ─────────────────────────────
    # GA4 cannot see erddap or storage: their traffic is curl/R/Python pulling
    # .csv/.nc/parquet, which runs no JavaScript. The server aggregates its own
    # access logs nightly to a public JSON (no IPs, no user agents — see
    # CalCOFI/server scripts/caddy_usage.py); fetch it and keep it as a series
    # alongside, never blended into, the page-view numbers.
    import requests_log
    try:
        n = requests_log.fetch_and_store(reg)
        print(f"  caddy: {n} host-days", file=sys.stderr)
    except Exception as e:
        # a stale summary is not worth failing the GA4 pull over
        print(f"! caddy usage fetch failed: {e}", file=sys.stderr)

    sheet_id = os.environ.get("USAGE_SHEET_ID", "").strip()
    if sheet_id:
        import sheet
        tab = next((p["sheet_tab"] for p in reg["products"] if p.get("sheet_tab")), None)
        if tab:
            print(f"  sheet: {sheet.summarize(sheet_id, tab)}", file=sys.stderr)
    else:
        print("! USAGE_SHEET_ID unset — skipping the db-viz-hex query log", file=sys.stderr)

    import build
    s = build.build()
    print(f"built {s['n_products']} products, {s['totals_28d']['activeUsers']:.0f} "
          f"active users in 28d", file=sys.stderr)

    if failed:
        # whatever was pulled is already written and will still be committed
        # (the commit step runs on failure); exiting non-zero is what makes a
        # half-configured pipeline visible instead of quietly partial
        print(f"! incomplete: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
