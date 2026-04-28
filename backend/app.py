"""
GAD — Geospatial Architecture Database
Flask backend exposing weather, risk, history, and export endpoints.
"""
import io
import math
import os
from datetime import datetime

import requests
from flask import Flask, jsonify, request, send_file

app = Flask(__name__, static_folder='../frontend', static_url_path='/')

# ─── Risk categories with weights for composite score ───────────────────────
RISK_CATEGORIES = {
    'hurricane': {'label': 'Hurricane / Tropical Storm', 'weight': 0.20, 'icon': '🌀'},
    'tornado':   {'label': 'Tornado',                    'weight': 0.18, 'icon': '🌪️'},
    'flood':     {'label': 'Flooding',                   'weight': 0.15, 'icon': '🌊'},
    'winter':    {'label': 'Winter Storm / Ice',         'weight': 0.12, 'icon': '❄️'},
    'heat':      {'label': 'Extreme Heat',               'weight': 0.10, 'icon': '🔥'},
    'seismic':   {'label': 'Seismic / Earthquake',       'weight': 0.15, 'icon': '⚡'},
    'wildfire':  {'label': 'Wildfire',                   'weight': 0.10, 'icon': '🔥'},
}

# ─── Construction tips per hazard ────────────────────────────────────────────
CONSTRUCTION_TIPS = {
    'hurricane': [
        "Use hurricane straps/clips to secure roof to walls",
        "Install impact-resistant windows or hurricane shutters",
        "Reinforce garage doors — primary failure point in hurricanes",
        "Elevate the foundation above the base flood elevation (BFE)",
        "Use concrete block or reinforced masonry for exterior walls",
    ],
    'tornado': [
        "Include a reinforced safe room (FEMA P-320 / ICC 500 compliant)",
        "Anchor the structure to a continuous foundation",
        "Use hip roofs instead of gable — better wind resistance",
        "Install continuous plywood sheathing on roof and walls",
        "Specify impact-rated exterior cladding and doors",
    ],
    'flood': [
        "Elevate the lowest floor at least 1 ft above BFE",
        "Use flood-resistant materials below the Design Flood Elevation",
        "Install backflow valves on all sewer and drain lines",
        "Grade the site to slope away from the building on all sides",
        "Avoid finished basements in high-risk flood zones",
    ],
    'winter': [
        "Design roof for regional snow load per ASCE 7",
        "Insulate to or above IECC climate-zone requirements",
        "Install heat cables along eaves and gutters to prevent ice dams",
        "Use frost-protected shallow foundations in cold climates",
        "Specify freeze-resistant exterior plumbing and hose bibs",
    ],
    'heat': [
        "Specify high Solar Reflectance Index (SRI) roofing materials",
        "Design generous overhangs and shading on south/west facades",
        "Use insulated concrete forms (ICFs) for high thermal mass",
        "Plan for oversized HVAC capacity with redundancy",
        "Install radiant barriers in the attic space",
    ],
    'seismic': [
        "Design to ASCE 7 seismic design category for the site class",
        "Use moment-resisting frames or shear walls per IBC requirements",
        "Anchor non-structural components (water heaters, HVAC, ducts)",
        "Specify base isolation or damping for high-importance structures",
        "Avoid soft-story configurations on the ground floor",
    ],
    'wildfire': [
        "Use Class A fire-rated roofing (metal, tile, or asphalt shingle)",
        "Install ember-resistant vents (1/8\" mesh) on attic and crawl spaces",
        "Specify non-combustible exterior siding (fiber cement, stucco, masonry)",
        "Maintain a 5-ft non-combustible zone around the structure",
        "Use tempered or dual-pane windows to resist heat exposure",
    ],
}

