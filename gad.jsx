import { useState, useEffect, useRef, useCallback } from "react";

// ─── Constants ───
const NOMINATIM = "https://nominatim.openstreetmap.org";

const RISK_CATEGORIES = {
  hurricane: { label: "Hurricane / Tropical Storm", weight: 0.3, icon: "🌀" },
  tornado: { label: "Tornado", weight: 0.25, icon: "🌪️" },
  flood: { label: "Flooding", weight: 0.2, icon: "🌊" },
  winter: { label: "Winter Storm / Ice", weight: 0.15, icon: "❄️" },
  heat: { label: "Extreme Heat", weight: 0.1, icon: "🔥" },
};

const CONSTRUCTION_TIPS = {
  hurricane: [
    "Use hurricane straps/clips to secure roof to walls",
    "Install impact-resistant windows or hurricane shutters",
    "Reinforce garage doors — primary failure point in hurricanes",
    "Elevate the foundation above the base flood elevation (BFE)",
    "Use concrete block or reinforced masonry for exterior walls",
  ],
  tornado: [
    "Include a reinforced safe room (FEMA P-320 / ICC 500 compliant)",
    "Anchor the structure to a continuous foundation",
    "Use hip roofs instead of gable — better wind resistance",
    "Install continuous plywood sheathing on roof and walls",
    "Specify impact-rated exterior cladding and doors",
  ],
  flood: [
    "Elevate the lowest floor at least 1 ft above BFE",
    "Use flood-resistant materials below the Design Flood Elevation",
    "Install backflow valves on all sewer and drain lines",
    "Grade the site to slope away from the building on all sides",
    "Avoid finished basements in high-risk flood zones",
  ],
  winter: [
    "Design roof for regional snow load per ASCE 7",
    "Insulate to or above IECC climate-zone requirements",
    "Install heat cables along eaves and gutters to prevent ice dams",
    "Use frost-protected shallow foundations in cold climates",
    "Specify freeze-resistant exterior plumbing and hose bibs",
  ],
  heat: [
    "Specify high Solar Reflectance Index (SRI) roofing materials",
    "Design generous overhangs and shading on south/west facades",
    "Use insulated concrete forms (ICFs) for high thermal mass",
    "Plan for oversized HVAC capacity with redundancy",
    "Install radiant barriers in the attic space",
  ],
};

