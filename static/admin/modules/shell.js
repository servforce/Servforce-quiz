import { copyTextToClipboard, queueMathTypeset } from "/static/assets/js/shared/runtime.js";
import { ADMIN_COMPACT_BREAKPOINT_QUERY, ADMIN_COMPACT_TAB_CONFIG } from "./constants.js";

export function createAdminShellModule() {
  return {
    async boot() {
      this.initAdminCompactLayout();
      window.addEventListener("popstate", () => this.handleRoute(location.pathname, { replace: true }));
      await this.refreshSession();
      if (this.session.authenticated) {
        await this.loadBootstrap();
        await this.handleRoute(location.pathname, { replace: true });
      } else {
        this.route = this.resolveRoute("/admin/login");
        await this.renderCurrentRoute();
      }
      this.booting = false;
    },

    initAdminCompactLayout() {
      if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
        return;
      }
      if (!this.adminCompactScrollHandler) {
        this.adminCompactScrollHandler = () => this.updateAdminCompactTabsStickyState();
        window.addEventListener("scroll", this.adminCompactScrollHandler, { passive: true });
      }
      if (!this.adminCompactMediaQuery) {
        this.adminCompactMediaQuery = window.matchMedia(ADMIN_COMPACT_BREAKPOINT_QUERY);
        this.adminCompactMediaQueryHandler = (event) => {
          this.handleAdminCompactLayoutChange(Boolean(event?.matches));
        };
        if (typeof this.adminCompactMediaQuery.addEventListener === "function") {
          this.adminCompactMediaQuery.addEventListener("change", this.adminCompactMediaQueryHandler);
        } else if (typeof this.adminCompactMediaQuery.addListener === "function") {
          this.adminCompactMediaQuery.addListener(this.adminCompactMediaQueryHandler);
        }
      }
      this.handleAdminCompactLayoutChange(Boolean(this.adminCompactMediaQuery.matches));
    },

    async handleAdminCompactLayoutChange(matches) {
      this.isAdminCompactLayout = Boolean(matches);
      this.ensureAdminCompactTab(this.route?.name);
      await this.$nextTick();
      if (this.route?.name === "logs") {
        if (this.shouldRenderLogsChart()) {
          this.renderLogsChart();
        } else {
          this.destroyLogsChart();
        }
      }
      this.updateAdminCompactTabsStickyState();
    },

    adminCompactTabConfig(routeName) {
      return ADMIN_COMPACT_TAB_CONFIG[String(routeName || "").trim()] || null;
    },

    adminCompactTabs(routeName) {
      return this.adminCompactTabConfig(routeName)?.tabs || [];
    },

    ensureAdminCompactTab(routeName) {
      const key = String(routeName || "").trim();
      const config = this.adminCompactTabConfig(key);
      if (!config) return;
      const currentTab = String(this.adminCompactTabsState?.[key] || "").trim();
      const validTabIds = new Set((config.tabs || []).map((item) => item.id));
      if (!validTabIds.has(currentTab)) {
        this.adminCompactTabsState = {
          ...(this.adminCompactTabsState || {}),
          [key]: config.defaultTab,
        };
      }
    },

    adminCompactTab(routeName) {
      const key = String(routeName || "").trim();
      const config = this.adminCompactTabConfig(key);
      if (!config) return "";
      this.ensureAdminCompactTab(key);
      return String(this.adminCompactTabsState?.[key] || config.defaultTab || "").trim();
    },

    adminCompactPanelVisible(routeName, tabId) {
      if (!this.isAdminCompactLayout || !this.adminCompactTabs(routeName).length) {
        return true;
      }
      return this.adminCompactTab(routeName) === String(tabId || "").trim();
    },

    shouldShowAdminCompactTabs(routeName) {
      return this.isAdminCompactLayout && this.adminCompactTabs(routeName).length > 0;
    },

    updateAdminCompactTabsStickyState() {
      if (typeof window === "undefined" || typeof document === "undefined") {
        return;
      }
      const nodes = Array.from(document.querySelectorAll(".admin-compact-tabs"));
      for (const node of nodes) {
        if (!(node instanceof HTMLElement)) {
          continue;
        }
        const isVisible = node.getClientRects().length > 0;
        const stickyTop = Number.parseFloat(window.getComputedStyle(node).top || "0") || 0;
        const rect = node.getBoundingClientRect();
        const isStuck = Boolean(isVisible && window.scrollY > 0 && rect.top <= stickyTop + 1);
        node.dataset.stuck = String(isStuck);
      }
    },

    isPrimaryNavItemActive(href) {
      const target = String(href || "").trim();
      if (!target) return false;
      return String(this.route?.path || "").startsWith(target);
    },

    async setAdminCompactTab(routeName, tabId, { scroll = false } = {}) {
      const key = String(routeName || "").trim();
      const nextTab = String(tabId || "").trim();
      const config = this.adminCompactTabConfig(key);
      if (!config || !(config.tabs || []).some((item) => item.id === nextTab)) {
        return;
      }
      this.adminCompactTabsState = {
        ...(this.adminCompactTabsState || {}),
        [key]: nextTab,
      };
      await this.$nextTick();
      if (key === "logs") {
        if (this.shouldRenderLogsChart()) {
          this.renderLogsChart();
        } else {
          this.destroyLogsChart();
        }
      }
      if (scroll && this.isAdminCompactLayout) {
        this.scrollAdminCompactTabsIntoView(key);
      }
      this.updateAdminCompactTabsStickyState();
    },

    resetAdminCompactTab(routeName) {
      const key = String(routeName || "").trim();
      if (!this.adminCompactTabConfig(key)) return;
      const nextState = { ...(this.adminCompactTabsState || {}) };
      delete nextState[key];
      this.adminCompactTabsState = nextState;
    },

    shouldRenderLogsChart() {
      if (this.route?.name !== "logs") return false;
      return !this.isAdminCompactLayout || this.adminCompactPanelVisible("logs", "trend");
    },

    scrollAdminCompactTabsIntoView(routeName) {
      if (typeof document === "undefined") return;
      const selector = `[data-admin-compact-tabs="${String(routeName || "").trim()}"]`;
      const candidates = Array.from(document.querySelectorAll(selector));
      const target = candidates.find((node) => node instanceof HTMLElement && node.getClientRects().length > 0) || candidates[0];
      if (!target || typeof target.scrollIntoView !== "function") return;
      target.scrollIntoView({ behavior: "smooth", block: "start" });
    },

    pretty(value) {
      return JSON.stringify(value || {}, null, 2);
    },

    queueMathTypeset(root = null) {
      queueMathTypeset(root instanceof Element ? root : this.$root);
    },

    removeNotice(noticeId) {
      const targetId = Number(noticeId || 0);
      this.notices = (Array.isArray(this.notices) ? this.notices : []).filter(
        (item) => Number(item?.id || 0) !== targetId,
      );
      this.notice = this.notices.length
        ? String(this.notices[this.notices.length - 1]?.message || "")
        : "";
    },

    showNotice(message) {
      const text = String(message || "").trim();
      if (!text) return;
      const id = ++this.noticeSeq;
      const next = [...(Array.isArray(this.notices) ? this.notices : []), { id, message: text }];
      this.notices = next.slice(-3);
      this.notice = text;
      window.setTimeout(() => {
        this.removeNotice(id);
      }, 3600);
    },

    scheduleAssignmentsReload() {
      window.clearTimeout(this.assignmentsFilterTimer);
      this.assignmentsFilterTimer = window.setTimeout(() => {
        this.loadAssignments();
      }, 220);
    },

    async copyText(text, successMessage) {
      await copyTextToClipboard(text);
      this.showNotice(successMessage || "内容已复制");
      return true;
    },

    async login() {
      this.error = "";
      try {
        await this.api("/api/admin/session/login", {
          method: "POST",
          body: JSON.stringify(this.loginForm),
          headers: { "Content-Type": "application/json" },
        });
        await this.refreshSession();
        await this.$nextTick();
        await this.loadBootstrap();
        await this.handleRoute("/admin/quizzes");
      } catch (error) {
        this.error = error.message || "登录失败";
      }
    },

    async logout() {
      this.destroyLogsChart();
      this.stopSyncPolling();
      this.stopAssignmentsPolling();
      this.stopCandidateResumeUploadPolling();
      this.stopCandidateResumeReparsePolling();
      this.adminCompactTabsState = {};
      await this.api("/api/admin/session/logout", { method: "POST", quiet: true });
      this.session = { authenticated: false, username: "" };
      this.repoBinding = {};
      this.resetRebindForm();
      history.replaceState({}, "", "/admin/login");
      this.route = this.resolveRoute("/admin/login");
      await this.renderCurrentRoute();
    },
  };
}
