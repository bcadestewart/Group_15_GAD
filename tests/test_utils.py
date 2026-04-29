"""
Tests for backend/app.py pure-function utilities:
    - normalize_state
    - jitter
    - composite_from_scores

These functions are the deterministic core of the risk pipeline and have
no external dependencies — fastest tests in the suite.
"""
from __future__ import annotations

import app as gad_app

# ═══════════════ normalize_state ═════════════════════════════════════════════


class TestNormalizeState:
    def test_two_letter_code_passthrough(self):
        assert gad_app.normalize_state("TX") == "TX"

    def test_two_letter_code_lowercase_uppercased(self):
        assert gad_app.normalize_state("tx") == "TX"

    def test_full_state_name_resolves_to_code(self):
        assert gad_app.normalize_state("Texas") == "TX"
        assert gad_app.normalize_state("California") == "CA"
        assert gad_app.normalize_state("New York") == "NY"

    def test_empty_string_returns_empty(self):
        assert gad_app.normalize_state("") == ""

    def test_none_returns_empty(self):
        assert gad_app.normalize_state(None) == ""

    def test_unknown_returns_empty(self):
        assert gad_app.normalize_state("Atlantis") == ""

    def test_whitespace_is_stripped(self):
        assert gad_app.normalize_state("  Texas  ") == "TX"


# ═══════════════ jitter ═════════════════════════════════════════════════════


class TestJitter:
    def test_output_bounded_to_zero_ten(self):
        # Sweep a grid of lat/lon and scores; output must always stay in [0, 10].
        for lat in (-90, -33, 0, 27.95, 61.22, 90):
            for lon in (-180, -149.9, -82.45, 0, 100, 180):
                for score in (0, 1, 5, 9, 10):
                    out = gad_app.jitter(score, lat, lon)
                    assert 0 <= out <= 10, (lat, lon, score, out)

    def test_deterministic(self):
        # Same inputs → same output (reproducibility for caching).
        a = gad_app.jitter(7, 27.9506, -82.4572)
        b = gad_app.jitter(7, 27.9506, -82.4572)
        assert a == b

    def test_clamps_negative_inputs(self):
        # If a profile somehow had a -1, output should still be ≥ 0.
        out = gad_app.jitter(-5, 27.95, -82.45)
        assert out >= 0

    def test_clamps_above_ten_inputs(self):
        # Profile of 15 should still produce ≤ 10.
        out = gad_app.jitter(15, 27.95, -82.45)
        assert out <= 10


# ═══════════════ composite_from_scores ══════════════════════════════════════


class TestCompositeFromScores:
    def test_all_zeros_yields_zero(self):
        scores = {k: 0 for k in gad_app.RISK_CATEGORIES}
        assert gad_app.composite_from_scores(scores) == 0

    def test_all_tens_yields_one_hundred(self):
        scores = {k: 10 for k in gad_app.RISK_CATEGORIES}
        assert gad_app.composite_from_scores(scores) == 100

    def test_known_florida_profile(self):
        # FL profile: hurricane=9, tornado=4, flood=7, winter=0, heat=7,
        # seismic=0, wildfire=4. Weighted sum = 1.8+0.72+1.05+0+0.7+0+0.4 = 4.67.
        # composite = round(4.67 / 10 * 100) = 47.
        scores = {
            "hurricane": 9, "tornado": 4, "flood": 7, "winter": 0,
            "heat": 7, "seismic": 0, "wildfire": 4,
        }
        assert gad_app.composite_from_scores(scores) == 47

    def test_missing_keys_default_to_zero(self):
        # If the dict is missing a hazard, treat it as 0 (don't raise).
        scores = {"hurricane": 10}
        out = gad_app.composite_from_scores(scores)
        # Only hurricane (weight 0.20) contributes: 10*0.20/10 = 0.20 → 20.
        assert out == 20

    def test_output_always_in_range(self):
        # Even with an all-10s dict plus an extra unknown key, stay 0-100.
        scores = {k: 10 for k in gad_app.RISK_CATEGORIES}
        scores["meteor"] = 10  # ignored by the function
        out = gad_app.composite_from_scores(scores)
        assert 0 <= out <= 100


# ═══════════════ RISK_CATEGORIES sanity check ═══════════════════════════════


def test_risk_category_weights_sum_to_one():
    """Composite formula assumes weights sum to 1.0 (max possible = 10).
    If anyone edits weights, this guards the invariant."""
    total = sum(c["weight"] for c in gad_app.RISK_CATEGORIES.values())
    assert abs(total - 1.0) < 1e-9, f"weights sum to {total}, expected 1.0"


