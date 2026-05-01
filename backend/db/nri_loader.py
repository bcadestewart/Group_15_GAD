"""
FEMA National Risk Index (NRI) county-level data loader.

Reads a CSV in FEMA's published NRI_Table_Counties schema, maps each
hazard's verbal rating ('Very Low' through 'Very High') to a 1-9 score
using the bands FEMA documents, and inserts/replaces rows in the
`nri_counties` table.

Why the verbal-rating mapping instead of raw percentile / 10? FEMA's
`*_RISKS` column is a 0-100 percentile *rank* among US counties, not an
absolute risk magnitude. Populous, high-exposure metros (Harris/Houston,
Maricopa/Phoenix, etc.) sit in the top 1-5% across most hazards, which
made every score show as 10/10 under the previous naive scale. Mapping
the verbal `*_RATNG` column instead spreads scores across the 1-9 range:
'Very High' counties show as 9, 'Relatively High' as 7, etc. Reserves 10
for outliers we can detect explicitly later.

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
    flood     → max(CFLD, IFLD)        # Coastal Flooding + Inland Flooding
    winter    → max(WNTW, ISTM, CWAV)  # Winter Weather + Ice Storm + Cold Wave
    heat      → HWAV
    seismic   → ERQK                   # Earthquake
    wildfire  → WFIR

Note on column names: FEMA's actual CSV uses ERQK_RISKS / ERQK_RATNG
(not EQKE) for earthquake and IFLD_RISKS / IFLD_RATNG (not RFLD) for
inland flooding. Earlier versions of this loader used RFLD/EQKE, which
don't exist in any FEMA release — they silently parsed as zero, badly
underestimating flood and zeroing out seismic for every county.

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


# FEMA NRI verbal rating → our 0-10 score. Reserves wider gaps between
# bands so the typical "Very High" county shows as 9 (not 10), giving
# the UI room to differentiate truly extreme outliers. Top 0.5%
# of counties remain on the percentile scale and can still hit 10
# via a separate code path if we ever add one.
_RATING_TO_SCORE = {
    "very low":            1.0,
    "relatively low":      3.0,
    "relatively moderate": 5.0,
    "relatively high":     7.0,
    "very high":           9.0,
    # FEMA's null/sentinel rating values — map to 0 so they don't
    # accidentally inflate combined scores via max().
    "no rating":           0.0,
    "insufficient data":   0.0,
    "not applicable":      0.0,
}


def _rating_to_score(rating: str | None) -> float:
    """Map FEMA's verbal rating ('Very High', 'Relatively Low', ...) to
    our 0-10 score. Unknown / missing ratings return 0."""
    if not rating:
        return 0.0
    return _RATING_TO_SCORE.get(rating.strip().lower(), 0.0)


def _percentile_to_score(score_0_to_100: float) -> float:
    """Derive the 1-9 score from a 0-100 percentile using FEMA's
    documented rating bands:

        0.0–0     → 0  (no rating)
        0–20      → 1  (Very Low)
        20–40     → 3  (Relatively Low)
        40–60     → 5  (Relatively Moderate)
        60–80     → 7  (Relatively High)
        80+       → 9  (Very High)

    This is the fallback path for CSVs that don't ship *_RATNG columns
    (e.g. our committed sample). The real FEMA download has both
    *_RATNG and *_RISKS so we prefer the verbal value directly.
    """
    if score_0_to_100 <= 0:
        return 0.0
    if score_0_to_100 < 20:
        return 1.0
    if score_0_to_100 < 40:
        return 3.0
    if score_0_to_100 < 60:
        return 5.0
    if score_0_to_100 < 80:
        return 7.0
    return 9.0


# Annualized frequency below this threshold (≈1 event per century) is
# treated as "not really a hazard for this county" regardless of FEMA's
# percentile rank. This corrects a known NRI behavior where populous,
# high-exposure counties in low-baseline-hazard regions (Houston for
# earthquake, Phoenix for tsunami, etc.) are ranked "Relatively High"
# or "Very High" because they sit in the upper percentiles of a
# distribution where the bottom 80% is at literal-zero — the percentile
# rank is real but the absolute risk is tiny.
_AFREQ_RARE_EVENT_THRESHOLD = 0.01  # ~1 event per 100 years


def _resolve_hazard_score(
    row: dict,
    rating_col: str,
    risks_col: str,
    afreq_col: str | None = None,
) -> float:
    """Prefer the explicit verbal rating; fall back to deriving from the
    raw percentile. Both come from the same FEMA dataset so they should
    agree, but the verbal column is null for hazards that don't apply
    to a region — in that case the percentile is also empty and we
    correctly report 0.

    AFREQ sanity gate: if the caller passes the annualized-frequency
    column name AND that frequency is below the rare-event threshold,
    the score is capped at 1 (Very Low). This handles the case where
    FEMA's percentile-based rating overstates absolute risk for
    near-zero-baseline hazards in populous counties (Houston quakes,
    inland tsunamis, etc.).
    """
    rating = (row.get(rating_col) or "").strip()
    if rating:
        score = _rating_to_score(rating)
    else:
        score = _percentile_to_score(_to_float(row.get(risks_col)))

    # AFREQ gate — only applies when the column is explicitly present in
    # the input row. If the column is entirely absent (e.g. our sample
    # CSV doesn't carry AFREQ data), we skip the gate and trust the
    # rating-based score. If the column is present but empty/zero, the
    # gate fires — that's the caller signaling "I tried to look this up
    # and FEMA reports near-zero frequency for this county."
    if afreq_col is not None and afreq_col in row:
        afreq = _to_float(row.get(afreq_col))
        if afreq < _AFREQ_RARE_EVENT_THRESHOLD:
            return min(score, 1.0)

    return score


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

    # Each hazard passes the corresponding *_AFREQ column for the rare-
    # event sanity gate (caps the score at 1 when absolute frequency is
    # near zero, regardless of percentile rank — see docstring above).
    hurricane = _resolve_hazard_score(row, "HRCN_RATNG", "HRCN_RISKS", "HRCN_AFREQ")
    tornado   = _resolve_hazard_score(row, "TRND_RATNG", "TRND_RISKS", "TRND_AFREQ")
    # Flood = max of coastal + inland (FEMA NRI uses IFLD for "Inland
    # Flooding"; older docs called it "Riverine"/RFLD).
    flood = max(
        _resolve_hazard_score(row, "CFLD_RATNG", "CFLD_RISKS", "CFLD_AFREQ"),
        _resolve_hazard_score(row, "IFLD_RATNG", "IFLD_RISKS", "IFLD_AFREQ"),
    )
    # Winter = max of winter weather + ice storm + cold wave
    winter = max(
        _resolve_hazard_score(row, "WNTW_RATNG", "WNTW_RISKS", "WNTW_AFREQ"),
        _resolve_hazard_score(row, "ISTM_RATNG", "ISTM_RISKS", "ISTM_AFREQ"),
        _resolve_hazard_score(row, "CWAV_RATNG", "CWAV_RISKS", "CWAV_AFREQ"),
    )
    heat     = _resolve_hazard_score(row, "HWAV_RATNG", "HWAV_RISKS", "HWAV_AFREQ")
    # Seismic — FEMA NRI uses ERQK (earthquake) as the column code. The
    # AFREQ gate is most important for this hazard; FEMA ranks Houston as
    # 'Relatively High' for earthquake by percentile despite a near-zero
    # historical event frequency. The gate forces such cases to 1 (Very
    # Low) which matches actual seismic risk.
    seismic  = _resolve_hazard_score(row, "ERQK_RATNG", "ERQK_RISKS", "ERQK_AFREQ")
    wildfire = _resolve_hazard_score(row, "WFIR_RATNG", "WFIR_RISKS", "WFIR_AFREQ")

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

    Two-pass: parse the entire CSV into memory first, then only
    truncate-and-insert if we successfully extracted at least one valid
    row. This avoids destroying existing seed data when a user accidentally
    saves a non-CSV (e.g. an HTML redirect page) at the configured path —
    a real failure mode observed when curling the FEMA URL through a
    redirect without `-L`.

    Returns the number of rows inserted. Returns 0 (and leaves existing
    data untouched) when the file parses to zero valid rows.

    Raises FileNotFoundError if the path doesn't exist — callers that
    want graceful degradation should check for the file first.
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"NRI CSV not found at {path}")

    # First pass: parse without touching the database. Anything malformed
    # gets dropped silently; we only commit if we found real rows.
    parsed_rows: list[dict] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                kwargs = parse_nri_row(row)
            except (KeyError, ValueError):
                continue
            if not kwargs.get("county_fips") or not kwargs.get("state_code"):
                continue
            parsed_rows.append(kwargs)

    if not parsed_rows:
        # The file existed but produced zero valid rows — almost certainly
        # not a real NRI CSV. Don't touch the table; whatever was there
        # (likely the sample seed) stays.
        return 0

    # Second pass: now we know the file is valid, do the destructive part.
    session.execute(delete(NRICounty))
    for kwargs in parsed_rows:
        session.merge(NRICounty(**kwargs))
    session.commit()
    return len(parsed_rows)


def maybe_load_nri(session: Session, data_dir: Path | str) -> int:
    """Try the production CSV first, fall back to the sample bundled in
    the repo. Returns rows inserted (0 if no candidate file produces any
    valid rows). This is the entry point called from
    db.seed.seed_database() so a fresh checkout boots end-to-end whether
    or not the user has downloaded the full FEMA dataset yet.

    Production-CSV candidates tried in order:
        nri_counties.csv        — our convention (curl -o nri_counties.csv ...)
        NRI_Table_Counties.csv  — FEMA's native filename (saved as-is from a
                                  browser download from hazards.fema.gov)

    Whichever exists is parsed; if it produces ≥1 valid row, that data
    wins. If it parses to zero rows (e.g. an HTML stub from a missed
    redirect), the function falls through to the next candidate, and
    finally to the committed sample.
    """
    data_dir = Path(data_dir)
    candidates = (
        data_dir / "nri_counties.csv",
        data_dir / "NRI_Table_Counties.csv",
    )
    sample_path = data_dir / "nri_sample.csv"

    for path in candidates:
        if path.exists():
            n = load_nri_counties(session, path)
            if n > 0:
                return n
            # Existed but invalid — fall through to next candidate.

    if sample_path.exists():
        return load_nri_counties(session, sample_path)
    return 0
