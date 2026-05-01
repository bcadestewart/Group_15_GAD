"""
GAD — Geospatial Architecture Database
Flask backend exposing weather, risk, history, and export endpoints.

All static reference data (state hazard profiles, IECC zones, building
codes, historical events, decadal trends, risk categories, construction
tips) lives in a SQLite database accessed via the SQLAlchemy ORM. The
canonical Python representation is in `db/seed_data.py`; the schema is in
`db/models.py`; the seed loader is `db/seed.py`. `init_db()` creates and
seeds the DB on first import (idempotent), so a fresh checkout boots
end-to-end without any extra setup steps.
"""
import io
import math
import os
import sys
from datetime import datetime
from pathlib import Path

import requests
from flask import Flask, jsonify, request, send_file
from sqlalchemy import or_, select

# Make `db` importable when running `python3 backend/app.py` from any
# working directory (the repo root, or backend/).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from db import get_session, init_db  # noqa: E402
from db.models import (  # noqa: E402
    Analysis,
    DecadalTrend,
    HistoricalEvent,
    State,
)

# Re-exported here so tests and the PDF export path can keep accessing
# `RISK_CATEGORIES` / `CONSTRUCTION_TIPS` as module-level dicts. They're
# the same constants that seed the database, so the in-memory shape is
# guaranteed to match the database content.
from db.seed_data import (  # noqa: E402
    CONSTRUCTION_TIPS,
    DEFAULT_PROFILE,
    DEFAULT_TRENDS,
    RISK_CATEGORIES,
)

app = Flask(__name__, static_folder='../frontend', static_url_path='/')

# Create tables and seed reference data on first boot. Subsequent calls
# are no-ops (the seed loader checks for existing rows). Tests override
# the DB URL via the GAD_DATABASE_URL env var before this module is
# imported.
init_db()



HEADERS = {"User-Agent": "GAD/1.0 (cs4398@group15.com)"}


# ═══════════════ UTILITIES ════════════════════════════════════════════════════

def normalize_state(s):
    """Accept either '2-letter code' or 'Full State Name' → 2-letter code (or '').
    Resolves via the database (states table) so this respects whatever data the
    seed loader populated, including DC and any future additions."""
    if not s:
        return ''
    s = s.strip()
    with get_session() as db:
        row = db.scalar(
            select(State.code).where(or_(
                State.code == s.upper(),
                State.full_name == s,
            ))
        )
        return row or ''


def jitter(score, lat, lon):
    """Apply small location-based variation to a state-level score."""
    seed = abs(math.sin(lat * 12.9898 + lon * 78.233)) % 1
    return max(0, min(10, score + round((seed - 0.5) * 2)))


def composite_from_scores(scores):
    """Weighted composite 0–100 from per-hazard scores."""
    total = sum(scores.get(k, 0) * RISK_CATEGORIES[k]['weight'] for k in RISK_CATEGORIES)
    # max possible: sum(10 * weight) = 10 * sum(weights). normalize → 0-100.
    max_possible = 10 * sum(c['weight'] for c in RISK_CATEGORIES.values())
    return max(0, min(100, round(total / max_possible * 100)))


# ─── NWS event-name → safety/info-page URL mapping ──────────────────────────
# Maps an NWS alert event name (e.g. "Coastal Flood Advisory", "Tornado
# Warning") to the corresponding NWS safety/info page so the frontend can
# render the alert as a deep-link. Order is significant — more specific
# substrings are checked first (e.g. "wind chill" → cold, not "wind").
ALERT_INFO_FALLBACK = 'https://www.weather.gov/alerts'

