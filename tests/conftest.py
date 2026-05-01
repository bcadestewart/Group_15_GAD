"""
Shared pytest fixtures for the GAD test suite.

Imports the Flask app from backend/app.py and provides a test client.
External HTTP calls (NWS, Nominatim) are stubbed via pytest-mock in
individual tests — never let CI hit real APIs.

Database isolation: the test suite uses an in-memory SQLite database
(via the GAD_DATABASE_URL env var, set BEFORE backend/app.py is imported
so its module-level init_db() call targets the in-memory DB). Each
session gets a freshly seeded copy.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Make `backend/` importable so `import app` works from anywhere.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

# Point at an in-memory SQLite *before* importing the app (whose module
# load calls init_db() against whatever URL is configured at that moment).
os.environ.setdefault("GAD_DATABASE_URL", "sqlite:///:memory:")

import app as gad_app  # noqa: E402 — sys.path setup must precede import


@pytest.fixture(autouse=True)
def _isolate_weather_cache():
    """Clear the in-process /api/weather TTL cache between tests so a
    cached entry from one test never silently turns into a "skip the
    mock" cache hit in the next."""
    gad_app.weather_cache.clear()
    yield
    gad_app.weather_cache.clear()


@pytest.fixture
def app():
    """Flask app in testing mode."""
    gad_app.app.config.update(TESTING=True)
    return gad_app.app


@pytest.fixture
def client(app):
    """Werkzeug test client for HTTP-level assertions."""
    return app.test_client()


# ─── Reusable fake upstream payloads ────────────────────────────────────────


@pytest.fixture
def nominatim_search_payload():
    """A representative response from Nominatim /search."""
    return [
        {
            "lat": "27.9506",
            "lon": "-82.4572",
            "display_name": "Tampa, Hillsborough County, Florida, USA",
        },
        {
            "lat": "27.9659",
            "lon": "-82.8001",
            "display_name": "Clearwater, Pinellas County, Florida, USA",
        },
    ]


@pytest.fixture
def nws_point_payload():
    """A representative response from NWS /points/{lat,lon}."""
    return {
        "properties": {
            "forecast": "https://api.weather.gov/gridpoints/TBW/52,68/forecast",
            "relativeLocation": {
                "properties": {"city": "Tampa", "state": "FL"},
            },
        }
    }


@pytest.fixture
def nws_forecast_payload():
    """A representative response from NWS forecast endpoint."""
    return {
        "properties": {
            "periods": [
                {
                    "name": "Tonight",
                    "temperature": 72,
                    "temperatureUnit": "F",
                    "windSpeed": "10 mph",
                    "shortForecast": "Mostly Clear",
                },
                {
                    "name": "Tuesday",
                    "temperature": 84,
                    "temperatureUnit": "F",
                    "windSpeed": "8 mph",
                    "shortForecast": "Sunny",
                },
            ]
        }
    }


@pytest.fixture
def nws_alerts_payload():
    """A representative response from NWS /alerts/active."""
    return {
        "features": [
            {
                "properties": {
                    "event": "Coastal Flood Advisory",
                    "severity": "Moderate",
                    "headline": "Coastal Flood Advisory in effect until 11 AM EST.",
                }
            }
        ]
    }


@pytest.fixture
def export_payload():
    """A complete payload to POST to /api/export."""
    return {
        "display": "Tampa, FL, USA",
        "lat": 27.9506,
        "lon": -82.4572,
        "state": "FL",
        "composite": 64,
        "climateZone": "1/2",
        "buildingCode": "FBC 2023 (IBC-based)",
        "scores": {
            "hurricane": 9,
            "tornado": 4,
            "flood": 7,
            "winter": 0,
            "heat": 7,
            "seismic": 0,
            "wildfire": 4,
        },
        "forecast": [
            {
                "name": "Tonight",
                "temperature": 72,
                "temperatureUnit": "F",
                "shortForecast": "Mostly Clear",
            }
        ],
    }


# ─── Helper for stubbing requests.get ───────────────────────────────────────


class _FakeResponse:
    """Minimal stand-in for requests.Response used in route tests."""

    def __init__(self, *, json_data=None, status_code=200, ok=True):
        self._json = json_data if json_data is not None else {}
        self.status_code = status_code
        self.ok = ok

    def json(self):
        return self._json


@pytest.fixture
def fake_response():
    """Factory for FakeResponse — keeps tests terse."""
    return _FakeResponse