# ─── State-level hazard profiles (0–10 scale) ───────────────────────────────
# tornado typo on Georgia is FIXED (was 'tornado:' previously)
STATE_PROFILES = {
    'TX': {'hurricane': 6, 'tornado': 7, 'flood': 6, 'winter': 2, 'heat': 8, 'seismic': 1, 'wildfire': 5},
    'FL': {'hurricane': 9, 'tornado': 4, 'flood': 7, 'winter': 0, 'heat': 7, 'seismic': 0, 'wildfire': 4},
    'OK': {'hurricane': 0, 'tornado': 9, 'flood': 5, 'winter': 4, 'heat': 6, 'seismic': 4, 'wildfire': 4},
    'KS': {'hurricane': 0, 'tornado': 9, 'flood': 4, 'winter': 5, 'heat': 5, 'seismic': 1, 'wildfire': 3},
    'LA': {'hurricane': 8, 'tornado': 5, 'flood': 8, 'winter': 1, 'heat': 7, 'seismic': 0, 'wildfire': 2},
    'MS': {'hurricane': 6, 'tornado': 6, 'flood': 6, 'winter': 1, 'heat': 7, 'seismic': 1, 'wildfire': 3},
    'AL': {'hurricane': 5, 'tornado': 7, 'flood': 5, 'winter': 2, 'heat': 7, 'seismic': 1, 'wildfire': 3},
    'GA': {'hurricane': 3, 'tornado': 4, 'flood': 4, 'winter': 2, 'heat': 6, 'seismic': 1, 'wildfire': 4},
    'SC': {'hurricane': 5, 'tornado': 3, 'flood': 5, 'winter': 2, 'heat': 6, 'seismic': 2, 'wildfire': 4},
    'NC': {'hurricane': 5, 'tornado': 3, 'flood': 5, 'winter': 3, 'heat': 5, 'seismic': 1, 'wildfire': 4},
    'VA': {'hurricane': 3, 'tornado': 2, 'flood': 4, 'winter': 4, 'heat': 4, 'seismic': 1, 'wildfire': 3},
    'CA': {'hurricane': 0, 'tornado': 1, 'flood': 3, 'winter': 2, 'heat': 6, 'seismic': 9, 'wildfire': 9},
    'AZ': {'hurricane': 0, 'tornado': 1, 'flood': 3, 'winter': 1, 'heat': 10, 'seismic': 2, 'wildfire': 7},
    'NV': {'hurricane': 0, 'tornado': 0, 'flood': 2, 'winter': 2, 'heat': 9, 'seismic': 5, 'wildfire': 7},
    'NM': {'hurricane': 0, 'tornado': 2, 'flood': 3, 'winter': 3, 'heat': 7, 'seismic': 2, 'wildfire': 6},
    'CO': {'hurricane': 0, 'tornado': 4, 'flood': 3, 'winter': 7, 'heat': 3, 'seismic': 2, 'wildfire': 7},
    'MN': {'hurricane': 0, 'tornado': 4, 'flood': 4, 'winter': 9, 'heat': 2, 'seismic': 0, 'wildfire': 2},
    'WI': {'hurricane': 0, 'tornado': 3, 'flood': 4, 'winter': 8, 'heat': 2, 'seismic': 0, 'wildfire': 2},
    'MI': {'hurricane': 0, 'tornado': 3, 'flood': 4, 'winter': 8, 'heat': 2, 'seismic': 0, 'wildfire': 2},
    'NY': {'hurricane': 2, 'tornado': 2, 'flood': 4, 'winter': 7, 'heat': 3, 'seismic': 1, 'wildfire': 1},
    'ME': {'hurricane': 1, 'tornado': 1, 'flood': 3, 'winter': 9, 'heat': 1, 'seismic': 1, 'wildfire': 2},
    'MT': {'hurricane': 0, 'tornado': 2, 'flood': 3, 'winter': 8, 'heat': 2, 'seismic': 4, 'wildfire': 7},
    'WY': {'hurricane': 0, 'tornado': 2, 'flood': 2, 'winter': 8, 'heat': 2, 'seismic': 3, 'wildfire': 5},
    'ND': {'hurricane': 0, 'tornado': 4, 'flood': 4, 'winter': 9, 'heat': 2, 'seismic': 0, 'wildfire': 2},
    'SD': {'hurricane': 0, 'tornado': 5, 'flood': 4, 'winter': 8, 'heat': 3, 'seismic': 0, 'wildfire': 3},
    'NE': {'hurricane': 0, 'tornado': 7, 'flood': 4, 'winter': 6, 'heat': 4, 'seismic': 0, 'wildfire': 3},
    'IA': {'hurricane': 0, 'tornado': 6, 'flood': 5, 'winter': 7, 'heat': 3, 'seismic': 0, 'wildfire': 1},
    'MO': {'hurricane': 0, 'tornado': 6, 'flood': 5, 'winter': 5, 'heat': 5, 'seismic': 4, 'wildfire': 2},
    'AR': {'hurricane': 1, 'tornado': 6, 'flood': 5, 'winter': 3, 'heat': 6, 'seismic': 4, 'wildfire': 3},
    'TN': {'hurricane': 1, 'tornado': 5, 'flood': 5, 'winter': 3, 'heat': 5, 'seismic': 4, 'wildfire': 3},
    'IN': {'hurricane': 0, 'tornado': 5, 'flood': 4, 'winter': 6, 'heat': 3, 'seismic': 1, 'wildfire': 1},
    'IL': {'hurricane': 0, 'tornado': 6, 'flood': 5, 'winter': 6, 'heat': 4, 'seismic': 3, 'wildfire': 1},
    'OH': {'hurricane': 0, 'tornado': 3, 'flood': 4, 'winter': 6, 'heat': 3, 'seismic': 1, 'wildfire': 1},
    'PA': {'hurricane': 1, 'tornado': 2, 'flood': 4, 'winter': 6, 'heat': 3, 'seismic': 1, 'wildfire': 1},
    'WV': {'hurricane': 0, 'tornado': 2, 'flood': 5, 'winter': 6, 'heat': 3, 'seismic': 1, 'wildfire': 2},
    'KY': {'hurricane': 0, 'tornado': 4, 'flood': 5, 'winter': 4, 'heat': 4, 'seismic': 3, 'wildfire': 2},
    'MD': {'hurricane': 2, 'tornado': 2, 'flood': 4, 'winter': 5, 'heat': 4, 'seismic': 1, 'wildfire': 1},
    'DE': {'hurricane': 2, 'tornado': 1, 'flood': 4, 'winter': 4, 'heat': 4, 'seismic': 1, 'wildfire': 1},
    'NJ': {'hurricane': 2, 'tornado': 2, 'flood': 4, 'winter': 5, 'heat': 4, 'seismic': 1, 'wildfire': 2},
    'CT': {'hurricane': 2, 'tornado': 1, 'flood': 3, 'winter': 6, 'heat': 3, 'seismic': 1, 'wildfire': 1},
    'RI': {'hurricane': 2, 'tornado': 1, 'flood': 3, 'winter': 6, 'heat': 2, 'seismic': 1, 'wildfire': 1},
    'MA': {'hurricane': 2, 'tornado': 1, 'flood': 3, 'winter': 7, 'heat': 2, 'seismic': 1, 'wildfire': 1},
    'VT': {'hurricane': 1, 'tornado': 1, 'flood': 4, 'winter': 8, 'heat': 1, 'seismic': 1, 'wildfire': 1},
    'NH': {'hurricane': 1, 'tornado': 1, 'flood': 3, 'winter': 8, 'heat': 1, 'seismic': 1, 'wildfire': 1},
    'WA': {'hurricane': 0, 'tornado': 1, 'flood': 4, 'winter': 4, 'heat': 2, 'seismic': 8, 'wildfire': 7},
    'OR': {'hurricane': 0, 'tornado': 1, 'flood': 4, 'winter': 4, 'heat': 3, 'seismic': 7, 'wildfire': 8},
    'ID': {'hurricane': 0, 'tornado': 1, 'flood': 3, 'winter': 6, 'heat': 3, 'seismic': 4, 'wildfire': 6},
    'UT': {'hurricane': 0, 'tornado': 1, 'flood': 2, 'winter': 5, 'heat': 5, 'seismic': 5, 'wildfire': 5},
    'HI': {'hurricane': 3, 'tornado': 0, 'flood': 4, 'winter': 0, 'heat': 3, 'seismic': 6, 'wildfire': 4},
    'AK': {'hurricane': 0, 'tornado': 0, 'flood': 2, 'winter': 10, 'heat': 0, 'seismic': 9, 'wildfire': 4},
}
DEFAULT_PROFILE = {'hurricane': 2, 'tornado': 3, 'flood': 3, 'winter': 4, 'heat': 3, 'seismic': 2, 'wildfire': 3}

