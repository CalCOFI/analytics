// CalCOFI Usage — the only client-side code on the site.
//
// Charts are inline SVG rendered by Hugo at build time, so nothing here parses
// data or draws anything. This file adds the three behaviors that cannot be
// pre-rendered: hover tooltips, table sorting, and the geo map.

// ── tooltips ────────────────────────────────────────────────────────────────
// ONE listener on the document covers every mark on the page, including marks
// inside a <details> that was closed at load. Per-element handlers would be
// hundreds of listeners for a 400-point chart.
function initTooltip() {
  const tip = document.createElement("div");
  tip.id = "chart-tooltip";
  document.body.appendChild(tip);

  document.addEventListener("mouseover", (e) => {
    const t = e.target.closest("[data-tip]");
    if (!t) return;
    tip.textContent = t.dataset.tip;
    tip.classList.add("on");
  });
  document.addEventListener("mousemove", (e) => {
    if (!tip.classList.contains("on")) return;
    const pad = 12;
    const r = tip.getBoundingClientRect();
    // flip before the right edge rather than letting the tooltip clip
    const x = e.clientX + pad + r.width > window.innerWidth
      ? e.clientX - pad - r.width : e.clientX + pad;
    tip.style.left = `${x}px`;
    tip.style.top = `${Math.max(4, e.clientY - r.height - pad)}px`;
  });
  document.addEventListener("mouseout", (e) => {
    if (e.target.closest("[data-tip]")) tip.classList.remove("on");
  });
}

// ── sortable rank table ─────────────────────────────────────────────────────
function initSort() {
  document.querySelectorAll("table.sortable").forEach((table) => {
    const tbody = table.tBodies[0];
    table.querySelectorAll("th[data-sort]").forEach((th, i) => {
      th.addEventListener("click", () => {
        const numeric = th.dataset.sort === "n";
        const asc = !(th.classList.contains("sorted") && !th.classList.contains("asc"));
        table.querySelectorAll("th").forEach((o) => o.classList.remove("sorted", "asc"));
        th.classList.add("sorted");
        if (asc) th.classList.add("asc");

        const rows = [...tbody.rows];
        rows.sort((a, b) => {
          const ca = a.cells[i], cb = b.cells[i];
          const va = numeric ? parseFloat(ca.dataset.v ?? ca.textContent) || 0 : ca.textContent.trim().toLowerCase();
          const vb = numeric ? parseFloat(cb.dataset.v ?? cb.textContent) || 0 : cb.textContent.trim().toLowerCase();
          return (va < vb ? -1 : va > vb ? 1 : 0) * (asc ? 1 : -1);
        });
        rows.forEach((r) => tbody.appendChild(r));
      });
    });
  });
}

// ── geo map ─────────────────────────────────────────────────────────────────
// Circles sized by √users so AREA tracks the count — radius would exaggerate
// the big countries by squaring them. One hue, matching every other mark.
function initMap() {
  const el = document.getElementById("geo-map");
  if (!el || typeof L === "undefined") return;

  let pts;
  try { pts = JSON.parse(el.dataset.points || "[]"); } catch { return; }
  const byCountry = new Map();
  for (const p of pts) {
    if (!p.countryId) continue;
    byCountry.set(p.countryId, (byCountry.get(p.countryId) || 0) + (+p.activeUsers || 0));
  }
  if (!byCountry.size) return;

  const map = L.map(el, { attributionControl: false, scrollWheelZoom: false }).setView([20, 0], 1);
  L.tileLayer("https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png", {
    subdomains: "abcd", maxZoom: 6,
  }).addTo(map);

  const accent = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim();
  const max = Math.max(...byCountry.values());

  // the URL comes from Hugo (site-root relative); resolving it against
  // document.baseURI would look under /<slug>/ and 404
  fetch(el.dataset.centroids)
    .then((r) => (r.ok ? r.json() : null))
    .then((cent) => {
      if (!cent) return;
      const bounds = [];
      for (const [id, n] of byCountry) {
        const c = cent[id];
        if (!c) continue;
        const name = pts.find((p) => p.countryId === id)?.country || id;
        L.circleMarker([c[0], c[1]], {
          radius: 4 + 18 * Math.sqrt(n / max),
          color: accent, weight: 1.5, fillColor: accent, fillOpacity: 0.35,
        }).addTo(map).bindTooltip(`${name} · ${n.toLocaleString()} users`);
        bounds.push([c[0], c[1]]);
      }
      if (bounds.length > 1) map.fitBounds(bounds, { padding: [30, 30], maxZoom: 4 });
    })
    .catch(() => {});
}

// ── staleness stamp ─────────────────────────────────────────────────────────
// A cron that quietly stops would otherwise leave numbers that look current.
function initStamp() {
  const el = document.querySelector(".stamp");
  if (!el) return;
  const when = new Date(el.dataset.generated);
  if (isNaN(when)) return;
  const hours = (Date.now() - when) / 36e5;
  el.querySelector(".stamp-when").textContent = when.toLocaleString();
  if (hours > (+el.dataset.staleHours || 48)) {
    el.classList.add("stale");
    el.title = `The daily refresh has not succeeded in ${Math.round(hours)} hours.`;
  }
}

initTooltip();
initSort();
initStamp();
window.addEventListener("load", initMap);
