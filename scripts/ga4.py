"""Pull per-product usage from the two CalCOFI GA4 properties.

WHY contentGroup AND NOT app_name
---------------------------------
Every CalCOFI app sets both `content_group` and `app_name` on its gtag config
(calcofi4r::cc_ga_js). Only `content_group` is a BUILT-IN Data API dimension —
`app_name` is an event parameter, which the Data API can only expose as
`customEvent:app_name` after someone registers it as a custom dimension in the
GA4 admin UI, and even then it backfills nothing. contentGroup needs no admin
step and works retroactively, so it is the join key. Products that predate
their tag (or that Quarto/pkgdown render for us) are matched on page path
instead — see `registry.yml`.

Metrics are requested RAW and derived here; never ask GA4 for an average it
would compute over a different denominator than the one shown on the page.
"""

from __future__ import annotations

import datetime as dt
import json
import os

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange, Dimension, Metric, RunReportRequest,
)
from google.oauth2 import service_account

# raw metrics pulled for every time-series row; everything shown on the site is
# derived from these in build.py
METRICS = [
    "activeUsers", "newUsers", "sessions", "engagedSessions",
    "screenPageViews", "eventCount", "userEngagementDuration",
]

PAGE_SIZE = 100_000

# GA4 itself did not exist before this date and the Data API hard-rejects any
# earlier start_date with
#   "start_date = ... must be greater than 2015-08-13"
# — a 400, not an empty result, so a backfill that reaches back "far enough to
# be safe" fails the whole run. This is the earliest date the API accepts.
GA4_EPOCH = "2015-08-14"


def client() -> BetaAnalyticsDataClient:
    """Auth from the GCP_SA_KEY secret (raw JSON, not a path)."""
    raw = os.environ.get("GCP_SA_KEY", "").strip()
    if not raw:
        raise SystemExit(
            "GCP_SA_KEY is empty — set the repo secret to the service-account "
            "JSON key, and grant that account Viewer on both GA4 properties "
            "(see OPERATIONS.md)."
        )
    creds = service_account.Credentials.from_service_account_info(
        json.loads(raw),
        scopes=["https://www.googleapis.com/auth/analytics.readonly"],
    )
    return BetaAnalyticsDataClient(credentials=creds)


def run(cli, property_id: str, dimensions: list[str], metrics: list[str],
        start: str, end: str = "today") -> list[dict]:
    """Run one report, following offset pagination to the end."""
    # clamp rather than trust the caller: an out-of-range start is a 400 that
    # kills the run, and the only sane response is the earliest legal date
    if start < GA4_EPOCH:
        start = GA4_EPOCH
    out: list[dict] = []
    offset = 0
    while True:
        resp = cli.run_report(RunReportRequest(
            property=f"properties/{property_id}",
            dimensions=[Dimension(name=d) for d in dimensions],
            metrics=[Metric(name=m) for m in metrics],
            date_ranges=[DateRange(start_date=start, end_date=end)],
            limit=PAGE_SIZE, offset=offset,
        ))
        for row in resp.rows:
            rec = {d: row.dimension_values[i].value for i, d in enumerate(dimensions)}
            rec.update({m: row.metric_values[i].value for i, m in enumerate(metrics)})
            # GA4 returns `date` as YYYYMMDD. Everything downstream compares
            # dates as ISO strings, and "20260728" sorts ABOVE every ISO date
            # ("0" > "-"), so leaving it raw silently emptied every window and
            # reported 0 users from a full pull.
            d = rec.get("date", "")
            if len(d) == 8 and d.isdigit():
                rec["date"] = f"{d[:4]}-{d[4:6]}-{d[6:]}"
            out.append(rec)
        offset += len(resp.rows)
        if offset >= resp.row_count or not resp.rows:
            return out


def since(days: int) -> str:
    return (dt.date.today() - dt.timedelta(days=days)).isoformat()


def fetch_all(cli, property_id: str, backfill: bool) -> dict[str, list[dict]]:
    """The four reports the site is built from, for one property.

    `backfill` widens the time series to everything GA4 still holds; the daily
    run only re-reads a trailing 35-day window, because GA4 keeps revising the
    last couple of days as late hits arrive.
    """
    start_ts = GA4_EPOCH if backfill else since(35)
    return {
        # 1. usage over time, by content group
        "daily_group": run(cli, property_id, ["date", "contentGroup"], METRICS, start_ts),
        # 2. usage over time, by page path — the fallback for untagged products
        "daily_path": run(cli, property_id, ["date", "hostName", "pagePath"], METRICS, start_ts),
        # 3. users over space (GA4 resolves geography server-side; no IPs are
        #    ever exposed to this API)
        "geo": run(cli, property_id, ["contentGroup", "country", "countryId", "region"],
                   ["activeUsers", "sessions"], since(365)),
        # 4. what people do / read
        "events": run(cli, property_id, ["contentGroup", "eventName"],
                      ["eventCount", "activeUsers"], since(90)),
        "pages": run(cli, property_id, ["hostName", "pagePath"],
                     ["screenPageViews", "activeUsers"], since(90)),
    }
