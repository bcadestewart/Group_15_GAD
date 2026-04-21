import os
import math
import requests
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__, static_folder='../frontend', static_url_path='/')

RISK_CATEGORIES = {
    'hurricane': {'label': 'Hurricane / Tropical Storm', 'weight': 0.3},
    'tornado': {'label': 'Tornado', 'weight': 0.25},
    'flood': {'label': 'Flooding', 'weight': 0.2},
    'winter': {'label': 'Winter Storm / Ice', 'weight': 0.15},
    'heat': {'label': 'Extreme Heat', 'weight': 0.1},
}

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
}

STATE_PROFILES = {
  'TX': {'hurricane': 6, 'tornado': 7, 'flood': 6, 'winter': 2, 'heat': 8},
  'FL': {'hurricane': 9, 'tornado': 4, 'flood': 7, 'winter': 0, 'heat': 7},
  'OK': {'hurricane': 0, 'tornado': 9, 'flood': 5, 'winter': 4, 'heat': 6},
  'KS': {'hurricane': 0, 'tornado': 9, 'flood': 4, 'winter': 5, 'heat': 5},
  'LA': {'hurricane': 8, 'tornado': 5, 'flood': 8, 'winter': 1, 'heat': 7},
  'MS': {'hurricane': 6, 'tornado': 6, 'flood': 6, 'winter': 1, 'heat': 7},
  'AL': {'hurricane': 5, 'tornado': 7, 'flood': 5, 'winter': 2, 'heat': 7},
  'GA': {'hurricane': 3, 'tornado:': 4, 'flood': 4, 'winter': 2, 'heat': 6},
  'SC': {'hurricane': 5, 'tornado': 3, 'flood': 5, 'winter': 2, 'heat': 6},
  'NC': {'hurricane': 5, 'tornado': 3, 'flood': 5, 'winter': 3, 'heat': 5},
  'VA': {'hurricane': 3, 'tornado': 2, 'flood': 4, 'winter': 4, 'heat': 4},
  'CA': {'hurricane': 0, 'tornado': 1, 'flood': 3, 'winter': 2, 'heat': 6},
  'AZ': {'hurricane': 0, 'tornado': 1, 'flood': 3, 'winter': 1, 'heat': 10},
  'NV': {'hurricane': 0, 'tornado': 0, 'flood': 2, 'winter': 2, 'heat': 9},
  'NM': {'hurricane': 0, 'tornado': 2, 'flood': 3, 'winter': 3, 'heat': 7},
  'CO': {'hurricane': 0, 'tornado': 4, 'flood': 3, 'winter': 7, 'heat': 3},
  'MN': {'hurricane': 0, 'tornado': 4, 'flood': 4, 'winter': 9, 'heat': 2},
  'WI': {'hurricane': 0, 'tornado': 3, 'flood': 4, 'winter': 8, 'heat': 2},
  'MI': {'hurricane': 0, 'tornado': 3, 'flood': 4, 'winter': 8, 'heat': 2},
  'NY': {'hurricane': 2, 'tornado': 2, 'flood': 4, 'winter': 7, 'heat': 3},
  'ME': {'hurricane': 1, 'tornado': 1, 'flood': 3, 'winter': 9, 'heat': 1},
  'MT': {'hurricane': 0, 'tornado': 2, 'flood': 3, 'winter': 8, 'heat': 2},
  'WY': {'hurricane': 0, 'tornado': 2, 'flood': 2, 'winter': 8, 'heat': 2},
  'ND': {'hurricane': 0, 'tornado': 4, 'flood': 4, 'winter': 9, 'heat': 2},
  'SD': {'hurricane': 0, 'tornado': 5, 'flood': 4, 'winter': 8, 'heat': 3},
  'NE': {'hurricane': 0, 'tornado': 7, 'flood': 4, 'winter': 6, 'heat': 4},
  'IA': {'hurricane': 0, 'tornado': 6, 'flood': 5, 'winter': 7, 'heat': 3},
  'MO': {'hurricane': 0, 'tornado': 6, 'flood': 5, 'winter': 5, 'heat': 5},
  'AR': {'hurricane': 1, 'tornado': 6, 'flood': 5, 'winter': 3, 'heat': 6},
  'TN': {'hurricane': 1, 'tornado': 5, 'flood': 5, 'winter': 3, 'heat': 5},
  'IN': {'hurricane': 0, 'tornado': 5, 'flood': 4, 'winter': 6, 'heat': 3},
  'IL': {'hurricane': 0, 'tornado': 6, 'flood': 5, 'winter': 6, 'heat': 4},
  'OH': {'hurricane': 0, 'tornado': 3, 'flood': 4, 'winter': 6, 'heat': 3},
  'PA': {'hurricane': 1, 'tornado': 2, 'flood': 4, 'winter': 6, 'heat': 3},
  'WV': {'hurricane': 0, 'tornado': 2, 'flood': 5, 'winter': 6, 'heat': 3},
  'KY': {'hurricane': 0, 'tornado': 4, 'flood': 5, 'winter': 4, 'heat': 4},
  'MD': {'hurricane': 2, 'tornado': 2, 'flood': 4, 'winter': 5, 'heat': 4},
  'DE': {'hurricane': 2, 'tornado': 1, 'flood': 4, 'winter': 4, 'heat': 4},
  'NJ': {'hurricane': 2, 'tornado': 2, 'flood': 4, 'winter': 5, 'heat': 4},
  'CT': {'hurricane': 2, 'tornado': 1, 'flood': 3, 'winter': 6, 'heat': 3},
  'RI': {'hurricane': 2, 'tornado': 1, 'flood': 3, 'winter': 6, 'heat': 2},
  'MA': {'hurricane': 2, 'tornado': 1, 'flood': 3, 'winter': 7, 'heat': 2},
  'VT': {'hurricane': 1, 'tornado': 1, 'flood': 4, 'winter': 8, 'heat': 1},
  'NH': {'hurricane': 1, 'tornado': 1, 'flood': 3, 'winter': 8, 'heat': 1},
  'WA': {'hurricane': 0, 'tornado': 1, 'flood': 4, 'winter': 4, 'heat': 2},
  'OR': {'hurricane': 0, 'tornado': 1, 'flood': 4, 'winter': 4, 'heat': 3},
  'ID': {'hurricane': 0, 'tornado': 1, 'flood': 3, 'winter': 6, 'heat': 3},
  'UT': {'hurricane': 0, 'tornado': 1, 'flood': 2, 'winter': 5, 'heat': 5},
  'HI': {'hurricane': 3, 'tornado': 0, 'flood': 4, 'winter': 0, 'heat': 3},
  'AK': {'hurricane': 0, 'tornado': 0, 'flood': 2, 'winter': 10, 'heat': 0},
}
DEFAULT_PROFILE = {'hurricane': 2, 'tornado': 3, 'flood': 3, 'winter': 4, 'heat': 3}