// ─── Regional weather profiles (based on NOAA historical data patterns) ───
const STATE_PROFILES = {
  TX: { hurricane: 6, tornado: 7, flood: 6, winter: 2, heat: 8, tempRange: [55, 98], cond: "Partly Cloudy", hum: 62, wind: 12 },
  FL: { hurricane: 9, tornado: 4, flood: 7, winter: 0, heat: 7, tempRange: [65, 95], cond: "Scattered Showers", hum: 75, wind: 10 },
  OK: { hurricane: 0, tornado: 9, flood: 5, winter: 4, heat: 6, tempRange: [40, 100], cond: "Clear", hum: 50, wind: 15 },
  KS: { hurricane: 0, tornado: 9, flood: 4, winter: 5, heat: 5, tempRange: [35, 100], cond: "Windy", hum: 48, wind: 18 },
  LA: { hurricane: 8, tornado: 5, flood: 8, winter: 1, heat: 7, tempRange: [55, 96], cond: "Humid", hum: 80, wind: 8 },
  MS: { hurricane: 6, tornado: 6, flood: 6, winter: 1, heat: 7, tempRange: [50, 95], cond: "Partly Cloudy", hum: 72, wind: 7 },
  AL: { hurricane: 5, tornado: 7, flood: 5, winter: 2, heat: 7, tempRange: [48, 94], cond: "Mostly Sunny", hum: 68, wind: 6 },
  GA: { hurricane: 3, tornado: 4, flood: 4, winter: 2, heat: 6, tempRange: [45, 95], cond: "Sunny", hum: 65, wind: 7 },
  SC: { hurricane: 5, tornado: 3, flood: 5, winter: 2, heat: 6, tempRange: [48, 94], cond: "Partly Cloudy", hum: 67, wind: 8 },
  NC: { hurricane: 5, tornado: 3, flood: 5, winter: 3, heat: 5, tempRange: [40, 90], cond: "Overcast", hum: 63, wind: 9 },
  VA: { hurricane: 3, tornado: 2, flood: 4, winter: 4, heat: 4, tempRange: [35, 90], cond: "Cloudy", hum: 60, wind: 8 },
  CA: { hurricane: 0, tornado: 1, flood: 3, winter: 2, heat: 6, tempRange: [50, 95], cond: "Sunny", hum: 35, wind: 10 },
  AZ: { hurricane: 0, tornado: 1, flood: 3, winter: 1, heat: 10, tempRange: [55, 115], cond: "Clear", hum: 15, wind: 8 },
  NV: { hurricane: 0, tornado: 0, flood: 2, winter: 2, heat: 9, tempRange: [40, 110], cond: "Clear", hum: 18, wind: 12 },
  NM: { hurricane: 0, tornado: 2, flood: 3, winter: 3, heat: 7, tempRange: [35, 100], cond: "Sunny", hum: 25, wind: 14 },
  CO: { hurricane: 0, tornado: 4, flood: 3, winter: 7, heat: 3, tempRange: [20, 90], cond: "Clear", hum: 30, wind: 12 },
  MN: { hurricane: 0, tornado: 4, flood: 4, winter: 9, heat: 2, tempRange: [-5, 85], cond: "Overcast", hum: 60, wind: 14 },
  WI: { hurricane: 0, tornado: 3, flood: 4, winter: 8, heat: 2, tempRange: [0, 85], cond: "Cloudy", hum: 62, wind: 11 },
  MI: { hurricane: 0, tornado: 3, flood: 4, winter: 8, heat: 2, tempRange: [5, 83], cond: "Partly Cloudy", hum: 65, wind: 12 },
  NY: { hurricane: 2, tornado: 2, flood: 4, winter: 7, heat: 3, tempRange: [15, 85], cond: "Variable", hum: 58, wind: 11 },
  ME: { hurricane: 1, tornado: 1, flood: 3, winter: 9, heat: 1, tempRange: [5, 80], cond: "Cloudy", hum: 65, wind: 10 },
  MT: { hurricane: 0, tornado: 2, flood: 3, winter: 8, heat: 2, tempRange: [-10, 90], cond: "Clear", hum: 35, wind: 16 },
  WY: { hurricane: 0, tornado: 2, flood: 2, winter: 8, heat: 2, tempRange: [-5, 88], cond: "Windy", hum: 30, wind: 20 },
  ND: { hurricane: 0, tornado: 4, flood: 4, winter: 9, heat: 2, tempRange: [-15, 90], cond: "Clear", hum: 50, wind: 15 },
  SD: { hurricane: 0, tornado: 5, flood: 4, winter: 8, heat: 3, tempRange: [-10, 95], cond: "Clear", hum: 48, wind: 14 },
  NE: { hurricane: 0, tornado: 7, flood: 4, winter: 6, heat: 4, tempRange: [5, 98], cond: "Partly Cloudy", hum: 52, wind: 13 },
  IA: { hurricane: 0, tornado: 6, flood: 5, winter: 7, heat: 3, tempRange: [5, 92], cond: "Variable", hum: 60, wind: 12 },
  MO: { hurricane: 0, tornado: 6, flood: 5, winter: 5, heat: 5, tempRange: [20, 95], cond: "Partly Cloudy", hum: 62, wind: 10 },
  AR: { hurricane: 1, tornado: 6, flood: 5, winter: 3, heat: 6, tempRange: [35, 96], cond: "Humid", hum: 68, wind: 8 },
  TN: { hurricane: 1, tornado: 5, flood: 5, winter: 3, heat: 5, tempRange: [35, 93], cond: "Partly Cloudy", hum: 66, wind: 7 },
  IN: { hurricane: 0, tornado: 5, flood: 4, winter: 6, heat: 3, tempRange: [15, 90], cond: "Variable", hum: 64, wind: 10 },
  IL: { hurricane: 0, tornado: 6, flood: 5, winter: 6, heat: 4, tempRange: [10, 92], cond: "Partly Cloudy", hum: 62, wind: 12 },
  OH: { hurricane: 0, tornado: 3, flood: 4, winter: 6, heat: 3, tempRange: [15, 88], cond: "Cloudy", hum: 64, wind: 10 },
  PA: { hurricane: 1, tornado: 2, flood: 4, winter: 6, heat: 3, tempRange: [18, 87], cond: "Variable", hum: 60, wind: 9 },
  WV: { hurricane: 0, tornado: 2, flood: 5, winter: 6, heat: 3, tempRange: [20, 86], cond: "Cloudy", hum: 65, wind: 7 },
  KY: { hurricane: 0, tornado: 4, flood: 5, winter: 4, heat: 4, tempRange: [25, 90], cond: "Partly Cloudy", hum: 66, wind: 8 },
  MD: { hurricane: 2, tornado: 2, flood: 4, winter: 5, heat: 4, tempRange: [25, 88], cond: "Variable", hum: 60, wind: 9 },
  DE: { hurricane: 2, tornado: 1, flood: 4, winter: 4, heat: 4, tempRange: [28, 88], cond: "Partly Cloudy", hum: 62, wind: 10 },
  NJ: { hurricane: 2, tornado: 2, flood: 4, winter: 5, heat: 4, tempRange: [22, 88], cond: "Variable", hum: 60, wind: 10 },
  CT: { hurricane: 2, tornado: 1, flood: 3, winter: 6, heat: 3, tempRange: [15, 85], cond: "Variable", hum: 58, wind: 10 },
  RI: { hurricane: 2, tornado: 1, flood: 3, winter: 6, heat: 2, tempRange: [18, 83], cond: "Cloudy", hum: 62, wind: 11 },
  MA: { hurricane: 2, tornado: 1, flood: 3, winter: 7, heat: 2, tempRange: [15, 84], cond: "Variable", hum: 60, wind: 12 },
  VT: { hurricane: 1, tornado: 1, flood: 4, winter: 8, heat: 1, tempRange: [0, 82], cond: "Cloudy", hum: 62, wind: 9 },
  NH: { hurricane: 1, tornado: 1, flood: 3, winter: 8, heat: 1, tempRange: [2, 82], cond: "Overcast", hum: 60, wind: 10 },
  WA: { hurricane: 0, tornado: 1, flood: 4, winter: 4, heat: 2, tempRange: [30, 78], cond: "Rainy", hum: 72, wind: 10 },
  OR: { hurricane: 0, tornado: 1, flood: 4, winter: 4, heat: 3, tempRange: [32, 85], cond: "Overcast", hum: 68, wind: 9 },
  ID: { hurricane: 0, tornado: 1, flood: 3, winter: 6, heat: 3, tempRange: [15, 92], cond: "Clear", hum: 35, wind: 10 },
  UT: { hurricane: 0, tornado: 1, flood: 2, winter: 5, heat: 5, tempRange: [20, 100], cond: "Clear", hum: 22, wind: 8 },
  HI: { hurricane: 3, tornado: 0, flood: 4, winter: 0, heat: 3, tempRange: [68, 88], cond: "Tropical Showers", hum: 70, wind: 12 },
  AK: { hurricane: 0, tornado: 0, flood: 2, winter: 10, heat: 0, tempRange: [-20, 65], cond: "Cold", hum: 55, wind: 14 },
};