# ─── IECC climate zones (most common zone per state) ────────────────────────
IECC_ZONES = {
    'AK': '7/8', 'AL': '3', 'AR': '3/4', 'AZ': '2/3', 'CA': '3/4',
    'CO': '5/6', 'CT': '5', 'DE': '4', 'FL': '1/2', 'GA': '2/3',
    'HI': '1', 'IA': '5/6', 'ID': '5/6', 'IL': '4/5', 'IN': '4/5',
    'KS': '4/5', 'KY': '4', 'LA': '2/3', 'MA': '5', 'MD': '4',
    'ME': '6/7', 'MI': '5/6', 'MN': '6/7', 'MO': '4/5', 'MS': '3',
    'MT': '6/7', 'NC': '3/4', 'ND': '7', 'NE': '5', 'NH': '5/6',
    'NJ': '4/5', 'NM': '4/5', 'NV': '3/5', 'NY': '4/6', 'OH': '4/5',
    'OK': '3/4', 'OR': '4/5', 'PA': '4/5', 'RI': '5', 'SC': '3',
    'SD': '5/6', 'TN': '3/4', 'TX': '2/3', 'UT': '5/6', 'VA': '4',
    'VT': '6', 'WA': '4/5', 'WI': '6/7', 'WV': '4/5', 'WY': '6/7',
}

