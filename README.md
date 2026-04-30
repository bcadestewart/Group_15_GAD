# GAD — Geospatial Architecture Database

A web-based decision-support tool that takes a US location and returns a multi-hazard weather-risk profile, the locally adopted IECC climate zone and building code, and tailored construction recommendations. Reports can be exported as PDF or CSV.

> **Course context:** CS 4398 — Software Engineering, Group 15 (Texas State University). See [`Group15SRS.html`](./Group15SRS.html) for the full requirements specification.

---

## What it does

Given a search query (address, city, or coordinates) or a click on the map, GAD will:

1. **Geocode** the input via the OpenStreetMap Nominatim API.
2. **Pull live weather data** from the US National Weather Service: current observation, 7-day forecast, and active alerts.
3. **Compute a multi-hazard risk score** — hurricane, tornado, flood, winter storm, extreme heat, seismic, and wildfire — blended into a 0–100 composite.
4. **Surface the locally adopted building code** (IBC year per state) and **IECC climate zone**.
5. **Recommend construction practices** keyed to the dominant hazards (e.g. hurricane straps, FEMA P-320 safe room, frost-protected shallow foundation).
6. **Export** the resulting site report as a styled PDF (server-rendered via reportlab) or CSV.

A comparison panel lets the user save up to 3 sites side-by-side, and recent searches persist locally for fast re-analysis.

---

## Quick start

### Prerequisites
- Python 3.8 or newer
- A modern browser (Chrome, Firefox, Safari, Edge)
- Internet connection (the app calls live NWS and Nominatim APIs)

### Install and run
```bash
git clone https://github.com/bcadestewart/Group_15_GAD.git
cd Group_15_GAD

# Optional but recommended: virtual environment
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r backend/requirements.txt
python3 backend/app.py
```

The server boots on **http://localhost:5001** by default. Port 5001 (not the Flask default 5000) avoids a collision with macOS AirPlay Receiver. Override with `PORT=8000 python3 backend/app.py` if you need a different port.

---

## Project structure

```
Group_15_GAD/
├── .github/workflows/
│   └── ci.yml                # GitHub Actions: ruff + pytest on every PR
├── backend/
│   ├── app.py                # Flask server: routes, risk engine, PDF export
│   ├── db/                   # SQLAlchemy data layer
│   │   ├── __init__.py       # Engine, session factory, init_db()
│   │   ├── models.py         # State, HistoricalEvent, DecadalTrend,
│   │   │                     #   RiskCategory, ConstructionTip
│   │   ├── seed_data.py      # Canonical Python source for all reference data
│   │   └── seed.py           # Idempotent loader (data → tables)
│   ├── gad.db                # SQLite file (gitignored; auto-created on boot)
│   ├── requirements.txt      # Pinned runtime dependencies (with SRS traceability)
│   └── requirements-dev.txt  # Dev tooling: pytest, pytest-mock, ruff
├── frontend/
│   ├── index.html            # Single-page UI (sidebar + map + tabbed dashboard)
│   ├── app.js                # Client logic: map, search, tabs, charts, export
│   └── styles.css            # Glass-morphism theme, accessibility, responsive
├── tests/                    # Backend test suite (pytest)
│   ├── conftest.py           # Flask test client + reusable fake-API fixtures
│   ├── test_utils.py         # normalize_state, jitter, composite math
│   ├── test_routes.py        # Each /api/* route, NWS/Nominatim mocked
│   └── test_export.py        # PDF generation smoke tests
├── pyproject.toml            # pytest + ruff configuration
├── Group15SRS.html           # Software Requirements Specification (source of truth)
├── DESIGN.md                 # System design document
└── README.md                 # This file
```

---

## Database

All static reference data (state hazard profiles, IECC zones, building codes, historical events, decadal trends, risk categories, construction tips) lives in a SQLite database accessed via the **SQLAlchemy 2.0 ORM**. The canonical Python representation is in `backend/db/seed_data.py`; the schema is in `backend/db/models.py`.

On the first app boot, `init_db()` creates the schema and seeds it from `seed_data` automatically — no manual migration step is required for a fresh checkout. The seed loader is idempotent, so subsequent boots are no-ops. The default DB file is `backend/gad.db` (gitignored). Override with the `GAD_DATABASE_URL` environment variable, e.g. `GAD_DATABASE_URL=sqlite:///:memory: python3 backend/app.py`. The test suite uses `sqlite:///:memory:` so CI never touches a file on disk.

