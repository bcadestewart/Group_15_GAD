"""
SQLAlchemy 2.0 declarative models for GAD's reference data.

All static lookup tables that previously lived as Python dicts in app.py are
now first-class entities here:

    State                  → STATE_PROFILES + IECC_ZONES + BUILDING_CODES +
                             STATE_NAME_TO_CODE (consolidated)
    HistoricalEvent        → HISTORICAL_EVENTS rows
    DecadalTrend           → DECADAL_TRENDS rows
    RiskCategory           → RISK_CATEGORIES (label + weight + icon per hazard)
    ConstructionTip        → CONSTRUCTION_TIPS rows

The data layer is intentionally read-only at runtime — the seed function in
db/seed.py populates these tables on first startup and tests reset/reseed
in-memory before each suite. Future work (Alembic migrations, a writable
`analyses` audit-log table, user accounts) builds on this foundation.
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Shared declarative base for all GAD ORM models."""


# ─── States (consolidated profile + IECC zone + building code) ──────────────


class State(Base):
    """One row per US state + DC. Combines the four prior dicts:
    STATE_PROFILES (per-hazard 0–10 scores), IECC_ZONES (climate zone),
    BUILDING_CODES (adopted IBC year), and STATE_NAME_TO_CODE (full name)."""

    __tablename__ = "states"

    code:          Mapped[str] = mapped_column(String(2), primary_key=True)
    full_name:     Mapped[str] = mapped_column(String(64), unique=True, index=True)
    iecc_zone:     Mapped[str] = mapped_column(String(8))
    building_code: Mapped[str] = mapped_column(String(64))

    # Per-hazard 0–10 scores
    hurricane: Mapped[int] = mapped_column(Integer)
    tornado:   Mapped[int] = mapped_column(Integer)
    flood:     Mapped[int] = mapped_column(Integer)
    winter:    Mapped[int] = mapped_column(Integer)
    heat:      Mapped[int] = mapped_column(Integer)
    seismic:   Mapped[int] = mapped_column(Integer)
    wildfire:  Mapped[int] = mapped_column(Integer)

    events: Mapped[list[HistoricalEvent]] = relationship(
        back_populates="state", cascade="all, delete-orphan",
        order_by="HistoricalEvent.year.desc()",
    )
    trends: Mapped[list[DecadalTrend]] = relationship(
        back_populates="state", cascade="all, delete-orphan",
        order_by="DecadalTrend.decade",
    )

    def profile_dict(self) -> dict[str, int]:
        """Return per-hazard scores in the dict shape the routes expect."""
        return {
            "hurricane": self.hurricane,
            "tornado":   self.tornado,
            "flood":     self.flood,
            "winter":    self.winter,
            "heat":      self.heat,
            "seismic":   self.seismic,
            "wildfire":  self.wildfire,
        }

    def __repr__(self) -> str:  # pragma: no cover — debug helper
        return f"<State {self.code} ({self.full_name})>"


# ─── Historical events ──────────────────────────────────────────────────────


class HistoricalEvent(Base):
    """Notable past disaster (Hurricane Andrew, Camp Fire, Joplin Tornado, …)
    associated with a single state. Each carries a hand-verified Wikipedia
    URL for the History tab's deep-link feature."""

    __tablename__ = "historical_events"

    id:         Mapped[int] = mapped_column(primary_key=True)
    state_code: Mapped[str] = mapped_column(
        ForeignKey("states.code", ondelete="CASCADE"), index=True,
    )
    year:     Mapped[int] = mapped_column(Integer)
    event:    Mapped[str] = mapped_column(String(128))
    severity: Mapped[str] = mapped_column(String(32))
    note:     Mapped[str] = mapped_column(String(512))
    wiki:     Mapped[str] = mapped_column(String(512))

    state: Mapped[State] = relationship(back_populates="events")

    def to_dict(self) -> dict:
        return {
            "year":     self.year,
            "event":    self.event,
            "severity": self.severity,
            "note":     self.note,
            "wiki":     self.wiki,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return f"<HistoricalEvent {self.state_code} {self.year} {self.event!r}>"


# ─── Decadal trends ─────────────────────────────────────────────────────────


class DecadalTrend(Base):
    """Hazard-events-per-decade for a given state. Used by the History tab's
    Chart.js trend chart. (state_code, decade) is the natural key."""

    __tablename__ = "decadal_trends"

    state_code: Mapped[str] = mapped_column(
        ForeignKey("states.code", ondelete="CASCADE"), primary_key=True,
    )
    decade: Mapped[str] = mapped_column(String(8), primary_key=True)
    count:  Mapped[int] = mapped_column(Integer)

    state: Mapped[State] = relationship(back_populates="trends")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DecadalTrend {self.state_code} {self.decade}={self.count}>"


# ─── Risk categories + construction tips ────────────────────────────────────


class RiskCategory(Base):
    """One of the seven hazard categories used in the composite risk score
    (hurricane, tornado, flood, winter, heat, seismic, wildfire). Carries
    the display label, weight, and emoji icon."""

    __tablename__ = "risk_categories"

    key:    Mapped[str]   = mapped_column(String(16), primary_key=True)
    label:  Mapped[str]   = mapped_column(String(64))
    weight: Mapped[float]
    icon:   Mapped[str]   = mapped_column(String(8))

    sort_order: Mapped[int] = mapped_column(Integer)

    tips: Mapped[list[ConstructionTip]] = relationship(
        back_populates="category", cascade="all, delete-orphan",
        order_by="ConstructionTip.sort_order",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<RiskCategory {self.key} weight={self.weight}>"


class ConstructionTip(Base):
    """A single construction recommendation associated with one hazard
    category (e.g. hurricane → 'Use hurricane straps/clips...')."""

    __tablename__ = "construction_tips"

    id:         Mapped[int] = mapped_column(primary_key=True)
    hazard_key: Mapped[str] = mapped_column(
        ForeignKey("risk_categories.key", ondelete="CASCADE"), index=True,
    )
    tip:        Mapped[str] = mapped_column(String(256))
    sort_order: Mapped[int] = mapped_column(Integer)

    category: Mapped[RiskCategory] = relationship(back_populates="tips")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ConstructionTip {self.hazard_key} #{self.sort_order}>"
