(() => {
  const isoDate = (d) => {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  };

  const ensureDefaultInviteDates = () => {
    const start = document.getElementById("invite_start_date");
    const end = document.getElementById("invite_end_date");
    if (!start || !end) return;
    if (!String(start.value || "").trim()) {
      start.value = isoDate(new Date());
    }
    if (!String(end.value || "").trim()) {
      const base = start.value ? new Date(`${start.value}T00:00:00`) : new Date();
      base.setDate(base.getDate() + 1);
      end.value = isoDate(base);
    }
  };

  const initDateProxy = (id) => {
    const native = document.getElementById(id);
    const display = document.getElementById(`${id}_display`);
    if (!native || !display) return;
    const sync = () => { display.value = native.value ? String(native.value).replaceAll("-", "/") : ""; };
    const open = () => {
      try { if (native.showPicker) native.showPicker(); else native.click(); } catch (_) { try { native.focus(); } catch (_) {} }
    };
    sync();
    native.addEventListener("change", sync);
    display.addEventListener("click", open);
  };

  ensureDefaultInviteDates();
  ["invite_start_date", "invite_end_date", "attempt_start_from", "attempt_start_to"].forEach(initDateProxy);
  document.querySelectorAll("button.date-btn[data-for]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.getAttribute("data-for");
      const native = id ? document.getElementById(id) : null;
      if (!native) return;
      try { if (native.showPicker) native.showPicker(); else native.click(); } catch (_) {}
    });
  });

  const attemptQ = document.getElementById("attempt_q");
  if (attemptQ && attemptQ.form) {
    let timer = null;
    attemptQ.addEventListener("input", () => {
      if (timer) window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        const u = new URL(window.location.href);
        const v = String(attemptQ.value || "").trim();
        if (v) u.searchParams.set("attempt_q", v);
        else u.searchParams.delete("attempt_q");
        u.searchParams.delete("attempt_page");
        window.location.href = u.toString();
      }, 260);
    });
  }

  const copyText = async (text) => {
    const t = String(text || "");
    if (!t) return false;
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(t);
        return true;
      }
    } catch (_) {}
    return false;
  };

  const copyInviteLink = async (token) => {
    const t = String(token || "").trim();
    if (!t) return;
    const url = new URL(`/t/${encodeURIComponent(t)}`, window.location.origin).toString();
    const ok = await copyText(url);
    if (!ok) {
      try { window.prompt("复制下面的邀请链接：", url); } catch (_) {}
    }
  };

  document.addEventListener("click", async (ev) => {
    const tokenLink = ev.target && ev.target.closest ? ev.target.closest("a.token-copy") : null;
    if (tokenLink) {
      ev.preventDefault();
      ev.stopPropagation();
      await copyInviteLink(tokenLink.dataset.token || "");
      return;
    }
    const row = ev.target && ev.target.closest ? ev.target.closest("tr[data-href], tr[data-msg]") : null;
    if (!row) return;
    if (ev.target && (ev.target.closest("a") || ev.target.closest("button") || ev.target.closest("form"))) return;
    const href = row.getAttribute("data-href");
    if (href) {
      window.location.href = href;
      return;
    }
    const msg = row.getAttribute("data-msg");
    if (msg) window.alert(msg);
  });

  const table = document.querySelector("table.attempt-table");
  if (!table) return;

  const tokensFromTable = () =>
    Array.from(table.querySelectorAll("tbody tr[data-token]"))
      .map((tr) => String(tr.dataset.token || "").trim())
      .filter(Boolean)
      .slice(0, 50);

  const applyItems = (items) => {
    const m = new Map();
    for (const it of items || []) {
      const token = String(it && it.token ? it.token : "").trim();
      if (token) m.set(token, it);
    }
    for (const tr of table.querySelectorAll("tbody tr[data-token]")) {
      const token = String(tr.dataset.token || "").trim();
      const it = m.get(token);
      if (!it) continue;
      const pill = tr.querySelector(".status-cell .status-pill");
      if (pill) {
        pill.textContent = String(it.status_label || it.status || pill.textContent);
        pill.className = `status-pill ${String(it.status || "").trim()}`.trim();
      }
      const scoreTd = tr.querySelector("td.score-cell");
      if (scoreTd) scoreTd.textContent = it.score == null ? "" : String(it.score);
    }
  };

  let timer = null;
  let inFlight = false;
  const refreshOnce = async () => {
    if (inFlight || document.hidden) return;
    const tokens = tokensFromTable();
    if (!tokens.length) return;
    inFlight = true;
    try {
      const resp = await fetch(`/admin/api/attempt-status?tokens=${encodeURIComponent(tokens.join(","))}`, { method: "GET", headers: { Accept: "application/json" } });
      if (!resp.ok) return;
      const data = await resp.json();
      applyItems(data && data.items ? data.items : []);
    } catch (_) {
      // ignore
    } finally {
      inFlight = false;
    }
  };

  const start = () => {
    if (timer) window.clearInterval(timer);
    timer = window.setInterval(refreshOnce, 8000);
    refreshOnce();
  };
  start();
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refreshOnce();
  });
  window.addEventListener("beforeunload", () => {
    if (timer) window.clearInterval(timer);
  });
})();