headers = {"User-Agent": "GAD/1.0 (cs4398@group15.com)"}

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/api/search')
def search():
    q = request.args.get('q')
    if not q:
        return jsonify([])
    try:
        url = f"https://nominatim.openstreetmap.org/search?format=json&q={requests.utils.quote(q)}&limit=5&countrycodes=us"
        resp = requests.get(url, headers=headers).json()
        return jsonify([{'lat': float(x['lat']), 'lon': float(x['lon']), 'display': x['display_name']} for x in resp])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/weather')
def weather():
    lat = request.args.get('lat', type=float)
    lon = request.args.get('lon', type=float)
    
    if lat is None or lon is None:
        return jsonify({'error': 'Missing coordinates'}), 400

    try:
        # NWS Point API
        point_url = f"https://api.weather.gov/points/{lat},{lon}"
        point_res = requests.get(point_url, headers=headers)
        if not point_res.ok:
            return jsonify({'error': 'Location not found or not supported by NWS (Ensure it is within US)'}), 404
            
        point_data = point_res.json()
        props = point_data.get('properties', {})
        forecast_url = props.get('forecast')
        state = props.get('relativeLocation', {}).get('properties', {}).get('state', '')

        # Fallback state if empty
        if not state:
            # We can use Nominatim reverse geocode
            try:
                rev = requests.get(f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}", headers=headers).json()
                state = rev.get('address', {}).get('state', '')
            except:
                pass

        # NWS Forecast API
        forecasts = []
        obs = {}
        if forecast_url:
            f_res = requests.get(forecast_url, headers=headers)
            if f_res.ok:
                periods = f_res.json().get('properties', {}).get('periods', [])
                forecasts = [{'name': p['name'], 'temperature': p['temperature'], 'temperatureUnit': p['temperatureUnit'], 'shortForecast': p['shortForecast']} for p in periods[:14]]
                if periods:
                    obs = {
                        'temperature': periods[0]['temperature'],
                        'windSpeed': periods[0]['windSpeed'],
                        'humidity': 'N/A', # NWS forecast doesn't easily return current RH, mock or omit
                        'conditions': periods[0]['shortForecast']
                    }

        # NWS Active Alerts
        alerts = []
        if state:
            alert_url = f"https://api.weather.gov/alerts/active?area={state}"
            alert_res = requests.get(alert_url, headers=headers)
            if alert_res.ok:
                alert_features = alert_res.json().get('features', [])
                for f in alert_features:
                    ap = f.get('properties', {})
                    alerts.append({
                        'event': ap.get('event'),
                        'severity': ap.get('severity'),
                        'headline': ap.get('headline')
                    })
        
        # Simulated properties to supplement
        profile = STATE_PROFILES.get(state, DEFAULT_PROFILE)
        seed = abs(math.sin(lat * 12.9898 + lon * 78.233)) % 1
        scores = {k: min(10, max(0, v + round((seed - 0.5) * 2))) for k, v in profile.items() if k != 'tornado:'}
        
        # fix typo from dictionary
        if 'tornado:' in profile:
            scores['tornado'] = min(10, max(0, profile['tornado:'] + round((seed - 0.5) * 2)))

        c = 0
        for k, sc in scores.items():
            if k in RISK_CATEGORIES:
                c += sc * RISK_CATEGORIES[k]['weight']
        composite = max(0, min(100, round(c * 10)))

        return jsonify({
            'forecast': forecasts,
            'alerts': alerts,
            'scores': scores,
            'composite': composite,
            'observation': obs,
            'state': state
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
