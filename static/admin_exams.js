(() => {
  const examQ = document.getElementById("exam_q");
  const uploadForm = document.getElementById("examUploadForm");
  const uploadInput = document.getElementById("file");
  const uploadTrigger = document.getElementById("examUploadTrigger");
  const aiGenToggle = document.getElementById("ai_gen_toggle");
  const aiGenModal = document.getElementById("ai_gen_modal");
  const aiGenPanel = document.getElementById("ai_gen_panel");
  const aiGenClose = document.getElementById("ai_gen_close");
  const aiCheckBtn = document.getElementById("ai_check_btn");
  const aiGenerateBtn = document.getElementById("ai_generate_btn");
  const aiCheckResult = document.getElementById("ai_check_result");
  const aiGenLoading = document.getElementById("ai_gen_loading");
  const aiPromptEl = document.getElementById("ai_exam_prompt");
  const aiIncludeDiagramsEl = document.getElementById("ai_include_diagrams");
  const aiUseSamplePromptEl = document.getElementById("ai_use_sample_prompt");
  const deleteExamModal = document.getElementById("delete_exam_confirm_modal");
  const deleteExamOk = document.getElementById("delete_exam_confirm_ok");
  const deleteExamCancel = document.getElementById("delete_exam_confirm_cancel");

  const RETURN_STATE_KEY = "admin.exams.return_state";
  const LS_AI_PROMPT_KEY = "admin.ai_exam_prompt.draft";
  const LS_AI_INCLUDE_DIAGRAMS_KEY = "admin.ai_exam_prompt.include_diagrams";
  const SAMPLE_AI_PROMPT = "请生成一份结构化技术试卷，包含岗位、题型、题量、难度、评分标准和答案解析。";

  let pendingDeleteForm = null;
  let aiCheckPassed = false;

  const renderAiCheckResult = (ok, text) => {
    if (!aiCheckResult) return;
    aiCheckResult.hidden = false;
    aiCheckResult.className = ok ? "ai-check-result ok" : "ai-check-result warn";
    aiCheckResult.textContent = text;
  };

  const syncGenerateEnabled = () => {
    if (aiGenerateBtn) aiGenerateBtn.disabled = !aiCheckPassed;
  };

  const saveAiDraft = () => {
    try {
      if (aiPromptEl) localStorage.setItem(LS_AI_PROMPT_KEY, String(aiPromptEl.value || ""));
      if (aiIncludeDiagramsEl) localStorage.setItem(LS_AI_INCLUDE_DIAGRAMS_KEY, aiIncludeDiagramsEl.checked ? "1" : "0");
    } catch (_) {}
  };

  const loadAiDraft = () => {
    try {
      if (aiPromptEl) {
        const v = localStorage.getItem(LS_AI_PROMPT_KEY);
        if (typeof v === "string" && v.trim()) aiPromptEl.value = v;
      }
      if (aiIncludeDiagramsEl) {
        const d = localStorage.getItem(LS_AI_INCLUDE_DIAGRAMS_KEY);
        if (d === "1" || d === "0") aiIncludeDiagramsEl.checked = d === "1";
      }
    } catch (_) {}
  };

  const openModal = (modal, opener, focusTarget) => {
    if (!modal) return;
    if (window.AdminShell && window.AdminShell.openModal) {
      window.AdminShell.openModal(modal, { opener, focusTarget });
    } else {
      modal.hidden = false;
    }
  };

  const closeModal = (modal) => {
    if (!modal) return;
    if (window.AdminShell && window.AdminShell.closeModal) {
      window.AdminShell.closeModal(modal);
    } else {
      modal.hidden = true;
    }
  };

  if (examQ && examQ.form) {
    let timer = null;
    examQ.addEventListener("input", () => {
      if (timer) window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        const u = new URL(window.location.href);
        const v = String(examQ.value || "").trim();
        if (v) u.searchParams.set("exam_q", v);
        else u.searchParams.delete("exam_q");
        u.searchParams.delete("exam_page");
        window.location.href = u.toString();
      }, 300);
    });
  }

  if (uploadForm && uploadInput && uploadTrigger) {
    uploadTrigger.addEventListener("click", () => {
      try { uploadInput.value = ""; } catch (_) {}
      uploadInput.click();
    });
    uploadInput.addEventListener("change", () => {
      if (!uploadInput.files || uploadInput.files.length < 1) return;
      uploadTrigger.disabled = true;
      uploadTrigger.textContent = "解析中...";
      uploadForm.submit();
    });
  }

  if (aiGenToggle && aiGenModal && aiGenPanel) {
    loadAiDraft();
    syncGenerateEnabled();
    aiGenToggle.addEventListener("click", () => openModal(aiGenModal, aiGenToggle, aiPromptEl));
    if (aiGenClose) aiGenClose.addEventListener("click", () => closeModal(aiGenModal));
    if (aiPromptEl) aiPromptEl.addEventListener("input", () => { aiCheckPassed = false; syncGenerateEnabled(); saveAiDraft(); });
    if (aiIncludeDiagramsEl) aiIncludeDiagramsEl.addEventListener("change", () => { aiCheckPassed = false; syncGenerateEnabled(); saveAiDraft(); });
    if (aiUseSamplePromptEl) {
      aiUseSamplePromptEl.addEventListener("change", () => {
        if (!aiPromptEl) return;
        if (aiUseSamplePromptEl.checked) aiPromptEl.value = SAMPLE_AI_PROMPT;
        else if (aiPromptEl.value.trim() === SAMPLE_AI_PROMPT) aiPromptEl.value = "";
        aiCheckPassed = false;
        syncGenerateEnabled();
        saveAiDraft();
      });
    }
    if (aiCheckBtn) {
      aiCheckBtn.addEventListener("click", async () => {
        const prompt = aiPromptEl ? String(aiPromptEl.value || "") : "";
        const fd = new FormData();
        fd.set("ai_exam_prompt", prompt);
        if (aiIncludeDiagramsEl && aiIncludeDiagramsEl.checked) fd.set("ai_include_diagrams", "1");
        try {
          aiCheckBtn.disabled = true;
          const resp = await fetch("/admin/exams/ai/check", { method: "POST", body: fd });
          const j = await resp.json().catch(() => ({}));
          if (!resp.ok || !j || !j.ok || !j.complete) {
            aiCheckPassed = false;
            syncGenerateEnabled();
            const err = (j && (j.error || j.message)) ? String(j.error || j.message) : "提示词检查未通过";
            renderAiCheckResult(false, err);
            return;
          }
          aiCheckPassed = true;
          syncGenerateEnabled();
          renderAiCheckResult(true, "提示词检查通过，可以生成试卷。");
        } catch (_) {
          aiCheckPassed = false;
          syncGenerateEnabled();
          renderAiCheckResult(false, "检查失败，请重试。");
        } finally {
          aiCheckBtn.disabled = false;
        }
      });
    }
    aiGenPanel.addEventListener("submit", (e) => {
      const submitter = e.submitter || document.activeElement;
      const op = submitter && submitter.getAttribute ? String(submitter.getAttribute("value") || "").trim() : "";
      if (op !== "generate") return;
      if (aiGenLoading) aiGenLoading.hidden = false;
      if (aiCheckBtn) aiCheckBtn.disabled = true;
      if (aiGenerateBtn) aiGenerateBtn.disabled = true;
      if (aiGenClose) aiGenClose.disabled = true;
    });
    const aiServerNoticeEl = document.getElementById("ai_server_notice");
    if (aiServerNoticeEl) {
      const txt = String(aiServerNoticeEl.dataset.text || "").trim();
      const lvl = String(aiServerNoticeEl.dataset.level || "error").trim().toLowerCase();
      if (txt) {
        openModal(aiGenModal, aiGenToggle, aiPromptEl);
        renderAiCheckResult(lvl === "ok", txt);
      }
    }
  }

  document.addEventListener("submit", (ev) => {
    const form = ev.target && ev.target.matches ? (ev.target.matches("form[data-exam-delete-form]") ? ev.target : null) : null;
    if (!form) return;
    ev.preventDefault();
    pendingDeleteForm = form;
    openModal(deleteExamModal, form, deleteExamOk);
  }, true);

  if (deleteExamCancel) {
    deleteExamCancel.addEventListener("click", () => {
      pendingDeleteForm = null;
      closeModal(deleteExamModal);
    });
  }
  if (deleteExamOk) {
    deleteExamOk.addEventListener("click", () => {
      const form = pendingDeleteForm;
      pendingDeleteForm = null;
      closeModal(deleteExamModal);
      if (form && form.submit) form.submit();
    });
  }

  for (const tr of document.querySelectorAll("tr[data-href]")) {
    tr.addEventListener("click", (ev) => {
      const el = ev.target;
      if (el && (el.closest("a") || el.closest("button") || el.closest("form"))) return;
      const href = tr.getAttribute("data-href");
      if (!href) return;
      try {
        const u = new URL(window.location.href);
        sessionStorage.setItem(RETURN_STATE_KEY, JSON.stringify({
          scrollY: Math.max(0, Math.round(window.scrollY || window.pageYOffset || 0)),
          exam_q: String(u.searchParams.get("exam_q") || "").trim(),
          exam_page: String(u.searchParams.get("exam_page") || "").trim(),
        }));
      } catch (_) {}
      window.location.href = href;
    });
  }
})();
