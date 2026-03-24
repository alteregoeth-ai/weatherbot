/* WeatherBet Operations Center — Client-side logic */

(function () {
    "use strict";

    const DATA = window.__DASHBOARD_DATA__;
    let ws = null;
    let reconnectDelay = 1000;

    // =========================================================================
    // Leaflet Map
    // =========================================================================
    const map = L.map("map", {
        zoomControl: false,
        attributionControl: false,
    }).setView([20, 0], 2);

    L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
        maxZoom: 18,
    }).addTo(map);

    const markers = {};

    function buildMarkerHtml(city, loc, forecasts, positions) {
        const code = city.toUpperCase().slice(0, 3);
        const forecast = forecasts.find(f => f.city === city);
        const position = positions.find(p => p.city === city);

        let temp = "";
        let evText = "";
        let dotColor = "#8b949e";

        if (forecast) {
            temp = forecast.best + "°" + forecast.unit;
        }
        if (position) {
            const ev = position.ev || 0;
            evText = (ev >= 0 ? "+" : "") + ev.toFixed(2);
            const pnl = position.pnl || 0;
            dotColor = pnl >= 0 ? "#3fb950" : "#f85149";
        }

        return `<div class="city-marker">` +
            `<span class="code">${code}</span>` +
            `<span class="temp">${temp}</span>` +
            (evText ? `<span class="ev" style="color:${dotColor}">${evText}</span>` : "") +
            `</div>`;
    }

    function buildPopupHtml(city, loc, forecasts, positions) {
        const forecast = forecasts.find(f => f.city === city);
        const position = positions.find(p => p.city === city);

        let html = `<div class="popup-detail">`;
        html += `<div style="font-weight:600;font-size:13px;margin-bottom:4px;">${loc.name}</div>`;

        if (forecast) {
            html += `<div class="label">Forecasts</div>`;
            html += `<div class="value">ECMWF: ${forecast.ecmwf ?? "—"}° | HRRR: ${forecast.hrrr ?? "—"}° | METAR: ${forecast.metar ?? "—"}°</div>`;
            html += `<div class="value">Best: <span style="color:#3fb950;font-weight:600;">${forecast.best}°${forecast.unit}</span> (${(forecast.best_source || "").toUpperCase()})</div>`;
            html += `<div class="value">Horizon: ${forecast.horizon || "—"} | Date: ${forecast.date || "—"}</div>`;
        }

        if (position) {
            html += `<div class="label" style="margin-top:6px;">Position</div>`;
            html += `<div class="value">Bucket: ${position.bucket_low}-${position.bucket_high}°${position.unit}</div>`;
            html += `<div class="value">Entry: $${position.entry_price?.toFixed(3)} | Cost: $${position.cost?.toFixed(0)}</div>`;
            html += `<div class="value">EV: +${position.ev?.toFixed(2)} | Kelly: ${position.kelly?.toFixed(2)} | σ: ${position.sigma?.toFixed(1)}</div>`;
            const pnl = position.pnl;
            if (pnl !== null && pnl !== undefined) {
                const color = pnl >= 0 ? "#3fb950" : "#f85149";
                html += `<div class="value">P&L: <span style="color:${color};font-weight:600;">$${pnl.toFixed(2)}</span></div>`;
            }
        }

        html += `</div>`;
        return html;
    }

    function updateMap(data) {
        const locations = data.locations || {};
        const forecasts = data.forecasts || [];
        const positions = data.open_positions || [];

        for (const [city, loc] of Object.entries(locations)) {
            const html = buildMarkerHtml(city, loc, forecasts, positions);
            const icon = L.divIcon({
                html: html,
                className: "",
                iconAnchor: [0, 0],
            });

            if (markers[city]) {
                markers[city].setIcon(icon);
                markers[city].setPopupContent(buildPopupHtml(city, loc, forecasts, positions));
            } else {
                markers[city] = L.marker([loc.lat, loc.lon], { icon: icon })
                    .addTo(map)
                    .bindPopup(buildPopupHtml(city, loc, forecasts, positions), {
                        maxWidth: 280,
                    });
            }
        }

        // Fit bounds only on first load (don't reset user's zoom/pan on updates)
        if (!map._boundsSet) {
            const bounds = Object.values(locations).map(l => [l.lat, l.lon]);
            if (bounds.length > 0) {
                map.fitBounds(bounds, { padding: [20, 20] });
                map._boundsSet = true;
            }
        }
    }

    // =========================================================================
    // Chart.js — Balance History
    // =========================================================================
    const ctx = document.getElementById("balance-chart").getContext("2d");
    const balanceChart = new Chart(ctx, {
        type: "line",
        data: {
            labels: [],
            datasets: [{
                data: [],
                borderColor: "#58a6ff",
                backgroundColor: "rgba(88,166,255,0.1)",
                fill: true,
                tension: 0.3,
                pointRadius: 2,
                pointHoverRadius: 4,
                borderWidth: 1.5,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: "#21262d",
                    titleColor: "#e1e4e8",
                    bodyColor: "#c9d1d9",
                    borderColor: "#30363d",
                    borderWidth: 1,
                    callbacks: {
                        label: function (ctx) {
                            return "$" + ctx.parsed.y.toFixed(2);
                        },
                    },
                },
            },
            scales: {
                x: {
                    display: true,
                    ticks: { color: "#8b949e", font: { size: 9 }, maxTicksLimit: 6 },
                    grid: { color: "rgba(48,54,61,0.5)", drawBorder: false },
                },
                y: {
                    display: true,
                    ticks: {
                        color: "#8b949e",
                        font: { size: 9 },
                        callback: v => "$" + v,
                    },
                    grid: { color: "rgba(48,54,61,0.5)", drawBorder: false },
                },
            },
        },
    });

    function updateChart(history) {
        if (!history || history.length === 0) return;
        balanceChart.data.labels = history.map(h => {
            const d = new Date(h.ts);
            return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        });
        balanceChart.data.datasets[0].data = history.map(h => h.balance);
        balanceChart.update("none");
    }

    // =========================================================================
    // Update city cards
    // =========================================================================
    function updateCityCards(data) {
        const container = document.getElementById("city-cards");
        const forecasts = data.forecasts || [];
        const positions = data.open_positions || [];
        const locations = data.locations || {};

        let html = "";
        for (const [key, loc] of Object.entries(locations)) {
            const forecast = forecasts.find(f => f.city === key);
            const position = positions.find(p => p.city === key);

            let statusClass = "";
            if (position) {
                statusClass = (position.pnl || 0) >= 0 ? "profitable" : "losing";
            }

            const temp = forecast ? `${forecast.best}°${forecast.unit}` : "—";
            const bucket = position ? `${position.bucket_low}-${position.bucket_high}` : "—";
            const price = position ? `$${position.entry_price.toFixed(2)}` : "—";

            html += `<div class="city-card ${statusClass}">` +
                `<div class="city-code">${key.toUpperCase().slice(0, 3)}</div>` +
                `<div class="city-detail">${temp} → ${bucket} @ ${price}</div>` +
                `</div>`;
        }
        container.innerHTML = html;
    }

    // =========================================================================
    // Update KPIs
    // =========================================================================
    function updateKPIs(kpi) {
        document.getElementById("kpi-starting").textContent = "$" + kpi.starting_balance.toFixed(2);
        document.getElementById("kpi-open-cost").textContent = "$" + kpi.open_cost.toFixed(2);
        document.getElementById("kpi-cash").textContent = "$" + kpi.cash.toFixed(2);

        function setPnl(id, value) {
            const el = document.getElementById(id);
            el.textContent = (value >= 0 ? "+" : "") + "$" + value.toFixed(2);
            el.className = "kpi-value " + (value >= 0 ? "text-green" : "text-red");
        }
        setPnl("kpi-realized", kpi.realized_pnl);
        setPnl("kpi-unrealized", kpi.unrealized_pnl);

        document.getElementById("kpi-open").textContent = kpi.open_count;
        document.getElementById("kpi-winrate").textContent = kpi.win_rate !== null ? kpi.win_rate.toFixed(1) + "%" : "—";

        const ddEl = document.getElementById("kpi-drawdown");
        ddEl.textContent = kpi.drawdown.toFixed(1) + "%";
        ddEl.className = "kpi-value " + (kpi.drawdown < 0 ? "text-red" : "text-muted");
    }

    // =========================================================================
    // Update Positions Table
    // =========================================================================
    function updatePositions(positions) {
        const body = document.getElementById("positions-body");
        const count = document.getElementById("positions-count");
        count.textContent = positions.length + " active";

        if (positions.length === 0) {
            body.innerHTML = '<div class="empty-state">No open positions</div>';
            return;
        }

        let html = "";
        for (const p of positions) {
            const pnl = p.pnl ?? 0;
            const pnlClass = pnl >= 0 ? "text-green" : "text-red";
            const pnlSign = pnl >= 0 ? "+" : "";
            const pnlText = pnlSign + "$" + pnl.toFixed(2);
            const curPrice = p.current_price ? "$" + p.current_price.toFixed(3) : "—";

            html += `<div class="table-row">` +
                `<span>${p.city.toUpperCase().slice(0, 3)}</span>` +
                `<span>${p.bucket_low}-${p.bucket_high}°${p.unit}</span>` +
                `<span>$${p.entry_price.toFixed(3)} → ${curPrice}</span>` +
                `<span class="text-green">+${p.ev.toFixed(2)}</span>` +
                `<span>${p.kelly.toFixed(2)}</span>` +
                `<span class="${pnlClass}">${pnlText}</span>` +
                `</div>`;
        }
        body.innerHTML = html;
    }

    // =========================================================================
    // Update Forecasts Table
    // =========================================================================
    function updateForecasts(forecasts) {
        const body = document.getElementById("forecast-body");

        if (!forecasts || forecasts.length === 0) {
            body.innerHTML = '<div class="empty-state">Waiting for first scan...</div>';
            return;
        }

        let html = "";
        for (const f of forecasts) {
            html += `<div class="forecast-row">` +
                `<span style="font-weight:600;">${f.city.toUpperCase().slice(0, 3)}</span>` +
                `<span>${f.ecmwf !== null && f.ecmwf !== undefined ? f.ecmwf + "°" : "—"}</span>` +
                `<span>${f.hrrr !== null && f.hrrr !== undefined ? f.hrrr + "°" : "—"}</span>` +
                `<span>${f.metar !== null && f.metar !== undefined ? f.metar + "°" : "—"}</span>` +
                `<span class="best">${f.best}°${f.unit}</span>` +
                `</div>`;
        }
        body.innerHTML = html;
    }

    // =========================================================================
    // Update Calibration
    // =========================================================================
    function updateCalibration(calibration) {
        const container = document.getElementById("calibration-bars");

        if (!calibration) {
            container.innerHTML = '<div class="empty-state" style="height:auto;padding:12px;">Calibration data not yet available — requires resolved markets</div>';
            return;
        }

        let html = "";
        for (const [key, val] of Object.entries(calibration)) {
            if (val.n < 10) continue;
            const pct = Math.min(val.sigma / 4 * 100, 100);
            const color = val.sigma < 1.5 ? "var(--accent-green)" : val.sigma < 2.5 ? "var(--accent-yellow)" : "var(--accent-red)";
            const textClass = val.sigma < 1.5 ? "text-green" : val.sigma < 2.5 ? "text-yellow" : "text-red";

            html += `<div class="calibration-entry">` +
                `<span class="label">${key}</span>` +
                `<div class="calibration-bar-track"><div class="calibration-bar-fill" style="width:${pct}%;background:${color};"></div></div>` +
                `<span class="calibration-value ${textClass}">σ=${val.sigma.toFixed(1)}</span>` +
                `</div>`;
        }
        container.innerHTML = html || '<div class="empty-state" style="height:auto;padding:12px;">No calibration entries with n≥10</div>';
    }

    // =========================================================================
    // Update Trade History
    // =========================================================================
    function updateHistory(trades) {
        const body = document.getElementById("history-body");
        const count = document.getElementById("history-count");
        count.textContent = trades.length + " closed";

        if (trades.length === 0) {
            body.innerHTML = '<div class="empty-state">No closed trades yet</div>';
            return;
        }

        let html = "";
        for (const t of trades) {
            const pnl = t.pnl ?? 0;
            const pnlClass = pnl >= 0 ? "text-green" : "text-red";
            const pnlSign = pnl >= 0 ? "+" : "";
            const reason = t.close_reason || "unknown";

            html += `<div class="history-row">` +
                `<span>${t.city_name}</span>` +
                `<span>${t.date}</span>` +
                `<span>$${t.entry_price.toFixed(3)} → $${t.exit_price.toFixed(3)}</span>` +
                `<span class="reason-badge reason-${reason}">${reason}</span>` +
                `<span class="${pnlClass}">${pnlSign}$${pnl.toFixed(2)}</span>` +
                `</div>`;
        }
        body.innerHTML = html;
    }

    // =========================================================================
    // Update Activity Feed
    // =========================================================================
    function updateActivity(events) {
        const feed = document.getElementById("activity-feed");
        if (!events || events.length === 0) return;

        let html = "";
        for (const ev of events) {
            const ts = ev.ts ? ev.ts.slice(11, 19) : "";
            html += `<div class="activity-entry ${ev.type}">${ts} ${ev.msg}</div>`;
        }
        feed.innerHTML = html;
        feed.scrollTop = feed.scrollHeight;
    }

    // =========================================================================
    // Update Bot Status
    // =========================================================================
    function updateBotStatus(status) {
        const el = document.getElementById("bot-status");
        if (status.running) {
            el.textContent = "Bot: PID " + status.pid;
        } else {
            el.innerHTML = '<span class="badge badge-stopped">STOPPED</span>';
        }
    }

    // =========================================================================
    // Full dashboard update
    // =========================================================================
    function updateDashboard(data) {
        updateKPIs(data.kpi);
        updateMap(data);
        updateChart(data.balance_history);
        updateCityCards(data);
        updatePositions(data.open_positions || []);
        updateHistory(data.closed_positions || []);
        updateForecasts(data.forecasts || []);
        updateCalibration(data.calibration);
        updateActivity(data.activity || []);
        updateBotStatus(data.bot_status || {});
    }

    // =========================================================================
    // Connection status UI
    // =========================================================================
    function setConnectionStatus(status) {
        const dot = document.getElementById("connection-dot");
        const badge = document.getElementById("connection-badge");

        dot.className = "live-dot " + status;
        badge.className = "badge badge-" + status;
        badge.textContent = status.toUpperCase();
    }

    // =========================================================================
    // WebSocket connection
    // =========================================================================
    let pollInterval = null;

    function connectWebSocket() {
        const protocol = location.protocol === "https:" ? "wss:" : "ws:";
        ws = new WebSocket(`${protocol}//${location.host}/ws`);

        ws.onopen = function () {
            reconnectDelay = 1000;
            setConnectionStatus("live");
            if (pollInterval) {
                clearInterval(pollInterval);
                pollInterval = null;
            }
        };

        ws.onmessage = function (event) {
            const msg = JSON.parse(event.data);
            if (msg.data) {
                updateDashboard(msg.data);
            }
        };

        ws.onclose = function () {
            setConnectionStatus("polling");
            startPolling();
            // Reconnect with exponential backoff
            setTimeout(connectWebSocket, reconnectDelay);
            reconnectDelay = Math.min(reconnectDelay * 2, 30000);
        };

        ws.onerror = function () {
            ws.close();
        };
    }

    // =========================================================================
    // Polling fallback
    // =========================================================================
    function startPolling() {
        if (pollInterval) return;
        pollInterval = setInterval(async function () {
            try {
                const resp = await fetch("/api/dashboard");
                if (resp.ok) {
                    const data = await resp.json();
                    updateDashboard(data);
                    setConnectionStatus("polling");
                } else {
                    setConnectionStatus("offline");
                }
            } catch {
                setConnectionStatus("offline");
            }
        }, 30000);
    }

    // =========================================================================
    // Init
    // =========================================================================
    updateDashboard(DATA);
    connectWebSocket();

    // Keep WebSocket alive with pings
    setInterval(function () {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send("ping");
        }
    }, 30000);

})();
