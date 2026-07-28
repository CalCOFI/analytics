"""Summarize the db-viz-hex query log (a Google Sheet) — aggregates only.

The Sheet is written by calcofi4r::cc_track()/cc_track_query() from the app and
holds one row per user interaction, with the columns of
`calcofi4r::cc_log_header()`. It is the ONE place in this pipeline that touches
personal data: `ip` is a real client address and `user_agent` a real
fingerprint. GA4, by contrast, never exposes an IP to the Data API at all.

So this module drops those columns before anything else looks at the rows, uses
the id columns only to count distinct visitors, and asserts on the way out that
none of them reached a written file. Everything published here is a count, a
percentile or a top-N — never a row.

What it adds over GA4: the query detail GA4 buckets into "(other)" once past
its cardinality limit — which taxa people ask for, how long those queries take,
how often they fail, and which deployed build produced them.
"""

from __future__ import annotations

import collections
import datetime as dt
import json
import os
import re
import statistics

from googleapiclient.discovery import build as gbuild
from google.oauth2 import service_account

from common import DATA, upsert_csv

# columns that must never reach a written file, dropped at read time
PII = {"ip", "user_agent", "session", "client_id", "session_id"}
# ...of which these two are used, before being discarded, to count distinct
# people rather than distinct events
COUNT_ONLY = {"client_id", "session_id"}


def _rows(sheet_id: str, tab: str) -> tuple[list[str], list[list[str]]]:
    raw = os.environ.get("GCP_SA_KEY", "").strip()
    creds = service_account.Credentials.from_service_account_info(
        json.loads(raw),
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
    )
    svc = gbuild("sheets", "v4", credentials=creds, cache_discovery=False)
    resp = svc.spreadsheets().values().get(
        spreadsheetId=sheet_id, range=f"'{tab}'!A:P",
        # UNFORMATTED: the timestamp column holds real Date cells, which the API
        # otherwise renders in the SHEET's locale ("7/28/2026 16:25:40"). Slicing
        # ten characters off that yields "7/28/2026 " — a broken day key that
        # silently shifts with whoever owns the spreadsheet. Unformatted gives a
        # serial number, which is locale-proof.
        valueRenderOption="UNFORMATTED_VALUE").execute()
    values = resp.get("values", [])
    if not values:
        return [], []
    return values[0], values[1:]


# Sheets serial epoch: day 1 is 1899-12-31, so day 0 is 1899-12-30
_SHEETS_EPOCH = dt.date(1899, 12, 30)


def _day(v) -> str:
    """The ISO day of a timestamp cell, whatever form it arrives in."""
    if isinstance(v, (int, float)) and v > 0:
        return (_SHEETS_EPOCH + dt.timedelta(days=int(v))).isoformat()
    s = str(v or "").strip()
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":      # 2026-07-28T…
        return s[:10]
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)        # 7/28/2026 …
    if m:
        mo, dd, yy = (int(x) for x in m.groups())
        return f"{yy:04d}-{mo:02d}-{dd:02d}"
    return ""


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pct(xs, q):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return ""
    return round(statistics.quantiles(xs, n=100)[q - 1] if len(xs) > 1 else xs[0], 1)


def summarize(sheet_id: str, tab: str = "db-viz-hex") -> dict:
    header, rows = _rows(sheet_id, tab)
    if not header:
        return {"rows": 0}
    idx = {name: i for i, name in enumerate(header)}

    def cell(r, name):
        i = idx.get(name)
        return r[i] if i is not None and i < len(r) else ""

    daily = collections.defaultdict(lambda: {
        "events": 0, "errors": 0, "ms": [], "clients": set(), "sessions": set()})
    events = collections.defaultdict(lambda: {"n": 0, "ms": [], "errors": 0, "rows": []})
    params = collections.defaultdict(collections.Counter)
    versions = collections.defaultdict(lambda: {"n": 0, "first": "", "last": ""})

    for r in rows:
        day = _day(cell(r, "timestamp"))
        if not day:
            continue
        ev = cell(r, "event") or "(none)"
        ms = _num(cell(r, "ms"))
        status = cell(r, "status")
        is_err = status not in ("", "ok")

        d = daily[day]
        d["events"] += 1
        d["errors"] += is_err
        if ms is not None:
            d["ms"].append(ms)
        # distinct-count use only; the values themselves are discarded below
        if cell(r, "client_id"):
            d["clients"].add(cell(r, "client_id"))
        if cell(r, "session_id"):
            d["sessions"].add(cell(r, "session_id"))

        e = events[ev]
        e["n"] += 1
        e["errors"] += is_err
        if ms is not None:
            e["ms"].append(ms)
        nr = _num(cell(r, "n_rows"))
        if nr is not None:
            e["rows"].append(nr)

        # the interesting bit GA4 cannot hold: which taxa / variables are asked for
        try:
            p = json.loads(cell(r, "params") or "{}")
        except json.JSONDecodeError:
            p = {}
        for k in ("taxa", "env_var", "layers"):
            v = p.get(k)
            if isinstance(v, str) and v:
                for one in (s.strip() for s in v.split(",")):
                    if one:
                        params[k][one] += 1

        ver = cell(r, "app_version")
        if ver:
            v = versions[ver]
            v["n"] += 1
            v["first"] = min(v["first"] or day, day)
            v["last"] = max(v["last"], day)

    out_daily = [{
        "date": day, "events": d["events"],
        "distinct_sessions": len(d["sessions"]), "distinct_clients": len(d["clients"]),
        "errors": d["errors"],
        "p50_ms": _pct(d["ms"], 50), "p95_ms": _pct(d["ms"], 95),
    } for day, d in sorted(daily.items())]

    out_events = [{
        "event": ev, "n": e["n"],
        "p50_ms": _pct(e["ms"], 50), "p95_ms": _pct(e["ms"], 95),
        "error_rate": round(e["errors"] / e["n"], 4) if e["n"] else 0,
        "median_n_rows": round(statistics.median(e["rows"]), 1) if e["rows"] else "",
    } for ev, e in sorted(events.items(), key=lambda kv: -kv[1]["n"])]

    # top-20 only: a long tail of one-off values would be closer to a
    # fingerprint than to a statistic
    out_params = [{"param": k, "value": v, "n": n}
                  for k, c in params.items() for v, n in c.most_common(20)]

    out_versions = [{"app_version": k, "n": v["n"],
                     "first_seen": v["first"], "last_seen": v["last"]}
                    for k, v in sorted(versions.items(), key=lambda kv: kv[1]["first"])]

    written = {
        "hex_log/daily.csv":    (out_daily, ["date"], list(out_daily[0]) if out_daily else ["date"]),
        "hex_log/events.csv":   (out_events, ["event"], list(out_events[0]) if out_events else ["event"]),
        "hex_log/params.csv":   (out_params, ["param", "value"], ["param", "value", "n"]),
        "hex_log/versions.csv": (out_versions, ["app_version"], ["app_version", "n", "first_seen", "last_seen"]),
    }
    for rel, (recs, key, fields) in written.items():
        # the guarantee, enforced rather than promised
        assert not (PII & set(fields)), f"PII column would be published in {rel}: {PII & set(fields)}"
        upsert_csv(DATA / rel, recs, key, fields)

    return {
        "rows": len(rows),
        "days": len(out_daily),
        "events": len(out_events),
        "last_day": out_daily[-1]["date"] if out_daily else "",
    }
