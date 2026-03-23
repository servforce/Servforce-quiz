(() => {
  const PER_PAGE = 20;
  const elAlert = document.getElementById("status_head");
  const elAlertText = document.getElementById("status_head_text");
  const elLlmUsed = document.getElementById("kpi_llm_used");
  const elLlmLimit = document.getElementById("kpi_llm_limit");
  const elLlmRatio = document.getElementById("kpi_llm_ratio");
  const elSmsUsed = document.getElementById("kpi_sms_used");
  const elSmsLimit = document.getElementById("kpi_sms_limit");
  const elSmsRatio = document.getElementById("kpi_sms_ratio");
  const elLlmLimitInput = document.getElementById("llm_tokens_limit");
  const elSmsLimitInput = document.getElementById("sms_calls_limit");
  const elCfgForm = document.getElementById("status_cfg_form");
  const elCfgSave = document.getElementById("status_cfg_save");
  const elCfgMsg = document.getElementById("status_cfg_msg");
  const elRangeForm = document.getElementById("status_range_form");
  const elStartDisplay = document.getElementById("status_start_display");
  const elStart = document.getElementById("status_start");
  const elEndDisplay = document.getElementById("status_end_display");
  const elEnd = document.getElementById("status_end");
  const elReset = document.getElementById("status_range_reset");
  const elTbody = document.getElementById("status_table_body");
  const elPager = document.getElementById("status_pager");
  const elPageInfo = document.getElementById("status_page_info");
  const elPrev = document.getElementById("status_page_prev");
  const elNext = document.getElementById("status_page_next");

  let allItems = [];
  let page = 1;

  const pad2 = (n) => String(n).padStart(2, "0");
  const fmtYmd = (d) => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
  const fmtPct = (ratio) => `${Math.round((Number(ratio || 0) || 0) * 100)}%`;
  const totalPages = () => Math.max(1, Math.ceil((allItems || []).length / PER_PAGE));
  const clampPage = () => { if (!Number.isFinite(page) || page <= 0) page = 1; if (page > totalPages()) page = totalPages(); };

  const initDateProxy = (id) => {
    if (!window.AdminDatePicker || typeof window.AdminDatePicker.bind !== "function") return;
    window.AdminDatePicker.bind(id);
  };

  ["status_start", "status_end"].forEach(initDateProxy);

  const setAlert = (summary) => {
    const overall = String(summary && summary.overall_level ? summary.overall_level : "ok");
    if (elAlert) {
      elAlert.classList.remove("level-ok", "level-warn", "level-danger", "level-critical");
      elAlert.classList.add(`level-${overall}`);
    }
    const llm = summary && summary.llm ? summary.llm : null;
    const sms = summary && summary.sms ? summary.sms : null;
    const parts = [];
    if (llm && String(llm.level || "ok") !== "ok") parts.push(`大模型 Token：${fmtPct(llm.ratio)}`);
    if (sms && String(sms.level || "ok") !== "ok") parts.push(`短信认证：${fmtPct(sms.ratio)}`);
    if (elAlertText) elAlertText.textContent = parts.length ? `当前预警：${parts.join("，")}` : "今日用量正常";
  };

  const setKpis = (summary) => {
    const llm = summary && summary.llm ? summary.llm : {};
    const sms = summary && summary.sms ? summary.sms : {};
    if (elLlmUsed) elLlmUsed.textContent = String(llm.used ?? "0");
    if (elLlmLimit) elLlmLimit.textContent = String(llm.limit ?? "0");
    if (elLlmRatio) elLlmRatio.textContent = fmtPct(llm.ratio);
    if (elSmsUsed) elSmsUsed.textContent = String(sms.used ?? "0");
    if (elSmsLimit) elSmsLimit.textContent = String(sms.limit ?? "0");
    if (elSmsRatio) elSmsRatio.textContent = fmtPct(sms.ratio);
    setAlert(summary);
  };

  const renderPager = () => {
    if (!elPager) return;
    const n = allItems.length;
    clampPage();
    if (n <= PER_PAGE) {
      elPager.hidden = true;
      return;
    }
    elPager.hidden = false;
    if (elPageInfo) elPageInfo.textContent = `第 ${page} / ${totalPages()} 页（共 ${n} 条）`;
    if (elPrev) elPrev.disabled = page <= 1;
    if (elNext) elNext.disabled = page >= totalPages();
  };

  const renderCurrentPage = () => {
    if (!elTbody) return;
    clampPage();
    const rows = allItems.slice((page - 1) * PER_PAGE, page * PER_PAGE).map((it) => `
      <tr>
        <td>${it.day || ""}</td>
        <td>${Number(it.exams_new || 0)}</td>
        <td>${Number(it.invites_new || 0)}</td>
        <td>${Number(it.candidates_new || 0)}</td>
        <td>${Number(it.llm_tokens || 0)}</td>
        <td>${Number(it.sms_calls || 0)}</td>
      </tr>
    `).join("");
    elTbody.innerHTML = rows || '<tr class="empty-row"><td colspan="6">暂无数据</td></tr>';
    renderPager();
  };

  const fetchJson = async (url, opts) => {
    try {
      const res = await fetch(url, opts || {});
      if (!res.ok) return null;
      return await res.json();
    } catch (_) {
      return null;
    }
  };

  const loadRange = async ({ start, end } = {}) => {
    const u = new URL(window.location.origin + "/admin/api/system-status");
    if (start) u.searchParams.set("start", start);
    if (end) u.searchParams.set("end", end);
    const j = await fetchJson(u.toString());
    if (!j || !j.ok) return;
    const cfg = j.config || {};
    if (elLlmLimitInput) elLlmLimitInput.value = String(cfg.llm_tokens_limit ?? "");
    if (elSmsLimitInput) elSmsLimitInput.value = String(cfg.sms_calls_limit ?? "");
    allItems = Array.isArray(j.data && j.data.items) ? j.data.items.slice().reverse() : [];
    page = 1;
    renderCurrentPage();
  };

  const loadSummary = async () => {
    const j = await fetchJson("/admin/api/system-status/summary");
    if (j) setKpis(j);
  };

  const ensureDefaultRange = () => {
    if (!elStart || !elEnd) return;
    if (elStart.value && elEnd.value) return;
    const now = new Date();
    const end = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const start = new Date(end.getTime() - 19 * 24 * 3600 * 1000);
    const s = fmtYmd(start);
    const e = fmtYmd(end);
    elStart.value = s;
    elEnd.value = e;
    if (elStartDisplay) elStartDisplay.value = s.replaceAll("-", "/");
    if (elEndDisplay) elEndDisplay.value = e.replaceAll("-", "/");
  };

  if (elRangeForm) {
    elRangeForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      ensureDefaultRange();
      await loadRange({ start: elStart?.value || "", end: elEnd?.value || "" });
    });
  }
  if (elReset) {
    elReset.addEventListener("click", async () => {
      if (elStart) elStart.value = "";
      if (elEnd) elEnd.value = "";
      if (elStartDisplay) elStartDisplay.value = "";
      if (elEndDisplay) elEndDisplay.value = "";
      ensureDefaultRange();
      await loadRange({ start: elStart?.value || "", end: elEnd?.value || "" });
    });
  }
  if (elPrev) elPrev.addEventListener("click", () => { page = Math.max(1, page - 1); renderCurrentPage(); });
  if (elNext) elNext.addEventListener("click", () => { page = Math.min(totalPages(), page + 1); renderCurrentPage(); });

  if (elCfgForm) {
    elCfgForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const llmLim = elLlmLimitInput ? parseInt((elLlmLimitInput.value || "").trim() || "0", 10) : 0;
      const smsLim = elSmsLimitInput ? parseInt((elSmsLimitInput.value || "").trim() || "0", 10) : 0;
      if (elCfgSave) { elCfgSave.disabled = true; }
      const j = await fetchJson("/admin/api/system-status/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ llm_tokens_limit: llmLim, sms_calls_limit: smsLim }),
      });
      if (elCfgSave) { elCfgSave.disabled = false; }
      if (!j || !j.ok) {
        if (elCfgMsg) elCfgMsg.textContent = "保存失败，请重试";
        return;
      }
      if (j.summary) setKpis(j.summary);
      if (elCfgMsg) elCfgMsg.textContent = "";
    });
  }

  const refresh = async () => {
    if (document.hidden) return;
    ensureDefaultRange();
    await Promise.all([
      loadSummary(),
      loadRange({ start: elStart?.value || "", end: elEnd?.value || "" }),
    ]);
  };

  refresh();
  const timer = window.setInterval(loadSummary, 10000);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refresh();
  });
  window.addEventListener("beforeunload", () => window.clearInterval(timer));
})();