# ═══════════════ alert_info_url ═════════════════════════════════════════════


class TestAlertInfoUrl:
    """Maps NWS alert event names to weather.gov safety pages so the Alerts
    tab can deep-link. Substring matching with order-sensitive precedence."""

    def test_empty_inputs_return_none(self):
        assert gad_app.alert_info_url("") is None
        assert gad_app.alert_info_url(None) is None

    def test_tornado_routes_to_tornado_safety(self):
        assert gad_app.alert_info_url("Tornado Warning") == \
            "https://www.weather.gov/safety/tornado"
        assert gad_app.alert_info_url("Tornado Watch") == \
            "https://www.weather.gov/safety/tornado"

    def test_hurricane_and_tropical_route_to_hurricane(self):
        assert gad_app.alert_info_url("Hurricane Warning") == \
            "https://www.weather.gov/safety/hurricane"
        assert gad_app.alert_info_url("Tropical Storm Watch") == \
            "https://www.weather.gov/safety/hurricane"
        assert gad_app.alert_info_url("Storm Surge Warning") == \
            "https://www.weather.gov/safety/hurricane"

    def test_flood_variants_route_to_flood(self):
        for name in [
            "Flood Warning", "Flash Flood Warning",
            "Coastal Flood Advisory", "River Flood Watch",
        ]:
            assert gad_app.alert_info_url(name) == \
                "https://www.weather.gov/safety/flood", name

    def test_winter_variants_route_to_winter(self):
        for name in ["Winter Storm Warning", "Blizzard Warning",
                     "Ice Storm Warning", "Heavy Snow Warning"]:
            assert gad_app.alert_info_url(name) == \
                "https://www.weather.gov/safety/winter", name

    def test_heat_routes_to_heat(self):
        assert gad_app.alert_info_url("Heat Advisory") == \
            "https://www.weather.gov/safety/heat"
        assert gad_app.alert_info_url("Excessive Heat Warning") == \
            "https://www.weather.gov/safety/heat"

    def test_wind_chill_resolves_to_cold_not_wind(self):
        """Substring precedence: 'wind chill' contains both 'wind' and
        'chill', but it's a cold-weather hazard. Must hit /safety/cold,
        not /safety/wind."""
        assert gad_app.alert_info_url("Wind Chill Warning") == \
            "https://www.weather.gov/safety/cold"
        assert gad_app.alert_info_url("Wind Chill Advisory") == \
            "https://www.weather.gov/safety/cold"

    def test_high_wind_routes_to_wind(self):
        assert gad_app.alert_info_url("High Wind Warning") == \
            "https://www.weather.gov/safety/wind"
        assert gad_app.alert_info_url("Wind Advisory") == \
            "https://www.weather.gov/safety/wind"

    def test_fire_weather_routes_to_wildfire(self):
        assert gad_app.alert_info_url("Fire Weather Watch") == \
            "https://www.weather.gov/safety/wildfire"
        assert gad_app.alert_info_url("Red Flag Warning") == \
            "https://www.weather.gov/safety/wildfire"

    def test_thunderstorm_and_lightning(self):
        assert gad_app.alert_info_url("Severe Thunderstorm Warning") == \
            "https://www.weather.gov/safety/thunderstorm"

    def test_air_quality_and_smoke(self):
        assert gad_app.alert_info_url("Air Quality Alert") == \
            "https://www.weather.gov/safety/airquality"
        assert gad_app.alert_info_url("Dense Smoke Advisory") == \
            "https://www.weather.gov/safety/airquality"

    def test_tsunami_routes_to_tsunami(self):
        assert gad_app.alert_info_url("Tsunami Warning") == \
            "https://www.weather.gov/safety/tsunami"

    def test_unknown_event_falls_back_to_alerts_overview(self):
        """Anything we don't recognize lands on the general /alerts page
        rather than 404'ing the link."""
        assert gad_app.alert_info_url("Mystery Event") == \
            "https://www.weather.gov/alerts"
        assert gad_app.alert_info_url("Special Marine Statement") == \
            "https://www.weather.gov/alerts"

    def test_case_insensitivity(self):
        assert gad_app.alert_info_url("TORNADO WARNING") == \
            "https://www.weather.gov/safety/tornado"
        assert gad_app.alert_info_url("hurricane watch") == \
            "https://www.weather.gov/safety/hurricane"
