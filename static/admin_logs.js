(() => {
  const initDateProxy = (id) => {
    if (!window.AdminDatePicker || typeof window.AdminDatePicker.bind !== "function") return;
    window.AdminDatePicker.bind(id);
  };

  ["chart_start", "chart_end"].forEach(initDateProxy);

  const resize = () => {
    const el = document.getElementById("log_density_plotly");
    if (!el || !window.Plotly || typeof window.Plotly.Plots?.resize !== "function") return;
    try { window.Plotly.Plots.resize(el); } catch (_) {}
  };

  try {
    const payloadEl = document.getElementById("log_density_data");
    const plotlyEl = document.getElementById("log_density_plotly");
    const emptyEl = document.getElementById("log_density_empty");
    let payload = {};
    try { payload = JSON.parse((payloadEl && payloadEl.textContent) || "{}"); } catch (_) {}
    const xVals = Array.isArray(payload.days) ? payload.days.slice() : [];
    const yVals = Array.isArray(payload.counts) ? payload.counts.map((v) => Number(v || 0)) : [];
    if (!plotlyEl || !emptyEl || !xVals.length || yVals.every((v) => v <= 0) || !window.Plotly) {
      if (plotlyEl) plotlyEl.hidden = true;
      if (emptyEl) emptyEl.hidden = false;
    } else {
      plotlyEl.hidden = false;
      emptyEl.hidden = true;
      const isNarrowScreen = typeof window !== "undefined" && typeof window.matchMedia === "function"
        ? window.matchMedia("(max-width: 980px)").matches
        : false;
      const plotHeight = Math.max(isNarrowScreen ? 236 : 400, plotlyEl.clientHeight || 0);
      window.Plotly.newPlot(plotlyEl, [{
        x: xVals,
        y: yVals,
        type: "scatter",
        mode: "lines+markers",
        fill: "tozeroy",
        fillcolor: "rgba(37,99,235,0.16)",
        line: { color: "rgba(37,99,235,0.95)", width: 3, shape: "spline", smoothing: 0.9 },
        marker: { color: "rgba(37,99,235,1)", size: 7, line: { color: "rgba(255,255,255,0.9)", width: 1.2 } },
        hovertemplate: "%{x}<br>操作数：%{y}<extra></extra>",
        name: "每日操作数",
      }], {
        height: plotHeight,
        margin: isNarrowScreen
          ? { l: 22, r: 6, t: 4, b: 22 }
          : { l: 56, r: 48, t: 22, b: 46 },
        paper_bgcolor: "rgba(0,0,0,0)",
        plot_bgcolor: "rgba(0,0,0,0)",
        hovermode: "x unified",
        dragmode: false,
        xaxis: { type: "date", nticks: 9, showgrid: true, gridcolor: "rgba(148,163,184,0.12)", fixedrange: true, automargin: true },
        yaxis: { rangemode: "tozero", gridcolor: "rgba(148,163,184,0.18)", zerolinecolor: "rgba(148,163,184,0.26)", fixedrange: true },
      }, { displayModeBar: false, responsive: true, scrollZoom: false, locale: "zh-CN" });
      window.setTimeout(resize, 0);
      window.setTimeout(resize, 120);
    }
  } catch (_) {
    // ignore
  }

  const tbody = document.getElementById("logs_table_body");
  let inFlight = false;
  const currentMaxId = () => {
    try {
      const firstRow = tbody?.querySelector("tr");
      const td = firstRow?.querySelector("td");
      const n = parseInt(String(td?.textContent || "").trim(), 10);
      return Number.isFinite(n) ? n : 0;
    } catch (_) {
      return 0;
    }
  };
  const prependRow = (it) => {
    if (!tbody) return;
    const onlyRow = tbody.querySelector("tr");
    const muted = onlyRow ? onlyRow.querySelector("td.muted") : null;
    if (muted) tbody.innerHTML = "";
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${it.id}</td><td class="nowrap">${it.at || ""}</td><td><span class="type-pill cat-${it.type_key || "system"}">${it.type_label || ""}</span></td><td class="ellipsis">${it.detail_text || ""}</td>`;
    tbody.insertBefore(tr, tbody.firstChild);
  };
  const tick = async () => {
    if (!tbody || inFlight || document.hidden) return;
    const afterId = currentMaxId();
    if (!afterId) return;
    inFlight = true;
    try {
      const j = await fetch(`/admin/api/operation-logs/updates?after_id=${encodeURIComponent(String(afterId))}&limit=20`, { method: "GET", headers: { Accept: "application/json" } }).then((r) => r.ok ? r.json() : null).catch(() => null);
      if (!j || !j.ok || !Array.isArray(j.items) || !j.items.length) return;
      for (let i = j.items.length - 1; i >= 0; i -= 1) prependRow(j.items[i]);
    } finally {
      inFlight = false;
    }
  };
  const timer = window.setInterval(tick, 8000);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) tick();
  });
  window.addEventListener("resize", () => window.requestAnimationFrame(resize));
  window.addEventListener("beforeunload", () => window.clearInterval(timer));
})();
