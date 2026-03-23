(() => {
  const modalSelector = ".modal-shell";
  const modalState = new WeakMap();
  let modalSeq = 0;
  let listenersBound = false;

  const getBody = () => document.body;
  const getRoot = () => document.documentElement;
  const getStore = () => (window.Alpine ? window.Alpine.store("adminUI") : null);

  const findFocusable = (el) => {
    if (!el) return [];
    return Array.from(
      el.querySelectorAll(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      )
    );
  };

  const deriveActiveNav = () => {
    const body = getBody();
    const explicit = String(body?.dataset.adminActive || "").trim();
    if (location.pathname === "/admin/status") return "status";
    if (location.pathname === "/admin/logs") return "logs";
    if (location.pathname === "/admin/assignments") return "assign";
    if (location.pathname.startsWith("/admin/candidates")) return "candidates";
    if (location.pathname === "/admin" || location.pathname.startsWith("/admin/exams")) return "exams";
    return explicit || "exams";
  };

  const applyActiveNav = (activeNav) => {
    document.querySelectorAll("[data-admin-nav]").forEach((link) => {
      const isActive = link.getAttribute("data-admin-nav") === activeNav;
      link.classList.toggle("active", isActive);
      if (isActive) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
  };

  const registerAlpine = (Alpine) => {
    if (!Alpine || Alpine.store("adminUI")) return;

    Alpine.store("adminUI", {
      activeNav: "exams",
      shellReady: false,
      initShell() {
        const body = getBody();
        if (!body || !body.classList.contains("admin-app")) return;
        const titleEl = document.querySelector("[data-admin-page-title-target]");
        if (titleEl && titleEl.textContent.trim()) {
          titleEl.dataset.staticTitle = "1";
        }
        this.syncActiveNav();
        document.querySelectorAll(modalSelector).forEach((modal) => this.bindModal(modal));
        if (!listenersBound) {
          listenersBound = true;
          window.addEventListener("hashchange", () => this.syncActiveNav());
          document.addEventListener("keydown", (event) => {
            if (event.key !== "Escape") return;
            const opened = Array.from(document.querySelectorAll(`${modalSelector}.is-open`)).pop();
            if (!opened) return;
            event.preventDefault();
            this.closeModal(opened);
          });
        }
        getRoot()?.classList.add("admin-shell-ready");
        this.shellReady = true;
      },
      syncActiveNav() {
        this.activeNav = deriveActiveNav();
        applyActiveNav(this.activeNav);
        const titleEl = document.querySelector("[data-admin-page-title-target]");
        const activeLink = document.querySelector(`[data-admin-nav="${this.activeNav}"]`);
        const activeLabel = String(activeLink?.dataset.adminPageTitle || activeLink?.textContent || "").trim();
        if (titleEl && activeLabel && !titleEl.dataset.staticTitle) {
          titleEl.textContent = activeLabel;
        }
      },
      bindModal(modal) {
        if (!modal || modal.dataset.modalBound === "1") return;
        modal.dataset.modalBound = "1";
        modal.classList.add("modal-shell");
        modal.addEventListener("click", (event) => {
          if (event.target === modal) this.closeModal(modal);
        });
      },
      openModal(modal, opts = {}) {
        if (!modal) return;
        this.bindModal(modal);
        modalState.set(modal, { opener: opts.opener || document.activeElement || null });
        modal.hidden = false;
        modal.setAttribute("data-modal-state", "opening");
        modal.dataset.modalId = modal.dataset.modalId || `modal-${++modalSeq}`;
        window.requestAnimationFrame(() => {
          modal.classList.add("is-open");
          modal.setAttribute("data-modal-state", "open");
        });
        const focusables = findFocusable(modal);
        const target = opts.focusTarget || focusables[0] || modal;
        window.setTimeout(() => {
          try { target.focus(); } catch (_) {}
        }, 40);
      },
      closeModal(modal, opts = {}) {
        if (!modal || modal.hidden) return;
        const restoreFocus = opts.restoreFocus !== false;
        modal.classList.remove("is-open");
        modal.setAttribute("data-modal-state", "closing");
        const state = modalState.get(modal) || {};
        const finalize = () => {
          modal.hidden = true;
          modal.setAttribute("data-modal-state", "closed");
          modal.removeEventListener("transitionend", onEnd);
          if (restoreFocus && state.opener && typeof state.opener.focus === "function") {
            try { state.opener.focus(); } catch (_) {}
          }
        };
        const onEnd = (event) => {
          if (event.target !== modal) return;
          finalize();
        };
        modal.addEventListener("transitionend", onEnd);
        window.setTimeout(finalize, 220);
      },
    });

    Alpine.data("adminShell", () => ({
      init() {
        this.$store.adminUI.initShell();
      },
    }));
  };

  if (window.Alpine) {
    registerAlpine(window.Alpine);
  } else {
    document.addEventListener("alpine:init", () => registerAlpine(window.Alpine), { once: true });
  }

  window.AdminShell = {
    syncActiveNav() {
      getStore()?.syncActiveNav();
    },
    bindModal(modal) {
      getStore()?.bindModal(modal);
    },
    openModal(modal, opts = {}) {
      getStore()?.openModal(modal, opts);
    },
    closeModal(modal, opts = {}) {
      getStore()?.closeModal(modal, opts);
    },
  };
})();