_ALERT_RULES = (
    # (substring, safety URL)
    ('tornado',        'https://www.weather.gov/safety/tornado'),
    ('tsunami',        'https://www.weather.gov/safety/tsunami'),
    ('hurricane',      'https://www.weather.gov/safety/hurricane'),
    ('tropical',       'https://www.weather.gov/safety/hurricane'),
    ('typhoon',        'https://www.weather.gov/safety/hurricane'),
    ('storm surge',    'https://www.weather.gov/safety/hurricane'),
    ('flood',          'https://www.weather.gov/safety/flood'),
    ('thunder',        'https://www.weather.gov/safety/thunderstorm'),
    ('lightning',      'https://www.weather.gov/safety/lightning'),
    ('hail',           'https://www.weather.gov/safety/thunderstorm'),
    ('fire weather',   'https://www.weather.gov/safety/wildfire'),
    ('red flag',       'https://www.weather.gov/safety/wildfire'),
    ('wildfire',       'https://www.weather.gov/safety/wildfire'),
    ('smoke',          'https://www.weather.gov/safety/airquality'),
    ('air quality',    'https://www.weather.gov/safety/airquality'),
    ('excessive heat', 'https://www.weather.gov/safety/heat'),
    ('heat',           'https://www.weather.gov/safety/heat'),
    ('wind chill',     'https://www.weather.gov/safety/cold'),
    ('cold',           'https://www.weather.gov/safety/cold'),
    ('freeze',         'https://www.weather.gov/safety/cold'),
    ('frost',          'https://www.weather.gov/safety/cold'),
    ('blizzard',       'https://www.weather.gov/safety/winter'),
    ('winter',         'https://www.weather.gov/safety/winter'),
    ('snow',           'https://www.weather.gov/safety/winter'),
    ('ice storm',      'https://www.weather.gov/safety/winter'),
    ('sleet',          'https://www.weather.gov/safety/winter'),
    ('high wind',      'https://www.weather.gov/safety/wind'),
    ('wind',           'https://www.weather.gov/safety/wind'),
    ('fog',            'https://www.weather.gov/safety/fog'),
    ('rip current',    'https://www.weather.gov/safety/ripcurrent'),
    ('beach hazard',   'https://www.weather.gov/safety/ripcurrent'),
    ('surf',           'https://www.weather.gov/safety/ripcurrent'),
)


def alert_info_url(event_name):
    """Return an NWS safety/info-page URL for a given alert event type, or
    the general /alerts page as a fallback. Returns None for empty input."""
    if not event_name:
        return None
    e = event_name.lower()
    for needle, url in _ALERT_RULES:
        if needle in e:
            return url
    return ALERT_INFO_FALLBACK


def _record_analysis(lat, lon, state, composite, alert_count):
    """Insert one Analysis row recording the metadata of a /api/weather
    call. SRS §3.6 — anonymous metadata only, no PII per §4.4.

    This is intentionally best-effort: any DB error is swallowed so a
    failure to log can never break the user's analysis. Caller does not
    need to wrap this in its own try/except.
    """
    try:
        with get_session() as db:
            db.add(Analysis(
                lat=lat,
                lon=lon,
                state=state or None,  # nullable — NWS sometimes can't resolve
                composite=int(composite),
                alert_count=int(alert_count),
            ))
            db.commit()
    except Exception:
        # Don't surface logging failures to the user. In a future PR with
        # structured logging set up, emit a warning here.
        pass


# ═══════════════ ROUTES ═════════════════════════════════════════════════════

@app.route('/')
def index():
    return app.send_static_file('index.html')


@app.route('/api/search')
def search():
    q = request.args.get('q', '').strip()
    if len(q) < 3:
        return jsonify([])
    try:
        url = f"https://nominatim.openstreetmap.org/search?format=json&q={requests.utils.quote(q)}&limit=5&countrycodes=us"
        resp = requests.get(url, headers=HEADERS, timeout=8).json()
        return jsonify([
            {'lat': float(x['lat']), 'lon': float(x['lon']), 'display': x['display_name']}
            for x in resp
        ])
    except requests.exceptions.RequestException as e:
        return jsonify({'error': f'Geocoding service unavailable: {e}'}), 503


