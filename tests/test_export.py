"""
Smoke tests for POST /api/export — both the reportlab PDF path and the
server-side CSV path (SRS §3.3 requires PDF and CSV).

We don't crack the PDF open and inspect content; we just verify:
  - the response is content-type application/pdf
  - the body actually starts with %PDF (magic bytes)
  - the Content-Disposition header attaches a filename
This catches the common failure modes (reportlab missing, payload schema
drift) without coupling the test to the exact PDF rendering output.

The CSV tests check section markers (=== COMPOSITE RISK ===, etc.) and
that quoting handles values with embedded commas and quotes correctly,
since the previous client-side implementation hand-rolled quoting and
broke on display names like "Tampa, FL".
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


# ─── CSV path (SRS §3.3) ────────────────────────────────────────────────────


def test_export_csv_full_payload(client, export_payload):
    """Happy path — full payload, format chosen via the query string."""
    res = client.post("/api/export?format=csv", json=export_payload)

    assert res.status_code == 200
    assert res.mimetype == "text/csv"

    body = res.data.decode("utf-8")
    # Header + every section banner the PDF carries
    assert "Geospatial Architecture Database" in body
    assert "=== COMPOSITE RISK ===" in body
    assert "=== HAZARD ASSESSMENT ===" in body
    assert "=== 7-DAY FORECAST ===" in body
    assert "=== ACTIVE ALERTS ===" in body
    assert "=== CONSTRUCTION RECOMMENDATIONS ===" in body

    # Filename + Content-Disposition
    cd = res.headers.get("Content-Disposition", "")
    assert "attachment" in cd
    assert "GAD_Report" in cd
    assert ".csv" in cd


def test_export_csv_format_in_body(client, export_payload):
    """`format` may be passed in the JSON body instead of the query string."""
    payload = {**export_payload, "format": "csv"}
    res = client.post("/api/export", json=payload)

    assert res.status_code == 200
    assert res.mimetype == "text/csv"
    assert b"COMPOSITE RISK" in res.data


def test_export_csv_minimal_payload(client):
    """SRS §3.3 — CSV export should not crash on a minimal payload."""
    minimal = {
        "display": "Somewhere, USA",
        "lat": 30.0,
        "lon": -95.0,
        "scores": {},
    }
    res = client.post("/api/export?format=csv", json=minimal)

    assert res.status_code == 200
    assert res.mimetype == "text/csv"
    body = res.data.decode("utf-8")
    # Fallback recommendation message when no hazards meet threshold
    assert "Standard construction practices apply" in body


def test_export_csv_quotes_embedded_commas_and_quotes(client):
    """Display names like 'Tampa, FL' and headlines containing commas must
    be CSV-quoted by the writer — the prior client-side hand-rolled
    quoting broke on these and corrupted the column count."""
    payload = {
        "display": 'Tampa, "Bay Area", FL',
        "lat": 27.95,
        "lon": -82.46,
        "scores": {"hurricane": 9, "flood": 7},
        "alerts": [
            {
                "event": "Coastal Flood Advisory",
                "severity": "Moderate",
                "headline": 'Coastal Flood Advisory in effect, "high tide cycle"',
            }
        ],
    }
    res = client.post("/api/export?format=csv", json=payload)
    assert res.status_code == 200

    body = res.data.decode("utf-8")
    # The display name should round-trip verbatim through the CSV writer's
    # double-quote escaping ("" inside a quoted field).
    assert '"Tampa, ""Bay Area"", FL"' in body
    # And the alert headline should likewise be properly escaped.
    assert '"Coastal Flood Advisory in effect, ""high tide cycle"""' in body


def test_export_csv_active_alerts_fallback(client, export_payload):
    """When the payload carries no alerts, CSV must still render the
    'None' row so the section is never silently empty."""
    payload = {**export_payload}
    payload.pop("alerts", None)
    res = client.post("/api/export?format=csv", json=payload)
    assert res.status_code == 200

    # Find the "ACTIVE ALERTS" section and check the row beneath the header.
    lines = res.data.decode("utf-8").splitlines()
    idx = next(i for i, line in enumerate(lines) if "=== ACTIVE ALERTS ===" in line)
    # idx     -> banner
    # idx + 1 -> column header (Event,Severity,Headline)
    # idx + 2 -> "None,," fallback
    assert lines[idx + 2].startswith("None")


def test_export_unknown_format_returns_400(client, export_payload):
    """Bug-prevention — a typo in the format param should fail loudly."""
    res = client.post("/api/export?format=xml", json=export_payload)
    assert res.status_code == 400

    err = res.get_json()
    assert err and "format" in err.get("error", "").lower()


def test_export_default_format_is_pdf(client, export_payload):
    """Backward-compat — callers that don't pass a format still get PDF."""
    res = client.post("/api/export", json=export_payload)
    assert res.status_code == 200
    assert res.mimetype == "application/pdf"
