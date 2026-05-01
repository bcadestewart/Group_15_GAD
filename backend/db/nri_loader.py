"""
FEMA National Risk Index (NRI) county-level data loader.

Reads a CSV in FEMA's published NRI_Table_Counties schema, normalizes the
0–100 hazard scores down to our 0–10 internal scale, and inserts/replaces
rows in the `nri_counties` table.

Public source for the production CSV (download once locally):

    curl -o backend/data/nri_counties.csv \\
        https://hazards.fema.gov/nri/data/NRI_Table_Counties.csv

Run via `seed_database()` (called automatically at app boot) — the loader
short-circuits if no CSV file is present, so a fresh checkout still boots
end-to-end. The repo includes a small sample CSV at
`backend/data/nri_sample.csv` so tests + dev have data to exercise the
lookup path.

Hazard mapping (FEMA's 18 NRI categories → our 7):
    hurricane → HRCN
    tornado   → TRND
    flood     → max(CFLD, RFLD)        # Coastal + Riverine
    winter    → max(WNTW, ISTM, CWAV)  # Winter Weather + Ice Storm + Cold Wave
    heat      → HWAV
    seismic   → EQKE
    wildfire  → WFIR

The score is normalized from FEMA's 0–100 percentile scale to our 0–10
internal scale by simple division. The composite `risk_score` stays on the
0–100 scale to preserve the standard NRI presentation.
"""
from __future__ import annotations

import csv
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.orm import Session

from .models import NRICounty


def _to_float(s: str | None) -> float:
    """FEMA CSVs use empty strings for unknown / not-applicable hazard
    scores (e.g. coastal flood for an inland county). Map those to 0."""
    if s is None or s == "":
        return 0.0
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def _normalize(score_0_to_100: float) -> float:
    """FEMA 0-100 → our 0-10 scale. Clamped defensively."""
    return max(0.0, min(10.0, score_0_to_100 / 10.0))


def _zone_id(state_abbrv: str, county_3fips: str) -> str:
    """Build the NWS county zone id (e.g. 'FLC057') from FEMA fields."""
    return f"{state_abbrv}C{county_3fips.zfill(3)}"


def parse_nri_row(row: dict) -> dict:
    """Map one CSV row dict (keyed by FEMA column names) to the kwargs
    NRICounty(**...) expects. Pure function — no DB access. Exposed for
    tests."""
    state_abbrv  = row["STATEABBRV"].strip()
    county_3fips = str(row["COUNTYFIPS"]).strip().zfill(3)
    county_fips  = row.get("STCOFIPS", "").strip() or (
        f"{int(row['STATEFIPS']):02d}{county_3fips}"
    )

    hurricane = _normalize(_to_float(row.get("HRCN_RISKS")))
    tornado   = _normalize(_to_float(row.get("TRND_RISKS")))
    # Flood = max of coastal + riverine
    flood = _normalize(max(
        _to_float(row.get("CFLD_RISKS")),
        _to_float(row.get("RFLD_RISKS")),
    ))
    # Winter = max of winter weather + ice storm + cold wave
    winter = _normalize(max(
        _to_float(row.get("WNTW_RISKS")),
        _to_float(row.get("ISTM_RISKS")),
        _to_float(row.get("CWAV_RISKS")),
    ))
    heat     = _normalize(_to_float(row.get("HWAV_RISKS")))
    seismic  = _normalize(_to_float(row.get("EQKE_RISKS")))
    wildfire = _normalize(_to_float(row.get("WFIR_RISKS")))

    return {
        "county_fips": county_fips,
        "nws_zone_id": _zone_id(state_abbrv, county_3fips),
        "state_code":  state_abbrv,
        "county_name": row.get("COUNTY", "").strip(),
        "population":  int(_to_float(row.get("POPULATION"))),
        "risk_score":  _to_float(row.get("RISK_SCORE")),
        "risk_rating": (row.get("RISK_RATNG") or "").strip() or None,
        "hurricane":   hurricane,
        "tornado":     tornado,
        "flood":       flood,
        "winter":      winter,
        "heat":        heat,
        "seismic":     seismic,
        "wildfire":    wildfire,
    }


def load_nri_counties(session: Session, csv_path: Path | str) -> int:
    """Idempotently load NRI county data from a CSV file.

    Truncate-and-reinsert: simpler than upsert, fast enough for ~3,200
    rows, and gives us a clean slate every time the source CSV is
    refreshed. Returns the number of rows inserted.

    Raises FileNotFoundError if the path doesn't exist — callers that
    want graceful degradation should check for the file first.
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"NRI CSV not found at {path}")

    # Wipe the table first
    session.execute(delete(NRICounty))

    inserted = 0
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                kwargs = parse_nri_row(row)
            except (KeyError, ValueError):
                # Skip malformed rows rather than aborting the whole load
                continue
            if not kwargs.get("county_fips") or not kwargs.get("state_code"):
                continue
            session.merge(NRICounty(**kwargs))
            inserted += 1

    session.commit()
    return inserted


def maybe_load_nri(session: Session, data_dir: Path | str) -> int:
    """Try the production CSV first, fall back to the sample bundled in
    the repo. Returns rows inserted (0 if neither file exists). This is
    the entry point called from db.seed.seed_database() so a fresh
    checkout boots end-to-end whether or not the user has downloaded the
    full FEMA dataset yet.
    """
    data_dir = Path(data_dir)
    full_path   = data_dir / "nri_counties.csv"
    sample_path = data_dir / "nri_sample.csv"

    if full_path.exists():
        return load_nri_counties(session, full_path)
    if sample_path.exists():
        return load_nri_counties(session, sample_path)
    return 0
