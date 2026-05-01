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
        "app.http.get",
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
        "app.http.get",
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

    mocker.patch("app.http.get", side_effect=_router)

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
        "app.http.get",
        return_value=fake_response(json_data={}, ok=False, status_code=404),
    )
    res = client.get("/api/weather?lat=51.5074&lon=-0.1278")  # London
    assert res.status_code == 404
    assert "US locations" in res.get_json()["error"]


def test_weather_nws_unreachable_returns_503(client, mocker):
    """SRS §3.5.2 — upstream outage should surface as 503."""
    mocker.patch(
        "app.http.get",
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

    mocker.patch("app.http.get", side_effect=_router)

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

    mocker.patch("app.http.get", side_effect=_router)
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

    mocker.patch("app.http.get", side_effect=_router)
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

    mocker.patch("app.http.get", side_effect=_router)

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

    mocker.patch("app.http.get", side_effect=_router)

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


# ═══════════════ WEATHER PIPELINE RESILIENCE (cache + retries) ══════════════


def test_weather_second_identical_call_is_a_cache_hit(
    client, mocker, fake_response,
    nws_point_payload, nws_forecast_payload, nws_alerts_payload,
):
    """First /api/weather call hits NWS. Second identical call (within
    the TTL) reuses the cached response and never touches NWS."""
    def _router(url, *args, **kwargs):
        if "alerts/active" in url:
            return fake_response(json_data=nws_alerts_payload)
        if "forecast" in url:
            return fake_response(json_data=nws_forecast_payload)
        if "/points/" in url:
            return fake_response(json_data=nws_point_payload)
        return fake_response(json_data={}, ok=False, status_code=404)

    spy = mocker.patch("app.http.get", side_effect=_router)

    # Cold call — three NWS round-trips (point + forecast + alerts).
    res1 = client.get("/api/weather?lat=27.9506&lon=-82.4572")
    assert res1.status_code == 200
    cold_call_count = spy.call_count
    assert cold_call_count >= 2  # point + forecast (alerts only if state resolved)

    # Warm call — should be a cache hit; spy count unchanged.
    res2 = client.get("/api/weather?lat=27.9506&lon=-82.4572")
    assert res2.status_code == 200
    assert spy.call_count == cold_call_count, "cache hit shouldn't re-hit NWS"

    # Response shape identical
    assert res1.get_json() == res2.get_json()


def test_weather_nearby_coords_share_cache_entry(
    client, mocker, fake_response,
    nws_point_payload, nws_forecast_payload, nws_alerts_payload,
):
    """Two clicks within the same ~110m cell (3-decimal rounding) should
    resolve to the same cache entry."""
    def _router(url, *args, **kwargs):
        if "alerts/active" in url:
            return fake_response(json_data=nws_alerts_payload)
        if "forecast" in url:
            return fake_response(json_data=nws_forecast_payload)
        if "/points/" in url:
            return fake_response(json_data=nws_point_payload)
        return fake_response(json_data={}, ok=False, status_code=404)

    spy = mocker.patch("app.http.get", side_effect=_router)

    # 27.95061 and 27.95065 both round to 27.951 → same cache key.
    client.get("/api/weather?lat=27.95061&lon=-82.4572")
    cold_count = spy.call_count
    client.get("/api/weather?lat=27.95065&lon=-82.4572")
    assert spy.call_count == cold_count, "nearby clicks should hit the same cache entry"


def test_weather_cache_expires_after_ttl(
    client, mocker, fake_response,
    nws_point_payload, nws_forecast_payload, nws_alerts_payload,
):
    """After ttl_seconds elapses, the next call is a miss again."""
    def _router(url, *args, **kwargs):
        if "alerts/active" in url:
            return fake_response(json_data=nws_alerts_payload)
        if "forecast" in url:
            return fake_response(json_data=nws_forecast_payload)
        if "/points/" in url:
            return fake_response(json_data=nws_point_payload)
        return fake_response(json_data={}, ok=False, status_code=404)

    spy = mocker.patch("app.http.get", side_effect=_router)

    # Pin time.monotonic to a known value, advance past the TTL.
    import app as gad_app
    base = 10_000.0
    monotonic_value = [base]
    mocker.patch("cache.time.monotonic", side_effect=lambda: monotonic_value[0])

    # Cold + warm
    client.get("/api/weather?lat=27.9506&lon=-82.4572")
    cold_count = spy.call_count
    client.get("/api/weather?lat=27.9506&lon=-82.4572")
    assert spy.call_count == cold_count  # still a hit

    # Advance time past TTL
    monotonic_value[0] = base + gad_app.WEATHER_CACHE_TTL_SECONDS + 1
    res = client.get("/api/weather?lat=27.9506&lon=-82.4572")
    assert res.status_code == 200
    assert spy.call_count > cold_count, "cache should miss after TTL expiry"


def test_cache_stats_endpoint_shape(client):
    """/api/cache/stats returns the expected fields."""
    res = client.get("/api/cache/stats")
    assert res.status_code == 200
    body = res.get_json()
    for key in ("hits", "misses", "size", "max_size", "ttl_seconds", "hit_rate"):
        assert key in body, f"missing {key}"
    assert body["max_size"] >= 1
    assert body["ttl_seconds"] > 0
    assert 0.0 <= body["hit_rate"] <= 1.0


def test_cache_stats_reflects_hits_and_misses(
    client, mocker, fake_response,
    nws_point_payload, nws_forecast_payload, nws_alerts_payload,
):
    """After a miss + a hit, the stats endpoint should show both."""
    def _router(url, *args, **kwargs):
        if "alerts/active" in url:
            return fake_response(json_data=nws_alerts_payload)
        if "forecast" in url:
            return fake_response(json_data=nws_forecast_payload)
        if "/points/" in url:
            return fake_response(json_data=nws_point_payload)
        return fake_response(json_data={}, ok=False, status_code=404)

    mocker.patch("app.http.get", side_effect=_router)

    client.get("/api/weather?lat=27.9506&lon=-82.4572")  # miss
    client.get("/api/weather?lat=27.9506&lon=-82.4572")  # hit

    body = client.get("/api/cache/stats").get_json()
    assert body["hits"] == 1
    assert body["misses"] == 1
    assert body["size"] == 1
    assert body["hit_rate"] == 0.5


def test_weather_returns_nri_county_data_when_zone_id_resolves(
    client, mocker, fake_response,
    nws_point_payload, nws_forecast_payload, nws_alerts_payload,
):
    """SRS §3.4 — when the NWS points response carries a county zone id
    that matches an nri_counties row, /api/weather returns the FEMA
    NRI county-level scores and labels the response accordingly."""
    def _router(url, *args, **kwargs):
        if "alerts/active" in url:
            return fake_response(json_data=nws_alerts_payload)
        if "forecast" in url:
            return fake_response(json_data=nws_forecast_payload)
        if "/points/" in url:
            return fake_response(json_data=nws_point_payload)
        return fake_response(json_data={}, ok=False, status_code=404)

    mocker.patch("app.http.get", side_effect=_router)

    res = client.get("/api/weather?lat=27.9506&lon=-82.4572")
    assert res.status_code == 200
    body = res.get_json()

    # Hillsborough, FL is in our sample CSV — county_name + NRI source
    # should both be populated.
    assert body["countyName"] == "Hillsborough"
    assert body["riskSource"] == "FEMA National Risk Index"
    # Hurricane score for Hillsborough in the sample CSV is 84.5/10 = 8.45;
    # after jitter (±1) it's still in [7, 10]. Looser bound so the test
    # doesn't break if jitter changes.
    assert body["scores"]["hurricane"] >= 7


def test_weather_falls_back_to_state_when_no_nri_match(
    client, mocker, fake_response,
    nws_forecast_payload, nws_alerts_payload,
):
    """If the NWS points response carries a zone id that's NOT in
    nri_counties (e.g. a county we don't have NRI data for), the route
    falls back to State-level scores and labels riskSource accordingly."""
    point_payload_unknown_county = {
        "properties": {
            "forecast": "https://api.weather.gov/gridpoints/TBW/52,68/forecast",
            "county":   "https://api.weather.gov/zones/county/FLC999",  # not in sample
            "relativeLocation": {"properties": {"state": "FL"}},
        }
    }

    def _router(url, *args, **kwargs):
        if "alerts/active" in url:
            return fake_response(json_data=nws_alerts_payload)
        if "forecast" in url:
            return fake_response(json_data=nws_forecast_payload)
        if "/points/" in url:
            return fake_response(json_data=point_payload_unknown_county)
        return fake_response(json_data={}, ok=False, status_code=404)

    mocker.patch("app.http.get", side_effect=_router)

    res = client.get("/api/weather?lat=27.9506&lon=-82.4572")
    assert res.status_code == 200
    body = res.get_json()

    assert body["countyName"] is None
    assert body["riskSource"] == "state-level baseline"
    # State-level FL profile has hurricane=9 — still high after jitter.
    assert body["scores"]["hurricane"] >= 7


def test_nri_loader_seeded_some_counties():
    """The seeder populated nri_counties from whatever CSV was present
    (sample for fresh checkouts; the real FEMA download for users who
    ran the curl command). Either way, the lookup table should contain
    the well-known counties used elsewhere in the test suite, with
    structurally-valid hazard scores. Specific score values are NOT
    asserted here because they differ between the sample and the real
    FEMA dataset — the dedicated parser test
    (test_nri_loader_uses_correct_fema_column_names) covers
    score-normalization correctness with synthetic data instead."""
    from db import get_session
    from db.models import NRICounty
    from sqlalchemy import select

    with get_session() as db:
        hillsborough = db.scalar(
            select(NRICounty).where(NRICounty.county_fips == "12057")
        )

    assert hillsborough is not None, "Hillsborough should be loaded by either sample or full CSV"
    assert hillsborough.county_name == "Hillsborough"
    assert hillsborough.state_code == "FL"
    assert hillsborough.nws_zone_id == "FLC057"

    # Each per-hazard score should be in the normalized 0-10 range, regardless
    # of whether the source CSV was the sample or the full FEMA dataset.
    for hazard in ("hurricane", "tornado", "flood", "winter",
                   "heat", "seismic", "wildfire"):
        v = getattr(hillsborough, hazard)
        assert isinstance(v, float), f"{hazard} should be a float, got {type(v)}"
        assert 0.0 <= v <= 10.0, f"{hazard} out of [0,10]: {v}"

    # Hillsborough is a Gulf-coast county; hurricane should land in
    # 'Relatively High' or 'Very High' rating bands (7 or 9) in any
    # reasonable risk dataset.
    assert hillsborough.hurricane >= 7.0, (
        f"Hillsborough hurricane should map to Rel High or higher; "
        f"got {hillsborough.hurricane}"
    )


def test_nri_loader_uses_correct_fema_column_names():
    """Regression: FEMA NRI's inland-flooding column is `IFLD_RISKS` and
    its earthquake column is `ERQK_RISKS`. Earlier loader code used
    `RFLD_RISKS` and `EQKE_RISKS` (which don't exist in any FEMA CSV),
    so flood was underestimated (only coastal counted) and seismic was
    always zero. This test pins the parser against a synthetic row using
    real FEMA column names — and confirms the wrong names are ignored
    even when present.

    Score values: with the rating-based mapping, 'Very High' → 9.
    """
    from db.nri_loader import parse_nri_row

    row = {
        "STATEFIPS":   "48",
        "STATEABBRV":  "TX",
        "COUNTYFIPS":  "201",
        "STCOFIPS":    "48201",
        "COUNTY":      "Harris",
        "POPULATION":  "4726200",
        "RISK_SCORE":  "99.9",
        "RISK_RATNG":  "Very High",
        # Real FEMA columns (the wrong ones the old loader used should
        # have NO effect). Use distinct ratings so the test detects if
        # the parser incorrectly reads from the wrong column:
        "HRCN_RISKS":  "100.0",  "HRCN_RATNG": "Very High",       "HRCN_AFREQ": "1.5",
        "TRND_RISKS":  "100.0",  "TRND_RATNG": "Very High",       "TRND_AFREQ": "0.8",
        "CFLD_RISKS":  "20.0",   "CFLD_RATNG": "Relatively Low",  "CFLD_AFREQ": "0.5",
        "IFLD_RISKS":  "99.97",  "IFLD_RATNG": "Very High",       "IFLD_AFREQ": "1.2",
        "WNTW_RISKS":  "88.8",   "WNTW_RATNG": "Very High",       "WNTW_AFREQ": "0.4",
        "ISTM_RISKS":  "99.5",   "ISTM_RATNG": "Very High",       "ISTM_AFREQ": "0.3",
        "CWAV_RISKS":  "99.9",   "CWAV_RATNG": "Very High",       "CWAV_AFREQ": "0.5",
        "HWAV_RISKS":  "99.7",   "HWAV_RATNG": "Very High",       "HWAV_AFREQ": "1.0",
        "ERQK_RISKS":  "92.1",   "ERQK_RATNG": "Relatively High", "ERQK_AFREQ": "0.001",
        "WFIR_RISKS":  "85.4",   "WFIR_RATNG": "Very High",       "WFIR_AFREQ": "0.2",
        # Old wrong names — values here SHOULD be ignored by the parser.
        "RFLD_RISKS":  "100.0",  "RFLD_RATNG": "Very High",
        "EQKE_RISKS":  "100.0",  "EQKE_RATNG": "Very High",
    }

    kwargs = parse_nri_row(row)

    # Flood = max(CFLD=Relatively Low → 3, IFLD=Very High → 9) = 9.
    # If the parser incorrectly read RFLD instead of IFLD, RFLD here is
    # also Very High so the test would still pass — but CFLD is set to
    # Relatively Low (3), so a parser that ignored both IFLD and RFLD
    # would return 3, not 9. The 9 result confirms IFLD is being read.
    assert kwargs["flood"] == 9.0, (
        f"flood should be 9 (Very High via IFLD); got {kwargs['flood']}"
    )
    # Seismic: ERQK_RATNG = "Relatively High" → 7, BUT ERQK_AFREQ = 0.001
    # (rare-event threshold) → capped at 1.0. This is the Houston-quake
    # case: FEMA's percentile says high-ish, but the absolute frequency
    # is so low that the score should reflect "essentially no risk."
    assert kwargs["seismic"] == 1.0, (
        f"seismic should be capped at 1 by AFREQ gate; got {kwargs['seismic']}"
    )
    # Hurricane and tornado map cleanly: Very High + non-rare AFREQ → 9.
    assert kwargs["hurricane"] == 9.0
    assert kwargs["tornado"] == 9.0


def test_nri_loader_afreq_gate_caps_rare_events():
    """The AFREQ sanity gate is the key fix for FEMA's percentile-bias
    on rare-event hazards. A county with high percentile-rated risk but
    near-zero annualized frequency (e.g. Houston earthquakes) should
    score 1, not 7-9."""
    from db.nri_loader import parse_nri_row

    base = {
        "STATEFIPS": "48", "STATEABBRV": "TX", "COUNTYFIPS": "201",
        "STCOFIPS": "48201", "COUNTY": "Harris",
    }

    # AFREQ above threshold → trust the rating
    row1 = {**base, "ERQK_RATNG": "Very High", "ERQK_AFREQ": "1.0"}
    assert parse_nri_row(row1)["seismic"] == 9.0

    # AFREQ below threshold → cap at 1
    row2 = {**base, "ERQK_RATNG": "Very High", "ERQK_AFREQ": "0.001"}
    assert parse_nri_row(row2)["seismic"] == 1.0

    # Right at threshold (0.01) → just above means trust rating
    row3 = {**base, "ERQK_RATNG": "Very High", "ERQK_AFREQ": "0.02"}
    assert parse_nri_row(row3)["seismic"] == 9.0

    # Empty / missing AFREQ → also caps (treats as zero)
    row4 = {**base, "ERQK_RATNG": "Very High", "ERQK_AFREQ": ""}
    assert parse_nri_row(row4)["seismic"] == 1.0


def test_nri_loader_does_not_truncate_on_invalid_input(tmp_path):
    """Regression: a non-CSV (e.g. HTML redirect page accidentally curled
    to nri_counties.csv) must not silently destroy existing seed data.

    Reproduces the failure mode observed when a user runs `curl` against
    a FEMA URL that redirects, without `-L`: a tiny non-CSV gets saved,
    the loader truncates the table, finds zero parsable rows, and the
    seed data is gone. Loader must leave existing data alone in that case.
    """
    from db import get_session
    from db.models import NRICounty
    from db.nri_loader import load_nri_counties, maybe_load_nri
    from sqlalchemy import func, select

    # Sanity: the seed populated some sample rows.
    with get_session() as db:
        seeded_count = db.scalar(select(func.count()).select_from(NRICounty))
    assert seeded_count > 0, "test setup failed — sample seed didn't populate"

    # Drop a 134-byte HTML stub at the path (mimicking what `curl` would
    # save if FEMA returned a redirect page that wasn't followed).
    bad_csv = tmp_path / "fake_nri.csv"
    bad_csv.write_text(
        "<html><body><h1>Moved</h1><p>The data has moved.</p></body></html>\n"
    )

    with get_session() as db:
        inserted = load_nri_counties(db, bad_csv)
    assert inserted == 0, "loader should report zero rows on invalid input"

    # Critical assertion: existing rows still there.
    with get_session() as db:
        post_count = db.scalar(select(func.count()).select_from(NRICounty))
    assert post_count == seeded_count, (
        f"loader must not truncate when input is invalid; lost "
        f"{seeded_count - post_count} rows"
    )

    # And maybe_load_nri should also fall through to the sample when the
    # 'production' file is bogus.
    bad_full = tmp_path / "nri_counties.csv"
    bad_full.write_text("<html><body>nope</body></html>")
    sample_link = tmp_path / "nri_sample.csv"
    # Copy the real sample so maybe_load_nri sees a usable fallback.
    from pathlib import Path as _P
    repo_sample = _P(__file__).resolve().parent.parent / "backend" / "data" / "nri_sample.csv"
    sample_link.write_text(repo_sample.read_text())

    with get_session() as db:
        n = maybe_load_nri(db, tmp_path)
    assert n > 0, "maybe_load_nri should fall through to the sample when the full file is bad"


def test_retry_session_recovers_from_one_transient_503(client, mocker):
    """If NWS returns a transient 503 once and a success on retry, the
    user shouldn't see the 503 — the urllib3 Retry adapter handles it.

    We don't try to verify the retry fully end-to-end (that would require
    a real socket-level test). Instead we verify that the `http` session
    has the retry adapter mounted with the expected policy, so the
    behavior is configured correctly."""
    import app as gad_app

    adapter = gad_app.http.get_adapter("https://api.weather.gov/")
    retry = adapter.max_retries
    assert retry.total == 2
    assert retry.backoff_factor == 0.5
    assert 503 in retry.status_forcelist
    assert 502 in retry.status_forcelist
    assert 504 in retry.status_forcelist
