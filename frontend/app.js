document.addEventListener('DOMContentLoaded', () => {
    const locationInput = document.getElementById('locationInput');
    const suggestionsBox = document.getElementById('suggestions');
    const sidebarContent = document.getElementById('sidebarContent');
    const googleMap = document.getElementById('googleMap');
    const mapOverlay = document.getElementById('mapOverlay');
    const exportBtn = document.getElementById('exportBtn');
    const dataPanel = document.getElementById('dataPanel');
    const alertCount = document.getElementById('alertCount');
    
    // Tabs state
    const tabs = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');
    
    let currentData = null; // Store weather/risk data for export
    
    // Default Map
    googleMap.src = `https://maps.google.com/maps?q=United+States&hl=en&z=4&output=embed`;

    // Tab switching
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            tabs.forEach(t => t.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));
            tab.classList.add('active');
            document.getElementById(tab.dataset.tab).classList.add('active');
        });
    });

    let searchTimeout;

    locationInput.addEventListener('input', (e) => {
        const query = e.target.value.trim();
        if (query.length < 3) {
            suggestionsBox.innerHTML = '';
            suggestionsBox.classList.add('hidden');
            return;
        }

        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(async () => {
            try {
                const res = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
                const data = await res.json();
                renderSuggestions(data);
            } catch (err) {
                console.error(err);
            }
        }, 400);
    });

    function renderSuggestions(data) {
        if (!data || data.length === 0) {
            suggestionsBox.innerHTML = '<div class="suggestion-item">No results found</div>';
        } else {
            suggestionsBox.innerHTML = data.map(item => `
                <div class="suggestion-item" data-lat="${item.lat}" data-lon="${item.lon}" data-display="${item.display}">
                    ${item.display}
                </div>
            `).join('');
        }
        suggestionsBox.classList.remove('hidden');

        document.querySelectorAll('.suggestion-item').forEach(item => {
            item.addEventListener('click', (e) => {
                const trg = e.currentTarget;
                if(!trg.dataset.lat) return;
                const lat = parseFloat(trg.dataset.lat);
                const lon = parseFloat(trg.dataset.lon);
                const display = trg.dataset.display;
                
                locationInput.value = display;
                suggestionsBox.classList.add('hidden');
                
                analyzeLocation(lat, lon, display);
            });
        });
    }

    async function analyzeLocation(lat, lon, display) {
        mapOverlay.classList.add('active');
        googleMap.src = `https://maps.google.com/maps?q=${lat},${lon}&hl=en&z=12&output=embed`;
        
        try {
            const res = await fetch(`/api/weather?lat=${lat}&lon=${lon}`);
            const data = await res.json();
            
            if (!res.ok) {
                throw new Error(data.error || 'Failed to fetch weather data');
            }
            
            currentData = { lat, lon, display, ...data };
            renderUI(currentData);
        } catch (err) {
            sidebarContent.innerHTML = `
                <div class="card" style="border-color: var(--danger)">
                    <h3 style="color: var(--danger)">Error</h3>
                    <p style="font-size:0.9rem; margin-top:0.5rem; color:var(--text-secondary);">${err.message}</p>
                </div>
            `;
            dataPanel.style.display = 'none';
            exportBtn.style.display = 'none';
        } finally {
            mapOverlay.classList.remove('active');
        }
    }

    function getColor(score) {
        if (score <= 3) return 'var(--success)';
        if (score <= 6) return 'var(--warning)';
        return 'var(--danger)';
    }

    function getColorComp(score) {
        if (score <= 30) return 'var(--success)';
        if (score <= 60) return 'var(--warning)';
        return 'var(--danger)';
    }

    const RISK_LABELS = {
        hurricane: 'Hurricane / Tropical Storm',
        tornado: 'Tornado',
        flood: 'Flooding',
        winter: 'Winter Storm / Ice',
        heat: 'Extreme Heat'
    };

    const TIPS = {
        hurricane: [
            "Use hurricane straps/clips to secure roof to walls",
            "Install impact-resistant windows or hurricane shutters",
            "Reinforce garage doors — primary failure point in hurricanes",
            "Elevate the foundation above the base flood elevation (BFE)",
            "Use concrete block or reinforced masonry for exterior walls"
        ],
        tornado: [
            "Include a reinforced safe room (FEMA P-320 / ICC 500 compliant)",
            "Anchor the structure to a continuous foundation",
            "Use hip roofs instead of gable — better wind resistance",
            "Install continuous plywood sheathing on roof and walls",
            "Specify impact-rated exterior cladding and doors"
        ],
        flood: [
            "Elevate the lowest floor at least 1 ft above BFE",
            "Use flood-resistant materials below the Design Flood Elevation",
            "Install backflow valves on all sewer and drain lines",
            "Grade the site to slope away from the building on all sides",
            "Avoid finished basements in high-risk flood zones"
        ],
        winter: [
            "Design roof for regional snow load per ASCE 7",
            "Insulate to or above IECC climate-zone requirements",
            "Install heat cables along eaves and gutters to prevent ice dams",
            "Use frost-protected shallow foundations in cold climates",
            "Specify freeze-resistant exterior plumbing and hose bibs"
        ],
        heat: [
            "Specify high Solar Reflectance Index (SRI) roofing materials",
            "Design generous overhangs and shading on south/west facades",
            "Use insulated concrete forms (ICFs) for high thermal mass",
            "Plan for oversized HVAC capacity with redundancy",
            "Install radiant barriers in the attic space"
        ]
    };

    function renderUI(data) {
        dataPanel.style.display = 'flex';
        exportBtn.style.display = 'block';

        // Update sidebar
        const obs = data.observation;
        sidebarContent.innerHTML = `
            <div class="card">
                <h4 style="text-transform:uppercase;letter-spacing:1px;font-size:0.75rem;">Location</h4>
                <p style="font-weight:600;font-size:0.9rem;">${data.display}</p>
                <p style="font-size:0.75rem;color:var(--text-secondary);margin-top:0.25rem;">${data.lat.toFixed(4)}°, ${data.lon.toFixed(4)}° | State: ${data.state}</p>
            </div>
            
            ${obs && obs.temperature ? `
            <div class="card" style="margin-top:1rem;">
                <h4 style="text-transform:uppercase;letter-spacing:1px;font-size:0.75rem;">Current Conditions</h4>
                <div style="font-size:3rem;font-weight:300;">${obs.temperature}°<span style="font-size:1.5rem">F</span></div>
                <p>${obs.conditions}</p>
                <p style="font-size:0.8rem;color:var(--text-secondary);margin-top:0.5rem">Wind: ${obs.windSpeed}</p>
            </div>
            ` : ''}

            <div class="composite-score">
                <h4 style="text-transform:uppercase;letter-spacing:1px;color:var(--text-secondary)">Risk Composite</h4>
                <h2 style="color: ${getColorComp(data.composite)}">${data.composite}</h2>
                <div class="risk-bar">
                    <div class="risk-bar-fill" style="width: ${data.composite}%; background: ${getColorComp(data.composite)}"></div>
                </div>
            </div>
        `;

        // Update Overview
        const overviewHtml = Object.entries(data.scores).map(([k, v]) => `
            <div class="card">
                <h4>${RISK_LABELS[k] || k}</h4>
                <div class="value" style="color: ${getColor(v)}">${v}/10</div>
                <div class="risk-bar">
                    <div class="risk-bar-fill" style="width: ${v * 10}%; background: ${getColor(v)}"></div>
                </div>
            </div>
        `).join('');
        document.getElementById('overview').innerHTML = `<h3>Hazard Assessment Ratings</h3><div class="grid-cards">${overviewHtml}</div>`;

        // Update Forecast
        if (data.forecast && data.forecast.length > 0) {
            const forecastHtml = data.forecast.map(f => `
                <div class="card">
                    <h4>${f.name}</h4>
                    <div class="value">${f.temperature}°${f.temperatureUnit}</div>
                    <p style="font-size:0.8rem;margin-top:0.5rem;color:var(--text-secondary);line-height:1.4;">${f.shortForecast}</p>
                </div>
            `).join('');
            document.getElementById('forecast').innerHTML = `<div class="grid-cards">${forecastHtml}</div>`;
        } else {
            document.getElementById('forecast').innerHTML = '<p>Forecast data not available for this location.</p>';
        }

        // Update Alerts
        if (data.alerts && data.alerts.length > 0) {
            const alertsHtml = data.alerts.map(a => `
                <div class="alert-card ${a.severity}">
                    <h4>${a.event}</h4>
                    <p style="font-size:0.8rem;color:var(--text-secondary)">Severity: ${a.severity}</p>
                    <p style="margin-top:0.5rem;font-size:0.9rem">${a.headline}</p>
                </div>
            `).join('');
            document.getElementById('alerts').innerHTML = alertsHtml;
            alertCount.textContent = `(${data.alerts.length})`;
            alertCount.style.display = 'inline-block';
            alertCount.style.background = 'var(--danger)';
            alertCount.style.borderRadius = '10px';
            alertCount.style.padding = '0 6px';
            alertCount.style.color = '#fff';
            alertCount.style.marginLeft = '4px';
        } else {
            document.getElementById('alerts').innerHTML = '<p>No active weather alerts.</p>';
            alertCount.style.display = 'none';
        }

        // Update Recommendations
        let activeRisks = Object.entries(data.scores).filter(([k,v]) => v >= 3);
        if (activeRisks.length > 0) {
            activeRisks.sort((a,b) => b[1] - a[1]);
            const tipsHtml = activeRisks.map(([k, v]) => `
                <div class="tip-section">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem;">
                        <h4 style="font-size:1.1rem;color:var(--text-primary);margin-bottom:0;">${RISK_LABELS[k] || k} Precautions</h4>
                        <span style="color:${getColor(v)};font-weight:700">Risk: ${v}/10</span>
                    </div>
                    <ul class="tips-list">
                        ${TIPS[k] ? TIPS[k].map(t => `<li>${t}</li>`).join('') : '<li>Consult local building codes.</li>'}
                    </ul>
                </div>
            `).join('');
            document.getElementById('recommendations').innerHTML = `
                <p style="margin-bottom:1.5rem;color:var(--text-secondary)">Recommendations based on historical risk patterns:</p>
                ${tipsHtml}
                <div class="card" style="margin-top:2rem;border-color:rgba(255,255,255,0.1)">
                    <p style="font-size:0.8rem;color:var(--text-secondary);font-style:italic;">Disclaimer: These recommendations are advisory. Always consult local building codes and a structural engineer.</p>
                </div>
            `;
        } else {
            document.getElementById('recommendations').innerHTML = '<p>All risk categories below threshold. Standard construction practices apply.</p>';
        }
    }

    // Export functionality
    exportBtn.addEventListener('click', () => {
        if (!currentData) return;
        
        const d = currentData;
        const rows = [
            ["Geospatial Architecture Database — Export"],
            ["Location", `"${d.display}"`],
            ["Coordinates", `${d.lat}, ${d.lon}`],
            ["Generated", new Date().toISOString()],
            [],
            ["=== FORECAST ==="],
            ["Period", "Temperature", "Forecast"]
        ];

        if(d.forecast) {
            d.forecast.forEach(f => rows.push([f.name, `${f.temperature}°${f.temperatureUnit}`, `"${f.shortForecast}"`]));
        }

        rows.push([], ["=== ALERTS ==="]);
        if(d.alerts.length) {
            d.alerts.forEach(a => rows.push([a.event, a.severity, `"${a.headline}"`]));
        } else {
            rows.push(["None"]);
        }

        rows.push([], ["=== RISK ASSESSMENT ==="]);
        Object.entries(d.scores).forEach(([k,v]) => {
            rows.push([RISK_LABELS[k] || k, v]);
        });
        rows.push(["Composite Risk Score", `${d.composite}/100`]);

        rows.push([], ["=== CONSTRUCTION RECOMMENDATIONS ==="]);
        Object.entries(d.scores).forEach(([k,v]) => {
            if (v >= 3 && TIPS[k]) {
                rows.push([`--- ${RISK_LABELS[k] || k} ---`]);
                TIPS[k].forEach(t => rows.push([`"${t}"`]));
            }
        });

        const csvContent = rows.map(r => r.join(",")).join("\n");
        const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.setAttribute("download", `GAD_Report_${new Date().toISOString().slice(0,10)}.csv`);
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    });

    // Close suggestions on outside click
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.search-box')) {
            suggestionsBox.classList.add('hidden');
        }
    });

    // Handle enter key mapped out
    locationInput.addEventListener('keydown', (e) => {
        if(e.key === 'Enter') {
            const firstChild = suggestionsBox.querySelector('.suggestion-item');
            if (firstChild && firstChild.dataset.lat) {
                firstChild.click();
            }
        }
    });
});
