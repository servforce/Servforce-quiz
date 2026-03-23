(() => {
  const WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"];
  const REGEX_YMD = /^(\d{4})-(\d{2})-(\d{2})$/;
  const proxyMap = new Map();

  let popover = null;
  let panel = null;
  let titleEl = null;
  let gridEl = null;
  let activeEntry = null;
  let viewDate = null;
  let lastTrigger = null;

  const pad2 = (value) => String(value).padStart(2, "0");
  const fmtIso = (date) => `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;
  const fmtSlash = (date) => `${date.getFullYear()}/${pad2(date.getMonth() + 1)}/${pad2(date.getDate())}`;
  const sameDay = (a, b) =>
    !!a && !!b &&
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate();
  const isValidDate = (date) => date instanceof Date && !Number.isNaN(date.getTime());

  const parseIso = (raw) => {
    const match = String(raw || "").trim().match(REGEX_YMD);
    if (!match) return null;
    const year = Number(match[1]);
    const month = Number(match[2]) - 1;
    const day = Number(match[3]);
    const date = new Date(year, month, day);
    if (!isValidDate(date)) return null;
    if (date.getFullYear() !== year || date.getMonth() !== month || date.getDate() !== day) return null;
    return date;
  };

  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

  const ensurePopover = () => {
    if (popover) return;
    popover = document.createElement("div");
    popover.className = "admin-date-popover";
    popover.hidden = true;
    popover.innerHTML = `
      <div class="admin-date-popover__panel" role="dialog" aria-modal="false" aria-label="选择日期" tabindex="-1">
        <div class="admin-date-popover__head">
          <div class="admin-date-popover__title" data-role="title"></div>
          <div class="admin-date-popover__nav">
            <button class="admin-date-popover__icon-btn" type="button" data-role="prev-month" aria-label="上一个月">
              <span class="material-symbols-rounded" aria-hidden="true">chevron_left</span>
            </button>
            <button class="admin-date-popover__icon-btn" type="button" data-role="next-month" aria-label="下一个月">
              <span class="material-symbols-rounded" aria-hidden="true">chevron_right</span>
            </button>
          </div>
        </div>
        <div class="admin-date-popover__body">
          <div class="admin-date-popover__weekdays">${WEEKDAYS.map((day) => `<span class="admin-date-popover__weekday">${day}</span>`).join("")}</div>
          <div class="admin-date-popover__grid" data-role="grid"></div>
          <div class="admin-date-popover__foot">
            <button class="admin-date-popover__text-btn is-danger" type="button" data-role="clear">清除</button>
            <button class="admin-date-popover__text-btn" type="button" data-role="today">今天</button>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(popover);
    panel = popover.querySelector(".admin-date-popover__panel");
    titleEl = popover.querySelector("[data-role='title']");
    gridEl = popover.querySelector("[data-role='grid']");

    popover.querySelector("[data-role='prev-month']").addEventListener("click", () => {
      if (!activeEntry || !viewDate) return;
      viewDate = new Date(viewDate.getFullYear(), viewDate.getMonth() - 1, 1);
      render();
      position();
    });
    popover.querySelector("[data-role='next-month']").addEventListener("click", () => {
      if (!activeEntry || !viewDate) return;
      viewDate = new Date(viewDate.getFullYear(), viewDate.getMonth() + 1, 1);
      render();
      position();
    });
    popover.querySelector("[data-role='today']").addEventListener("click", () => {
      if (!activeEntry) return;
      applyDate(new Date());
    });
    popover.querySelector("[data-role='clear']").addEventListener("click", () => {
      if (!activeEntry) return;
      setValue(activeEntry, "");
      close();
    });

    gridEl.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-date]");
      if (!button || !activeEntry) return;
      applyDate(parseIso(button.getAttribute("data-date")));
    });

    document.addEventListener("mousedown", (event) => {
      if (!isOpen()) return;
      if (panel.contains(event.target)) return;
      if (activeEntry?.proxy?.contains(event.target)) return;
      close();
    }, true);
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape" || !isOpen()) return;
      event.preventDefault();
      close();
    });
    window.addEventListener("resize", () => {
      if (isOpen()) position();
    });
    window.addEventListener("scroll", () => {
      if (isOpen()) position();
    }, true);
  };

  const isOpen = () => !!popover && !popover.hidden;

  const render = () => {
    if (!activeEntry || !viewDate || !titleEl || !gridEl) return;
    titleEl.textContent = `${viewDate.getFullYear()}年${pad2(viewDate.getMonth() + 1)}月`;

    const selected = parseIso(activeEntry.native.value);
    const today = new Date();
    const firstOfMonth = new Date(viewDate.getFullYear(), viewDate.getMonth(), 1);
    const offset = (firstOfMonth.getDay() + 6) % 7;
    const cursor = new Date(viewDate.getFullYear(), viewDate.getMonth(), 1 - offset);
    const cells = [];

    for (let index = 0; index < 42; index += 1) {
      const current = new Date(cursor.getFullYear(), cursor.getMonth(), cursor.getDate() + index);
      const classes = ["admin-date-popover__day"];
      if (current.getMonth() !== viewDate.getMonth()) classes.push("is-outside");
      if (sameDay(current, today)) classes.push("is-today");
      if (sameDay(current, selected)) classes.push("is-selected");
      cells.push(`
        <button
          class="${classes.join(" ")}"
          type="button"
          data-date="${fmtIso(current)}"
          aria-pressed="${sameDay(current, selected) ? "true" : "false"}"
        >${current.getDate()}</button>
      `);
    }

    gridEl.innerHTML = cells.join("");
  };

  const position = () => {
    if (!activeEntry || !panel) return;
    const anchor = activeEntry.proxy || activeEntry.display;
    if (!anchor) return;
    const rect = anchor.getBoundingClientRect();
    const panelRect = panel.getBoundingClientRect();
    const spacing = 8;
    const maxLeft = window.innerWidth - panelRect.width - spacing;
    let left = clamp(rect.left, spacing, Math.max(spacing, maxLeft));
    const spaceBelow = window.innerHeight - rect.bottom - spacing;
    const openUpward = spaceBelow < panelRect.height && rect.top > spaceBelow;
    let top = openUpward ? rect.top - panelRect.height - spacing : rect.bottom + spacing;
    const maxTop = window.innerHeight - panelRect.height - spacing;
    top = clamp(top, spacing, Math.max(spacing, maxTop));
    if (rect.right - panelRect.width >= spacing) {
      left = clamp(rect.right - panelRect.width, spacing, Math.max(spacing, maxLeft));
    }
    panel.style.left = `${Math.round(left)}px`;
    panel.style.top = `${Math.round(top)}px`;
  };

  const syncDisplay = (entry) => {
    if (!entry?.display || !entry?.native) return;
    const date = parseIso(entry.native.value);
    entry.display.value = date ? fmtSlash(date) : "";
  };

  const setValue = (entry, nextValue) => {
    if (!entry?.native) return;
    entry.native.value = nextValue;
    syncDisplay(entry);
    entry.native.dispatchEvent(new Event("change", { bubbles: true }));
    entry.native.dispatchEvent(new Event("input", { bubbles: true }));
  };

  const applyDate = (date) => {
    if (!activeEntry || !isValidDate(date)) return;
    setValue(activeEntry, fmtIso(date));
    close();
  };

  const open = (idOrEntry, trigger) => {
    ensurePopover();
    const entry = typeof idOrEntry === "string" ? proxyMap.get(idOrEntry) : idOrEntry;
    if (!entry) return;
    activeEntry = entry;
    lastTrigger = trigger || document.activeElement || entry.display;
    viewDate = parseIso(entry.native.value) || new Date();
    viewDate = new Date(viewDate.getFullYear(), viewDate.getMonth(), 1);
    popover.hidden = false;
    render();
    position();
    window.requestAnimationFrame(() => {
      try { panel.focus(); } catch (_) {}
    });
  };

  const close = () => {
    if (!popover || popover.hidden) return;
    popover.hidden = true;
    activeEntry = null;
    viewDate = null;
    const trigger = lastTrigger;
    lastTrigger = null;
    if (trigger && typeof trigger.focus === "function") {
      window.requestAnimationFrame(() => {
        try { trigger.focus({ preventScroll: true }); } catch (_) {}
      });
    }
  };

  const bind = (id) => {
    const native = document.getElementById(id);
    const display = document.getElementById(`${id}_display`);
    const proxy = native?.closest(".date-proxy") || display?.closest(".date-proxy");
    if (!native || !display || !proxy) return null;
    const existing = proxyMap.get(id);
    if (existing) {
      syncDisplay(existing);
      return existing;
    }
    const button = proxy.querySelector(`button.date-btn[data-for="${id}"]`) || proxy.querySelector(".date-btn");
    const entry = { id, native, display, proxy, button };
    const openFrom = (event) => {
      event.preventDefault();
      open(entry, event.currentTarget);
    };
    syncDisplay(entry);
    native.addEventListener("change", () => syncDisplay(entry));
    display.addEventListener("click", openFrom);
    display.addEventListener("keydown", (event) => {
      if (!["Enter", " ", "ArrowDown"].includes(event.key)) return;
      event.preventDefault();
      open(entry, display);
    });
    if (button) {
      button.addEventListener("click", openFrom);
    }
    proxyMap.set(id, entry);
    return entry;
  };

  const sync = (id) => {
    const entry = proxyMap.get(id);
    if (entry) syncDisplay(entry);
  };

  window.AdminDatePicker = {
    bind,
    open,
    close,
    sync,
  };
})();