const DEFAULT_PROFILE = { hurricane: 2, tornado: 3, flood: 3, winter: 4, heat: 3, tempRange: [30, 85], cond: "Variable", hum: 55, wind: 10 };

function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

const STATE_NAMES = {
  "Alabama":"AL","Alaska":"AK","Arizona":"AZ","Arkansas":"AR","California":"CA",
  "Colorado":"CO","Connecticut":"CT","Delaware":"DE","Florida":"FL","Georgia":"GA",
  "Hawaii":"HI","Idaho":"ID","Illinois":"IL","Indiana":"IN","Iowa":"IA",
  "Kansas":"KS","Kentucky":"KY","Louisiana":"LA","Maine":"ME","Maryland":"MD",
  "Massachusetts":"MA","Michigan":"MI","Minnesota":"MN","Mississippi":"MS","Missouri":"MO",
  "Montana":"MT","Nebraska":"NE","Nevada":"NV","New Hampshire":"NH","New Jersey":"NJ",
  "New Mexico":"NM","New York":"NY","North Carolina":"NC","North Dakota":"ND","Ohio":"OH",
  "Oklahoma":"OK","Oregon":"OR","Pennsylvania":"PA","Rhode Island":"RI","South Carolina":"SC",
  "South Dakota":"SD","Tennessee":"TN","Texas":"TX","Utah":"UT","Vermont":"VT",
  "Virginia":"VA","Washington":"WA","West Virginia":"WV","Wisconsin":"WI","Wyoming":"WY",
};

function extractState(display) {
  if (!display) return null;
  const parts = display.split(",").map(s => s.trim());
  for (const p of parts) { if (p.length === 2 && STATE_PROFILES[p.toUpperCase()]) return p.toUpperCase(); }
  for (const p of parts) { if (STATE_NAMES[p]) return STATE_NAMES[p]; }
  if (!display.toLowerCase().includes("united states") && !display.toLowerCase().includes("usa")) return null;
  return null;
}

function simulateWeather(stateCode, lat, lon) {
  const p = STATE_PROFILES[stateCode] || DEFAULT_PROFILE;
  const seed = Math.abs(Math.sin(lat * 12.9898 + lon * 78.233) * 43758.5453) % 1;
  const currentTemp = Math.round(p.tempRange[0] + (p.tempRange[1] - p.tempRange[0]) * (0.4 + seed * 0.3));

  const names = ["Today","Tonight","Tomorrow","Tomorrow Night","Day 3","Night 3","Day 4","Night 4","Day 5","Night 5","Day 6","Night 6","Day 7","Night 7"];
  const shorts = ["Sunny","Partly Cloudy","Mostly Cloudy","Scattered Showers","Clear","Thunderstorms Possible","Windy","Fair","Isolated Storms","Mostly Sunny","Cloudy","Light Rain","Breezy","Hot and Humid"];

  const forecast = names.map((name, i) => {
    const isNight = name.includes("Night") || name === "Tonight";
    const v = Math.sin(seed * 100 + i * 2.5) * 12;
    const t = isNight ? Math.round(currentTemp - 15 + v) : Math.round(currentTemp + v);
    return { name, temperature: t, temperatureUnit: "F", shortForecast: shorts[(Math.floor(seed * 100) + i * 3) % shorts.length] };
  });

  const alerts = [];
  if (p.hurricane >= 7 && seed > 0.5) alerts.push({ event: "Tropical Storm Watch", severity: "Moderate", headline: "Tropical storm conditions possible within 48 hours for the coastal region." });
  if (p.tornado >= 7 && seed > 0.4) alerts.push({ event: "Severe Thunderstorm Watch", severity: "Severe", headline: "Conditions favorable for severe thunderstorms with possible tornado development." });
  if (p.flood >= 6 && seed > 0.6) alerts.push({ event: "Flash Flood Watch", severity: "Moderate", headline: "Heavy rainfall may lead to flash flooding in low-lying and urban areas." });
  if (p.heat >= 8 && seed > 0.3) alerts.push({ event: "Excessive Heat Warning", severity: "Severe", headline: "Dangerously hot conditions expected with temperatures exceeding 105°F." });
  if (p.winter >= 8 && seed > 0.5) alerts.push({ event: "Winter Storm Watch", severity: "Moderate", headline: "Heavy snow and ice accumulation possible. Travel may become hazardous." });

  const scores = {
    hurricane: clamp(p.hurricane + Math.round((seed - 0.5) * 2), 0, 10),
    tornado: clamp(p.tornado + Math.round((seed - 0.5) * 2), 0, 10),
    flood: clamp(p.flood + Math.round((seed - 0.5) * 2), 0, 10),
    winter: clamp(p.winter + Math.round((seed - 0.5) * 2), 0, 10),
    heat: clamp(p.heat + Math.round((seed - 0.5) * 2), 0, 10),
  };

  return {
    forecast, alerts, scores,
    observation: { temperature: currentTemp, windSpeed: Math.round(p.wind + (seed - 0.5) * 6), humidity: Math.round(p.hum + (seed - 0.5) * 10), conditions: p.cond },
    state: stateCode,
  };
}

