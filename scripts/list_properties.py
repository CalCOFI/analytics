"""Print the GA4 properties this service account can actually see.

Run when `data/registry.yml` needs a property id, or to confirm a Viewer grant
landed. GA4 shows three different numbers and only one of them works here:

    Measurement ID   G-0HVK8TDMCF    the gtag snippet on the site
    Stream ID        4625567227      identifies a data stream; useless to us
    Property ID      509537765       what the Data API takes, what goes in registry.yml

The Property ID is the `p`-prefixed number in a GA4 URL
(analytics.google.com/analytics/web/#/p509537765/…) and appears top-right under
Admin → Property Settings. This script asks Google instead of relying on
reading the right box.

    GCP_SA_KEY="$(cat key.json)" python3 scripts/list_properties.py
"""

from __future__ import annotations

import json
import os
import sys

from google.oauth2 import service_account


def main() -> int:
    raw = os.environ.get("GCP_SA_KEY", "").strip()
    if not raw:
        print("GCP_SA_KEY is empty", file=sys.stderr)
        return 1

    try:
        from google.analytics.admin_v1beta import AnalyticsAdminServiceClient
    except ImportError:
        print("pip install google-analytics-admin", file=sys.stderr)
        return 1

    creds = service_account.Credentials.from_service_account_info(
        json.loads(raw),
        scopes=["https://www.googleapis.com/auth/analytics.readonly"])

    try:
        client = AnalyticsAdminServiceClient(credentials=creds)
        summaries = list(client.list_account_summaries())
    except Exception as e:
        # the Admin API is a SEPARATE API from the Data API — a fresh project
        # usually has neither enabled, and only analyticsdata is needed for the
        # daily run, so this failing does not mean the pipeline is broken
        print(f"admin API call failed: {e}\n", file=sys.stderr)
        print("If this says the API is disabled, either enable "
              "analyticsadmin.googleapis.com or read the Property ID off "
              "GA4 → Admin → Property Settings (top right).", file=sys.stderr)
        return 1

    if not summaries:
        print("No accounts visible to this service account — the Viewer grant "
              "(OPERATIONS.md step 4) has not landed.", file=sys.stderr)
        return 1

    print(f"{'PROPERTY ID':<14} {'DISPLAY NAME':<24} {'MEASUREMENT ID':<16} "
          f"{'STREAM ID':<12} ACCOUNT")
    for acct in summaries:
        for p in acct.property_summaries:
            pid = p.property.split("/")[-1]      # "properties/509537765"
            # print each stream too: the measurement id is what a site's gtag
            # snippet carries, so this is what lets you match a property to the
            # G-… you actually know
            try:
                streams = list(client.list_data_streams(parent=p.property))
            except Exception:
                streams = []
            if not streams:
                print(f"{pid:<14} {p.display_name:<24} {'—':<16} {'—':<12} {acct.display_name}")
            for s in streams:
                w = getattr(s, "web_stream_data", None)
                print(f"{pid:<14} {p.display_name:<24} "
                      f"{(w.measurement_id if w else '—'):<16} "
                      f"{s.name.split('/')[-1]:<12} {acct.display_name}")
    print("\nMatch on MEASUREMENT ID, then put that row's PROPERTY ID into "
          "data/registry.yml → properties.site, and push.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
