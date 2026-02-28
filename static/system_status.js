(() => {
  const ENDPOINT = "/admin/api/system-status/summary";
  // Keep this small so the topbar badge feels "real-time" without needing a full push channel (SSE/WebSocket).
  const POLL_SECONDS = 2;

  const badgeText = (level) => {
    const k = String(level || "ok");
    if (k === "warn") return "70%";
    if (k === "danger") return "90%";
    if (k === "critical") return "100%";
    return "";
  };

  const applyBadge = (el, level) => {
    if (!el) return;
    const lvl = String(level || "ok");
    el.textContent = badgeText(lvl);
    el.classList.remove("level-ok", "level-warn", "level-danger", "level-critical");
    el.classList.add(`level-${lvl}`);
  };

  const updateAllBadges = (summary) => {
    const lvl = summary && summary.overall_level ? summary.overall_level : "ok";
    const nodes = Array.from(document.querySelectorAll("[data-system-status-badge]"));
    for (const n of nodes) applyBadge(n, lvl);
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