Schema versioning via Alembic is planned as a follow-up — see [DESIGN.md §15](./DESIGN.md#15-future-work--known-limitations).

---

## API endpoints

| Method | Path                        | Purpose                                                     | SRS ref     |
| ------ | --------------------------- | ----------------------------------------------------------- | ----------- |
| GET    | `/`                         | Serves the SPA (`frontend/index.html`)                      | §2.4        |
| GET    | `/api/search?q=…`           | Address autocomplete via OpenStreetMap Nominatim            | §3.1        |
| GET    | `/api/weather?lat=…&lon=…`  | Forecast, alerts, risk scores, IECC zone, building code     | §3.2, §3.4  |
| GET    | `/api/history?state=XX`     | Notable historical disasters + decadal hazard-event trend   | §3.2        |
| POST   | `/api/export`               | Server-rendered PDF site report (reportlab)                 | §3.3        |
| GET    | `/api/health`               | Liveness probe for monitoring                               | §4.1        |

CSV export is generated client-side in `frontend/app.js`.

---

## Data sources

| Source                          | Used for                                  |
| ------------------------------- | ----------------------------------------- |
| `api.weather.gov`               | Forecast, active alerts, point metadata   |
| `nominatim.openstreetmap.org`   | Forward + reverse geocoding               |
| OpenStreetMap tile servers      | Leaflet base map tiles                    |
| Static tables in `app.py`       | State hazard profiles, IECC zones, IBC code adoption, historical events, decadal trends |

The static tables represent state-level baselines drawn from NOAA Storm Events, FEMA, and ICC code-adoption summaries; see [DESIGN.md](./DESIGN.md#data-model) for sourcing notes.

---

## Architecture at a glance

```
┌────────────────────┐    HTTPS    ┌────────────────────┐
│  Browser (SPA)     │ ──────────▶ │  Flask backend     │
│  Leaflet + Chart.js│             │  (backend/app.py)  │
└────────────────────┘             └────────────────────┘
                                         │
            ┌────────────────────────────┼────────────────────────────┐
            ▼                            ▼                            ▼
   api.weather.gov (NWS)     nominatim.openstreetmap.org      Static state tables
   (forecast, alerts)         (geocoding)                     (profiles, codes, history)
```

For the full breakdown — component design, data flow sequence, risk-scoring math, SRS traceability matrix — see [**DESIGN.md**](./DESIGN.md).

---

## Testing

The backend has a [pytest](https://docs.pytest.org/) suite under `tests/`. External calls (NWS, Nominatim) are mocked via `pytest-mock` so the suite runs offline and is deterministic.

```bash
pip install -r backend/requirements-dev.txt   # installs runtime + dev deps

ruff check .         # lint (also formats imports)
pytest -v            # run the test suite (~36 tests, < 1 s)
```

GitHub Actions runs both on every PR and push to `main` (Python 3.10 + 3.12 matrix) — see [`.github/workflows/ci.yml`](./.github/workflows/ci.yml). PRs cannot be merged until CI is green.

---

## Development workflow

This project uses a feature-branch + pull-request workflow even though the team is small:

1. Create a branch from `main`: `git checkout -b feat/<short-description>`.
2. Make focused commits.
3. Open a PR back to `main` with a description tied to the SRS section it touches.
4. Wait for CI to pass (ruff + pytest on Python 3.10 and 3.12).
5. Self-review, run the app, then **squash-merge** to keep `main` history linear.

Living docs convention: when a PR changes anything that's documented in [README.md](./README.md) or [DESIGN.md](./DESIGN.md) — endpoints, dependencies, file structure, run instructions, the risk model, the data tables, deployment, or SRS traceability — those docs are updated **in the same PR**. The DESIGN.md revision history gets bumped as well.

---

## Contributors (Group 15)

- Oscar Puente
- Brandon Stewart
- Ethan Sklar

---

## License & disclaimer

Course project, all rights reserved by the authors. Reports generated by GAD are advisory only — always consult local building codes, a licensed structural engineer, and FEMA / ICC standards before construction.

---

*Last reviewed: 2026-04-28*
