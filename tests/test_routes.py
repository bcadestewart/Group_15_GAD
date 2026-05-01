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


# ═══════════════ ANALYSES AUDIT LOG (SRS §3.6) ═══════════════════════════════


def _purge_analyses():
    """Clear the analyses table so each test starts from a known state.
    The reference tables (states, historical_events, etc.) stay seeded."""
    from db import get_session
    from db.models import Analysis
    from sqlalchemy import delete

    with get_session() as db:
        db.execute(delete(Analysis))
        db.commit()


def test_weather_happy_path_writes_an_analysis_row(
    client, mocker, fake_response,
    nws_point_payload, nws_forecast_payload, nws_alerts_payload,
):
    """SRS §3.6 — every successful /api/weather call should append one
    row to the analyses table. Anonymous metadata only."""
    from db import get_session
    from db.models import Analysis
    from sqlalchemy import func, select

    _purge_analyses()

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

    with get_session() as db:
        count = db.scalar(select(func.count()).select_from(Analysis))
        latest = db.scalars(
            select(Analysis).order_by(Analysis.created_at.desc()).limit(1)
        ).first()

    assert count == 1
    assert latest is not None
    assert latest.lat == 27.9506
    assert latest.lon == -82.4572
    assert latest.state == "FL"
    assert 0 <= latest.composite <= 100
    assert latest.alert_count == 1  # one mocked alert in nws_alerts_payload


def test_analysis_write_failure_does_not_break_weather(
    client, mocker, fake_response,
    nws_point_payload, nws_forecast_payload, nws_alerts_payload,
):
    """Best-effort write — a DB failure during the audit-log insert must
    NOT take down the user's weather analysis."""
    def _router(url, *args, **kwargs):
        if "alerts/active" in url:
            return fake_response(json_data=nws_alerts_payload)
        if "forecast" in url:
            return fake_response(json_data=nws_forecast_payload)
        if "/points/" in url:
            return fake_response(json_data=nws_point_payload)
        return fake_response(json_data={}, ok=False, status_code=404)

    mocker.patch("app.requests.get", side_effect=_router)
    # Stub _record_analysis to raise — the route should still return 200.
    mocker.patch("app._record_analysis", side_effect=RuntimeError("DB down"))

    # The route wraps _record_analysis in best-effort try/except, BUT we're
    # patching the function itself to raise. The route's try/except over
    # the body should still catch and produce a 503... actually no, we want
    # the audit path to be silent. Let's verify the contract: if
    # _record_analysis itself raises (vs internal swallow), the route
    # catches as part of its general try/except. To test pure best-effort,
    # we instead simulate a commit failure inside the function.
    pass  # Replaced by the more precise commit-failure test below.


def test_analysis_db_commit_failure_is_silent(
    client, mocker, fake_response,
    nws_point_payload, nws_forecast_payload, nws_alerts_payload,
):
    """If commit() inside _record_analysis raises, the user still gets a
    successful weather response. The exception is swallowed."""
    from sqlalchemy.orm import Session

    def _router(url, *args, **kwargs):
        if "alerts/active" in url:
            return fake_response(json_data=nws_alerts_payload)
        if "forecast" in url:
            return fake_response(json_data=nws_forecast_payload)
        if "/points/" in url:
            return fake_response(json_data=nws_point_payload)
        return fake_response(json_data={}, ok=False, status_code=404)

    mocker.patch("app.requests.get", side_effect=_router)
    mocker.patch.object(Session, "commit", side_effect=RuntimeError("commit failed"))

    res = client.get("/api/weather?lat=27.9506&lon=-82.4572")
    assert res.status_code == 200
    assert "scores" in res.get_json()


def test_analyses_recent_orders_descending_and_paginates(
    client, mocker, fake_response,
    nws_point_payload, nws_forecast_payload, nws_alerts_payload,
):
    """/api/analyses/recent returns rows newest-first, supports limit + offset."""
    _purge_analyses()

    def _router(url, *args, **kwargs):
        if "alerts/active" in url:
            return fake_response(json_data=nws_alerts_payload)
        if "forecast" in url:
            return fake_response(json_data=nws_forecast_payload)
        if "/points/" in url:
            return fake_response(json_data=nws_point_payload)
        return fake_response(json_data={}, ok=False, status_code=404)

    mocker.patch("app.requests.get", side_effect=_router)

    # Generate 5 analyses
    for i in range(5):
        client.get(f"/api/weather?lat=27.95{i}&lon=-82.45")

    # Default page size
    res = client.get("/api/analyses/recent")
    body = res.get_json()
    assert res.status_code == 200
    assert body["total"] == 5
    assert body["limit"] == 20
    assert body["offset"] == 0
    assert len(body["items"]) == 5

    # Newest first — created_at descending. Compare ISO timestamps.
    timestamps = [item["createdAt"] for item in body["items"]]
    assert timestamps == sorted(timestamps, reverse=True)

    # Pagination: limit=2, offset=2 → 3rd and 4th newest
    res2 = client.get("/api/analyses/recent?limit=2&offset=2")
    body2 = res2.get_json()
    assert res2.status_code == 200
    assert body2["limit"] == 2
    assert body2["offset"] == 2
    assert len(body2["items"]) == 2
    assert body2["items"] == body["items"][2:4]


def test_analyses_recent_clamps_limit_at_100(client):
    res = client.get("/api/analyses/recent?limit=9999")
    assert res.status_code == 200
    assert res.get_json()["limit"] == 100


def test_analyses_recent_handles_garbage_query_params(client):
    """Invalid limit/offset should fall back to defaults instead of 500."""
    res = client.get("/api/analyses/recent?limit=abc&offset=xyz")
    assert res.status_code == 200
    body = res.get_json()
    assert body["limit"] == 20
    assert body["offset"] == 0


def test_analyses_stats_aggregates_correctly(
    client, mocker, fake_response,
    nws_point_payload, nws_forecast_payload, nws_alerts_payload,
):
    """/api/analyses/stats groups by state and by day."""
    _purge_analyses()

    def _router(url, *args, **kwargs):
        if "alerts/active" in url:
            return fake_response(json_data=nws_alerts_payload)
        if "forecast" in url:
            return fake_response(json_data=nws_forecast_payload)
        if "/points/" in url:
            return fake_response(json_data=nws_point_payload)
        return fake_response(json_data={}, ok=False, status_code=404)

    mocker.patch("app.requests.get", side_effect=_router)

    # 3 analyses (all hit FL via the mocked NWS payload)
    for _ in range(3):
        client.get("/api/weather?lat=27.9506&lon=-82.4572")

    res = client.get("/api/analyses/stats")
    body = res.get_json()
    assert res.status_code == 200
    assert body["total"] == 3
    assert body["last24h"] == 3
    assert body["byState"] == {"FL": 3}
    # Today's date in UTC should be the only key in byDay
    assert sum(body["byDay"].values()) == 3


def test_analyses_stats_empty_table(client):
    """With no analyses, stats should return all-zero / empty containers."""
    _purge_analyses()
    res = client.get("/api/analyses/stats")
    body = res.get_json()
    assert res.status_code == 200
    assert body["total"] == 0
    assert body["last24h"] == 0
    assert body["byState"] == {}
    assert body["byDay"] == {}