# ─── Currently adopted IBC code year per state (approximate) ────────────────
BUILDING_CODES = {
    'AK': 'IBC 2018', 'AL': 'IBC 2021', 'AR': 'IBC 2021', 'AZ': 'IBC 2018',
    'CA': 'CBC 2022 (IBC-based)', 'CO': 'IBC 2021', 'CT': 'IBC 2021',
    'DE': 'IBC 2018', 'FL': 'FBC 2023 (IBC-based)', 'GA': 'IBC 2018',
    'HI': 'IBC 2018', 'IA': 'IBC 2021', 'ID': 'IBC 2018', 'IL': 'IBC 2021',
    'IN': 'IBC 2014', 'KS': 'IBC 2018', 'KY': 'IBC 2018', 'LA': 'IBC 2021',
    'MA': 'IBC 2021', 'MD': 'IBC 2021', 'ME': 'IBC 2015', 'MI': 'IBC 2015',
    'MN': 'IBC 2018', 'MO': 'IBC 2018', 'MS': 'IBC 2018', 'MT': 'IBC 2021',
    'NC': 'IBC 2018', 'ND': 'IBC 2018', 'NE': 'IBC 2018', 'NH': 'IBC 2018',
    'NJ': 'IBC 2021', 'NM': 'IBC 2018', 'NV': 'IBC 2018', 'NY': 'IBC 2020',
    'OH': 'IBC 2017', 'OK': 'IBC 2018', 'OR': 'IBC 2021', 'PA': 'IBC 2018',
    'RI': 'IBC 2018', 'SC': 'IBC 2021', 'SD': 'IBC 2021', 'TN': 'IBC 2018',
    'TX': 'IBC 2021', 'UT': 'IBC 2021', 'VA': 'IBC 2021', 'VT': 'IBC 2018',
    'WA': 'IBC 2021', 'WI': 'IBC 2015', 'WV': 'IBC 2018', 'WY': 'IBC 2018',
}

