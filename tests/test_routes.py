"""
Route-level tests for backend/app.py.

External calls (NWS, Nominatim) are mocked via pytest-mock — CI never hits
real APIs, so tests are deterministic and don't depend on network or
upstream availability.
"""
from __future__ import annotations

import requests

# ═══════════════ GET / ═══════════════════════════════════════════════════════


def test_index_serves_html(client):
    """SPA entry point — should serve frontend/index.html as HTML."""
    res = client.get("/")
    assert res.status_code == 200
    assert b"<!DOCTYPE html>" in res.data
    assert b"GAD" in res.data


# ═══════════════ GET /api/health ════════════════════════════════════════════


def test_health_returns_ok(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.get_json()
    assert body["status"] == "ok"
    assert "time" in body
    # ISO 8601 timestamp should at least be parseable
    from datetime import datetime
    datetime.fromisoformat(body["time"])


# ═══════════════ GET /api/search ════════════════════════════════════════════


def test_search_too_short_returns_empty_list(client):
    """SRS §3.5.1 — short queries should not hit Nominatim."""
    res = client.get("/api/search?q=ab")
    assert res.status_code == 200
    assert res.get_json() == []


def test_search_empty_query_returns_empty_list(client):
    res = client.get("/api/search")
    assert res.status_code == 200
    assert res.get_json() == []


def test_search_valid_query_returns_results(client, mocker, fake_response, nominatim_search_payload):
    mocker.patch(
        "app.requests.get",
        return_value=fake_response(json_data=nominatim_search_payload),
    )
    res = client.get("/api/search?q=Tampa")
    assert res.status_code == 200
    body = res.get_json()
    assert len(body) == 2
    assert body[0]["display"] == "Tampa, Hillsborough County, Florida, USA"
    assert isinstance(body[0]["lat"], float)
    assert isinstance(body[0]["lon"], float)


def test_search_handles_nominatim_unreachable(client, mocker):
    mocker.patch(
        "app.requests.get",
        side_effect=requests.exceptions.ConnectionError("Nominatim down"),
    )
    res = client.get("/api/search?q=Tampa")
    assert res.status_code == 503
    assert "error" in res.get_json()


# ═══════════════ GET /api/weather ═══════════════════════════════════════════


def test_weather_missing_coords_returns_400(client):
    res = client.get("/api/weather")
    assert res.status_code == 400
    assert "Missing coordinates" in res.get_json()["error"]


def test_weather_only_lat_returns_400(client):
    res = client.get("/api/weather?lat=27.95")
    assert res.status_code == 400


def test_weather_happy_path(
    client, mocker, fake_response,
    nws_point_payload, nws_forecast_payload, nws_alerts_payload,
):
    """SRS §3.2 — successful weather pull returns forecast, alerts, and risk scores."""
    # Patch requests.get to return different payloads based on URL.
    # Check most-specific patterns first — note that the NWS forecast URL is
    # /gridpoints/.../forecast, so a naive "points" substring check would match
    # both the point endpoint AND the forecast endpoint. Order matters here.
    def _router(url, *args, **kwargs):
        if "alerts/active" in url:
            return fake_response(json_data=nws_alerts_payload)
        if "forecast" in url:
            return fake_response(json_data=nws_forecast_payload)
        if "/points/" in url:
            return fake_response(json_data=nws_point_payload)
        return fake_response(json_data={}, ok=False, status_code=404)

    mocker.patch("app.requests.get", side_effect=_router)

    res = client.get("/api/weather?lat=27.9506&lon=-82.4572")
    assert res.status_code == 200
    body = res.get_json()

    # Schema sanity — every contracted field is present.
    for key in ("forecast", "alerts", "scores", "composite",
                "observation", "state", "climateZone", "buildingCode"):
        assert key in body, f"missing {key}"

    # State resolved + lookups joined correctly.
    assert body["state"] == "FL"
    assert body["climateZone"] == "1/2"
    assert "FBC 2023" in body["buildingCode"]

    # Forecast and alerts came through.
    assert len(body["forecast"]) == 2
    assert body["forecast"][0]["name"] == "Tonight"
    assert len(body["alerts"]) == 1
    assert body["alerts"][0]["event"] == "Coastal Flood Advisory"
    # Alerts ship with a `url` linking to the relevant NWS safety page so
    # the Alerts tab can render them as deep-links.
    assert body["alerts"][0]["url"] == "https://www.weather.gov/safety/flood"

    # All seven hazards scored, composite in range.
    assert set(body["scores"].keys()) == {
        "hurricane", "tornado", "flood", "winter", "heat", "seismic", "wildfire",
    }
    assert 0 <= body["composite"] <= 100


def test_weather_non_us_returns_404(client, mocker, fake_response):
    """NWS only covers the US; non-US coords should yield a clean 404."""
    mocker.patch(
        "app.requests.get",
        return_value=fake_response(json_data={}, ok=False, status_code=404),
    )
    res = client.get("/api/weather?lat=51.5074&lon=-0.1278")  # London
    assert res.status_code == 404
    assert "US locations" in res.get_json()["error"]


def test_weather_nws_unreachable_returns_503(client, mocker):
    """SRS §3.5.2 — upstream outage should surface as 503."""
    mocker.patch(
        "app.requests.get",
        side_effect=requests.exceptions.ConnectionError("NWS unreachable"),
    )
    res = client.get("/api/weather?lat=27.9506&lon=-82.4572")
    assert res.status_code == 503
    assert "Weather service unavailable" in res.get_json()["error"]


# ═══════════════ GET /api/history ═══════════════════════════════════════════


def test_history_known_state_returns_curated_events(client):
    res = client.get("/api/history?state=FL")
    assert res.status_code == 200
    body = res.get_json()
    assert body["state"] == "FL"
    assert len(body["events"]) >= 1
    assert any("Hurricane" in e["event"] for e in body["events"])
    assert "1980s" in body["trends"]
    # Every curated event should ship with a Wikipedia URL so the History
    # tab can render it as a deep-link.
    for ev in body["events"]:
        assert "wiki" in ev, f"event {ev['event']} missing wiki URL"
        assert ev["wiki"].startswith("https://en.wikipedia.org/"), ev["wiki"]


def test_history_every_curated_event_has_wiki_url(client):
    """Inventory check across all curated states — guards against future
    additions to historical_events forgetting the wiki field. Queries the
    database directly (post-ORM-migration the data lives there, not in a
    module-level dict)."""
    from db import get_session
    from db.models import HistoricalEvent
    from sqlalchemy import select

    with get_session() as db:
        events = db.scalars(select(HistoricalEvent)).all()
    assert len(events) >= 51, f"expected ≥51 events, got {len(events)}"
    for ev in events:
        assert ev.wiki, f"{ev.state_code}/{ev.event} missing wiki URL"
        assert ev.wiki.startswith("https://en.wikipedia.org/"), \
            f"{ev.state_code}/{ev.event}: {ev.wiki}"


def test_history_covers_all_us_states_and_dc():
    """Every clickable point on the map should resolve to historical events.
    The `states` table covers all 50 states + DC (51 rows) and every state
    has at least one curated historical event. Future edits that drop
    coverage from any of the reference tables get caught here."""
    from db import get_session
    from db.models import DecadalTrend, HistoricalEvent, State
    from sqlalchemy import func, select

    with get_session() as db:
        state_count = db.scalar(select(func.count()).select_from(State))
        states_with_events = set(db.scalars(
            select(HistoricalEvent.state_code).distinct()
        ).all())
        states_with_trends = set(db.scalars(
            select(DecadalTrend.state_code).distinct()
        ).all())
        all_states = set(db.scalars(select(State.code)).all())

    assert state_count == 51, f"expected 51 states (50 + DC), got {state_count}"
    assert states_with_events == all_states, \
        f"states without events: {all_states - states_with_events}"
    assert states_with_trends == all_states, \
        f"states without decadal trends: {all_states - states_with_trends}"


def test_history_unknown_state_returns_default_trends(client):
    res = client.get("/api/history?state=ZZ")
    assert res.status_code == 200
    body = res.get_json()
    assert body["events"] == []
    # Default trends still populated for the chart.
    assert "1980s" in body["trends"]


def test_history_missing_state_returns_default_trends(client):
    res = client.get("/api/history")
    assert res.status_code == 200
    body = res.get_json()
    assert body["events"] == []


def test_history_state_param_normalizes_to_upper(client):
    """Lowercase state code should still resolve."""
    res = client.get("/api/history?state=fl")
    assert res.status_code == 200
    body = res.get_json()
    assert body["state"] == "FL"
    assert len(body["events"]) >= 1
