"""
Idempotent seed loader for GAD reference data.

`seed_database(session)` reads the canonical Python dicts in
`db/seed_data.py` and inserts them into the database. The `states` row
count is checked first — if non-zero, the function returns immediately,
so calling it on every app boot is safe.

Schema mapping (also documented in DESIGN.md §8):

    seed_data.RISK_CATEGORIES   →  risk_categories rows (key, label, weight, icon, sort_order)
    seed_data.CONSTRUCTION_TIPS →  construction_tips rows (hazard_key, tip, sort_order)
    seed_data.STATE_PROFILES    ┐
    seed_data.IECC_ZONES        │ →  states rows (one row per state code)
    seed_data.BUILDING_CODES    │
    seed_data.STATE_NAME_TO_CODE┘
    seed_data.HISTORICAL_EVENTS →  historical_events rows
    seed_data.DECADAL_TRENDS    →  decadal_trends rows (with DEFAULT_TRENDS
                                  filling in for states without curated data)
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import seed_data as sd
from .models import (
    ConstructionTip,
    DecadalTrend,
    HistoricalEvent,
    RiskCategory,
    State,
)


def seed_database(session: Session) -> None:
    """Populate every reference table from `seed_data` if not already done.

    Idempotent: returns immediately if `states` is non-empty, so this is
    safe to call on every app boot. Commits at the end so a partial seed
    on error rolls back cleanly.
    """
    if session.scalar(select(State.code).limit(1)) is not None:
        return  # already seeded

    # ─── Risk categories (preserve original insertion order via sort_order) ─
    for i, (key, meta) in enumerate(sd.RISK_CATEGORIES.items()):
        session.add(RiskCategory(
            key=key,
            label=meta["label"],
            weight=meta["weight"],
            icon=meta["icon"],
            sort_order=i,
        ))

    # ─── Construction tips ─────────────────────────────────────────────────
    for hazard, tips in sd.CONSTRUCTION_TIPS.items():
        for i, tip in enumerate(tips):
            session.add(ConstructionTip(hazard_key=hazard, tip=tip, sort_order=i))

    # ─── States (consolidates four prior dicts) ────────────────────────────
    code_to_name = {code: name for name, code in sd.STATE_NAME_TO_CODE.items()}
    for code, profile in sd.STATE_PROFILES.items():
        session.add(State(
            code=code,
            full_name=code_to_name.get(code, code),
            iecc_zone=sd.IECC_ZONES.get(code, "N/A"),
            building_code=sd.BUILDING_CODES.get(code, "Consult local jurisdiction"),
            **profile,
        ))

    # ─── Historical events ─────────────────────────────────────────────────
    for code, events in sd.HISTORICAL_EVENTS.items():
        for ev in events:
            session.add(HistoricalEvent(state_code=code, **ev))

    # ─── Decadal trends (extend coverage to all 51 states using
    #     DEFAULT_TRENDS as fallback so the History tab chart always renders)
    for code in sd.STATE_PROFILES:
        trends = sd.DECADAL_TRENDS.get(code, sd.DEFAULT_TRENDS)
        for decade, count in trends.items():
            session.add(DecadalTrend(state_code=code, decade=decade, count=count))

    session.commit()