@app.route('/api/weather')
def weather():
    lat = request.args.get('lat', type=float)
    lon = request.args.get('lon', type=float)
    if lat is None or lon is None:
        return jsonify({'error': 'Missing coordinates'}), 400

    try:
        # NWS Point API
        point_res = requests.get(f"https://api.weather.gov/points/{lat},{lon}",
                                 headers=HEADERS, timeout=8)
        if not point_res.ok:
            return jsonify({'error': 'Location not supported by NWS — only US locations are supported.'}), 404

        props = point_res.json().get('properties', {})
        forecast_url = props.get('forecast')
        state = props.get('relativeLocation', {}).get('properties', {}).get('state', '')

        # Fallback state via reverse geocoding (returns full state name)
        if not state:
            try:
                rev = requests.get(
                    f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}",
                    headers=HEADERS, timeout=6
                ).json()
                state = rev.get('address', {}).get('state', '')
            except requests.exceptions.RequestException:
                pass
        state = normalize_state(state)

        # Forecast
        forecasts, obs = [], {}
        if forecast_url:
            f_res = requests.get(forecast_url, headers=HEADERS, timeout=8)
            if f_res.ok:
                periods = f_res.json().get('properties', {}).get('periods', [])
                forecasts = [{
                    'name': p['name'],
                    'temperature': p['temperature'],
                    'temperatureUnit': p['temperatureUnit'],
                    'shortForecast': p['shortForecast']
                } for p in periods[:14]]
                if periods:
                    obs = {
                        'temperature': periods[0]['temperature'],
                        'windSpeed': periods[0]['windSpeed'],
                        'humidity': 'N/A',
                        'conditions': periods[0]['shortForecast']
                    }

        # Active alerts
        alerts = []
        if state:
            a_res = requests.get(f"https://api.weather.gov/alerts/active?area={state}",
                                 headers=HEADERS, timeout=8)
            if a_res.ok:
                for f in a_res.json().get('features', []):
                    ap = f.get('properties', {})
                    alerts.append({
                        'event': ap.get('event'),
                        'severity': ap.get('severity'),
                        'headline': ap.get('headline'),
                        'url': alert_info_url(ap.get('event')),
                    })

        # Risk scores: pull the per-state profile + climate zone + building
        # code from the database in a single query. Falls back to the
        # default profile / labels when the state is unknown.
        with get_session() as db:
            state_row = db.get(State, state) if state else None
        if state_row:
            profile = state_row.profile_dict()
            climate_zone = state_row.iecc_zone
            building_code_label = state_row.building_code
        else:
            profile = DEFAULT_PROFILE
            climate_zone = 'N/A'
            building_code_label = 'Consult local jurisdiction'

        scores = {k: jitter(profile.get(k, DEFAULT_PROFILE.get(k, 0)), lat, lon)
                  for k in RISK_CATEGORIES}
        composite = composite_from_scores(scores)

        # ── Audit log (SRS §3.6) — best-effort write so a transient DB
        # error never breaks the user-facing analysis. No PII is stored;
        # see the Analysis model docstring for the §4.4 rationale.
        _record_analysis(lat, lon, state, composite, len(alerts))

        return jsonify({
            'forecast':    forecasts,
            'alerts':      alerts,
            'scores':      scores,
            'composite':   composite,
            'observation': obs,
            'state':       state,
            'climateZone': climate_zone,
            'buildingCode': building_code_label,
        })

    except requests.exceptions.RequestException as e:
        return jsonify({'error': f'Weather service unavailable: {e}'}), 503
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/history')
def history():
    """Historical disaster events + decadal trend for a state.

    Queries the database (`historical_events` + `decadal_trends`) instead
    of in-memory dicts. Unknown states return empty events and the
    default decadal-trend baseline so the History tab chart still renders.
    """
    state = request.args.get('state', '').upper()
    with get_session() as db:
        events = db.scalars(
            select(HistoricalEvent)
            .where(HistoricalEvent.state_code == state)
            .order_by(HistoricalEvent.year.desc())
        ).all()
        trend_rows = db.scalars(
            select(DecadalTrend).where(DecadalTrend.state_code == state)
        ).all()

    trends = {r.decade: r.count for r in trend_rows} if trend_rows else DEFAULT_TRENDS
    return jsonify({
        'events': [ev.to_dict() for ev in events],
        'trends': trends,
        'state':  state,
    })


