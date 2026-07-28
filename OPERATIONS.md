# Operations notes

The Google side of this repo cannot be set up from code — it is UI grants and a
key. This is that checklist, plus the things that will confuse you later.

## One-time Google setup

1. **Find the site property's numeric id — and commit it.** GA4 → Admin →
   Property Settings; the ID sits top-right. Put it in `data/registry.yml` under
   `properties.site`, replacing the empty `""` (the apps property, `509537765`,
   is already there), and **push that change** — the workflow reads the
   committed file, not your working copy.

   ⚠️ **GA4 shows three numbers and only one of them works here.** For the
   calcofi.io site stream they are:

   | | value | used by |
   |---|---|---|
   | Measurement ID | `G-0HVK8TDMCF` | the gtag snippet on each site |
   | Stream ID | `4625567227` | nothing in this pipeline |
   | **Property ID** | *what you need* | the Data API, `registry.yml` |

   The Stream ID is the one the Data Streams screen shows you first, and it is
   *not* interchangeable. The Property ID is the `p`-prefixed number in a GA4
   URL (`analytics.google.com/analytics/web/#/p509537765/…`). If you would
   rather not hunt for it, run the **List GA4 properties** workflow (Actions →
   Run workflow): the service account prints every property id it can read,
   which doubles as a check that step 4's Viewer grant landed.

   Until `site` is filled, the daily run finishes **red** with
   `! property 'site' has no id` and the eight calcofi.io products (db-schema,
   docs, workflows, calcofi4r, calcofi4db, db-viz-station, ucla-monitoring-map,
   hypoxia-story) stay empty, while the apps property still publishes normally.

2. **Create a dedicated service account — do not reuse `calcofi-admin@`.**

   ```bash
   gcloud iam service-accounts create calcofi-analytics \
     --project=ucsd-sio-calcofi --display-name="CalCOFI analytics (read-only)"
   gcloud iam service-accounts keys create key.json \
     --iam-account=calcofi-analytics@ucsd-sio-calcofi.iam.gserviceaccount.com \
     --project=ucsd-sio-calcofi
   ```

   **Grant it no IAM roles at all.** GA4 and Sheets access come from *sharing*,
   not from project IAM. `calcofi-admin@` holds `storage.objectAdmin` on three
   buckets, so putting its key in a public repo's Actions secrets would turn any
   workflow-injection bug into a bucket compromise.

3. **Enable the APIs** in `ucsd-sio-calcofi`: `analyticsdata.googleapis.com` and
   `sheets.googleapis.com`.

4. **Grant GA4 access** — in *both* properties: Admin → Property Access
   Management → add `calcofi-analytics@ucsd-sio-calcofi.iam.gserviceaccount.com`
   as **Viewer**. UI only; there is no API for this.

5. **Share the usage-log Sheet** (`1fBUZlq8zIjWjfYROOkgcnWdHSNxIV2TUuZAvzpt75KU`,
   "calcofi.io apps log") with that same address, **Viewer**.
   Note there is a *second* Drive file with the identical title,
   `1VQcfdP3…`, holding the retired 10-column header — it is a decoy and should
   be deleted.

6. **Raise data retention to 14 months** on both properties (Admin → Data
   Settings → Data Retention). Free, one toggle, and it decides how far back the
   first `--backfill` can reach.

7. **Repo secrets** (Settings → Secrets and variables → Actions):
   `GCP_SA_KEY` = the full contents of `key.json`;
   `USAGE_SHEET_ID` = `1fBUZlq8zIjWjfYROOkgcnWdHSNxIV2TUuZAvzpt75KU`.
   Then delete your local `key.json`.

8. **Pages**: Settings → Pages → Source = **GitHub Actions**.

9. **First run**: Actions → "Refresh usage data" → Run workflow, with
   **backfill** ticked. Subsequent runs only re-read 35 days.

   A run goes red if *either* property is unreachable, but the data it did get
   is still committed and published — the commit and build steps run on failure
   by design. So a red first run with real numbers on the site usually means one
   property is misconfigured, not that nothing worked. Read the
   `! property '<name>' … failed:` line for which and why.

   How far back the backfill actually reaches is set by each property's data
   retention (step 6), not by the request: the API accepts no start date earlier
   than **2015-08-14**, and `scripts/ga4.py` clamps to it.

## ⚠️ The daily trigger is Cloud Scheduler, not GitHub cron

GitHub silently drops most `schedule:` runs on public repos — the same problem
documented in [CalCOFI/uptime](https://github.com/CalCOFI/uptime)'s
OPERATIONS.md. The cron in `refresh.yml` is a fallback; the real trigger is a
Cloud Scheduler job, mirroring `calcofi-uptime-dispatch`:

```bash
gcloud scheduler jobs create http calcofi-analytics-dispatch \
  --project=ucsd-sio-calcofi --location=us-central1 \
  --schedule="17 11 * * *" --time-zone=Etc/UTC \
  --uri=https://api.github.com/repos/CalCOFI/analytics/dispatches \
  --http-method=POST \
  --headers="Authorization=Bearer <PAT>,Accept=application/vnd.github+json,Content-Type=application/json" \
  --message-body='{"event_type":"analytics"}'
```

**If the numbers look frozen, that job is the first place to check.** The site
footer stamps "data as of …" and turns warn-colored past 48 hours precisely so a
dead scheduler is visible on the page instead of quietly showing stale figures.

## Why refresh.yml builds and deploys itself

A push made with `GITHUB_TOKEN` does not trigger `on: push` workflows, and
`[skip ci]` in a commit message suppresses them too. So the tempting split —
"refresh commits, pages.yml deploys" — silently never deploys. `db-viz-station`
has exactly this bug today. Keep fetch → commit → build → deploy in one workflow.

## Adding or renaming a product

1. Add it to `data/registry.yml` (`slug`, `property`, `content_groups`,
   `path_prefixes`).
2. Make sure the product actually emits that content group — Shiny apps get it
   from `calcofi4r::cc_ga_head()`, static sites from `snippets/gtag-site.html`.
3. Add `usage: <slug>` to its card in
   `CalCOFI.github.io/_data/products.yml`, and keep `uptime: <slug>` matching
   `CalCOFI/uptime`'s `.upptimerc.yml`. The three slugs are meant to be the
   same string.
4. `python3 scripts/build.py` regenerates the page stub; commit it.

**Renaming a slug breaks the published link** from calcofi.io until that repo is
updated too, and starts a fresh CSV — the old file keeps the old history under
the old name. Prefer adding an alias in `content_groups` over renaming.
