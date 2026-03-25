(() => {
  const modalSelector = ".modal-shell";
  const sidebarCollapsedClass = "admin-sidebar-collapsed";
  const sidebarStorageKey = "admin.sidebar.collapsed";
  const sidebarAutoCollapseQuery = "(max-width: 980px)";
  const modalState = new WeakMap();
  let modalSeq = 0;
  let listenersBound = false;
  let sidebarMediaQuery = null;

  const getBody = () => document.body;
  const getRoot = () => document.documentElement;
  const getStore = () => (window.Alpine ? window.Alpine.store("adminUI") : null);

  const readSidebarPreference = () => {
    try {
      return window.localStorage.getItem(sidebarStorageKey) === "1";
    } catch (_) {
      return getRoot()?.classList.contains(sidebarCollapsedClass) || false;
    }
  };

  const writeSidebarPreference = (collapsed) => {
    try {
      window.localStorage.setItem(sidebarStorageKey, collapsed ? "1" : "0");
    } catch (_) {}
  };

  const applySidebarCollapsed = (collapsed) => {
    getRoot()?.classList.toggle(sidebarCollapsedClass, collapsed);
    getBody()?.classList.toggle(sidebarCollapsedClass, collapsed);
  };

  const bindSidebarViewport = (callback) => {
    if (typeof window.matchMedia !== "function") return null;
    const media = window.matchMedia(sidebarAutoCollapseQuery);
    const listener = () => callback(Boolean(media.matches));
    if (typeof media.addEventListener === "function") media.addEventListener("change", listener);
    else if (typeof media.addListener === "function") media.addListener(listener);
    return { media, listener };
  };

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
      sidebarCollapsed: false,
      sidebarAutoCollapsed: false,
      sidebarNarrowOverride: null,
      get isSidebarCollapsed() {
        if (!this.sidebarAutoCollapsed) return this.sidebarCollapsed;
        return this.sidebarNarrowOverride === null ? true : this.sidebarNarrowOverride;
      },
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
        this.initSidebar();
        this.shellReady = true;
      },
      initSidebar() {
        this.sidebarCollapsed = readSidebarPreference();
        if (!sidebarMediaQuery) {
          sidebarMediaQuery = bindSidebarViewport((matches) => this.syncSidebarViewport(matches));
        }
        this.syncSidebarViewport(Boolean(sidebarMediaQuery?.media?.matches));
      },
      syncSidebarViewport(matches) {
        const nextMatches = Boolean(matches);
        if (this.sidebarAutoCollapsed !== nextMatches) {
          this.sidebarNarrowOverride = null;
        }
        this.sidebarAutoCollapsed = nextMatches;
        applySidebarCollapsed(this.isSidebarCollapsed);
      },
      toggleSidebar() {
        if (this.sidebarAutoCollapsed) {
          this.sidebarNarrowOverride = !this.isSidebarCollapsed;
          applySidebarCollapsed(this.isSidebarCollapsed);
          return;
        }
        this.sidebarCollapsed = !this.sidebarCollapsed;
        applySidebarCollapsed(this.isSidebarCollapsed);
        writeSidebarPreference(this.sidebarCollapsed);
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