# ─── Notable historical disasters (state-level highlights) ──────────────────
# Drawn from NOAA Storm Events / NWS records. Representative not exhaustive.
HISTORICAL_EVENTS = {
    'FL': [
        {'year': 1992, 'event': 'Hurricane Andrew', 'severity': 'Catastrophic',
         'note': 'Cat 5 landfall, $27B damage, drove major FBC reforms.'},
        {'year': 2017, 'event': 'Hurricane Irma',   'severity': 'Severe',
         'note': 'Cat 4 landfall in Florida Keys, statewide impact.'},
        {'year': 2022, 'event': 'Hurricane Ian',    'severity': 'Catastrophic',
         'note': 'Cat 4/5 landfall near Fort Myers, $113B damage.'},
    ],
    'TX': [
        {'year': 2017, 'event': 'Hurricane Harvey', 'severity': 'Catastrophic',
         'note': '60+ inches of rain in Houston, record US flood event.'},
        {'year': 2021, 'event': 'February Winter Storm', 'severity': 'Severe',
         'note': 'Statewide grid failure, $195B damage.'},
        {'year': 2013, 'event': 'Granbury / Cleburne Tornadoes', 'severity': 'Severe',
         'note': 'EF-4 tornadoes, 6 fatalities.'},
    ],
    'OK': [
        {'year': 2013, 'event': 'Moore Tornado', 'severity': 'Catastrophic',
         'note': 'EF-5, 24 fatalities, 1.3 mi wide damage path.'},
        {'year': 1999, 'event': 'Bridge Creek–Moore Tornado', 'severity': 'Catastrophic',
         'note': 'Highest wind speed on record (302 mph).'},
    ],
    'LA': [
        {'year': 2005, 'event': 'Hurricane Katrina', 'severity': 'Catastrophic',
         'note': '1,800 fatalities, levee failures in New Orleans.'},
        {'year': 2021, 'event': 'Hurricane Ida',     'severity': 'Severe',
         'note': 'Cat 4 landfall, widespread power loss for weeks.'},
    ],
    'CA': [
        {'year': 1994, 'event': 'Northridge Earthquake', 'severity': 'Catastrophic',
         'note': 'M6.7, 60 fatalities, $20B damage.'},
        {'year': 2018, 'event': 'Camp Fire', 'severity': 'Catastrophic',
         'note': 'Most destructive wildfire in CA history, 85 fatalities.'},
        {'year': 1989, 'event': 'Loma Prieta Earthquake', 'severity': 'Severe',
         'note': 'M6.9, World Series quake, 63 fatalities.'},
    ],
    'AK': [
        {'year': 1964, 'event': 'Great Alaska Earthquake', 'severity': 'Catastrophic',
         'note': 'M9.2, 2nd-largest recorded quake worldwide.'},
    ],
    'WA': [
        {'year': 2001, 'event': 'Nisqually Earthquake', 'severity': 'Severe',
         'note': 'M6.8, $2B damage to Seattle area.'},
        {'year': 1980, 'event': 'Mount St. Helens Eruption', 'severity': 'Catastrophic',
         'note': 'Volcanic explosion, 57 fatalities.'},
    ],
    'KS': [
        {'year': 2007, 'event': 'Greensburg Tornado', 'severity': 'Catastrophic',
         'note': 'EF-5 tornado destroyed 95% of the town.'},
    ],
    'MO': [
        {'year': 2011, 'event': 'Joplin Tornado', 'severity': 'Catastrophic',
         'note': 'EF-5, 158 fatalities, deadliest US tornado since 1947.'},
    ],
    'AL': [
        {'year': 2011, 'event': 'April 27 Super Outbreak', 'severity': 'Catastrophic',
         'note': '62 tornadoes in one day across AL, 252 fatalities.'},
    ],
}

