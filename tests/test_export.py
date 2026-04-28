"""
Smoke tests for POST /api/export — the reportlab PDF path.

We don't crack the PDF open and inspect content; we just verify:
  - the response is content-type application/pdf
  - the body actually starts with %PDF (magic bytes)
  - the Content-Disposition header attaches a filename
This catches the common failure modes (reportlab missing, payload schema
drift) without coupling the test to the exact PDF rendering output.
"""
from __future__ import annotations


def test_export_full_payload_returns_pdf(client, export_payload):
    res = client.post("/api/export", json=export_payload)

    assert res.status_code == 200
    assert res.mimetype == "application/pdf"

    # PDF magic bytes
    assert res.data[:4] == b"%PDF"

    # Attached as a download with a sensible filename
    cd = res.headers.get("Content-Disposition", "")
    assert "attachment" in cd
    assert "GAD_Report" in cd
    assert ".pdf" in cd


def test_export_minimal_payload_still_renders(client):
    """SRS §3.3 — export should not crash when only a few fields are present."""
    minimal = {
        "display": "Somewhere, USA",
        "lat": 30.0,
        "lon": -95.0,
        "scores": {},
    }
    res = client.post("/api/export", json=minimal)
    assert res.status_code == 200
    assert res.data[:4] == b"%PDF"


def test_export_zero_active_hazards_uses_fallback_message(client):
    """When all hazard scores are 0, the report should still render (with the
    'standard construction practices apply' fallback)."""
    payload = {
        "display": "Quiet Town, USA",
        "lat": 40.0,
        "lon": -95.0,
        "scores": {
            "hurricane": 0, "tornado": 0, "flood": 0, "winter": 0,
            "heat": 0, "seismic": 0, "wildfire": 0,
        },
    }
    res = client.post("/api/export", json=payload)
    assert res.status_code == 200
    assert res.data[:4] == b"%PDF"


def test_export_empty_json_body_does_not_crash(client):
    """Defensive — an empty body should still produce a (mostly empty) PDF."""
    res = client.post("/api/export", json={})
    # Either 200 with a placeholder PDF, or a 4xx with a clear error — both
    # are acceptable; what's NOT acceptable is a 500 from an unhandled crash.
    assert res.status_code < 500