function computeComposite(scores) {
  let c = 0;
  for (const k of Object.keys(RISK_CATEGORIES)) c += scores[k] * RISK_CATEGORIES[k].weight;
  return clamp(Math.round(c * 10), 0, 100);
}

function riskColor(s) { return s <= 3 ? "#22c55e" : s <= 6 ? "#eab308" : "#ef4444"; }
function compColor(s) { return s <= 30 ? "#22c55e" : s <= 60 ? "#eab308" : "#ef4444"; }
function riskLabel(s) { return s <= 30 ? "Low" : s <= 60 ? "Moderate" : "High"; }

function generateCSV(loc, weather, scores, composite) {
  const o = weather.observation;
  const rows = [
    ["Geospatial Architecture Database — Export"],["Location",`"${loc.display}"`],["Coordinates",`${loc.lat}, ${loc.lon}`],["Generated",new Date().toISOString()],[],
    ["=== CURRENT CONDITIONS ==="],["Temperature (°F)",o.temperature],["Wind (mph)",o.windSpeed],["Humidity (%)",o.humidity],["Conditions",o.conditions],[],
    ["=== 7-DAY FORECAST ==="],["Period","Temperature","Forecast"],
  ];
  weather.forecast.forEach(p => rows.push([p.name,`${p.temperature}°${p.temperatureUnit}`,`"${p.shortForecast}"`]));
  rows.push([],["=== ACTIVE ALERTS ==="],["Event","Severity","Headline"]);
  if (!weather.alerts.length) rows.push(["None","",""]);
  weather.alerts.forEach(a => rows.push([a.event,a.severity,`"${a.headline}"`]));
  rows.push([],["=== RISK ASSESSMENT ==="],["Category","Score (0-10)"]);
  for (const k of Object.keys(RISK_CATEGORIES)) rows.push([RISK_CATEGORIES[k].label, scores[k]]);
  rows.push(["Composite Risk Score",`${composite}/100`]);
  rows.push([],["=== CONSTRUCTION RECOMMENDATIONS ==="]);
  for (const k of Object.keys(RISK_CATEGORIES)) {
    if (scores[k] >= 3) { rows.push([`--- ${RISK_CATEGORIES[k].label} ---`]); CONSTRUCTION_TIPS[k].forEach(t => rows.push([`"${t}"`])); }
  }
  return rows.map(r => r.join(",")).join("\n");
}

// ─── Leaflet ───
function LeafletMap({ center, zoom, marker, onMapClick }) {
  const ref = useRef(null);
  const mapRef = useRef(null);
  const mkRef = useRef(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (window.L) { setReady(true); return; }
    const l = document.createElement("link"); l.rel = "stylesheet"; l.href = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css"; document.head.appendChild(l);
    const s = document.createElement("script"); s.src = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"; s.onload = () => setReady(true); document.head.appendChild(s);
  }, []);

  useEffect(() => {
    if (!ready || !ref.current || mapRef.current) return;
    const m = window.L.map(ref.current, { zoomControl: false }).setView(center, zoom);
    window.L.control.zoom({ position: "topright" }).addTo(m);
    window.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "© OpenStreetMap" }).addTo(m);
    m.on("click", e => onMapClick?.(e.latlng.lat, e.latlng.lng));
    mapRef.current = m;
    setTimeout(() => m.invalidateSize(), 200);
  }, [ready]);

  useEffect(() => { mapRef.current?.setView(center, zoom); }, [center, zoom]);
  useEffect(() => {
    if (!mapRef.current || !window.L) return;
    mkRef.current?.remove();
    if (marker) mkRef.current = window.L.marker([marker.lat, marker.lon]).addTo(mapRef.current);
  }, [marker]);

  return <div ref={ref} style={{ width: "100%", height: "100%", borderRadius: 12, overflow: "hidden" }} />;
}

const TABS = ["overview","forecast","alerts","risk","recommendations"];
const TAB_LABELS = { overview:"Overview", forecast:"Forecast", alerts:"Alerts", risk:"Risk Score", recommendations:"Build Tips" };