# Decadal event frequency estimates (per state) used for the trend chart.
# Values are normalized hazard-events-per-decade, derived from NOAA aggregates.
DECADAL_TRENDS = {
    'FL': {'1980s': 14, '1990s': 22, '2000s': 28, '2010s': 31, '2020s': 19},
    'TX': {'1980s': 38, '1990s': 45, '2000s': 52, '2010s': 61, '2020s': 35},
    'OK': {'1980s': 42, '1990s': 48, '2000s': 51, '2010s': 47, '2020s': 28},
    'KS': {'1980s': 39, '1990s': 44, '2000s': 49, '2010s': 46, '2020s': 27},
    'CA': {'1980s': 18, '1990s': 24, '2000s': 28, '2010s': 35, '2020s': 22},
    'LA': {'1980s': 16, '1990s': 22, '2000s': 27, '2010s': 24, '2020s': 18},
    'AK': {'1980s': 8,  '1990s': 9,  '2000s': 11, '2010s': 13, '2020s': 8},
    'WA': {'1980s': 7,  '1990s': 9,  '2000s': 11, '2010s': 14, '2020s': 9},
}
DEFAULT_TRENDS = {'1980s': 8, '1990s': 11, '2000s': 14, '2010s': 17, '2020s': 11}


# Full state name → 2-letter code (used to normalize Nominatim fallback)
STATE_NAME_TO_CODE = {
    'Alabama':'AL','Alaska':'AK','Arizona':'AZ','Arkansas':'AR','California':'CA',
    'Colorado':'CO','Connecticut':'CT','Delaware':'DE','Florida':'FL','Georgia':'GA',
    'Hawaii':'HI','Idaho':'ID','Illinois':'IL','Indiana':'IN','Iowa':'IA',
    'Kansas':'KS','Kentucky':'KY','Louisiana':'LA','Maine':'ME','Maryland':'MD',
    'Massachusetts':'MA','Michigan':'MI','Minnesota':'MN','Mississippi':'MS','Missouri':'MO',
    'Montana':'MT','Nebraska':'NE','Nevada':'NV','New Hampshire':'NH','New Jersey':'NJ',
    'New Mexico':'NM','New York':'NY','North Carolina':'NC','North Dakota':'ND','Ohio':'OH',
    'Oklahoma':'OK','Oregon':'OR','Pennsylvania':'PA','Rhode Island':'RI','South Carolina':'SC',
    'South Dakota':'SD','Tennessee':'TN','Texas':'TX','Utah':'UT','Vermont':'VT',
    'Virginia':'VA','Washington':'WA','West Virginia':'WV','Wisconsin':'WI','Wyoming':'WY',
}


def normalize_state(s):
    """Accept either '2-letter code' or 'Full State Name' → 2-letter code (or '')."""
    if not s:
        return ''
    s = s.strip()
    if len(s) == 2 and s.upper() in STATE_PROFILES:
        return s.upper()
    return STATE_NAME_TO_CODE.get(s, '')


HEADERS = {"User-Agent": "GAD/1.0 (cs4398@group15.com)"}


# ═══════════════ UTILITIES ════════════════════════════════════════════════════

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
                    })

        # Risk scores (state-level + jitter for cross-location variation)
        profile = STATE_PROFILES.get(state, DEFAULT_PROFILE)
        scores = {k: jitter(profile.get(k, DEFAULT_PROFILE.get(k, 0)), lat, lon)
                  for k in RISK_CATEGORIES}
        composite = composite_from_scores(scores)

        return jsonify({
            'forecast':    forecasts,
            'alerts':      alerts,
            'scores':      scores,
            'composite':   composite,
            'observation': obs,
            'state':       state,
            'climateZone': IECC_ZONES.get(state, 'N/A'),
            'buildingCode': BUILDING_CODES.get(state, 'Consult local jurisdiction'),
        })

    except requests.exceptions.RequestException as e:
        return jsonify({'error': f'Weather service unavailable: {e}'}), 503
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/history')
def history():
    """Historical disaster events + decadal trend for a state."""
    state = request.args.get('state', '').upper()
    return jsonify({
        'events': HISTORICAL_EVENTS.get(state, []),
        'trends': DECADAL_TRENDS.get(state, DEFAULT_TRENDS),
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


@app.route('/api/health')
def health():
    return jsonify({'status': 'ok', 'time': datetime.utcnow().isoformat()})


if __name__ == '__main__':
    # Default to 5001 because macOS AirPlay Receiver claims 5000.
    # Override with `PORT=xxxx python3 app.py` if you need a different port.
    port = int(os.environ.get('PORT', 5001))
    app.run(debug=True, port=port)
