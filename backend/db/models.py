"""
SQLAlchemy 2.0 declarative models for GAD's reference data + audit log.

Reference (read-only at runtime, populated once by db/seed.py):

    State                  → STATE_PROFILES + IECC_ZONES + BUILDING_CODES +
                             STATE_NAME_TO_CODE (consolidated)
    HistoricalEvent        → HISTORICAL_EVENTS rows
    DecadalTrend           → DECADAL_TRENDS rows
    RiskCategory           → RISK_CATEGORIES (label + weight + icon per hazard)
    ConstructionTip        → CONSTRUCTION_TIPS rows

Transactional (writable):

    Analysis               → one anonymous record per /api/weather call
                             (timestamp, coordinates, resolved state,
                             composite score, active alert count). No
                             user-identifying information is stored.
                             SRS §3.6 + §4.4 compliance.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
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


# ─── Audit log (writable) ──────────────────────────────────────────────────


def _utcnow() -> datetime:
    """Naive UTC timestamp default. SQLite has no native tzinfo support so
    we store wall-clock UTC and document it; production deployments on
    Postgres can swap this for `func.now()` with a `TIMESTAMPTZ` column."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Analysis(Base):
    """One anonymous record per `/api/weather` request. Captures the
    metadata needed for usage analytics and operational visibility (which
    states are most frequently analyzed, request rate over time, alert
    incidence at the time of analysis) without persisting any
    user-identifying information.

    SRS traceability:
      §3.6 Analytics & Audit Log — defines this entity and its read API.
      §4.4 Security — only anonymous metadata; no IP, no session id, no
      user id. The lat/lon are at the resolution the user clicked, which
      is itself derived from a publicly-available map; no reverse-lookup
      to identity is performed or stored.
    """

    __tablename__ = "analyses"

    id:          Mapped[int]      = mapped_column(primary_key=True)
    created_at:  Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, index=True, nullable=False,
    )
    lat:         Mapped[float]    = mapped_column(Float, nullable=False)
    lon:         Mapped[float]    = mapped_column(Float, nullable=False)
    # `state` is nullable because NWS occasionally returns coordinates
    # without a resolvable state (open ocean, very small coastal islands).
    state:       Mapped[str | None] = mapped_column(String(2), index=True, nullable=True)
    composite:   Mapped[int]      = mapped_column(Integer, nullable=False)
    alert_count: Mapped[int]      = mapped_column(Integer, default=0, nullable=False)

    def to_dict(self) -> dict:
        return {
            "id":         self.id,
            "createdAt":  self.created_at.isoformat() + "Z",
            "lat":        self.lat,
            "lon":        self.lon,
            "state":      self.state,
            "composite":  self.composite,
            "alertCount": self.alert_count,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Analysis #{self.id} {self.state or '??'} "
            f"({self.lat:.2f},{self.lon:.2f}) composite={self.composite}>"
        )


# ─── FEMA National Risk Index — county-level reference data ────────────────


class NRICounty(Base):
    """One row per US county, sourced from the FEMA National Risk Index
    (NRI). Provides county-level hazard scores that supersede the
    state-level rough averages in the `states` table when available.

    Score scale: NRI publishes risk scores on a 0–100 percentile scale;
    we normalize to the same 0–10 scale used elsewhere (state profiles,
    composite formula) by dividing by 10. The composite score in the
    `risk_score` column stays on the 0–100 scale to preserve the
    standard NRI presentation.

    Hazard mapping from FEMA's 18 NRI categories to our 7:
        hurricane → HRCN
        tornado   → TRND
        flood     → max(CFLD, RFLD)        # Coastal + Riverine
        winter    → max(WNTW, ISTM, CWAV)  # Winter Weather + Ice Storm + Cold Wave
        heat      → HWAV
        seismic   → EQKE
        wildfire  → WFIR

    Source URL (download with `curl` to backend/data/nri_counties.csv):
        https://hazards.fema.gov/nri/data/NRI_Table_Counties.csv

    SRS traceability:
        §3.4 Assessments of Environment Constraints — replaces the
        hand-curated state-level scores with authoritative county-level
        FEMA data when a county can be resolved from the NWS response.
    """

    __tablename__ = "nri_counties"

    # 5-digit FIPS code: state (2) + county (3). E.g. "12057" = Hillsborough
    # County, FL. PK because it's the universal identifier in FEMA data.
    county_fips: Mapped[str] = mapped_column(String(5), primary_key=True)
    # NWS county zone id (e.g. "FLC057") — secondary index because the
    # /api/weather route extracts this from the NWS points response.
    nws_zone_id: Mapped[str | None] = mapped_column(String(8), index=True, nullable=True)

    state_code:  Mapped[str] = mapped_column(String(2), index=True)
    county_name: Mapped[str] = mapped_column(String(64))
    population:  Mapped[int] = mapped_column(Integer, default=0)

    # Composite NRI score on the 0–100 percentile scale, plus the verbal
    # rating ("Very Low" through "Very High").
    risk_score:  Mapped[float]    = mapped_column(Float, default=0.0)
    risk_rating: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Per-hazard scores normalized to our 0–10 scale (FEMA's 0–100 / 10).
    hurricane: Mapped[float] = mapped_column(Float, default=0.0)
    tornado:   Mapped[float] = mapped_column(Float, default=0.0)
    flood:     Mapped[float] = mapped_column(Float, default=0.0)
    winter:    Mapped[float] = mapped_column(Float, default=0.0)
    heat:      Mapped[float] = mapped_column(Float, default=0.0)
    seismic:   Mapped[float] = mapped_column(Float, default=0.0)
    wildfire:  Mapped[float] = mapped_column(Float, default=0.0)

    def profile_dict(self) -> dict[str, float]:
        """Per-hazard scores in the dict shape /api/weather expects.
        Matches `State.profile_dict()` so the route can swap between them
        transparently."""
        return {
            "hurricane": self.hurricane,
            "tornado":   self.tornado,
            "flood":     self.flood,
            "winter":    self.winter,
            "heat":      self.heat,
            "seismic":   self.seismic,
            "wildfire":  self.wildfire,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return f"<NRICounty {self.county_fips} {self.county_name}, {self.state_code}>"