export default function GADApp() {
  const [query, setQuery] = useState("");
  const [suggs, setSuggs] = useState([]);
  const [loc, setLoc] = useState(null);
  const [weather, setWeather] = useState(null);
  const [scores, setScores] = useState(null);
  const [composite, setComposite] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState("overview");
  const [mapC, setMapC] = useState([39.5, -98.35]);
  const [mapZ, setMapZ] = useState(4);
  const timer = useRef(null);

  const doSearch = useCallback(q => {
    if (q.length < 3) { setSuggs([]); return; }
    clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      try {
        const r = await fetch(`${NOMINATIM}/search?format=json&q=${encodeURIComponent(q)}&limit=5&countrycodes=us`);
        if (!r.ok) return;
        const d = await r.json();
        setSuggs(d.map(x => ({ lat: +x.lat, lon: +x.lon, display: x.display_name })));
      } catch { setSuggs([]); }
    }, 400);
  }, []);

  const select = useCallback(async (lat, lon, display) => {
    setLoading(true); setError(null); setSuggs([]); setWeather(null); setScores(null); setComposite(null); setTab("overview");
    const l = { lat, lon, display: display || `${lat.toFixed(4)}, ${lon.toFixed(4)}` };
    setLoc(l); setMapC([lat, lon]); setMapZ(10);
    if (!display) {
      try {
        const r = await fetch(`${NOMINATIM}/reverse?format=json&lat=${lat}&lon=${lon}`);
        if (r.ok) { const d = await r.json(); l.display = d.display_name || l.display; setLoc({...l}); }
      } catch {}
    }
    const st = extractState(l.display);
    if (!st) { setError("Location not supported. GAD provides data for US locations only."); setLoading(false); return; }
    await new Promise(r => setTimeout(r, 500));
    const w = simulateWeather(st, lat, lon);
    setWeather(w); setScores(w.scores);
    setComposite(computeComposite(w.scores));
    setLoading(false);
  }, []);

  const onMapClick = useCallback((lat, lon) => select(lat, lon, null), [select]);

  const doExport = useCallback(() => {
    if (!loc || !weather || !scores) return;
    const csv = generateCSV(loc, weather, scores, composite);
    const b = new Blob([csv], { type: "text/csv" });
    const u = URL.createObjectURL(b);
    const a = document.createElement("a"); a.href = u; a.download = `GAD_Report_${new Date().toISOString().slice(0,10)}.csv`; a.click();
    URL.revokeObjectURL(u);
  }, [loc, weather, scores, composite]);

  const onKey = e => {
    if (e.key === "Enter" && query.trim()) {
      fetch(`${NOMINATIM}/search?format=json&q=${encodeURIComponent(query)}&limit=1&countrycodes=us`)
        .then(r => r.json()).then(d => { if (d.length) select(+d[0].lat, +d[0].lon, d[0].display_name); else setError("Location not found. Please try again."); })
        .catch(() => setError("Location not found. Check your connection."));
    }
  };

  const obs = weather?.observation;
  const activeRisks = scores ? Object.keys(RISK_CATEGORIES).filter(k => scores[k] >= 3).sort((a,b) => scores[b] - scores[a]) : [];

  return (
    <div style={S.root}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,200;0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700&family=JetBrains+Mono:wght@400&display=swap');
        @keyframes spin{to{transform:rotate(360deg)}}
        @keyframes fadeIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}
        *{box-sizing:border-box}
        ::-webkit-scrollbar{width:5px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:rgba(255,255,255,0.08);border-radius:3px}
      `}</style>

      <header style={S.header}>
        <div style={S.headerInner}>
          <div style={S.logo}>
            <svg width="26" height="26" viewBox="0 0 28 28" fill="none"><path d="M14 2L26 8v12l-12 6L2 20V8l12-6z" stroke="#60a5fa" strokeWidth="1.5" fill="rgba(96,165,250,0.08)"/><circle cx="14" cy="14" r="4" fill="#60a5fa" opacity="0.7"/><path d="M14 6v4M14 18v4M6 14h4M18 14h4" stroke="#60a5fa" strokeWidth="1" opacity="0.4"/></svg>
            <div><div style={S.logoText}>GAD</div><div style={S.logoSub}>Geospatial Architecture Database</div></div>
          </div>
          <div style={{display:"flex",alignItems:"center",gap:12}}>
            <div style={S.simTag}>SIMULATED DATA</div>
            {weather && <button onClick={doExport} style={S.expBtn}>↓ Export CSV</button>}
          </div>
        </div>
      </header>

      <div style={S.body}>
        <aside style={S.side}>
          <div style={{position:"relative"}}>
            <div style={S.lbl}>Search Location</div>
            <div style={S.inWrap}>
              <svg width="15" height="15" viewBox="0 0 16 16" fill="none" style={{flexShrink:0,opacity:0.35}}><circle cx="7" cy="7" r="5.5" stroke="currentColor" strokeWidth="1.5"/><path d="M11 11l3.5 3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>
              <input value={query} onChange={e=>{setQuery(e.target.value);doSearch(e.target.value)}} onKeyDown={onKey} placeholder="Address or city…" style={S.inp}/>
            </div>
            {suggs.length > 0 && <div style={S.suggs}>{suggs.map((s,i) =>
              <div key={i} style={S.suggI} onClick={()=>{setQuery("");select(s.lat,s.lon,s.display)}}
                onMouseEnter={e=>e.currentTarget.style.background="rgba(255,255,255,0.05)"}
                onMouseLeave={e=>e.currentTarget.style.background="transparent"}>
                <span style={{opacity:0.35,flexShrink:0}}>📍</span><span>{s.display.length>55?s.display.slice(0,55)+"…":s.display}</span>
              </div>
            )}</div>}
            <div style={S.hint}>Or click anywhere on the map</div>
          </div>

          {loc && <div style={S.locCard}><div style={S.locN}>{loc.display}</div><div style={S.locC}>{loc.lat.toFixed(4)}°N, {loc.lon.toFixed(4)}°W</div></div>}

          {obs && <div style={S.condCard}>
            <div style={S.lbl}>Current Conditions</div>
            <div style={{display:"flex",alignItems:"baseline",gap:2,marginBottom:2}}><span style={S.tempBig}>{obs.temperature}°</span><span style={{fontSize:16,fontWeight:300,color:"#64748b"}}>F</span></div>
            <div style={{fontSize:13,color:"#94a3b8",marginBottom:12}}>{obs.conditions}</div>
            <div style={{display:"flex",gap:20}}>
              <div style={S.stat}><span style={S.statL}>Wind</span><span style={S.statV}>{obs.windSpeed} mph</span></div>
              <div style={S.stat}><span style={S.statL}>Humidity</span><span style={S.statV}>{obs.humidity}%</span></div>
            </div>
          </div>}

          {composite!=null && <div style={{...S.rBadge,borderColor:compColor(composite)}}>
            <div style={{fontSize:10,letterSpacing:2,color:"#64748b",textTransform:"uppercase"}}>RISK SCORE</div>
            <div style={{fontSize:52,fontWeight:200,lineHeight:1.1,marginTop:4,color:compColor(composite)}}>{composite}</div>
            <div style={{fontSize:13,fontWeight:700,textTransform:"uppercase",letterSpacing:1,marginTop:2,color:compColor(composite)}}>{riskLabel(composite)}</div>
          </div>}

          {weather?.alerts.length > 0 && <div style={S.alertBtn} onClick={()=>setTab("alerts")}>⚠ {weather.alerts.length} Active Alert{weather.alerts.length>1?"s":""}</div>}
        </aside>

        <main style={S.main}>
          <div style={S.mapBox}>
            <LeafletMap center={mapC} zoom={mapZ} marker={loc?{lat:loc.lat,lon:loc.lon}:null} onMapClick={onMapClick}/>
            {loading && <div style={S.mapOv}><div style={S.spin}/><div style={{marginTop:12,color:"#94a3b8",fontSize:13}}>Analyzing location…</div></div>}
          </div>

          {error && <div style={S.err}><strong>Error: </strong>{error}</div>}

          {weather && scores && <>
            <div style={S.tabBar}>{TABS.map(t=><button key={t} onClick={()=>setTab(t)} style={tab===t?{...S.tab,...S.tabA}:S.tab}>
              {TAB_LABELS[t]}{t==="alerts"&&weather.alerts.length>0&&<span style={S.tabBdg}>{weather.alerts.length}</span>}
            </button>)}</div>

            <div style={S.panel}>
              {tab==="overview" && <div style={{animation:"fadeIn .3s ease"}}>
                <h3 style={S.pTitle}>Location Overview</h3>
                <p style={S.pText}>Analysis for <strong>{loc.display}</strong>.
                  {composite<=30&&" This location presents a low overall risk for construction."}
                  {composite>30&&composite<=60&&" This location has moderate weather risks — review recommendations carefully."}
                  {composite>60&&" Significant weather hazards detected. Specialized construction techniques strongly recommended."}</p>
                <div style={S.oGrid}>{Object.keys(RISK_CATEGORIES).map(k=><div key={k} style={S.oItem}>
                  <div style={{fontSize:26,marginBottom:6}}>{RISK_CATEGORIES[k].icon}</div>
                  <div style={{fontSize:11,color:"#94a3b8",marginBottom:4}}>{RISK_CATEGORIES[k].label}</div>
                  <div style={{fontSize:20,fontWeight:700,color:riskColor(scores[k])}}>{scores[k]}/10</div>
                </div>)}</div>
              </div>}

              {tab==="forecast" && <div style={{animation:"fadeIn .3s ease"}}>
                <h3 style={S.pTitle}>7-Day Forecast</h3>
                <div style={S.fGrid}>{weather.forecast.map((p,i)=><div key={i} style={S.fCard}>
                  <div style={{fontSize:12,fontWeight:600,color:"#cbd5e1",marginBottom:4}}>{p.name}</div>
                  <div style={{fontSize:24,fontWeight:200,color:"#f1f5f9",marginBottom:4}}>{p.temperature}°{p.temperatureUnit}</div>
                  <div style={{fontSize:12,color:"#64748b",lineHeight:1.4}}>{p.shortForecast}</div>
                </div>)}</div>
              </div>}

              {tab==="alerts" && <div style={{animation:"fadeIn .3s ease"}}>
                <h3 style={S.pTitle}>Active Weather Alerts</h3>
                {!weather.alerts.length ? <p style={S.pText}>No active weather alerts for this location.</p>
                : weather.alerts.map((a,i)=><div key={i} style={{...S.aCard,borderLeftColor:a.severity==="Severe"?"#ef4444":"#eab308"}}>
                  <div style={{fontSize:14,fontWeight:700,color:"#f1f5f9"}}>{a.event}</div>
                  <div style={{fontSize:11,color:"#94a3b8",marginTop:2}}>Severity: {a.severity}</div>
                  <div style={{fontSize:12,color:"#cbd5e1",marginTop:6,lineHeight:1.5}}>{a.headline}</div>
                </div>)}
              </div>}

              {tab==="risk" && <div style={{animation:"fadeIn .3s ease"}}>
                <h3 style={S.pTitle}>Risk Assessment Breakdown</h3>
                <p style={S.pText}>Scores derived from regional weather history and geographic hazard patterns.</p>
                {Object.keys(RISK_CATEGORIES).map(k=><div key={k} style={S.rRow}>
                  <div style={S.rLeft}><span style={{fontSize:18}}>{RISK_CATEGORIES[k].icon}</span><span>{RISK_CATEGORIES[k].label}</span></div>
                  <div style={S.barO}><div style={{...S.barI,width:`${scores[k]*10}%`,background:riskColor(scores[k])}}/></div>
                  <div style={{width:28,textAlign:"right",fontWeight:700,fontSize:14,color:riskColor(scores[k])}}>{scores[k]}</div>
                </div>)}
                <div style={S.compR}><span>Composite Score</span><span style={{color:compColor(composite),fontWeight:700,fontSize:22}}>{composite}/100 — {riskLabel(composite)}</span></div>
              </div>}

              {tab==="recommendations" && <div style={{animation:"fadeIn .3s ease"}}>
                <h3 style={S.pTitle}>Construction Recommendations</h3>
                {!activeRisks.length ? <p style={S.pText}>All risk categories below threshold. Standard construction practices should suffice.</p>
                : activeRisks.map(k=><div key={k} style={S.tipSec}>
                  <div style={S.tipH}><span>{RISK_CATEGORIES[k].icon}</span><span>{RISK_CATEGORIES[k].label}</span><span style={{marginLeft:"auto",fontSize:12,fontWeight:700,color:riskColor(scores[k])}}>Risk: {scores[k]}/10</span></div>
                  <ul style={{margin:0,paddingLeft:20}}>{CONSTRUCTION_TIPS[k].map((t,i)=><li key={i} style={{fontSize:13,color:"#94a3b8",lineHeight:1.8,marginBottom:2}}>{t}</li>)}</ul>
                </div>)}
                <p style={S.disc}>These recommendations are advisory. Always consult local building codes, a licensed structural engineer, and relevant FEMA/ICC standards before construction.</p>
              </div>}
            </div>
          </>}

          {!weather&&!loading&&!error && <div style={S.empty}>
            <svg width="56" height="56" viewBox="0 0 64 64" fill="none" style={{marginBottom:16,opacity:0.25}}><path d="M32 4L60 18v28L32 60 4 46V18L32 4z" stroke="#60a5fa" strokeWidth="2"/><circle cx="32" cy="32" r="8" stroke="#60a5fa" strokeWidth="1.5" fill="rgba(96,165,250,0.08)"/><path d="M32 12v8M32 44v8M12 32h8M44 32h8" stroke="#60a5fa" strokeWidth="1.5" opacity="0.3"/></svg>
            <div style={{fontSize:18,fontWeight:600,color:"#e2e8f0",marginBottom:8}}>Select a Location</div>
            <div style={{fontSize:13,color:"#64748b",maxWidth:340,lineHeight:1.6}}>Search for a US address or click the map to analyze weather risks and get construction recommendations.</div>
          </div>}
        </main>
      </div>
    </div>
  );
}

const S = {
  root:{fontFamily:"'DM Sans',-apple-system,sans-serif",background:"#0b0f1a",color:"#e2e8f0",minHeight:"100vh",display:"flex",flexDirection:"column"},
  header:{background:"linear-gradient(135deg,#0f172a,#151d35)",borderBottom:"1px solid rgba(255,255,255,0.06)",padding:"0 24px",height:56,display:"flex",alignItems:"center",flexShrink:0},
  headerInner:{display:"flex",justifyContent:"space-between",alignItems:"center",width:"100%",maxWidth:1440,margin:"0 auto"},
  logo:{display:"flex",alignItems:"center",gap:12},
  logoText:{fontSize:18,fontWeight:700,letterSpacing:3,color:"#f1f5f9"},
  logoSub:{fontSize:10,letterSpacing:1.5,textTransform:"uppercase",color:"#64748b"},
  simTag:{fontSize:9,letterSpacing:1.5,color:"#eab308",background:"rgba(234,179,8,0.08)",border:"1px solid rgba(234,179,8,0.18)",borderRadius:4,padding:"3px 8px",fontWeight:600},
  expBtn:{background:"rgba(96,165,250,0.08)",color:"#60a5fa",border:"1px solid rgba(96,165,250,0.18)",borderRadius:8,padding:"8px 16px",fontSize:13,fontWeight:600,cursor:"pointer",fontFamily:"inherit"},
  body:{display:"flex",flex:1,overflow:"hidden"},
  side:{width:300,background:"#0f1629",borderRight:"1px solid rgba(255,255,255,0.06)",padding:20,overflowY:"auto",display:"flex",flexDirection:"column",gap:16,flexShrink:0},
  lbl:{fontSize:10,textTransform:"uppercase",letterSpacing:1.5,color:"#475569",marginBottom:8,display:"block",fontWeight:600},
  inWrap:{display:"flex",alignItems:"center",gap:8,background:"rgba(255,255,255,0.035)",border:"1px solid rgba(255,255,255,0.07)",borderRadius:10,padding:"0 12px"},
  inp:{flex:1,background:"transparent",border:"none",padding:"11px 0",color:"#e2e8f0",fontSize:14,outline:"none",fontFamily:"inherit"},
  hint:{fontSize:11,color:"#334155",marginTop:6},
  suggs:{position:"absolute",top:"calc(100% + 4px)",left:0,right:0,background:"#1a2035",border:"1px solid rgba(255,255,255,0.1)",borderRadius:10,zIndex:100,maxHeight:220,overflowY:"auto",boxShadow:"0 12px 40px rgba(0,0,0,0.5)"},
  suggI:{padding:"10px 12px",fontSize:12,cursor:"pointer",display:"flex",gap:8,alignItems:"flex-start",borderBottom:"1px solid rgba(255,255,255,0.03)",color:"#cbd5e1",lineHeight:1.4},
  locCard:{background:"rgba(96,165,250,0.04)",border:"1px solid rgba(96,165,250,0.1)",borderRadius:10,padding:14},
  locN:{fontSize:13,fontWeight:600,color:"#e2e8f0",lineHeight:1.4,marginBottom:4},
  locC:{fontSize:11,color:"#64748b",fontFamily:"'JetBrains Mono',monospace"},
  condCard:{background:"rgba(255,255,255,0.02)",border:"1px solid rgba(255,255,255,0.05)",borderRadius:10,padding:14},
  tempBig:{fontSize:42,fontWeight:200,color:"#f1f5f9",lineHeight:1},
  stat:{display:"flex",flexDirection:"column",gap:2},
  statL:{fontSize:10,textTransform:"uppercase",color:"#475569",letterSpacing:1},
  statV:{fontSize:14,color:"#cbd5e1",fontWeight:500},
  rBadge:{textAlign:"center",padding:16,borderRadius:10,border:"2px solid",background:"rgba(255,255,255,0.015)"},
  alertBtn:{background:"rgba(239,68,68,0.07)",border:"1px solid rgba(239,68,68,0.18)",borderRadius:8,padding:"10px 14px",textAlign:"center",fontSize:13,fontWeight:600,color:"#ef4444",cursor:"pointer"},
  main:{flex:1,display:"flex",flexDirection:"column",overflow:"hidden",padding:20,gap:16},
  mapBox:{height:340,borderRadius:12,overflow:"hidden",position:"relative",border:"1px solid rgba(255,255,255,0.06)",flexShrink:0},
  mapOv:{position:"absolute",inset:0,background:"rgba(11,15,26,0.75)",display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",zIndex:10,backdropFilter:"blur(4px)"},
  spin:{width:32,height:32,border:"3px solid rgba(96,165,250,0.12)",borderTopColor:"#60a5fa",borderRadius:"50%",animation:"spin .8s linear infinite"},
  err:{background:"rgba(239,68,68,0.07)",border:"1px solid rgba(239,68,68,0.18)",borderRadius:10,padding:"12px 16px",fontSize:13,color:"#fca5a5"},
  tabBar:{display:"flex",gap:4,background:"rgba(255,255,255,0.02)",borderRadius:10,padding:4,flexShrink:0,border:"1px solid rgba(255,255,255,0.04)"},
  tab:{flex:1,padding:"9px 12px",borderRadius:8,border:"none",background:"transparent",color:"#64748b",fontSize:12,fontWeight:600,cursor:"pointer",transition:"all .2s",display:"flex",alignItems:"center",justifyContent:"center",gap:6,fontFamily:"inherit"},
  tabA:{background:"rgba(96,165,250,0.1)",color:"#60a5fa"},
  tabBdg:{background:"#ef4444",color:"#fff",borderRadius:10,padding:"1px 6px",fontSize:10,fontWeight:700},
  panel:{flex:1,overflowY:"auto",background:"rgba(255,255,255,0.012)",border:"1px solid rgba(255,255,255,0.04)",borderRadius:12,padding:24},
  pTitle:{fontSize:17,fontWeight:600,color:"#f1f5f9",marginBottom:8,marginTop:0},
  pText:{fontSize:13,color:"#94a3b8",lineHeight:1.7,marginBottom:16},
  oGrid:{display:"grid",gridTemplateColumns:"repeat(auto-fill,minmax(130px,1fr))",gap:10,marginTop:16},
  oItem:{background:"rgba(255,255,255,0.02)",border:"1px solid rgba(255,255,255,0.04)",borderRadius:10,padding:14,textAlign:"center"},
  fGrid:{display:"grid",gridTemplateColumns:"repeat(auto-fill,minmax(170px,1fr))",gap:10},
  fCard:{background:"rgba(255,255,255,0.02)",border:"1px solid rgba(255,255,255,0.04)",borderRadius:10,padding:14},
  aCard:{borderLeft:"3px solid",background:"rgba(255,255,255,0.02)",borderRadius:"0 10px 10px 0",padding:14,marginBottom:10},
  rRow:{display:"flex",alignItems:"center",gap:12,marginBottom:14},
  rLeft:{display:"flex",alignItems:"center",gap:8,width:170,fontSize:13,color:"#cbd5e1",flexShrink:0},
  barO:{flex:1,height:8,background:"rgba(255,255,255,0.04)",borderRadius:4,overflow:"hidden"},
  barI:{height:"100%",borderRadius:4,transition:"width .6s ease"},
  compR:{display:"flex",justifyContent:"space-between",alignItems:"center",marginTop:20,paddingTop:16,borderTop:"1px solid rgba(255,255,255,0.06)",fontSize:14,color:"#94a3b8"},
  tipSec:{marginBottom:16,background:"rgba(255,255,255,0.02)",border:"1px solid rgba(255,255,255,0.04)",borderRadius:10,padding:16},
  tipH:{display:"flex",alignItems:"center",gap:8,fontSize:14,fontWeight:600,color:"#e2e8f0",marginBottom:10},
  disc:{fontSize:11,color:"#475569",marginTop:20,padding:12,background:"rgba(255,255,255,0.02)",borderRadius:8,lineHeight:1.6,fontStyle:"italic"},
  empty:{flex:1,display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",textAlign:"center",padding:40},
};
