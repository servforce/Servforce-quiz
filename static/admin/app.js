(() => {
  const LOG_TREND_WINDOW_DAYS = 30;
  const LOG_SERIES_META = [
    { key: "candidate", label: "候选人", color: "#2563eb", hint: "创建、编辑与简历入库" },
    { key: "exam", label: "试卷", color: "#14b8a6", hint: "试卷查看、更新与同步" },
    { key: "grading", label: "判卷", color: "#f59e0b", hint: "判卷完成与得分回写" },
    { key: "assignment", label: "邀约", color: "#7c3aed", hint: "邀约创建、验证与答题过程" },
    { key: "system", label: "系统", color: "#ef4444", hint: "告警与短信相关事件" },
  ];
  const TRAIT_COLOR_PALETTE = [
    { accent: "#2563eb", border: "rgba(37,99,235,0.22)", background: "rgba(37,99,235,0.10)", text: "#1d4ed8" },
    { accent: "#059669", border: "rgba(5,150,105,0.24)", background: "rgba(5,150,105,0.10)", text: "#047857" },
    { accent: "#7c3aed", border: "rgba(124,58,237,0.22)", background: "rgba(124,58,237,0.10)", text: "#6d28d9" },
    { accent: "#d97706", border: "rgba(217,119,6,0.24)", background: "rgba(217,119,6,0.10)", text: "#b45309" },
    { accent: "#db2777", border: "rgba(219,39,119,0.22)", background: "rgba(219,39,119,0.10)", text: "#be185d" },
    { accent: "#0891b2", border: "rgba(8,145,178,0.22)", background: "rgba(8,145,178,0.10)", text: "#0e7490" },
    { accent: "#4f46e5", border: "rgba(79,70,229,0.22)", background: "rgba(79,70,229,0.10)", text: "#4338ca" },
    { accent: "#ea580c", border: "rgba(234,88,12,0.24)", background: "rgba(234,88,12,0.10)", text: "#c2410c" },
  ];

  const register = () => {
    if (!window.Alpine) return;
    window.Alpine.data("adminApp", () => ({
      booting: true,
      error: "",
      notice: "",
      session: { authenticated: false, username: "" },
      route: { name: "login", path: "/admin/login", title: "管理员登录", section: "Login", params: {} },
      navItems: [
        { href: "/admin/exams", label: "试卷", icon: "library_books" },
        { href: "/admin/candidates", label: "候选人", icon: "group" },
        { href: "/admin/assignments", label: "邀约与答题", icon: "assignment" },
        { href: "/admin/logs", label: "系统日志", icon: "receipt_long" },
        { href: "/admin/status", label: "系统状态", icon: "monitoring" },
      ],
      loginForm: { username: "admin", password: "password" },
      filters: {
        exams: { q: "" },
        candidates: { q: "" },
        assignments: { q: "" },
      },
      syncForm: { repoUrl: "" },
      repoBinding: {},
      rebindForm: { open: false, repoUrl: "", confirmationText: "" },
      candidateForm: { name: "", phone: "" },
      candidateEvaluation: "",
      assignmentForm: {
        exam_key: "",
        candidate_id: "",
        invite_start_date: new Date().toISOString().slice(0, 10),
        invite_end_date: new Date(Date.now() + 86400000).toISOString().slice(0, 10),
        time_limit_seconds: "7200",
      },
      exams: { items: [] },
      examDetail: { exam: {}, selected_version: {}, version_history: [], stats: {} },
      candidates: { items: [] },
      candidateDetail: { candidate: {}, profile: {}, resume_parsed: {} },
      assignments: { items: [] },
      attemptDetail: { assignment: {}, archive: {} },
      logs: { items: [], counts: {}, trend: { days: [], series: {} } },
      logsChart: null,
      logsChartContainer: null,
      logsChartSeries: {},
      logsChartResizeObserver: null,
      logsChartWindowResize: null,
      syncState: {},
      syncPollTimer: null,
      syncPollIntervalMs: 2000,
      statusSummary: {},
      statusRange: { data: {} },
      statusConfig: { llm_tokens_limit: "", sms_calls_limit: "" },

      async boot() {
        window.addEventListener("popstate", () => this.handleRoute(location.pathname, { replace: true }));
        await this.refreshSession();
        if (this.session.authenticated) {
          await this.loadBootstrap();
          await this.handleRoute(location.pathname, { replace: true });
        } else {
          this.route = this.resolveRoute("/admin/login");
        }
        this.booting = false;
      },

      pretty(value) {
        return JSON.stringify(value || {}, null, 2);
      },

      examQuestions() {
        const questions = this.examDetail?.selected_version?.spec?.questions;
        return Array.isArray(questions) ? questions : [];
      },

      questionTypeLabel(value) {
        const labels = {
          single: "单选",
          multiple: "多选",
          short: "简答",
          unknown: "其他",
        };
        const key = String(value || "").trim().toLowerCase();
        return labels[key] || String(value || "其他");
      },

      formatDateTime(value) {
        const text = String(value || "").trim();
        if (!text) return "";
        const date = new Date(text);
        if (Number.isNaN(date.getTime())) {
          return text;
        }
        return new Intl.DateTimeFormat("zh-CN", {
          year: "numeric",
          month: "2-digit",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
        }).format(date);
      },

      traitPalette(index) {
        return TRAIT_COLOR_PALETTE[Math.abs(Number(index || 0)) % TRAIT_COLOR_PALETTE.length];
      },

      traitDimensions() {
        const names = [];
        const seen = new Set();
        const usedNames = [];
        const usedSet = new Set();
        const pushUsedName = (value) => {
          const name = String(value || "").trim();
          if (!name || usedSet.has(name)) return;
          usedSet.add(name);
          usedNames.push(name);
        };
        for (const question of this.examQuestions()) {
          for (const option of question?.options || []) {
            for (const traitName of Object.keys(option?.traits || {})) {
              pushUsedName(traitName);
            }
          }
        }
        if (!usedNames.length) {
          return [];
        }
        const pushName = (value) => {
          const name = String(value || "").trim();
          if (!name || seen.has(name) || !usedSet.has(name)) return;
          seen.add(name);
          names.push(name);
        };
        const configured = this.examDetail?.selected_version?.trait?.dimensions || this.examDetail?.exam?.trait?.dimensions;
        if (Array.isArray(configured)) {
          configured.forEach(pushName);
        }
        usedNames.forEach(pushName);
        return names.map((name, index) => ({
          name,
          ...this.traitPalette(index),
        }));
      },

      traitMeta(name) {
        const current = String(name || "").trim();
        if (!current) {
          return this.traitPalette(0);
        }
        const found = this.traitDimensions().find((item) => item.name === current);
        if (found) {
          return found;
        }
        const hash = Array.from(current).reduce((sum, char) => sum + (char.codePointAt(0) || 0), 0);
        return {
          name: current,
          ...this.traitPalette(hash),
        };
      },

      traitBadgeStyle(name) {
        const meta = this.traitMeta(name);
        return {
          borderColor: meta.border,
          backgroundColor: meta.background,
          color: meta.text,
        };
      },

      traitDotStyle(name) {
        const meta = this.traitMeta(name);
        return { backgroundColor: meta.accent };
      },

      optionTraits(option) {
        const traits = option?.traits;
        if (!traits || typeof traits !== "object") {
          return [];
        }
        return Object.entries(traits)
          .filter(([name]) => String(name || "").trim())
          .map(([name, score]) => {
            const value = Number(score || 0);
            const text = Number.isFinite(value) && value > 0 ? `+${value}` : String(score ?? "");
            return {
              name: String(name || "").trim(),
              scoreText: text,
            };
          });
      },

      logCategoryCards() {
        return LOG_SERIES_META.map((item) => ({
          ...item,
          count: Number(this.logs?.counts?.[item.key] || 0),
        }));
      },

      logTrendRangeLabel() {
        const trend = this.logs?.trend || {};
        if (!trend.start_day || !trend.end_day) {
          return `近 ${LOG_TREND_WINDOW_DAYS} 天`;
        }
        return `${trend.start_day} 至 ${trend.end_day}`;
      },

      hasLogTrendData() {
        return LOG_SERIES_META.some((item) =>
          (this.logs?.trend?.series?.[item.key] || []).some((point) => Number(point?.count || 0) > 0),
        );
      },

      formatNumber(value) {
        const number = Number(value || 0);
        if (!Number.isFinite(number)) {
          return "0";
        }
        return new Intl.NumberFormat("zh-CN").format(number);
      },

      statusRangeLabel() {
        const data = this.statusRange?.data || {};
        if (!data.range_start || !data.range_end) {
          return "近 30 天";
        }
        return `${data.range_start} 至 ${data.range_end}`;
      },

      statusDailyRows() {
        const items = Array.isArray(this.statusRange?.data?.items) ? this.statusRange.data.items : [];
        return [...items].reverse();
      },

      statusDailyTotals() {
        const totals = {
          exams_new: 0,
          invites_new: 0,
          candidates_new: 0,
          llm_tokens: 0,
          sms_calls: 0,
        };
        for (const item of this.statusDailyRows()) {
          totals.exams_new += Number(item?.exams_new || 0);
          totals.invites_new += Number(item?.invites_new || 0);
          totals.candidates_new += Number(item?.candidates_new || 0);
          totals.llm_tokens += Number(item?.llm_tokens || 0);
          totals.sms_calls += Number(item?.sms_calls || 0);
        }
        return totals;
      },

      browserTzOffsetMinutes() {
        return -new Date().getTimezoneOffset();
      },

      showNotice(message) {
        this.notice = message;
        window.clearTimeout(this.noticeTimer);
        this.noticeTimer = window.setTimeout(() => {
          this.notice = "";
        }, 3600);
      },

      syncStatus() {
        return String(this.syncState?.status || "").trim().toLowerCase();
      },

      isSyncBusy() {
        return ["queued", "running"].includes(this.syncStatus());
      },

      hasRepoBinding() {
        return Boolean(String(this.repoBinding?.repo_url || "").trim());
      },

      resetRebindForm() {
        this.rebindForm = { open: false, repoUrl: "", confirmationText: "" };
      },

      openRebindForm() {
        if (this.isSyncBusy()) return;
        this.rebindForm.open = true;
        this.rebindForm.repoUrl = "";
        this.rebindForm.confirmationText = "";
      },

      closeRebindForm() {
        this.resetRebindForm();
      },

      stopSyncPolling() {
        if (!this.syncPollTimer) return;
        window.clearTimeout(this.syncPollTimer);
        this.syncPollTimer = null;
      },

      scheduleSyncPolling() {
        if (this.syncPollTimer || !this.isSyncBusy() || this.route.name !== "exams") return;
        this.syncPollTimer = window.setTimeout(async () => {
          this.syncPollTimer = null;
          if (this.route.name !== "exams" || !this.session.authenticated) return;
          const previousSyncStatus = this.syncStatus();
          const previousSyncJobId = String(this.syncState?.last_job_id || "").trim();
          await this.loadExams({
            quiet: true,
            source: "sync-poll",
            previousSyncStatus,
            previousSyncJobId,
          });
        }, this.syncPollIntervalMs);
      },

      resolveRoute(pathname) {
        const path = pathname || "/admin";
        if (path === "/admin/login") {
          return { name: "login", path, title: "管理员登录", section: "Login", params: {} };
        }
        if (path === "/admin" || path === "/admin/exams") {
          return { name: "exams", path: "/admin/exams", title: "试卷", section: "Exams", params: {} };
        }
        let match = path.match(/^\/admin\/exams\/([^/]+)$/);
        if (match) {
          return {
            name: "exam-detail",
            path,
            title: "试卷详情",
            section: "Exams",
            params: { examKey: decodeURIComponent(match[1]) },
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
        return { name: "exams", path: "/admin/exams", title: "试卷", section: "Exams", params: {} };
      },

      async refreshSession() {
        const data = await this.api("/api/admin/session", { quiet: true });
        this.session = data || { authenticated: false, username: "" };
        return this.session;
      },

      async loadBootstrap() {
        await Promise.all([
          this.loadStatusSummary(),
          this.loadExams({ quiet: true }),
          this.loadCandidates({ quiet: true }),
        ]);
      },

      async handleRoute(pathname, { replace = false } = {}) {
        if (!this.session.authenticated && pathname !== "/admin/login") {
          this.stopSyncPolling();
          history.replaceState({}, "", "/admin/login");
          this.route = this.resolveRoute("/admin/login");
          return;
        }
        this.route = this.resolveRoute(pathname);
        if (this.route.name !== "exams") {
          this.stopSyncPolling();
        }
        if (!replace) {
          history.pushState({}, "", this.route.path);
        }
        this.error = "";
        switch (this.route.name) {
          case "exams":
            await this.loadExams();
            break;
          case "exam-detail":
            await this.loadExamDetail(this.route.params.examKey);
            break;
          case "candidates":
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
          default:
            break;
        }
      },

      async go(path) {
        await this.handleRoute(path);
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
          await this.loadBootstrap();
          await this.handleRoute("/admin/exams");
        } catch (error) {
          this.error = error.message || "登录失败";
        }
      },

      async logout() {
        this.destroyLogsChart();
        this.stopSyncPolling();
        await this.api("/api/admin/session/logout", { method: "POST", quiet: true });
        this.session = { authenticated: false, username: "" };
        this.repoBinding = {};
        this.resetRebindForm();
        history.replaceState({}, "", "/admin/login");
        this.route = this.resolveRoute("/admin/login");
      },

      async loadExams({ quiet = false, source = "manual", previousSyncStatus = "", previousSyncJobId = "" } = {}) {
        const query = new URLSearchParams();
        if (this.filters.exams.q) query.set("q", this.filters.exams.q);
        const data = await this.api(`/api/admin/exams?${query.toString()}`, { quiet });
        if (!data) return;
        this.exams = data;
        this.repoBinding = data.repo_binding || {};
        this.syncState = data.sync_state || {};
        if (!this.hasRepoBinding() && this.syncState.repo_url && (this.isSyncBusy() || !this.syncForm.repoUrl)) {
          this.syncForm.repoUrl = this.syncState.repo_url;
        }
        if (this.hasRepoBinding()) {
          this.syncForm.repoUrl = "";
        } else {
          this.resetRebindForm();
        }
        const currentSyncStatus = this.syncStatus();
        if (this.route.name === "exams" && this.isSyncBusy()) {
          this.scheduleSyncPolling();
        } else {
          this.stopSyncPolling();
        }
        if (
          source === "sync-poll" &&
          ["queued", "running"].includes(String(previousSyncStatus || "").trim().toLowerCase()) &&
          !["queued", "running"].includes(currentSyncStatus)
        ) {
          const finishedJobId = String(this.syncState?.last_job_id || "").trim();
          if (!previousSyncJobId || previousSyncJobId === finishedJobId) {
            this.showNotice(currentSyncStatus === "done" ? "试卷同步完成，列表已刷新" : "试卷同步失败");
          }
        }
      },

      async bindRepo() {
        if (this.isSyncBusy() || this.hasRepoBinding()) return;
        const result = await this.api("/api/admin/exams/binding", {
          method: "POST",
          body: JSON.stringify({ repo_url: this.syncForm.repoUrl || "" }),
          headers: { "Content-Type": "application/json" },
        });
        this.repoBinding = result.binding || {};
        this.syncForm.repoUrl = "";
        if (result.sync?.error) {
          this.showNotice("仓库已绑定，但自动同步投递失败");
        } else {
          this.showNotice("仓库已绑定，已开始同步");
        }
        await this.loadExams({ quiet: true });
      },

      async syncExams() {
        if (this.isSyncBusy() || !this.hasRepoBinding()) return;
        const result = await this.api("/api/admin/exams/sync", {
          method: "POST",
          body: JSON.stringify({}),
          headers: { "Content-Type": "application/json" },
        });
        this.showNotice(result.created ? "试卷同步任务已创建" : "已复用正在运行的同步任务");
        await this.loadExams({ quiet: true });
      },

      async confirmRebind() {
        if (this.isSyncBusy() || !this.hasRepoBinding()) return;
        const result = await this.api("/api/admin/exams/binding/rebind", {
          method: "POST",
          body: JSON.stringify({
            repo_url: this.rebindForm.repoUrl || "",
            confirmation_text: this.rebindForm.confirmationText || "",
          }),
          headers: { "Content-Type": "application/json" },
        });
        this.exams = { items: [], page: 1, per_page: 20, total: 0, total_pages: 1 };
        this.examDetail = { exam: {}, selected_version: {}, version_history: [], stats: {} };
        this.repoBinding = result.binding || {};
        this.resetRebindForm();
        if (result.sync?.error) {
          this.showNotice("仓库已重新绑定，现有问卷数据已清空，但自动同步投递失败");
        } else {
          this.showNotice("仓库已重新绑定，现有问卷数据已清空并开始同步");
        }
        await this.loadExams({ quiet: true });
      },

      async loadExamDetail(examKey) {
        this.examDetail = await this.api(`/api/admin/exams/${encodeURIComponent(examKey)}`);
      },

    async loadExamVersion(versionId) {
      this.examDetail = await this.api(`/api/admin/exam-versions/${versionId}`);
    },

    async togglePublicInvite() {
      const enabled = !Boolean(this.examDetail.exam?.public_invite_enabled);
      const result = await this.api(`/api/admin/exams/${encodeURIComponent(this.examDetail.exam.exam_key)}/public-invite`, {
        method: "POST",
        body: JSON.stringify({ enabled }),
        headers: { "Content-Type": "application/json" },
      });
      this.examDetail.exam.public_invite_enabled = result.enabled;
      this.examDetail.exam.public_invite_url = result.public_url;
      this.showNotice(result.enabled ? "公开邀约已开启" : "公开邀约已关闭");
    },

    async loadCandidates({ quiet = false } = {}) {
      const query = new URLSearchParams();
      if (this.filters.candidates.q) query.set("q", this.filters.candidates.q);
      const data = await this.api(`/api/admin/candidates?${query.toString()}`, { quiet });
      if (!data) return;
      this.candidates = data;
    },

    async createCandidate() {
      await this.api("/api/admin/candidates", {
        method: "POST",
        body: JSON.stringify(this.candidateForm),
        headers: { "Content-Type": "application/json" },
      });
      this.candidateForm = { name: "", phone: "" };
      this.showNotice("候选人创建成功");
      await this.loadCandidates({ quiet: true });
    },

    async uploadCandidateResume() {
      const file = this.$refs.candidateResumeUpload?.files?.[0];
      if (!file) {
        this.showNotice("请先选择简历文件");
        return;
      }
      const form = new FormData();
      form.append("file", file);
      const data = await this.api("/api/admin/candidates/resume/upload", { method: "POST", body: form });
      this.showNotice("简历已入库");
      await this.loadCandidates({ quiet: true });
      if (data?.candidate?.id) {
        await this.handleRoute(`/admin/candidates/${data.candidate.id}`);
      }
    },

    async loadCandidateDetail(candidateId) {
      this.candidateDetail = await this.api(`/api/admin/candidates/${candidateId}`);
      this.candidateEvaluation = "";
    },

    async saveCandidateEvaluation() {
      const payload = { evaluation: this.candidateEvaluation };
      this.candidateDetail = await this.api(`/api/admin/candidates/${this.candidateDetail.candidate.id}/evaluation`, {
        method: "POST",
        body: JSON.stringify(payload),
        headers: { "Content-Type": "application/json" },
      });
      this.candidateEvaluation = "";
      this.showNotice("管理员评价已保存");
    },

    downloadCandidateResume() {
      if (!this.candidateDetail.candidate?.id) return;
      window.location.href = `/api/admin/candidates/${this.candidateDetail.candidate.id}/resume`;
    },

    async reparseCandidateResume() {
      const file = this.$refs.candidateResumeReparse?.files?.[0];
      if (!file) {
        this.showNotice("请先选择新的简历文件");
        return;
      }
      const form = new FormData();
      form.append("file", file);
      this.candidateDetail = await this.api(`/api/admin/candidates/${this.candidateDetail.candidate.id}/resume/reparse`, {
        method: "POST",
        body: form,
      });
      this.showNotice("简历重新解析完成");
    },

    async deleteCandidate() {
      if (!window.confirm("确定删除该候选人吗？")) return;
      await this.api(`/api/admin/candidates/${this.candidateDetail.candidate.id}`, { method: "DELETE" });
      this.showNotice("候选人已删除");
      await this.handleRoute("/admin/candidates");
    },

    async loadAssignments() {
      const query = new URLSearchParams();
      if (this.filters.assignments.q) query.set("q", this.filters.assignments.q);
      this.assignments = await this.api(`/api/admin/assignments?${query.toString()}`);
    },

    async createAssignment() {
      const payload = {
        ...this.assignmentForm,
        candidate_id: Number(this.assignmentForm.candidate_id),
      };
      const result = await this.api("/api/admin/assignments", {
        method: "POST",
        body: JSON.stringify(payload),
        headers: { "Content-Type": "application/json" },
      });
      this.showNotice(`邀约已创建：${result.url}`);
      await this.loadAssignments();
    },

      async loadAttemptDetail(token) {
        this.attemptDetail = await this.api(`/api/admin/attempts/${encodeURIComponent(token)}`);
      },

      destroyLogsChart() {
        if (this.logsChartResizeObserver) {
          this.logsChartResizeObserver.disconnect();
          this.logsChartResizeObserver = null;
        }
        if (this.logsChartWindowResize) {
          window.removeEventListener("resize", this.logsChartWindowResize);
          this.logsChartWindowResize = null;
        }
        if (this.logsChart && typeof this.logsChart.remove === "function") {
          this.logsChart.remove();
        }
        this.logsChart = null;
        this.logsChartContainer = null;
        this.logsChartSeries = {};
      },

      resizeLogsChart() {
        const chart = this.logsChart;
        const container = this.logsChartContainer;
        if (!chart || !container) return;
        const width = Math.max(Math.round(container.clientWidth || 0), 280);
        const height = Math.max(Math.round(container.clientHeight || 0), 320);
        if (typeof chart.resize === "function") {
          chart.resize(width, height);
          return;
        }
        if (typeof chart.applyOptions === "function") {
          chart.applyOptions({ width, height });
        }
      },

      createLogsChartSeries(chart, options) {
        const chartLib = window.LightweightCharts;
        if (typeof chart?.addSeries === "function" && chartLib?.LineSeries) {
          return chart.addSeries(chartLib.LineSeries, options);
        }
        if (typeof chart?.addLineSeries === "function") {
          return chart.addLineSeries(options);
        }
        return null;
      },

      ensureLogsChart() {
        const chartLib = window.LightweightCharts;
        const container = this.$refs.logsTrendChart;
        if (!container || !chartLib?.createChart) {
          return null;
        }
        if (this.logsChart && this.logsChartContainer === container) {
          this.resizeLogsChart();
          return this.logsChart;
        }
        this.destroyLogsChart();
        this.logsChartContainer = container;
        this.logsChart = chartLib.createChart(container, {
          width: Math.max(Math.round(container.clientWidth || 0), 280),
          height: Math.max(Math.round(container.clientHeight || 0), 320),
          layout: {
            background: {
              color: "#020617",
              type: chartLib.ColorType ? chartLib.ColorType.Solid : "solid",
            },
            textColor: "#cbd5e1",
            fontFamily: "\"SF Pro Display\", \"Segoe UI Variable\", \"PingFang SC\", system-ui, sans-serif",
          },
          grid: {
            vertLines: { color: "rgba(148, 163, 184, 0.08)" },
            horzLines: { color: "rgba(148, 163, 184, 0.08)" },
          },
          rightPriceScale: {
            borderColor: "rgba(148, 163, 184, 0.18)",
          },
          timeScale: {
            borderColor: "rgba(148, 163, 184, 0.18)",
            tickMarkFormatter: (time) => {
              if (typeof time !== "string") return "";
              const parts = time.split("-");
              return parts.length === 3 ? `${parts[1]}/${parts[2]}` : time;
            },
          },
          crosshair: {
            vertLine: {
              color: "rgba(59, 130, 246, 0.28)",
              labelBackgroundColor: "#1d4ed8",
            },
            horzLine: {
              color: "rgba(148, 163, 184, 0.24)",
              labelBackgroundColor: "#0f172a",
            },
          },
          localization: {
            locale: "zh-CN",
          },
        });
        if (typeof ResizeObserver === "function") {
          this.logsChartResizeObserver = new ResizeObserver(() => this.resizeLogsChart());
          this.logsChartResizeObserver.observe(container);
        } else {
          this.logsChartWindowResize = () => this.resizeLogsChart();
          window.addEventListener("resize", this.logsChartWindowResize);
        }
        return this.logsChart;
      },

      renderLogsChart() {
        if (!this.hasLogTrendData()) {
          this.destroyLogsChart();
          return;
        }
        const chart = this.ensureLogsChart();
        if (!chart) return;
        for (const item of LOG_SERIES_META) {
          const points = (this.logs?.trend?.series?.[item.key] || []).map((point) => ({
            time: point.day,
            value: Number(point.count || 0),
          }));
          let series = this.logsChartSeries[item.key];
          if (!series) {
            series = this.createLogsChartSeries(chart, {
              color: item.color,
              lineWidth: 2,
              priceLineVisible: false,
              lastValueVisible: false,
              crosshairMarkerRadius: 4,
              crosshairMarkerBorderColor: item.color,
              crosshairMarkerBackgroundColor: "#020617",
              title: item.label,
            });
            if (!series) continue;
            this.logsChartSeries[item.key] = series;
          }
          series.setData(points);
        }
        if (typeof chart.timeScale === "function") {
          chart.timeScale().fitContent();
        }
      },

      async loadLogs() {
        const query = new URLSearchParams({
          days: String(LOG_TREND_WINDOW_DAYS),
          tz_offset_minutes: String(this.browserTzOffsetMinutes()),
        });
        const data = await this.api(`/api/admin/logs?${query.toString()}`);
        if (!data) return;
        this.logs = data;
        await this.$nextTick();
        this.renderLogsChart();
      },

      async loadStatusSummary() {
        this.statusSummary = await this.api("/api/admin/system-status/summary", { quiet: true }) || {};
      },

    async loadStatus() {
      const data = await this.api("/api/admin/system-status");
      this.statusRange = data || { data: {} };
      this.statusConfig = { ...(data?.config || {}) };
      await this.loadStatusSummary();
    },

    async saveStatusConfig() {
      const data = await this.api("/api/admin/system-status/config", {
        method: "PUT",
        body: JSON.stringify(this.statusConfig),
        headers: { "Content-Type": "application/json" },
      });
      this.statusSummary = data.summary || {};
      this.showNotice("系统阈值已保存");
    },

    async api(url, options = {}) {
      const { quiet = false, ...fetchOptions } = options;
      try {
        const response = await fetch(url, {
          credentials: "same-origin",
          ...fetchOptions,
        });
        if (response.status === 401) {
          this.session = { authenticated: false, username: "" };
          if (!quiet) this.error = "登录状态已失效";
          history.replaceState({}, "", "/admin/login");
          this.route = this.resolveRoute("/admin/login");
          return null;
        }
        const text = await response.text();
        const data = text ? JSON.parse(text) : {};
        if (!response.ok) {
          throw new Error(data.detail || data.error || "请求失败");
        }
        return data;
      } catch (error) {
        if (!quiet) this.error = error.message || "请求失败";
        if (!quiet) this.showNotice(error.message || "请求失败");
        throw error;
      }
    },
    }));
  };

  if (window.Alpine) {
    register();
  } else {
    document.addEventListener("alpine:init", register, { once: true });
  }
})();