@app.route('/api/export', methods=['POST'])
def export():
    """Generate a styled PDF report from a payload of analysis data."""
    data = request.get_json(force=True)
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import LETTER
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import (
            PageBreak,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError:
        return jsonify({'error': 'reportlab not installed. Run: pip install reportlab'}), 500

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=LETTER,
                            rightMargin=0.75 * inch, leftMargin=0.75 * inch,
                            topMargin=0.75 * inch, bottomMargin=0.75 * inch)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', parent=styles['Title'],
                                 fontSize=22, textColor=colors.HexColor('#0f172a'),
                                 spaceAfter=4)
    sub_style = ParagraphStyle('Sub', parent=styles['Normal'],
                               fontSize=10, textColor=colors.HexColor('#64748b'),
                               spaceAfter=18)
    h2_style = ParagraphStyle('H2', parent=styles['Heading2'],
                              fontSize=14, textColor=colors.HexColor('#0f172a'),
                              spaceBefore=14, spaceAfter=6)
    body_style = ParagraphStyle('Body', parent=styles['Normal'],
                                fontSize=10, textColor=colors.HexColor('#1f2937'),
                                leading=14)

    story = []
    story.append(Paragraph('Geospatial Architecture Database — Site Report', title_style))
    story.append(Paragraph(
        f"<b>Location:</b> {data.get('display','—')}<br/>"
        f"<b>Coordinates:</b> {data.get('lat','—')}, {data.get('lon','—')}<br/>"
        f"<b>Generated:</b> {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        sub_style))

    # Composite + climate zone summary
    story.append(Paragraph('Site Summary', h2_style))
    summary_data = [
        ['Composite Risk Score', f"{data.get('composite','—')}/100"],
        ['IECC Climate Zone',    data.get('climateZone', '—')],
        ['Building Code',        data.get('buildingCode', '—')],
        ['State',                data.get('state', '—')],
    ]
    t = Table(summary_data, colWidths=[2.5 * inch, 4 * inch])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f1f5f9')),
        ('TEXTCOLOR',  (0, 0), (-1, -1), colors.HexColor('#0f172a')),
        ('GRID',       (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
        ('PADDING',    (0, 0), (-1, -1), 8),
        ('FONTNAME',   (0, 0), (0, -1), 'Helvetica-Bold'),
    ]))
    story.append(t)

    # Risk table
    story.append(Paragraph('Hazard Assessment', h2_style))
    rows = [['Category', 'Score (0-10)', 'Weight']]
    for k, v in RISK_CATEGORIES.items():
        rows.append([v['label'], str(data.get('scores', {}).get(k, '—')),
                     f"{int(v['weight']*100)}%"])
    t = Table(rows, colWidths=[3 * inch, 1.5 * inch, 1.5 * inch])
    t.setStyle(TableStyle([
        ('BACKGROUND',   (0, 0), (-1, 0), colors.HexColor('#0f172a')),
        ('TEXTCOLOR',    (0, 0), (-1, 0), colors.white),
        ('FONTNAME',     (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID',         (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
        ('PADDING',      (0, 0), (-1, -1), 6),
    ]))
    story.append(t)

    # Recommendations
    story.append(PageBreak())
    story.append(Paragraph('Construction Recommendations', h2_style))
    scores = data.get('scores', {})
    active = [k for k in RISK_CATEGORIES if scores.get(k, 0) >= 3]
    active.sort(key=lambda k: -scores[k])
    if not active:
        story.append(Paragraph('All risk categories below threshold. Standard construction practices apply.', body_style))
    else:
        for k in active:
            story.append(Paragraph(
                f"<b>{RISK_CATEGORIES[k]['label']}</b> "
                f"<font color='#64748b'>(Risk: {scores[k]}/10)</font>", h2_style))
            for tip in CONSTRUCTION_TIPS.get(k, []):
                story.append(Paragraph(f"• {tip}", body_style))

    # Forecast
    forecast = data.get('forecast', [])
    if forecast:
        story.append(Spacer(1, 0.2 * inch))
        story.append(Paragraph('7-Day Forecast', h2_style))
        rows = [['Period', 'Temp', 'Conditions']]
        for p in forecast:
            rows.append([p['name'],
                         f"{p['temperature']}°{p['temperatureUnit']}",
                         p['shortForecast']])
        t = Table(rows, colWidths=[1.5 * inch, 1 * inch, 3.5 * inch])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f172a')),
            ('TEXTCOLOR',  (0, 0), (-1, 0), colors.white),
            ('FONTNAME',   (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID',       (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
            ('PADDING',    (0, 0), (-1, -1), 5),
            ('FONTSIZE',   (0, 0), (-1, -1), 9),
        ]))
        story.append(t)

    # Disclaimer
    story.append(Spacer(1, 0.3 * inch))
    story.append(Paragraph(
        '<i>Disclaimer: This report is advisory. Always consult local building codes, '
        'a licensed structural engineer, and relevant FEMA / ICC standards before construction.</i>',
        ParagraphStyle('Disc', parent=body_style, fontSize=9,
                       textColor=colors.HexColor('#64748b'))))

    doc.build(story)
    buf.seek(0)
    fname = f"GAD_Report_{datetime.utcnow().strftime('%Y%m%d')}.pdf"
    return send_file(buf, mimetype='application/pdf',
                     as_attachment=True, download_name=fname)


@app.route('/api/analyses/recent')
def analyses_recent():
    """Paginated list of recent /api/weather analyses (SRS §3.6).

    Query params:
        limit  — page size, default 20, capped at 100
        offset — number of rows to skip, default 0

    Response:
        {
            "items": [{...analysis...}, ...],
            "total": <int>,
            "limit": <int>,
            "offset": <int>
        }
    """
    from sqlalchemy import func
    try:
        limit = max(1, min(100, int(request.args.get('limit', 20))))
    except (TypeError, ValueError):
        limit = 20
    try:
        offset = max(0, int(request.args.get('offset', 0)))
    except (TypeError, ValueError):
        offset = 0

    with get_session() as db:
        total = db.scalar(select(func.count()).select_from(Analysis)) or 0
        rows = db.scalars(
            select(Analysis)
            .order_by(Analysis.created_at.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        items = [r.to_dict() for r in rows]

    return jsonify({
        'items': items,
        'total': total,
        'limit': limit,
        'offset': offset,
    })


@app.route('/api/analyses/stats')
def analyses_stats():
    """Aggregate statistics over the analyses table (SRS §3.6).

    Response:
        {
            "total":   <int>,                          # all-time count
            "last24h": <int>,                          # rolling 24h
            "byState": {"FL": 12, "TX": 8, ...},       # all-time per state
            "byDay":   {"2026-04-30": 5, ...}          # last 14 days
        }
    """
    from datetime import timedelta

    from sqlalchemy import func

    with get_session() as db:
        total = db.scalar(select(func.count()).select_from(Analysis)) or 0

        cutoff_24h = _utcnow_naive() - timedelta(hours=24)
        last_24h = db.scalar(
            select(func.count()).select_from(Analysis)
            .where(Analysis.created_at >= cutoff_24h)
        ) or 0

        by_state_rows = db.execute(
            select(Analysis.state, func.count(Analysis.id))
            .where(Analysis.state.is_not(None))
            .group_by(Analysis.state)
        ).all()
        by_state = {state: count for state, count in by_state_rows}

        cutoff_14d = _utcnow_naive() - timedelta(days=14)
        # SQLite-compatible day grouping: format as YYYY-MM-DD via strftime.
        day_expr = func.strftime('%Y-%m-%d', Analysis.created_at)
        by_day_rows = db.execute(
            select(day_expr, func.count(Analysis.id))
            .where(Analysis.created_at >= cutoff_14d)
            .group_by(day_expr)
            .order_by(day_expr)
        ).all()
        by_day = {day: count for day, count in by_day_rows}

    return jsonify({
        'total':   total,
        'last24h': last_24h,
        'byState': by_state,
        'byDay':   by_day,
    })


def _utcnow_naive():
    """Naive UTC `datetime.now()` matching the storage convention used by
    the Analysis model (SQLite has no native tzinfo support; we store
    wall-clock UTC). Local helper to keep the analyses_stats query free
    of inline imports."""
    return datetime.utcnow()


@app.route('/api/health')
def health():
    return jsonify({'status': 'ok', 'time': datetime.utcnow().isoformat()})


if __name__ == '__main__':
    # Default to 5001 because macOS AirPlay Receiver claims 5000.
    # Override with `PORT=xxxx python3 app.py` if you need a different port.
    port = int(os.environ.get('PORT', 5001))
    app.run(debug=True, port=port)
