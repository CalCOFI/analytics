# CalCOFI Usage

Which CalCOFI apps, sites and services people actually use — published at
**<https://calcofi.io/analytics/>** and refreshed daily from Google Analytics.
Each card on [calcofi.io](https://calcofi.io) links here from its `usage` link,
next to its `status` link into [status.calcofi.io](https://status.calcofi.io).

## Privacy — what is collected

The site publishes **aggregate counts only**. Specifically:

- **No IP address is published, and none is even available.** Google Analytics
  resolves visitor geography on its own servers; the Data API returns
  `country` / `region`, never an address. The map is built from those.
- **The db-viz-hex query log is the one place personal data exists** — that
  Sheet carries `ip` and `user_agent` per row, because the app records them
  server-side. [`scripts/sheet.py`](scripts/sheet.py) drops those columns as its
  first action, uses the id columns only to count *distinct* visitors, and
  asserts on the way out that none of them reached a written file.
- **Small cells are suppressed**: a `region` with fewer than 10 active users is
  folded into “Other”, on top of Google's own thresholding.
- **Free-text is capped**: the "most-requested" table publishes the top 20
  values only, so a one-off query cannot become a fingerprint.

Every number on the site is also downloadable as CSV under
`/analytics/data/`, so any claim here can be checked.

## How it works

```
GA4 (2 properties) ─┐
                    ├─ scripts/refresh.py ─→ static/data/**.csv ─→ scripts/build.py ─→ data/usage/*.json
db-viz-hex Sheet ───┘        (attribution)      (accumulated)                          content/products/*.md
                                                                                              │
                                                                              hugo ───────────┘──→ calcofi.io/analytics/
```

- **`data/registry.yml` is the only file to hand-edit.** It maps each product
  slug to a GA4 property and the rule that claims its rows.
- CSVs are **accumulated, not re-queried**: GA4's default retention is 2 months,
  so re-fetching the whole history each run would quietly lose the past. Each
  run re-reads a trailing 35-day window and upserts by date.
- **Attribution is `contentGroup` first, page path second.** `contentGroup` is a
  built-in Data API dimension already emitted by every CalCOFI app
  (`calcofi4r::cc_ga_js`) and by the static sites via
  [`snippets/gtag-site.html`](snippets/gtag-site.html). The path fallback covers
  Quarto/pkgdown pages that emit no group of ours, plus each product's history
  from before it was tagged.
- **Not** `app_name`: it is an event parameter, so the Data API can only reach it
  as `customEvent:app_name` after someone registers a custom dimension in the
  GA4 UI, and it backfills nothing.

Two properties feed the site — one for the Shiny apps (`G-VV117EV9ZT`), one for
the calcofi.io sites (`G-0HVK8TDMCF`) — and they cannot be de-duplicated against
each other, so org-wide totals count a person who visits both once per property.
The index page says so in a footnote.

## Local development

```bash
pip install -r scripts/requirements.txt
python3 scripts/build.py     # regenerate pages + JSON from whatever CSVs exist
hugo server                  # http://localhost:1313/analytics/
```

`build.py` runs with no credentials and no data — the site builds and every
`/analytics/<slug>/` URL resolves, showing "no data yet". That is deliberate, so
the links from calcofi.io are never broken while the data catches up.

To pull real data you need the Google setup in
[OPERATIONS.md](OPERATIONS.md), then:

```bash
GCP_SA_KEY="$(cat key.json)" USAGE_SHEET_ID=... python3 scripts/refresh.py --backfill
```

## Why Hugo

This is the org's first Hugo site; its siblings (`db-schema`, `db-query`,
`CalCOFI.github.io`) are Jekyll. The layouts here deliberately mirror theirs —
same palette, same pre-paint theme script, same dual-logo header — so that if the
others migrate, the port is mostly copy-paste.

Charts are **inline SVG rendered by Hugo at build time**; the only client-side
code is [`assets/js/app.js`](assets/js/app.js), which adds hover tooltips (one
delegated listener for the whole page), table sorting and the Leaflet map. There
is no charting library.
