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
    if (!window.AdminDatePicker || typeof window.AdminDatePicker.bind !== "function") return;
    window.AdminDatePicker.bind(id);
  };

  const initDurationPicker = () => {
    const hidden = document.getElementById("time_limit_seconds");
    const display = document.getElementById("time_limit_seconds_display");
    const modal = document.getElementById("duration_modal");
    const openBtn = document.getElementById("time_picker_open");
    const hours = document.getElementById("duration_hours");
    const minutes = document.getElementById("duration_minutes");
    const applyBtn = document.getElementById("duration_apply");
    const cancelBtn = document.getElementById("duration_cancel");
    const presetButtons = Array.from(document.querySelectorAll(".duration-preset[data-duration]"));
    if (!hidden || !display || !modal || !openBtn || !hours || !minutes || !applyBtn || !cancelBtn) return;

    const pad2 = (v) => String(v).padStart(2, "0");
    const parse = (raw) => {
      const m = String(raw || "").trim().match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?$/);
      if (!m) return { hours: 2, minutes: 0 };
      const h = Math.max(0, Math.min(23, parseInt(m[1], 10) || 0));
      const mm = Math.max(0, Math.min(55, parseInt(m[2], 10) || 0));
      return { hours: h, minutes: mm - (mm % 5) };
    };
    const format = (h, m) => `${pad2(h)}:${pad2(m)}:00`;
    const syncPresetState = () => {
      const value = format(hours.value, minutes.value);
      presetButtons.forEach((btn) => {
        btn.classList.toggle("is-active", btn.dataset.duration === value);
      });
    };
    const syncDisplay = () => {
      const next = format(hours.value, minutes.value);
      hidden.value = next;
      display.value = next;
      syncPresetState();
    };
    const syncSelectors = () => {
      const current = parse(hidden.value || display.value || "02:00:00");
      hours.value = pad2(current.hours);
      minutes.value = pad2(current.minutes);
      hidden.value = format(current.hours, current.minutes);
      display.value = hidden.value;
      syncPresetState();
    };
    const open = () => {
      syncSelectors();
      modal.hidden = false;
      document.body.style.overflow = "hidden";
      window.setTimeout(() => {
        try { hours.focus(); } catch (_) {}
      }, 0);
    };
    const close = () => {
      modal.hidden = true;
      document.body.style.overflow = "";
    };

    hours.innerHTML = "";
    minutes.innerHTML = "";
    for (let h = 0; h <= 23; h += 1) {
      const opt = document.createElement("option");
      opt.value = pad2(h);
      opt.textContent = `${pad2(h)} 小时`;
      hours.appendChild(opt);
    }
    for (let m = 0; m < 60; m += 5) {
      const opt = document.createElement("option");
      opt.value = pad2(m);
      opt.textContent = `${pad2(m)} 分钟`;
      minutes.appendChild(opt);
    }

    syncSelectors();
    display.addEventListener("click", open);
    display.addEventListener("keydown", (ev) => {
      if (ev.key !== "Enter" && ev.key !== " ") return;
      ev.preventDefault();
      open();
    });
    openBtn.addEventListener("click", open);
    cancelBtn.addEventListener("click", close);
    applyBtn.addEventListener("click", () => {
      syncDisplay();
      close();
    });
    hours.addEventListener("change", syncPresetState);
    minutes.addEventListener("change", syncPresetState);
    presetButtons.forEach((btn) => {
      btn.addEventListener("click", () => {
        const current = parse(btn.dataset.duration || "");
        hours.value = pad2(current.hours);
        minutes.value = pad2(current.minutes);
        syncPresetState();
      });
    });
    modal.addEventListener("click", (ev) => {
      if (ev.target === modal) close();
    });
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape" && !modal.hidden) close();
    });
  };

  ensureDefaultInviteDates();
  initDurationPicker();
  ["invite_start_date", "invite_end_date", "attempt_start_from", "attempt_start_to"].forEach(initDateProxy);

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
