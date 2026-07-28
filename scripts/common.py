"""Paths, registry loading and CSV upsert — shared by the fetch and build steps.

Everything the pipeline writes is a plain CSV under static/data/, committed to
the repo. That is deliberate:

  * GA4's default data retention is 2 months, so a site that re-queried its
    whole history every run would silently lose its past. Accumulating locally
    makes the archive independent of the property's retention setting.
  * the CSVs are served as-is at calcofi.io/analytics/data/..., so anyone can
    check the numbers or re-plot them without the API.
"""

from __future__ import annotations

import csv
import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "static" / "data"          # published + accumulated CSVs
USAGE = ROOT / "data" / "usage"          # per-product JSON consumed by Hugo
CONTENT = ROOT / "content" / "products"  # generated page stubs
REGISTRY = ROOT / "data" / "registry.yml"


def load_registry() -> dict:
    with open(REGISTRY) as f:
        return yaml.safe_load(f)


def products(reg: dict | None = None) -> list[dict]:
    return (reg or load_registry())["products"]


def upsert_csv(path: pathlib.Path, rows: list[dict], key: list[str],
               fieldnames: list[str]) -> int:
    """Merge `rows` into the CSV at `path`, replacing rows with a matching key.

    GA4 revises recent days for ~48h as late hits land, so each run re-fetches a
    trailing window and overwrites those dates rather than appending duplicates.
    Returns the total row count written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict[tuple, dict] = {}
    if path.exists():
        with open(path, newline="") as f:
            for r in csv.DictReader(f):
                existing[tuple(r.get(k, "") for k in key)] = r

    for r in rows:
        existing[tuple(str(r.get(k, "")) for k in key)] = r

    merged = sorted(existing.values(), key=lambda r: tuple(str(r.get(k, "")) for k in key))
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(merged)
    return len(merged)


def read_csv(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))
