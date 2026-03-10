(() => {
  const root = document.documentElement;
  const body = document.body;
  if (!body || !body.classList.contains("admin-app")) return;

  const navLinks = Array.from(document.querySelectorAll("[data-admin-nav]"));
  const titleEl = document.querySelector("[data-admin-page-title-target]");

  let modalSeq = 0;

  const deriveActiveNav = () => {
    const explicit = String(body.dataset.adminActive || "").trim();
    if (location.pathname === "/admin/status") return "status";
    if (location.pathname === "/admin/logs") return "logs";
    if (location.pathname === "/admin/assignments") return "assign";
    if (location.pathname.startsWith("/admin/candidates")) return "candidates";
    if (location.pathname === "/admin" || location.pathname.startsWith("/admin/exams")) return "exams";
    return explicit || "exams";
  };

  const syncActiveNav = () => {
    const key = deriveActiveNav();
    let activeLabel = "";
    navLinks.forEach((link) => {
      const isActive = String(link.dataset.adminNav || "") === key;
      link.classList.toggle("active", isActive);
      if (isActive) activeLabel = (link.dataset.adminPageTitle || link.textContent || "").trim();
    });
    if (titleEl && activeLabel && !titleEl.dataset.staticTitle) {
      titleEl.textContent = activeLabel;
    }
  };

  if (titleEl && titleEl.textContent.trim()) {
    titleEl.dataset.staticTitle = "1";
  }

  window.addEventListener("hashchange", syncActiveNav);
  syncActiveNav();

  const modalState = new WeakMap();
  const modalSelector = ".modal-shell";

  const findFocusable = (el) => {
    if (!el) return [];
    return Array.from(
      el.querySelectorAll(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      )
    );
  };

  const revealModal = (modal) => {
    modal.hidden = false;
    modal.setAttribute("data-modal-state", "opening");
    modal.dataset.modalId = modal.dataset.modalId || `modal-${++modalSeq}`;
    window.requestAnimationFrame(() => {
      modal.classList.add("is-open");
      modal.setAttribute("data-modal-state", "open");
    });
  };

  const hideModal = (modal, restoreFocus = true) => {
    if (!modal || modal.hidden) return;
    modal.classList.remove("is-open");
    modal.setAttribute("data-modal-state", "closing");
    const state = modalState.get(modal) || {};
    const finalize = () => {
      modal.hidden = true;
      modal.setAttribute("data-modal-state", "closed");
      modal.removeEventListener("transitionend", onEnd);
      if (restoreFocus && state.opener && state.opener.focus) {
        try { state.opener.focus(); } catch (_) {}
      }
    };
    const onEnd = (ev) => {
      if (ev.target !== modal) return;
      finalize();
    };
    modal.addEventListener("transitionend", onEnd);
    window.setTimeout(finalize, 220);
  };

  const bindModal = (modal) => {
    if (!modal || modal.dataset.modalBound === "1") return;
    modal.dataset.modalBound = "1";
    modal.classList.add("modal-shell");
    modal.addEventListener("click", (ev) => {
      if (ev.target === modal) hideModal(modal);
    });
  };

  const openModal = (modal, opts = {}) => {
    if (!modal) return;
    bindModal(modal);
    modalState.set(modal, { opener: opts.opener || document.activeElement || null });
    revealModal(modal);
    const focusables = findFocusable(modal);
    const target = opts.focusTarget || focusables[0] || modal;
    window.setTimeout(() => {
      try { target.focus(); } catch (_) {}
    }, 40);
  };

  const closeModal = (modal, opts = {}) => {
    hideModal(modal, opts.restoreFocus !== false);
  };

  document.querySelectorAll(modalSelector).forEach(bindModal);
  document.addEventListener("keydown", (ev) => {
    if (ev.key !== "Escape") return;
    const opened = Array.from(document.querySelectorAll(`${modalSelector}.is-open`)).pop();
    if (!opened) return;
    ev.preventDefault();
    closeModal(opened);
  });

  root.classList.add("admin-shell-ready");
  window.AdminShell = { openModal, closeModal, bindModal, syncActiveNav };
})();
