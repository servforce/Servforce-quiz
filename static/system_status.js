(() => {
  const ENDPOINT = "/admin/api/system-status/summary";
  // Keep this small so the topbar badge feels "real-time" without needing a full push channel (SSE/WebSocket).
  const POLL_SECONDS = 2;

  const maxRatioPct = (summary) => {
    const llm = summary && summary.llm ? summary.llm : {};
    const sms = summary && summary.sms ? summary.sms : {};
    const r1 = typeof llm.ratio === "number" ? llm.ratio : parseFloat(String(llm.ratio || "0"));
    const r2 = typeof sms.ratio === "number" ? sms.ratio : parseFloat(String(sms.ratio || "0"));
    const maxr = Math.max(Number.isFinite(r1) ? r1 : 0, Number.isFinite(r2) ? r2 : 0);
    return Math.min(100, Math.max(0, Math.round(maxr * 100)));
  };

  const applyBadge = (el, summary) => {
    if (!el) return;
    const lvl = String(summary && summary.overall_level ? summary.overall_level : "ok");
    el.textContent = lvl === "ok" ? "" : `${maxRatioPct(summary)}%`;
    el.classList.remove("level-ok", "level-warn", "level-danger", "level-critical");
    el.classList.add(`level-${lvl}`);
  };

  const updateAllBadges = (summary) => {
    const nodes = Array.from(document.querySelectorAll("[data-system-status-badge]"));
    for (const n of nodes) applyBadge(n, summary);
  };

  const fetchSummary = async () => {
    try {
      const resp = await fetch(ENDPOINT, { method: "GET", headers: { Accept: "application/json" } });
      if (!resp.ok) return null;
      return await resp.json();
    } catch (_) {
      return null;
    }
  };

  let inFlight = false;
  const tick = async () => {
    if (inFlight) return;
    if (document.hidden) return;
    if (!document.querySelector("[data-system-status-badge]")) return;
    inFlight = true;
    try {
      const s = await fetchSummary();
      if (!s) return;
      updateAllBadges(s);
      try {
        const ev = new CustomEvent("system-status:update", { detail: s });
        window.dispatchEvent(ev);
      } catch (_) {}
    } finally {
      inFlight = false;
    }
  };

  // First paint + polling.
  tick();
  const timer = window.setInterval(tick, Math.max(3, POLL_SECONDS) * 1000);
  window.addEventListener("focus", tick);
  window.addEventListener("pageshow", tick);
  // Allow other scripts to force an immediate refresh after an action completes.
  // Usage: window.dispatchEvent(new Event("system-status:refresh"))
  window.addEventListener("system-status:refresh", tick);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) tick();
  });
  window.addEventListener("beforeunload", () => {
    try {
      window.clearInterval(timer);
    } catch (_) {}
  });
})();
