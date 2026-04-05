import { clearFragmentMount, loadHtmlFragment } from "/static/assets/js/shared/runtime.js";

export const ADMIN_ROUTE_FRAGMENTS = {
  login: { fragment: "/static/admin/pages/login.html", mountRef: "loginMount" },
  quizzes: { fragment: "/static/admin/pages/quizzes.html", mountRef: "pageMount" },
  "quiz-detail": { fragment: "/static/admin/pages/quiz-detail.html", mountRef: "pageMount" },
  candidates: { fragment: "/static/admin/pages/candidates.html", mountRef: "pageMount" },
  "candidate-detail": { fragment: "/static/admin/pages/candidate-detail.html", mountRef: "pageMount" },
  assignments: { fragment: "/static/admin/pages/assignments.html", mountRef: "pageMount" },
  "attempt-detail": { fragment: "/static/admin/pages/attempt-detail.html", mountRef: "pageMount" },
  logs: { fragment: "/static/admin/pages/logs.html", mountRef: "pageMount" },
  status: { fragment: "/static/admin/pages/status.html", mountRef: "pageMount" },
  mcp: { fragment: "/static/admin/pages/mcp.html", mountRef: "pageMount" },
};

export function createAdminRouterModule() {
  return {
    async resolveAdminRouteMount(refName, maxTicks = 4) {
      let mount = this.$refs?.[refName];
      if (mount instanceof HTMLElement) {
        return mount;
      }
      // 登录态切换依赖 x-if 重建壳层，先等挂载点真正进入 DOM。
      for (let index = 0; index < maxTicks; index += 1) {
        if (typeof this.$nextTick === "function") {
          await this.$nextTick();
        } else {
          await Promise.resolve();
        }
        mount = this.$refs?.[refName];
        if (mount instanceof HTMLElement) {
          return mount;
        }
      }
      return null;
    },

    currentAdminRouteFragment() {
      return ADMIN_ROUTE_FRAGMENTS[String(this.route?.name || "").trim()] || ADMIN_ROUTE_FRAGMENTS.quizzes;
    },

    async renderCurrentRoute() {
      const current = this.currentAdminRouteFragment();
      const target = await this.resolveAdminRouteMount(current.mountRef);
      const otherRef = current.mountRef === "loginMount" ? "pageMount" : "loginMount";
      const other = this.$refs?.[otherRef];
      clearFragmentMount(other, window.Alpine);
      if (!(target instanceof HTMLElement)) {
        return;
      }
      await loadHtmlFragment({
        mount: target,
        path: current.fragment,
        cache: this.fragmentCache,
        alpine: window.Alpine,
      });
    },

    resolveRoute(pathname) {
      const path = pathname || "/admin";
      if (path === "/admin/login") {
        return { name: "login", path, title: "管理员登录", section: "Login", params: {} };
      }
      if (path === "/admin" || path === "/admin/quizzes") {
        return { name: "quizzes", path: "/admin/quizzes", title: "测验", section: "Quizzes", params: {} };
      }
      let match = path.match(/^\/admin\/(?:quizzes|exams)\/([^/]+)$/);
      if (match) {
        return {
          name: "quiz-detail",
          path,
          title: "测验详情",
          section: "Quizzes",
          params: { quizKey: decodeURIComponent(match[1]) },
        };
      }
      if (path === "/admin/candidates") {
        return { name: "candidates", path, title: "候选人", section: "Candidates", params: {} };
      }
      match = path.match(/^\/admin\/candidates\/(\d+)$/);
      if (match) {
        return {
          name: "candidate-detail",
          path,
          title: "候选人详情",
          section: "Candidates",
          params: { candidateId: Number(match[1]) },
        };
      }
      if (path === "/admin/assignments") {
        return { name: "assignments", path, title: "邀约与答题", section: "Assignments", params: {} };
      }
      match = path.match(/^\/admin\/(?:attempt|result)\/([^/]+)$/);
      if (match) {
        return {
          name: "attempt-detail",
          path,
          title: "答题详情",
          section: "Assignments",
          params: { token: decodeURIComponent(match[1]) },
        };
      }
      if (path === "/admin/logs") {
        return { name: "logs", path, title: "系统日志", section: "Logs", params: {} };
      }
      if (path === "/admin/status") {
        return { name: "status", path, title: "系统状态", section: "Status", params: {} };
      }
      if (path === "/admin/mcp") {
        return { name: "mcp", path, title: "MCP", section: "MCP", params: {} };
      }
      return { name: "quizzes", path: "/admin/quizzes", title: "测验", section: "Quizzes", params: {} };
    },

    async refreshSession() {
      const data = await this.api("/api/admin/session", { quiet: true });
      this.session = data || { authenticated: false, username: "" };
      return this.session;
    },

    async loadBootstrap() {
      await Promise.all([
        this.loadSystemBootstrap(),
        this.loadStatusSummary(),
        this.loadQuizzes({ quiet: true }),
        this.loadCandidates({ quiet: true }),
      ]);
    },

    async handleRoute(pathname, { replace = false } = {}) {
      if (!this.session.authenticated && pathname !== "/admin/login") {
        this.destroyLogsChart();
        this.stopSyncPolling();
        this.stopAssignmentsPolling();
        history.replaceState({}, "", "/admin/login");
        this.route = this.resolveRoute("/admin/login");
        await this.renderCurrentRoute();
        return;
      }

      let nextRoute = this.resolveRoute(pathname);
      if (this.session.authenticated && nextRoute.name === "login") {
        nextRoute = this.resolveRoute("/admin/quizzes");
        replace = true;
      }

      const previousRouteName = String(this.route?.name || "").trim();
      if (previousRouteName === "logs" && nextRoute.name !== "logs") {
        this.destroyLogsChart();
      }
      if (previousRouteName && previousRouteName !== nextRoute.name) {
        this.resetAdminCompactTab(previousRouteName);
      }

      this.route = nextRoute;
      this.ensureAdminCompactTab(this.route.name);
      if (!replace) {
        history.pushState({}, "", this.route.path);
      } else {
        history.replaceState({}, "", this.route.path);
      }

      this.error = "";
      await this.renderCurrentRoute();
      await this.$nextTick();

      if (this.route.name !== "quizzes") {
        this.stopSyncPolling();
      }
      if (!["assignments", "attempt-detail"].includes(this.route.name)) {
        this.stopAssignmentsPolling();
      }
      if (this.route.name !== "candidates") {
        this.stopCandidateResumeUploadPolling();
      }
      if (this.route.name !== "candidate-detail") {
        this.stopCandidateResumeReparsePolling();
      }

      switch (this.route.name) {
        case "quizzes":
          await this.loadQuizzes();
          break;
        case "quiz-detail":
          await this.loadQuizDetail(this.route.params.quizKey);
          break;
        case "candidates":
          this.resetCandidateResumeUploadState();
          await this.loadCandidates();
          break;
        case "candidate-detail":
          await this.loadCandidateDetail(this.route.params.candidateId);
          break;
        case "assignments":
          await this.loadAssignments();
          break;
        case "attempt-detail":
          await this.loadAttemptDetail(this.route.params.token);
          break;
        case "logs":
          await this.loadLogs();
          break;
        case "status":
          await this.loadStatus();
          break;
        case "mcp":
          await this.loadMcpPage();
          break;
        default:
          break;
      }
      await this.$nextTick();
      this.updateAdminCompactTabsStickyState();
    },

    async go(path) {
      await this.handleRoute(path);
    },
  };
}
