/* ═══════════════════════════════════════════════════════════════════════════
   GAD — Geospatial Architecture Database (frontend)
   ─────────────────────────────────────────────────────────────────────────── */

document.addEventListener('DOMContentLoaded', () => {

  /* ─── Constants ────────────────────────────────────────────────────────── */
  const RECENT_KEY = 'gad.recent';
  const COMPARE_KEY = 'gad.compare';
  const MAX_RECENT = 5;
  const MAX_COMPARE = 3;

  const RISK_LABELS = {
    hurricane: 'Hurricane / Tropical Storm',
    tornado:   'Tornado',
    flood:     'Flooding',
    winter:    'Winter Storm / Ice',
    heat:      'Extreme Heat',
    seismic:   'Seismic / Earthquake',
    wildfire:  'Wildfire',
  };

  const RISK_ICONS = {
    hurricane: '🌀', tornado: '🌪️', flood: '🌊', winter: '❄️',
    heat: '🔥', seismic: '⚡', wildfire: '🔥',
  };

  // Color + icon + label triplet for risk levels — colorblind-safe pairing
  const TIPS = {
    hurricane: [
      'Use hurricane straps/clips to secure roof to walls',
      'Install impact-resistant windows or hurricane shutters',
      'Reinforce garage doors — primary failure point in hurricanes',
      'Elevate the foundation above the base flood elevation (BFE)',
      'Use concrete block or reinforced masonry for exterior walls',
    ],
    tornado: [
      'Include a reinforced safe room (FEMA P-320 / ICC 500 compliant)',
      'Anchor the structure to a continuous foundation',
      'Use hip roofs instead of gable — better wind resistance',
      'Install continuous plywood sheathing on roof and walls',
      'Specify impact-rated exterior cladding and doors',
    ],
    flood: [
      'Elevate the lowest floor at least 1 ft above BFE',
      'Use flood-resistant materials below the Design Flood Elevation',
      'Install backflow valves on all sewer and drain lines',
      'Grade the site to slope away from the building on all sides',
      'Avoid finished basements in high-risk flood zones',
    ],
    winter: [
      'Design roof for regional snow load per ASCE 7',
      'Insulate to or above IECC climate-zone requirements',
      'Install heat cables along eaves and gutters to prevent ice dams',
      'Use frost-protected shallow foundations in cold climates',
      'Specify freeze-resistant exterior plumbing and hose bibs',
    ],
    heat: [
      'Specify high Solar Reflectance Index (SRI) roofing materials',
      'Design generous overhangs and shading on south/west facades',
      'Use insulated concrete forms (ICFs) for high thermal mass',
      'Plan for oversized HVAC capacity with redundancy',
      'Install radiant barriers in the attic space',
    ],
    seismic: [
      'Design to ASCE 7 seismic design category for the site class',
      'Use moment-resisting frames or shear walls per IBC requirements',
      'Anchor non-structural components (water heaters, HVAC, ducts)',
      'Specify base isolation or damping for high-importance structures',
      'Avoid soft-story configurations on the ground floor',
    ],
    wildfire: [
      'Use Class A fire-rated roofing (metal, tile, or asphalt shingle)',
      'Install ember-resistant vents (1/8" mesh) on attic and crawl spaces',
      'Specify non-combustible exterior siding (fiber cement, stucco, masonry)',
      'Maintain a 5-ft non-combustible zone around the structure',
      'Use tempered or dual-pane windows to resist heat exposure',
    ],
  };

  /* ─── DOM refs ─────────────────────────────────────────────────────────── */
  const $ = (id) => document.getElementById(id);
  const locationInput = $('locationInput');
  const suggestionsBox = $('suggestions');
  const sidebarContent = $('sidebarContent');
  const mapOverlay = $('mapOverlay');
  const exportBtn = $('exportBtn');
  const compareBtn = $('compareBtn');
  const compareCount = $('compareCount');
  const dataPanel = $('dataPanel');
  const emptyState = $('emptyState');
  const alertCount = $('alertCount');
  const offlineBanner = $('offlineBanner');
  const recentSearches = $('recentSearches');
  const recentList = $('recentList');
  const clearRecentBtn = $('clearRecentBtn');
  const suggestedCities = $('suggestedCities');
  const exportModal = $('exportModal');
  const exportCancelBtn = $('exportCancelBtn');
  const exportConfirmBtn = $('exportConfirmBtn');
  const comparePanel = $('comparePanel');
  const compareCloseBtn = $('compareCloseBtn');
  const compareContent = $('compareContent');
  const toastContainer = $('toastContainer');

  const tabs = document.querySelectorAll('.tab-btn');
  const tabContents = document.querySelectorAll('.tab-content');

  /* ─── State ────────────────────────────────────────────────────────────── */
  let currentData = null;       // Last analyzed location's full payload
  let activeTab = 'overview';
  let activeSuggestionIndex = -1;
  let searchTimeout = null;
  let pendingRetry = null;      // For offline → reconnect retry
  let map = null;
  let marker = null;
  let radarChart = null;
  let trendChart = null;

  /* ─── Helpers: classify risk score → level + color + icon ──────────────── */
  function riskLevel(score, isComposite = false) {
    if (isComposite) {
      if (score <= 30) return { label: 'Low', color: '#22c55e', icon: '✓' };
      if (score <= 60) return { label: 'Moderate', color: '#eab308', icon: '⚠' };
      return { label: 'High', color: '#ef4444', icon: '⚠' };
    }
    if (score <= 3) return { label: 'Low', color: '#22c55e', icon: '✓' };
    if (score <= 6) return { label: 'Moderate', color: '#eab308', icon: '⚠' };
    return { label: 'High', color: '#ef4444', icon: '⚠' };
  }

  /* ─── Toast notifications ─────────────────────────────────────────────── */
  function toast(msg, type = 'info', ttl = 3500) {
    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    el.setAttribute('role', 'status');
    el.textContent = msg;
    toastContainer.appendChild(el);
    requestAnimationFrame(() => el.classList.add('visible'));
    setTimeout(() => {
      el.classList.remove('visible');
      setTimeout(() => el.remove(), 300);
    }, ttl);
  }

  /* ─── Leaflet map init ────────────────────────────────────────────────── */
  function initMap() {
    map = L.map('leafletMap', { zoomControl: true }).setView([39.5, -98.35], 4);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© OpenStreetMap contributors',
      maxZoom: 18,
    }).addTo(map);
    map.on('click', (e) => analyzeLocation(e.latlng.lat, e.latlng.lng));
    setTimeout(() => map.invalidateSize(), 100);
  }
  initMap();

  function setMapView(lat, lon, zoom = 11) {
    if (!map) return;
    map.setView([lat, lon], zoom);
    if (marker) marker.remove();
    marker = L.marker([lat, lon]).addTo(map);
  }

  /* ─── Search with debounce + suggestion list ──────────────────────────── */
  locationInput.addEventListener('input', (e) => {
    const q = e.target.value.trim();
    activeSuggestionIndex = -1;
    if (q.length < 3) {
      hideSuggestions();
      return;
    }
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => fetchSuggestions(q), 350);
  });

  async function fetchSuggestions(q) {
    if (!navigator.onLine) return;
    try {
      const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
      if (!res.ok) throw new Error('Search failed');
      renderSuggestions(await res.json());
    } catch (err) {
      console.error(err);
    }
  }

  function renderSuggestions(items) {
    if (!items || !items.length) {
      suggestionsBox.innerHTML = '<div class="suggestion-item" role="option" aria-disabled="true">No results found</div>';
    } else {
      suggestionsBox.innerHTML = items.map((it, i) => `
        <div class="suggestion-item" role="option" id="suggestion-${i}"
             data-lat="${it.lat}" data-lon="${it.lon}" data-display="${escapeAttr(it.display)}">
          <span class="suggestion-icon" aria-hidden="true">📍</span>
          <span>${escapeHtml(it.display)}</span>
        </div>`).join('');
    }
    suggestionsBox.classList.remove('hidden');
    locationInput.setAttribute('aria-expanded', 'true');

    suggestionsBox.querySelectorAll('.suggestion-item').forEach((item) => {
      item.addEventListener('click', () => {
        const lat = parseFloat(item.dataset.lat);
        const lon = parseFloat(item.dataset.lon);
        if (!isNaN(lat)) {
          locationInput.value = item.dataset.display;
          analyzeLocation(lat, lon, item.dataset.display);
        }
      });
    });
  }

  function hideSuggestions() {
    suggestionsBox.innerHTML = '';
    suggestionsBox.classList.add('hidden');
    locationInput.setAttribute('aria-expanded', 'false');
    locationInput.removeAttribute('aria-activedescendant');
    activeSuggestionIndex = -1;
  }

  /* Keyboard navigation through suggestions */
  locationInput.addEventListener('keydown', (e) => {
    const items = suggestionsBox.querySelectorAll('.suggestion-item[data-lat]');
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (!items.length) return;
      activeSuggestionIndex = Math.min(activeSuggestionIndex + 1, items.length - 1);
      highlightSuggestion(items);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (!items.length) return;
      activeSuggestionIndex = Math.max(activeSuggestionIndex - 1, 0);
      highlightSuggestion(items);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const target = activeSuggestionIndex >= 0 ? items[activeSuggestionIndex] : items[0];
      if (target) target.click();
    } else if (e.key === 'Escape') {
      hideSuggestions();
    }
  });

  function highlightSuggestion(items) {
    items.forEach((it, i) => {
      it.classList.toggle('active', i === activeSuggestionIndex);
    });
    if (activeSuggestionIndex >= 0) {
      const el = items[activeSuggestionIndex];
      locationInput.setAttribute('aria-activedescendant', el.id);
      el.scrollIntoView({ block: 'nearest' });
    }
  }

  /* Close suggestions on outside click */
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.search-box')) hideSuggestions();
  });

  /* ─── Suggested city chips + recent searches ──────────────────────────── */
  suggestedCities.querySelectorAll('.chip').forEach((chip) => {
    chip.addEventListener('click', () => {
      const lat = parseFloat(chip.dataset.lat);
      const lon = parseFloat(chip.dataset.lon);
      analyzeLocation(lat, lon, chip.dataset.name);
    });
  });

  function loadRecent() {
    try { return JSON.parse(localStorage.getItem(RECENT_KEY) || '[]'); }
    catch { return []; }
  }
  function saveRecent(item) {
    let recent = loadRecent().filter(r => r.display !== item.display);
    recent.unshift(item);
    recent = recent.slice(0, MAX_RECENT);
    localStorage.setItem(RECENT_KEY, JSON.stringify(recent));
    renderRecent();
  }
  function renderRecent() {
    const recent = loadRecent();
    if (!recent.length) {
      recentSearches.hidden = true;
      return;
    }
    recentSearches.hidden = false;
    recentList.innerHTML = recent.map((r, i) => `
      <li>
        <button class="recent-item" data-idx="${i}" title="${escapeAttr(r.display)}">
          <span aria-hidden="true">↻</span>
          <span class="recent-name">${escapeHtml(shortenName(r.display))}</span>
        </button>
      </li>
    `).join('');
    recentList.querySelectorAll('.recent-item').forEach((b) => {
      b.addEventListener('click', () => {
        const r = loadRecent()[parseInt(b.dataset.idx, 10)];
        if (r) analyzeLocation(r.lat, r.lon, r.display);
      });
    });
  }
  clearRecentBtn.addEventListener('click', () => {
    localStorage.removeItem(RECENT_KEY);
    renderRecent();
    toast('Recent searches cleared', 'info');
  });
  renderRecent();

  /* ─── Tabs (with arrow-key navigation) ────────────────────────────────── */
  tabs.forEach((tab, idx) => {
    tab.addEventListener('click', () => switchTab(tab.dataset.tab));
    tab.addEventListener('keydown', (e) => {
      let i = idx;
      if (e.key === 'ArrowRight') i = (idx + 1) % tabs.length;
      else if (e.key === 'ArrowLeft') i = (idx - 1 + tabs.length) % tabs.length;
      else if (e.key === 'Home') i = 0;
      else if (e.key === 'End') i = tabs.length - 1;
      else return;
      e.preventDefault();
      tabs[i].focus();
      switchTab(tabs[i].dataset.tab);
    });
  });

  function switchTab(name) {
    activeTab = name;
    tabs.forEach((t) => {
      const isActive = t.dataset.tab === name;
      t.classList.toggle('active', isActive);
      t.setAttribute('aria-selected', isActive ? 'true' : 'false');
      t.tabIndex = isActive ? 0 : -1;
    });
    tabContents.forEach((c) => {
      const isActive = c.id === name;
      c.classList.toggle('active', isActive);
      c.hidden = !isActive;
    });
    // Re-render charts on tab show (Chart.js needs visible canvas)
    if (name === 'risk' && currentData) renderRiskChart();
    if (name === 'history' && currentData) renderTrendChart();
  }

  /* ─── Analyze location ────────────────────────────────────────────────── */
  async function analyzeLocation(lat, lon, displayName) {
    if (!navigator.onLine) {
      toast('You are offline. Will retry when you reconnect.', 'warn', 5000);
      pendingRetry = () => analyzeLocation(lat, lon, displayName);
      return;
    }

    hideSuggestions();
    setMapView(lat, lon, 11);
    showOverlay(true);
    emptyState.hidden = true;

    try {
      const res = await fetch(`/api/weather?lat=${lat}&lon=${lon}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to fetch weather data');

      const display = displayName || `${lat.toFixed(4)}, ${lon.toFixed(4)}`;
      currentData = { lat, lon, display, ...data };

      // Fetch historical events in parallel
      try {
        const histRes = await fetch(`/api/history?state=${data.state}`);
        if (histRes.ok) {
          const hist = await histRes.json();
          currentData.history = hist;
        }
      } catch { /* non-fatal */ }

      saveRecent({ lat, lon, display });
      renderUI(currentData);
      toast(`Analysis complete for ${shortenName(display)}`, 'success');
    } catch (err) {
      sidebarContent.innerHTML = `
        <div class="card error-card" role="alert">
          <h3>Error</h3>
          <p>${escapeHtml(err.message)}</p>
        </div>`;
      dataPanel.hidden = true;
      exportBtn.hidden = true;
      emptyState.hidden = false;
      toast(err.message, 'error', 5000);
    } finally {
      showOverlay(false);
    }
  }

  function showOverlay(on) {
    mapOverlay.classList.toggle('active', on);
    mapOverlay.setAttribute('aria-hidden', on ? 'false' : 'true');
  }

  /* ─── Render UI from analysis data ────────────────────────────────────── */
  function renderUI(d) {
    dataPanel.hidden = false;
    exportBtn.hidden = false;
    compareBtn.hidden = false;
    emptyState.hidden = true;

    const compLevel = riskLevel(d.composite, true);
    const obs = d.observation || {};

    // Sidebar summary
    sidebarContent.innerHTML = `
      <div class="card">
        <p class="section-label">Location</p>
        <p class="loc-name">${escapeHtml(d.display)}</p>
        <p class="loc-coords">${d.lat.toFixed(4)}°, ${d.lon.toFixed(4)}° · ${d.state || '—'}</p>
      </div>

      ${obs.temperature != null ? `
      <div class="card">
        <p class="section-label">Current Conditions</p>
        <div class="temp-large">${obs.temperature}°<span class="temp-unit">F</span></div>
        <p class="cond-text">${escapeHtml(obs.conditions || '')}</p>
        <div class="stat-row">
          <div class="stat"><span class="stat-label">Wind</span><span class="stat-value">${escapeHtml(obs.windSpeed || 'N/A')}</span></div>
        </div>
      </div>` : ''}

      <div class="composite-score" style="border-color:${compLevel.color}">
        <p class="section-label">Composite Risk</p>
        <div class="composite-value" style="color:${compLevel.color}">${d.composite}</div>
        <div class="composite-label" style="color:${compLevel.color}">
          <span aria-hidden="true">${compLevel.icon}</span> ${compLevel.label.toUpperCase()}
        </div>
        <div class="risk-bar" role="progressbar" aria-valuenow="${d.composite}"
             aria-valuemin="0" aria-valuemax="100"
             aria-label="Composite risk score: ${d.composite} of 100, ${compLevel.label}">
          <div class="risk-bar-fill" style="width:${d.composite}%; background:${compLevel.color}"></div>
        </div>
      </div>

      <div class="card meta-card">
        <p class="section-label">Site Metadata</p>
        <div class="meta-row"><span>IECC Climate Zone</span><strong>${escapeHtml(d.climateZone || 'N/A')}</strong></div>
        <div class="meta-row"><span>Building Code</span><strong>${escapeHtml(d.buildingCode || 'N/A')}</strong></div>
      </div>

      <button id="addToCompareBtn" class="btn-secondary">⇄ Add to Compare</button>
    `;
    $('addToCompareBtn').addEventListener('click', addCurrentToCompare);

    renderOverview(d);
    renderForecast(d);
    renderHistory(d);
    renderAlerts(d);
    renderRiskTab(d);
    renderRecommendations(d);

    // Update alert badge
    if (d.alerts && d.alerts.length) {
      alertCount.textContent = d.alerts.length;
      alertCount.hidden = false;
    } else {
      alertCount.hidden = true;
    }
  }

  function renderOverview(d) {
    const { composite } = d;
    const compLevel = riskLevel(composite, true);
    let summary;
    if (composite <= 30) summary = 'This location presents low overall risk for construction. Standard practices generally apply, but review individual hazards below.';
    else if (composite <= 60) summary = 'This location has moderate weather-related risks. Review the recommendations carefully and consult local code requirements.';
    else summary = 'Significant weather hazards detected. Specialized construction techniques and engineering review are strongly recommended.';

    $('overview').innerHTML = `
      <h3 class="panel-title">Site Summary</h3>
      <p class="panel-text">Analysis for <strong>${escapeHtml(d.display)}</strong>. ${summary}</p>
      <div class="overview-grid">
        ${Object.keys(RISK_LABELS).map(k => `
          <div class="overview-card">
            <div class="overview-icon" aria-hidden="true">${RISK_ICONS[k]}</div>
            <p class="overview-label">${RISK_LABELS[k]}</p>
            <p class="overview-score" style="color:${riskLevel(d.scores[k]).color}">
              <span class="risk-pill" style="background:${riskLevel(d.scores[k]).color}20;color:${riskLevel(d.scores[k]).color}">
                ${riskLevel(d.scores[k]).icon} ${riskLevel(d.scores[k]).label}
              </span>
            </p>
            <p class="overview-num">${d.scores[k]}/10</p>
          </div>`).join('')}
      </div>
    `;
  }

  function renderForecast(d) {
    if (!d.forecast || !d.forecast.length) {
      $('forecast').innerHTML = '<p class="panel-text">Forecast data not available for this location.</p>';
      return;
    }
    $('forecast').innerHTML = `
      <h3 class="panel-title">7-Day Forecast</h3>
      <div class="forecast-grid">
        ${d.forecast.map(f => `
          <div class="forecast-card">
            <p class="forecast-name">${escapeHtml(f.name)}</p>
            <p class="forecast-temp">${f.temperature}°${f.temperatureUnit}</p>
            <p class="forecast-desc">${escapeHtml(f.shortForecast)}</p>
          </div>`).join('')}
      </div>
    `;
  }

  function renderHistory(d) {
    const h = d.history || { events: [], trends: {} };
    const eventsHtml = h.events && h.events.length ? h.events.map(ev => {
      // Prefer the curated wiki URL; fall back to a Wikipedia search if missing.
      const wikiUrl = ev.wiki
        || `https://en.wikipedia.org/wiki/Special:Search?search=${encodeURIComponent(ev.event)}`;
      return `
        <div class="event-card">
          <div class="event-header">
            <a class="event-link"
               href="${escapeAttr(wikiUrl)}"
               target="_blank"
               rel="noopener noreferrer"
               aria-label="Open Wikipedia article for ${escapeAttr(ev.event)} (opens in a new tab)">
              <strong>${escapeHtml(ev.event)}</strong>
              <span class="external-icon" aria-hidden="true">↗</span>
            </a>
            <span class="event-year">${ev.year}</span>
          </div>
          <span class="severity-pill severity-${(ev.severity || '').toLowerCase()}">${escapeHtml(ev.severity)}</span>
          <p class="event-note">${escapeHtml(ev.note)}</p>
        </div>
      `;
    }).join('') : '<p class="panel-text">No notable historical events on file for this state.</p>';

    $('history').innerHTML = `
      <h3 class="panel-title">Historical Disasters</h3>
      <p class="panel-text">Notable past disasters and decade-by-decade severe-weather event frequency for ${escapeHtml(d.state || 'this state')}.</p>
      <div class="history-events">${eventsHtml}</div>
      <h4 class="panel-subtitle">Severe Weather Events per Decade</h4>
      <div class="chart-wrap"><canvas id="trendChart" aria-label="Bar chart of severe weather events by decade"></canvas></div>
      <p class="caption">Source: NOAA Storm Events Database (state-level aggregates).</p>
    `;
    if (activeTab === 'history') renderTrendChart();
  }

  function renderTrendChart() {
    const canvas = $('trendChart');
    if (!canvas || !currentData?.history?.trends) return;
    const trends = currentData.history.trends;
    if (trendChart) trendChart.destroy();
    trendChart = new Chart(canvas, {
      type: 'bar',
      data: {
        labels: Object.keys(trends),
        datasets: [{
          label: 'Events per decade',
          data: Object.values(trends),
          backgroundColor: 'rgba(96,165,250,0.55)',
          borderColor: '#60a5fa',
          borderWidth: 1.5,
          borderRadius: 4,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          y: { beginAtZero: true, ticks: { color: '#94a3b8' }, grid: { color: 'rgba(255,255,255,0.05)' } },
          x: { ticks: { color: '#94a3b8' }, grid: { display: false } },
        },
      },
    });
  }

  function renderAlerts(d) {
    if (!d.alerts || !d.alerts.length) {
      $('alerts').innerHTML = '<p class="panel-text">No active weather alerts for this location.</p>';
      return;
    }
    $('alerts').innerHTML = `
      <h3 class="panel-title">Active Weather Alerts</h3>
      ${d.alerts.map(a => {
        // Backend ships a `url` linking to the NWS safety page for this
        // alert type. Defensive fallback to the NWS /alerts overview if
        // missing for any reason.
        const infoUrl = a.url || 'https://www.weather.gov/alerts';
        return `
        <div class="alert-card severity-${(a.severity || '').toLowerCase()}" role="alert">
          <div class="alert-header">
            <a class="alert-link"
               href="${escapeAttr(infoUrl)}"
               target="_blank"
               rel="noopener noreferrer"
               aria-label="Learn more about ${escapeAttr(a.event || 'this alert')} on weather.gov (opens in a new tab)">
              <strong>${escapeHtml(a.event)}</strong>
              <span class="external-icon" aria-hidden="true">↗</span>
            </a>
            <span class="severity-pill severity-${(a.severity || '').toLowerCase()}">${escapeHtml(a.severity)}</span>
          </div>
          <p>${escapeHtml(a.headline || '')}</p>
        </div>`;
      }).join('')}
    `;
  }

  function renderRiskTab(d) {
    const compLevel = riskLevel(d.composite, true);
    $('risk').innerHTML = `
      <h3 class="panel-title">Risk Assessment Breakdown</h3>
      <p class="panel-text">Scores derived from regional weather history, geographic hazard patterns, and seismic/wildfire profiles.</p>

      <div class="risk-layout">
        <div class="risk-list">
          ${Object.keys(RISK_LABELS).map(k => {
            const lvl = riskLevel(d.scores[k]);
            return `
              <div class="risk-row">
                <div class="risk-label">
                  <span aria-hidden="true">${RISK_ICONS[k]}</span>
                  <span>${RISK_LABELS[k]}</span>
                </div>
                <div class="risk-bar" role="progressbar" aria-valuenow="${d.scores[k]}"
                     aria-valuemin="0" aria-valuemax="10"
                     aria-label="${RISK_LABELS[k]} risk: ${d.scores[k]} of 10, ${lvl.label}">
                  <div class="risk-bar-fill" style="width:${d.scores[k] * 10}%; background:${lvl.color}"></div>
                </div>
                <span class="risk-pill" style="background:${lvl.color}20;color:${lvl.color}">
                  ${lvl.icon} ${d.scores[k]}/10
                </span>
              </div>`;
          }).join('')}
        </div>

        <div class="risk-chart-wrap">
          <canvas id="radarChart" aria-label="Radar chart of all risk categories"></canvas>
        </div>
      </div>

      <div class="composite-row">
        <span>Composite Risk Score</span>
        <strong style="color:${compLevel.color}">${d.composite}/100 — ${compLevel.label}</strong>
      </div>
    `;
    if (activeTab === 'risk') renderRiskChart();
  }

  function renderRiskChart() {
    const canvas = $('radarChart');
    if (!canvas || !currentData) return;
    if (radarChart) radarChart.destroy();
    radarChart = new Chart(canvas, {
      type: 'radar',
      data: {
        labels: Object.keys(RISK_LABELS).map(k => RISK_LABELS[k]),
        datasets: [{
          label: 'Risk Score',
          data: Object.keys(RISK_LABELS).map(k => currentData.scores[k]),
          backgroundColor: 'rgba(96,165,250,0.25)',
          borderColor: '#60a5fa',
          borderWidth: 2,
          pointBackgroundColor: '#60a5fa',
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          r: {
            min: 0, max: 10,
            angleLines: { color: 'rgba(255,255,255,0.08)' },
            grid: { color: 'rgba(255,255,255,0.08)' },
            pointLabels: { color: '#cbd5e1', font: { size: 11 } },
            ticks: { color: '#475569', backdropColor: 'transparent', stepSize: 2 },
          },
        },
      },
    });
  }

  function renderRecommendations(d) {
    const active = Object.entries(d.scores)
      .filter(([, v]) => v >= 3)
      .sort((a, b) => b[1] - a[1]);

    if (!active.length) {
      $('recommendations').innerHTML = '<p class="panel-text">All risk categories below threshold. Standard construction practices apply.</p>';
      return;
    }

    $('recommendations').innerHTML = `
      <h3 class="panel-title">Construction Recommendations</h3>
      <p class="panel-text">Recommendations based on the highest-scoring hazards for this site, ranked by severity.</p>
      ${active.map(([k, v]) => {
        const lvl = riskLevel(v);
        return `
          <div class="tip-section">
            <div class="tip-header">
              <span aria-hidden="true">${RISK_ICONS[k]}</span>
              <strong>${RISK_LABELS[k]}</strong>
              <span class="risk-pill" style="background:${lvl.color}20;color:${lvl.color};margin-left:auto">
                ${lvl.icon} Risk ${v}/10
              </span>
            </div>
            <ul class="tips-list">
              ${(TIPS[k] || []).map(t => `<li>${escapeHtml(t)}</li>`).join('')}
            </ul>
          </div>`;
      }).join('')}
      <p class="disclaimer">These recommendations are advisory. Always consult local building codes, a licensed structural engineer, and relevant FEMA/ICC standards before construction.</p>
    `;
  }

  /* ─── Export modal: PDF or CSV ───────────────────────────────────────── */
  exportBtn.addEventListener('click', openExportModal);
  function openExportModal() {
    if (!currentData) return;
    exportModal.hidden = false;
    requestAnimationFrame(() => exportModal.classList.add('open'));
    document.querySelector('input[name="exportFormat"][value="pdf"]').focus();
  }
  function closeModal(modal) {
    modal.classList.remove('open');
    setTimeout(() => modal.hidden = true, 200);
  }
  document.querySelectorAll('[data-close]').forEach(el =>
    el.addEventListener('click', (e) => closeModal(e.target.closest('.modal, .compare-panel')))
  );
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      if (!exportModal.hidden) closeModal(exportModal);
      if (!comparePanel.hidden) closeModal(comparePanel);
    }
  });

  exportConfirmBtn.addEventListener('click', async () => {
    const fmt = document.querySelector('input[name="exportFormat"]:checked').value;
    closeModal(exportModal);
    if (fmt === 'csv') downloadCSV();
    else await downloadPDF();
  });

  function downloadCSV() {
    const d = currentData;
    const rows = [
      ['Geospatial Architecture Database — Site Report'],
      ['Location', `"${d.display}"`],
      ['Coordinates', `${d.lat}, ${d.lon}`],
      ['State', d.state || ''],
      ['IECC Climate Zone', d.climateZone || ''],
      ['Building Code', d.buildingCode || ''],
      ['Generated', new Date().toISOString()],
      [],
      ['=== COMPOSITE RISK ==='],
      ['Composite Score', `${d.composite}/100`],
      [],
      ['=== HAZARD ASSESSMENT ==='],
      ['Category', 'Score (0-10)'],
    ];
    Object.keys(RISK_LABELS).forEach(k => rows.push([RISK_LABELS[k], d.scores[k]]));
    rows.push([], ['=== 7-DAY FORECAST ==='], ['Period', 'Temperature', 'Conditions']);
    (d.forecast || []).forEach(f => rows.push([f.name, `${f.temperature}°${f.temperatureUnit}`, `"${f.shortForecast}"`]));
    rows.push([], ['=== ACTIVE ALERTS ==='], ['Event', 'Severity', 'Headline']);
    if (!d.alerts || !d.alerts.length) rows.push(['None', '', '']);
    else d.alerts.forEach(a => rows.push([a.event, a.severity, `"${a.headline}"`]));
    rows.push([], ['=== HISTORICAL EVENTS ==='], ['Year', 'Event', 'Severity', 'Note']);
    (d.history?.events || []).forEach(e => rows.push([e.year, `"${e.event}"`, e.severity, `"${e.note}"`]));
    rows.push([], ['=== CONSTRUCTION RECOMMENDATIONS ===']);
    Object.keys(RISK_LABELS).forEach(k => {
      if (d.scores[k] >= 3 && TIPS[k]) {
        rows.push([`--- ${RISK_LABELS[k]} ---`]);
        TIPS[k].forEach(t => rows.push([`"${t}"`]));
      }
    });

    const csv = rows.map(r => r.join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `GAD_Report_${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    toast('CSV report exported successfully', 'success');
  }

  async function downloadPDF() {
    try {
      const res = await fetch('/api/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(currentData),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || 'PDF generation failed');
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `GAD_Report_${new Date().toISOString().slice(0, 10)}.pdf`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      toast('PDF report exported successfully', 'success');
    } catch (err) {
      toast(`Export failed: ${err.message}`, 'error', 5000);
    }
  }

  /* ─── Comparison mode ─────────────────────────────────────────────────── */
  function loadCompareSet() {
    try { return JSON.parse(sessionStorage.getItem(COMPARE_KEY) || '[]'); }
    catch { return []; }
  }
  function saveCompareSet(arr) {
    sessionStorage.setItem(COMPARE_KEY, JSON.stringify(arr));
    updateCompareBadge();
  }
  function updateCompareBadge() {
    const n = loadCompareSet().length;
    compareCount.textContent = n;
    compareBtn.classList.toggle('has-items', n > 0);
  }
  function addCurrentToCompare() {
    if (!currentData) return;
    let arr = loadCompareSet();
    if (arr.find(x => x.display === currentData.display)) {
      toast('Location already in comparison', 'info');
      return;
    }
    if (arr.length >= MAX_COMPARE) {
      toast(`Comparison is limited to ${MAX_COMPARE} locations.`, 'warn');
      return;
    }
    arr.push({
      display: currentData.display,
      lat: currentData.lat, lon: currentData.lon,
      state: currentData.state, composite: currentData.composite,
      scores: currentData.scores,
      climateZone: currentData.climateZone,
    });
    saveCompareSet(arr);
    toast(`Added to comparison (${arr.length}/${MAX_COMPARE})`, 'success');
  }

  compareBtn.addEventListener('click', () => {
    renderCompare();
    comparePanel.hidden = false;
    requestAnimationFrame(() => comparePanel.classList.add('open'));
  });

  function renderCompare() {
    const arr = loadCompareSet();
    if (!arr.length) {
      compareContent.innerHTML = '<p class="empty-msg">No locations saved yet. Analyze a site, then click "Add to Compare" to start.</p>';
      return;
    }
    const cats = Object.keys(RISK_LABELS);
    compareContent.innerHTML = `
      <table class="compare-table" aria-label="Side-by-side risk comparison">
        <thead>
          <tr>
            <th scope="col">Hazard</th>
            ${arr.map((loc, i) => `
              <th scope="col">
                <div class="compare-th">
                  <span class="compare-loc">${escapeHtml(shortenName(loc.display))}</span>
                  <button class="link-btn" data-rm="${i}" aria-label="Remove ${escapeAttr(loc.display)}">✕</button>
                </div>
              </th>
            `).join('')}
          </tr>
        </thead>
        <tbody>
          <tr class="compare-composite">
            <th scope="row">Composite Risk</th>
            ${arr.map(loc => {
              const lvl = riskLevel(loc.composite, true);
              return `<td><strong style="color:${lvl.color}">${loc.composite}/100</strong> ${lvl.label}</td>`;
            }).join('')}
          </tr>
          <tr>
            <th scope="row">Climate Zone</th>
            ${arr.map(loc => `<td>${escapeHtml(loc.climateZone || '—')}</td>`).join('')}
          </tr>
          ${cats.map(k => `
            <tr>
              <th scope="row"><span aria-hidden="true">${RISK_ICONS[k]}</span> ${RISK_LABELS[k]}</th>
              ${arr.map(loc => {
                const lvl = riskLevel(loc.scores[k]);
                return `<td><span class="risk-pill" style="background:${lvl.color}20;color:${lvl.color}">${loc.scores[k]}/10</span></td>`;
              }).join('')}
            </tr>
          `).join('')}
        </tbody>
      </table>
      <div class="compare-actions">
        <button id="compareClearBtn" class="btn-ghost">Clear All</button>
      </div>
    `;
    compareContent.querySelectorAll('[data-rm]').forEach(b => {
      b.addEventListener('click', () => {
        const arr2 = loadCompareSet();
        arr2.splice(parseInt(b.dataset.rm, 10), 1);
        saveCompareSet(arr2);
        renderCompare();
      });
    });
    $('compareClearBtn').addEventListener('click', () => {
      saveCompareSet([]);
      renderCompare();
    });
  }
  updateCompareBadge();

  /* ─── Offline detection ───────────────────────────────────────────────── */
  function updateOnlineStatus() {
    if (navigator.onLine) {
      offlineBanner.hidden = true;
      if (pendingRetry) {
        toast('Reconnected. Retrying…', 'success');
        const fn = pendingRetry;
        pendingRetry = null;
        fn();
      }
    } else {
      offlineBanner.hidden = false;
    }
  }
  window.addEventListener('online', updateOnlineStatus);
  window.addEventListener('offline', updateOnlineStatus);
  updateOnlineStatus();

  /* ─── Utilities ───────────────────────────────────────────────────────── */
  function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[c]);
  }
  function escapeAttr(s) { return escapeHtml(s); }
  function shortenName(s) {
    if (!s) return '—';
    return s.length > 50 ? s.slice(0, 50) + '…' : s;
  }
});
