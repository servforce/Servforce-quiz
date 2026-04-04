(() => {
  const LOG_TREND_WINDOW_DAYS = 30;
  const ADMIN_COMPACT_BREAKPOINT_QUERY = "(max-width: 1279px)";
  const MCP_CAPABILITY_GROUPS = [
    {
      key: "system",
      label: "系统与运维",
      icon: "monitoring",
      tools: [
        "system_health",
        "system_processes",
        "runtime_config_get",
        "runtime_config_update",
        "system_status_summary",
        "system_status_range",
        "system_status_update_thresholds",
        "job_list",
        "job_get",
        "job_wait",
      ],
    },
    {
      key: "quiz",
      label: "测验与同步",
      icon: "library_books",
      tools: [
        "quiz_repo_get_binding",
        "quiz_repo_bind",
        "quiz_repo_rebind",
        "quiz_repo_sync",
        "quiz_list",
        "quiz_get",
        "quiz_set_public_invite",
      ],
    },
    {
      key: "candidate",
      label: "候选人与档案",
      icon: "group",
      tools: [
        "candidate_list",
        "candidate_ensure",
        "candidate_get",
        "candidate_add_evaluation",
        "candidate_delete",
      ],
    },
    {
      key: "assignment",
      label: "邀约与结果",
      icon: "assignment",
      tools: [
        "assignment_list",
        "assignment_create",
        "assignment_get",
        "assignment_set_handling",
        "assignment_delete",
      ],
    },
  ];
  const MCP_FLOW_STEPS = [
    "1. 绑定或同步测验仓库，确保题库版本已落库。",
    "2. 使用 candidate_ensure 建立候选人，避免重复建档。",
    "3. 调用 assignment_create 生成邀约，再分发链接或二维码。",
    "4. 通过 assignment_get / assignment_list 查看作答进度与结果摘要。",
    "5. 通过 system_status_* 与 runtime_config_* 查看或调整系统状态。",
  ];
  const MCP_SECURITY_RULES = [
    "默认脱敏返回手机号、简历敏感字段与答卷细节。",
    "需要明文时，工具需显式传 include_sensitive=true。",
    "重新绑定仓库、删除候选人、删除邀约等高危操作默认只预检，confirm=true 才执行。",
    "远程 MCP 走 Bearer Token 鉴权，不复用后台浏览器登录态。",
  ];
  const ADMIN_COMPACT_TAB_CONFIG = {
    quizzes: {
      defaultTab: "list",
      tabs: [
        { id: "list", label: "测验列表" },
        { id: "repo", label: "仓库绑定" },
      ],
    },
    "quiz-detail": {
      defaultTab: "content",
      tabs: [
        { id: "content", label: "测验内容" },
        { id: "history", label: "版本历史" },
      ],
    },
    candidates: {
      defaultTab: "list",
      tabs: [
        { id: "list", label: "候选人列表" },
        { id: "create", label: "创建候选人" },
      ],
    },
    "candidate-detail": {
      defaultTab: "profile",
      tabs: [
        { id: "profile", label: "候选人档案" },
        { id: "actions", label: "管理操作" },
      ],
    },
    assignments: {
      defaultTab: "list",
      tabs: [
        { id: "list", label: "邀约列表" },
        { id: "create", label: "创建邀约" },
      ],
    },
    "attempt-detail": {
      defaultTab: "review",
      tabs: [
        { id: "review", label: "答题回放" },
        { id: "evaluation", label: "智能评价" },
      ],
    },
    logs: {
      defaultTab: "list",
      tabs: [
        { id: "list", label: "日志列表" },
        { id: "trend", label: "分类趋势" },
      ],
    },
    status: {
      defaultTab: "summary",
      tabs: [
        { id: "summary", label: "状态摘要" },
        { id: "config", label: "阈值配置" },
      ],
    },
    mcp: {
      defaultTab: "overview",
      tabs: [
        { id: "overview", label: "接入摘要" },
        { id: "capabilities", label: "能力范围" },
      ],
    },
  };
  const LOG_SERIES_META = [
    { key: "candidate", label: "候选人", color: "#2563eb", hint: "创建、编辑与简历入库" },
    { key: "quiz", label: "测验", color: "#14b8a6", hint: "测验查看、更新与同步" },
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
  const RESUME_PHASE_META = {
    idle: { label: "待选择", border: "rgba(148,163,184,0.24)", background: "rgba(248,250,252,0.92)", text: "#475569" },
    confirm: { label: "待确认", border: "rgba(245,158,11,0.28)", background: "rgba(255,251,235,0.96)", text: "#b45309" },
    running: { label: "解析中", border: "rgba(37,99,235,0.24)", background: "rgba(239,246,255,0.96)", text: "#1d4ed8" },
    success: { label: "成功", border: "rgba(5,150,105,0.26)", background: "rgba(236,253,245,0.96)", text: "#047857" },
    error: { label: "失败", border: "rgba(225,29,72,0.24)", background: "rgba(255,241,242,0.96)", text: "#be123c" },
  };
  const RESUME_PARSE_META = {
    done: { label: "解析完成", border: "rgba(5,150,105,0.22)", background: "rgba(236,253,245,0.92)", text: "#047857" },
    empty: { label: "结果为空", border: "rgba(245,158,11,0.24)", background: "rgba(255,251,235,0.96)", text: "#b45309" },
    failed: { label: "解析失败", border: "rgba(225,29,72,0.22)", background: "rgba(255,241,242,0.96)", text: "#be123c" },
  };
  const createCandidateResumeUploadState = () => ({
    phase: "idle",
    busy: false,
    fileName: "",
    message: "选择 PDF、DOCX 或图片简历后，系统会自动解析手机号并创建或更新候选人。",
    error: "",
    created: null,
    candidateName: "",
    candidateId: 0,
  });
  const createCandidateResumeReparseState = (
    message = "选择新简历后会先要求确认，再覆盖当前简历并重新解析。",
  ) => ({
    phase: "idle",
    busy: false,
    fileName: "",
    message,
    error: "",
    pendingFile: null,
  });
  const formatLogTrendCount = (value) => {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) {
      return "0";
    }
    return String(Math.round(numeric));
  };

  const register = () => {
    if (!window.Alpine) return;
    window.Alpine.data("adminApp", () => ({
      booting: true,
      error: "",
      notice: "",
      notices: [],
      noticeSeq: 0,
      session: { authenticated: false, username: "" },
      route: { name: "login", path: "/admin/login", title: "管理员登录", section: "Login", params: {} },
      navItems: [
        { href: "/admin/quizzes", label: "测验", icon: "library_books" },
        { href: "/admin/candidates", label: "候选人", icon: "group" },
        { href: "/admin/assignments", label: "邀约与答题", icon: "assignment" },
        { href: "/admin/logs", label: "系统日志", icon: "receipt_long" },
        { href: "/admin/status", label: "系统状态", icon: "monitoring" },
        { href: "/admin/mcp", label: "MCP", iconKind: "mcp" },
      ],
      loginForm: { username: "admin", password: "password" },
      filters: {
        quizzes: { q: "" },
        candidates: { q: "" },
        assignments: { q: "", start_from: "", end_to: "" },
      },
      syncForm: { repoUrl: "" },
      repoBinding: {},
      rebindForm: { open: false, repoUrl: "", confirmationText: "" },
      candidateForm: { name: "", phone: "" },
      candidateResumeUploadState: createCandidateResumeUploadState(),
      candidateResumeReparseState: createCandidateResumeReparseState(),
      candidateEvaluation: "",
      assignmentForm: {
        quiz_key: "",
        candidate_id: "",
        invite_start_date: new Date().toISOString().slice(0, 10),
        invite_end_date: new Date(Date.now() + 86400000).toISOString().slice(0, 10),
        require_phone_verification: false,
        ignore_timing: false,
      },
      assignmentSelect: {
        quiz: { open: false, query: "" },
        candidate: { open: false, query: "" },
      },
      quizzes: { items: [] },
      quizDetail: { quiz: {}, selected_quiz_version: {}, quiz_version_history: [], stats: {} },
      candidates: { items: [] },
      candidateDetail: { candidate: {}, profile: {}, resume_parsed: {} },
      assignments: { items: [], summary: { unhandled_finished_count: 0 } },
      attemptDetail: { assignment: {}, quiz_paper: {}, archive: {}, review: { answers: [], evaluation: {} } },
      logs: { items: [], counts: {}, trend: { days: [], series: {} } },
      logsChart: null,
      logsChartContainer: null,
      logsChartSeries: {},
      logsChartResizeObserver: null,
      logsChartWindowResize: null,
      isAdminCompactLayout: false,
      adminCompactTabsState: {},
      adminCompactMediaQuery: null,
      adminCompactMediaQueryHandler: null,
      adminCompactScrollHandler: null,
      syncState: {},
      syncPollTimer: null,
      syncPollIntervalMs: 2000,
      assignmentsPollTimer: null,
      assignmentsPollIntervalMs: 3000,
      assignmentStatusSnapshot: {},
      statusSummary: {},
      statusRange: { data: {} },
      statusConfig: { llm_tokens_limit: "", sms_calls_limit: "" },
      systemBootstrap: {},
      mcpCapabilityGroups: MCP_CAPABILITY_GROUPS,
      mcpFlowSteps: MCP_FLOW_STEPS,
      mcpSecurityRules: MCP_SECURITY_RULES,

      async boot() {
        this.initAdminCompactLayout();
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
        const target = root instanceof Element ? root : this.$root;
        if (target && typeof window.mdQuizQueueMathTypeset === "function") {
          window.mdQuizQueueMathTypeset(target);
        }
      },

      selectedAssignmentQuiz() {
        const quizKey = String(this.assignmentForm?.quiz_key || "").trim();
        if (!quizKey) return null;
        return (this.quizzes?.items || []).find((item) => String(item?.quiz_key || "").trim() === quizKey) || null;
      },

      selectedAssignmentCandidate() {
        const candidateId = String(this.assignmentForm?.candidate_id || "").trim();
        if (!candidateId) return null;
        return (this.candidates?.items || []).find((item) => String(item?.id || "").trim() === candidateId) || null;
      },

      filteredAssignmentQuizzes() {
        const query = String(this.assignmentSelect?.quiz?.query || "").trim().toLowerCase();
        const items = Array.isArray(this.quizzes?.items) ? this.quizzes.items : [];
        if (!query) return items;
        return items.filter((item) => {
          const haystacks = [
            String(item?.title || "").trim(),
            String(item?.quiz_key || "").trim(),
            ...(Array.isArray(item?.tags) ? item.tags.map((tag) => String(tag || "").trim()) : []),
          ]
            .filter(Boolean)
            .join(" ")
            .toLowerCase();
          return haystacks.includes(query);
        });
      },

      filteredAssignmentCandidates() {
        const query = String(this.assignmentSelect?.candidate?.query || "").trim().toLowerCase();
        const items = Array.isArray(this.candidates?.items) ? this.candidates.items : [];
        if (!query) return items;
        return items.filter((item) => {
          const haystacks = [
            String(item?.name || "").trim(),
            String(item?.phone || "").trim(),
          ]
            .filter(Boolean)
            .join(" ")
            .toLowerCase();
          return haystacks.includes(query);
        });
      },

      assignmentSelectDisplayValue(kind) {
        const target = kind === "candidate" ? "candidate" : "quiz";
        if (this.assignmentSelect?.[target]?.open) {
          return String(this.assignmentSelect[target].query || "");
        }
        if (target === "quiz") {
          const selected = this.selectedAssignmentQuiz();
          return selected ? String(selected.title || selected.quiz_key || "") : "";
        }
        const selected = this.selectedAssignmentCandidate();
        return selected ? String(selected.name || "") : "";
      },

      openAssignmentSelect(kind) {
        const target = kind === "candidate" ? "candidate" : "quiz";
        this.assignmentSelect.quiz.open = false;
        this.assignmentSelect.candidate.open = false;
        this.assignmentSelect[target].open = true;
        this.assignmentSelect[target].query = "";
      },

      handleAssignmentSelectInput(kind, event) {
        const target = kind === "candidate" ? "candidate" : "quiz";
        const value = String(event?.target?.value || "");
        this.assignmentSelect.quiz.open = false;
        this.assignmentSelect.candidate.open = false;
        this.assignmentSelect[target].open = true;
        this.assignmentSelect[target].query = value;
        if (target === "quiz" && this.assignmentForm.quiz_key) {
          this.assignmentForm.quiz_key = "";
        }
        if (target === "candidate" && this.assignmentForm.candidate_id) {
          this.assignmentForm.candidate_id = "";
        }
      },

      toggleAssignmentSelect(kind) {
        const target = kind === "candidate" ? "candidate" : "quiz";
        const nextOpen = !Boolean(this.assignmentSelect?.[target]?.open);
        this.assignmentSelect.quiz.open = false;
        this.assignmentSelect.candidate.open = false;
        this.assignmentSelect[target].open = nextOpen;
        if (!nextOpen) {
          this.assignmentSelect[target].query = "";
        }
      },

      closeAssignmentSelect(kind) {
        const target = kind === "candidate" ? "candidate" : "quiz";
        if (!this.assignmentSelect?.[target]) return;
        this.assignmentSelect[target].open = false;
        this.assignmentSelect[target].query = "";
      },

      selectAssignmentQuiz(item) {
        this.assignmentForm.quiz_key = String(item?.quiz_key || "").trim();
        this.closeAssignmentSelect("quiz");
      },

      clearAssignmentQuiz() {
        this.assignmentForm.quiz_key = "";
        this.closeAssignmentSelect("quiz");
      },

      selectAssignmentCandidate(item) {
        this.assignmentForm.candidate_id = String(item?.id || "").trim();
        this.closeAssignmentSelect("candidate");
      },

      clearAssignmentCandidate() {
        this.assignmentForm.candidate_id = "";
        this.closeAssignmentSelect("candidate");
      },

      resetAssignmentCandidateSelection() {
        this.assignmentForm.candidate_id = "";
        this.assignmentSelect.candidate.open = false;
        this.assignmentSelect.candidate.query = "";
      },

      candidateResumeParsedData() {
        const details = this.candidateDetail?.resume_parsed?.details;
        const data = details?.data;
        return data && typeof data === "object" ? data : {};
      },

      candidateResumeStatus() {
        const status = String(this.candidateDetail?.profile?.details_status || this.candidateDetail?.resume_parsed?.details?.status || "").trim().toLowerCase();
        return status || "empty";
      },

      candidateResumeStatusMeta() {
        return RESUME_PARSE_META[this.candidateResumeStatus()] || RESUME_PARSE_META.empty;
      },

      candidateResumeStatusBadgeStyle() {
        const meta = this.candidateResumeStatusMeta();
        return {
          borderColor: meta.border,
          backgroundColor: meta.background,
          color: meta.text,
        };
      },

      candidateResumeMethodLabel() {
        const method = this.candidateDetail?.resume_parsed?.method;
        if (!method || typeof method !== "object") return "";
        const labels = {
          llm_attachment: "附件推理",
          llm: "模型抽取",
          fast: "规则识别",
        };
        const entries = Object.entries(method)
          .map(([key, value]) => [String(key || "").trim(), String(value || "").trim()])
          .filter(([key, value]) => key && value);
        if (!entries.length) return "";
        const uniqueValues = [...new Set(entries.map(([, value]) => value))];
        if (uniqueValues.length === 1) {
          return labels[uniqueValues[0]] || uniqueValues[0];
        }
        return entries
          .map(([key, value]) => {
            const keyLabel = key === "identity" ? "身份" : key === "name" ? "姓名" : key === "details" ? "详情" : key;
            return `${keyLabel}:${labels[value] || value}`;
          })
          .join(" / ");
      },

      candidateResumeConfidenceItems() {
        const confidence = this.candidateDetail?.resume_parsed?.confidence;
        if (!confidence || typeof confidence !== "object") return [];
        const items = [
          { label: "姓名置信度", value: Number(confidence.name || 0) },
          { label: "手机置信度", value: Number(confidence.phone || 0) },
        ];
        return items.filter((item) => Number.isFinite(item.value) && item.value > 0);
      },

      candidateResumeSummary() {
        const profileSummary = String(this.candidateDetail?.profile?.evaluation_llm || "").trim();
        if (profileSummary) return profileSummary;
        return String(this.candidateResumeParsedData().summary || "").trim();
      },

      candidateResumeError() {
        return String(this.candidateDetail?.profile?.details_error || this.candidateDetail?.resume_parsed?.details?.error || "").trim();
      },

      candidateResumeBasicFacts() {
        const data = this.candidateResumeParsedData();
        const candidate = this.candidateDetail?.candidate || {};
        const facts = [
          { label: "姓名", value: String(candidate.name || "").trim() },
          { label: "手机号", value: String(candidate.phone || "").trim(), mono: true },
          { label: "性别", value: String(this.candidateDetail?.profile?.gender || data.gender || "").trim() },
          { label: "最高学历", value: String(this.candidateDetail?.profile?.highest_education || data.highest_education || "").trim() },
          { label: "邮箱", value: String(this.candidateDetail?.profile?.email || (Array.isArray(data.emails) ? data.emails[0] || "" : "")).trim() },
          { label: "经验年限", value: this.formatExperienceYears(data.experience_years) },
        ];
        return facts.filter((item) => item.value);
      },

      candidateResumeEducations() {
        const educations = this.candidateDetail?.profile?.educations;
        return Array.isArray(educations) ? educations.filter((item) => item && typeof item === "object") : [];
      },

      candidateResumeTags(key) {
        const raw = this.candidateResumeParsedData()[key];
        return Array.isArray(raw)
          ? raw.map((item) => String(item || "").trim()).filter(Boolean)
          : [];
      },

      candidateResumeEnglishItems() {
        const english = this.candidateDetail?.profile?.english;
        if (!english || typeof english !== "object") return [];
        const items = [];
        const pushItem = (label, value) => {
          const score = Number(value);
          if (!Number.isFinite(score) || score <= 0) return;
          items.push({ label, value: `${score}` });
        };
        pushItem("CET-4", english?.cet4?.score);
        pushItem("CET-6", english?.cet6?.score);
        return items;
      },

      candidateResumeWorkExperiences() {
        const rows = this.candidateResumeParsedData().work_experiences;
        if (Array.isArray(rows) && rows.length) {
          return rows
            .filter((item) => item && typeof item === "object")
            .map((item) => ({
              title: [String(item.company || "").trim(), String(item.title || "").trim()].filter(Boolean).join(" · "),
              period: String(item.period || "").trim(),
              bullets: Array.isArray(item.description)
                ? item.description.map((bullet) => String(bullet || "").trim()).filter(Boolean)
                : [],
            }))
            .filter((item) => item.title || item.period || item.bullets.length);
        }
        return this.candidateResumeExperienceBlocks("work");
      },

      candidateResumeProjects() {
        const rows = this.candidateDetail?.profile?.projects;
        if (Array.isArray(rows) && rows.length) {
          return rows
            .filter((item) => item && typeof item === "object")
            .map((item) => ({
              title: [String(item.name || "").trim(), String(item.role || "").trim()].filter(Boolean).join(" · "),
              period: String(item.period || "").trim(),
              bullets: Array.isArray(item.description)
                ? item.description.map((bullet) => String(bullet || "").trim()).filter(Boolean)
                : [],
            }))
            .filter((item) => item.title || item.period || item.bullets.length);
        }
        return this.candidateResumeExperienceBlocks("project");
      },

      candidateResumeExperienceBlocks(kind) {
        const blocks = this.candidateDetail?.profile?.experience_blocks;
        if (!Array.isArray(blocks)) return [];
        const expectedKind = String(kind || "").trim().toLowerCase();
        return blocks
          .filter((item) => item && typeof item === "object")
          .filter((item) => {
            const currentKind = String(item.kind || "").trim().toLowerCase();
            return expectedKind ? currentKind === expectedKind : true;
          })
          .map((item) => ({
            title: String(item.title || "").trim(),
            period: String(item.period || "").trim(),
            bullets: String(item.body || "")
              .split(/\n+/)
              .map((line) => line.trim())
              .filter(Boolean),
          }))
          .filter((item) => item.title || item.period || item.bullets.length);
      },

      candidateResumeCollectionGroups() {
        const groups = [
          { key: "awards", label: "奖项" },
          { key: "certifications", label: "证书" },
          { key: "publications", label: "发表" },
        ];
        return groups
          .map((group) => ({
            ...group,
            items: this.candidateResumeTags(group.key),
          }))
          .filter((group) => group.items.length);
      },

      candidateResumeAdminSummaries() {
        const items = [];
        const adminItems = Array.isArray(this.candidateDetail?.profile?.admin_evaluations)
          ? this.candidateDetail.profile.admin_evaluations
          : [];
        adminItems.slice(0, 3).forEach((item) => {
          const text = String(item?.text || "").trim();
          if (!text) return;
          items.push({
            label: "管理员评价",
            text,
            meta: String(item?.at_display || item?.at || "").trim(),
          });
        });
        return items;
      },

      candidateResumeHasStructuredContent() {
        return Boolean(
          this.candidateResumeSummary()
          || this.candidateResumeBasicFacts().length
          || this.candidateResumeEducations().length
          || this.candidateResumeTags("skills").length
          || this.candidateResumeEnglishItems().length
          || this.candidateResumeWorkExperiences().length
          || this.candidateResumeProjects().length
          || this.candidateResumeCollectionGroups().length
          || this.candidateResumeAdminSummaries().length,
        );
      },

      formatExperienceYears(value) {
        const number = Number(value);
        if (!Number.isFinite(number) || number <= 0) return "";
        if (Number.isInteger(number)) {
          return `${number} 年`;
        }
        return `${number.toFixed(1)} 年`;
      },

      quizQuestions() {
        const questions = this.quizDetail?.selected_quiz_version?.spec?.questions;
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

      attemptReviewAnswers() {
        const answers = this.attemptDetail?.review?.answers;
        return Array.isArray(answers) ? answers : [];
      },

      attemptReviewEvaluation() {
        const evaluation = this.attemptDetail?.review?.evaluation;
        return evaluation && typeof evaluation === "object" ? evaluation : {};
      },

      attemptReviewQuestionKind(question) {
        const explicit = String(question?.review_kind || "").trim().toLowerCase();
        if (explicit) {
          return explicit;
        }
        const type = String(question?.type || "").trim().toLowerCase();
        if (type === "short") {
          return "short";
        }
        if (type === "single" || type === "multiple") {
          const options = Array.isArray(question?.options) ? question.options : [];
          const hasTraits = options.some((option) => this.optionTraits(option).length > 0);
          return hasTraits ? "traits" : "objective";
        }
        return "unknown";
      },

      attemptReviewIsShortQuestion(question) {
        return this.attemptReviewQuestionKind(question) === "short";
      },

      attemptReviewIsTraitQuestion(question) {
        return this.attemptReviewQuestionKind(question) === "traits";
      },

      attemptReviewIsObjectiveQuestion(question) {
        return this.attemptReviewQuestionKind(question) === "objective";
      },

      attemptReviewHasOptions(question) {
        return Array.isArray(question?.options) && question.options.length > 0;
      },

      attemptReviewSelectedOptions(question) {
        const options = question?.selected_options;
        return Array.isArray(options)
          ? options.map((item) => String(item || "").trim()).filter(Boolean)
          : [];
      },

      attemptReviewCorrectOptions(question) {
        const options = question?.correct_options;
        return Array.isArray(options)
          ? options.map((item) => String(item || "").trim()).filter(Boolean)
          : [];
      },

      attemptReviewHasAnswer(question) {
        if (typeof question?.has_answer === "boolean") {
          return question.has_answer;
        }
        if (this.attemptReviewIsShortQuestion(question)) {
          return Boolean(String(question?.answer || "").trim());
        }
        return this.attemptReviewSelectedOptions(question).length > 0;
      },

      attemptReviewQuestionStatusLabel(question) {
        const hasAnswer = this.attemptReviewHasAnswer(question);
        if (this.attemptReviewIsTraitQuestion(question)) {
          return hasAnswer ? "已作答" : "未作答";
        }
        if (this.attemptReviewIsShortQuestion(question)) {
          if (!hasAnswer) {
            return "未作答";
          }
          return question?.has_score ? "已评分" : "待评分";
        }
        if (!hasAnswer) {
          return "未作答";
        }
        if (question?.is_correct) {
          return "回答正确";
        }
        if (question?.is_partial) {
          return "部分得分";
        }
        return "回答错误";
      },

      attemptReviewQuestionStatusClass(question) {
        const label = this.attemptReviewQuestionStatusLabel(question);
        const classes = [
          "inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-semibold",
        ];
        if (label === "回答正确") {
          classes.push("border-emerald-200 bg-emerald-50 text-emerald-700");
        } else if (label === "部分得分") {
          classes.push("border-amber-200 bg-amber-50 text-amber-700");
        } else if (label === "回答错误") {
          classes.push("border-rose-200 bg-rose-50 text-rose-700");
        } else if (label === "已评分") {
          classes.push("border-blue-200 bg-blue-50 text-blue-700");
        } else if (label === "待评分") {
          classes.push("border-amber-200 bg-amber-50 text-amber-700");
        } else if (label === "已作答") {
          classes.push("border-sky-200 bg-sky-50 text-sky-700");
        } else {
          classes.push("border-slate-200 bg-slate-50 text-slate-600");
        }
        return classes.join(" ");
      },

      attemptReviewOptionIsSelected(question, option) {
        const key = String(option?.key || "").trim();
        return Boolean(key) && this.attemptReviewSelectedOptions(question).includes(key);
      },

      attemptReviewOptionIsCorrect(question, option) {
        const key = String(option?.key || "").trim();
        return Boolean(key) && this.attemptReviewCorrectOptions(question).includes(key);
      },

      attemptReviewOptionRowClass(question, option) {
        const classes = ["flex items-start gap-2.5 px-3 py-3"];
        const selected = this.attemptReviewOptionIsSelected(question, option);
        const correct = this.attemptReviewOptionIsCorrect(question, option);
        if (this.attemptReviewIsTraitQuestion(question)) {
          classes.push(selected ? "bg-sky-50/85" : "bg-slate-50/80");
        } else if (selected && correct) {
          classes.push("bg-emerald-50/85");
        } else if (selected) {
          classes.push("bg-rose-50/80");
        } else if (correct) {
          classes.push("bg-emerald-50/60");
        } else {
          classes.push("bg-slate-50/80");
        }
        return classes.join(" ");
      },

      attemptReviewOptionSelectionBadgeClass(question, option) {
        const classes = ["shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-semibold"];
        if (this.attemptReviewIsTraitQuestion(question)) {
          classes.push("border-sky-200 bg-white text-sky-700");
        } else if (this.attemptReviewOptionIsCorrect(question, option)) {
          classes.push("border-emerald-200 bg-white text-emerald-700");
        } else {
          classes.push("border-rose-200 bg-white text-rose-700");
        }
        return classes.join(" ");
      },

      attemptReviewShortAnswerText(question) {
        const answer = question?.answer;
        if (typeof answer === "string") {
          return answer.trim() || "未作答";
        }
        if (Array.isArray(answer)) {
          return answer.length ? answer.join("、") : "未作答";
        }
        if (answer === null || answer === undefined || answer === "") {
          return "未作答";
        }
        try {
          return JSON.stringify(answer, null, 2);
        } catch (_error) {
          return String(answer);
        }
      },

      attemptEvaluationResultModeLabel() {
        const evaluation = this.attemptReviewEvaluation();
        if (String(evaluation?.result_mode_label || "").trim()) {
          return String(evaluation.result_mode_label).trim();
        }
        const mapping = {
          scored: "计分题",
          traits: "量表题",
          mixed: "计分 + 量表",
        };
        const key = String(evaluation?.result_mode || "").trim().toLowerCase();
        return mapping[key] || "未定义";
      },

      attemptEvaluationPrimaryDimensions() {
        const evaluation = this.attemptReviewEvaluation();
        const items = evaluation?.primary_dimensions || evaluation?.traits?.primary_dimensions;
        return Array.isArray(items) ? items.map((item) => String(item || "").trim()).filter(Boolean) : [];
      },

      attemptEvaluationTraitPairs() {
        const evaluation = this.attemptReviewEvaluation();
        const items = evaluation?.paired_dimensions || evaluation?.traits?.paired_dimensions;
        return Array.isArray(items) ? items : [];
      },

      attemptEvaluationDimensionList() {
        const evaluation = this.attemptReviewEvaluation();
        const items = evaluation?.dimension_list || evaluation?.traits?.dimension_list;
        return Array.isArray(items) ? items : [];
      },

      attemptEvaluationShowScore() {
        const evaluation = this.attemptReviewEvaluation();
        if (typeof evaluation?.has_score === "boolean") {
          return evaluation.has_score;
        }
        return Boolean(String(evaluation?.score_display || "").trim()) && String(evaluation?.result_mode || "").trim() !== "traits";
      },

      attemptEvaluationHasContent() {
        const evaluation = this.attemptReviewEvaluation();
        return Boolean(
          String(evaluation?.final_analysis || "").trim()
          || String(evaluation?.candidate_remark || "").trim()
          || String(evaluation?.score_display || "").trim()
          || String(evaluation?.result_mode || "").trim()
          || this.attemptEvaluationPrimaryDimensions().length
          || this.attemptEvaluationTraitPairs().length
          || this.attemptEvaluationDimensionList().length
        );
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

      formatDate(value) {
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
        }).format(date);
      },

      unhandledAssignmentCount() {
        return Math.max(0, Number(this.assignments?.summary?.unhandled_finished_count || 0));
      },

      assignmentSurfaceStateClass(item) {
        switch (this.assignmentStatusValue(item)) {
          case "in_quiz":
            return "assignment-surface--in-quiz";
          case "grading":
            return "assignment-surface--grading";
          case "finished":
            return "assignment-surface--finished";
          case "expired":
            return "assignment-surface--expired";
          case "invited":
          case "verified":
            return "assignment-surface--waiting";
          default:
            return "";
        }
      },

      assignmentCardClass(item) {
        const classes = [];
        const stateClass = this.assignmentSurfaceStateClass(item);
        if (stateClass) {
          classes.push(stateClass);
        }
        if (item?.needs_attention) {
          classes.push("assignment-card--attention");
        }
        return classes.join(" ");
      },

      assignmentDetailSectionClass(item) {
        const classes = [];
        const stateClass = this.assignmentSurfaceStateClass(item);
        if (stateClass) {
          classes.push(stateClass);
        }
        if (item?.needs_attention) {
          classes.push("assignment-detail-panel--attention");
        }
        return classes.join(" ");
      },

      assignmentSourceBadgeClass() {
        return "assignment-badge assignment-badge--source";
      },

      assignmentStatusBadgeClass(item) {
        const classes = ["assignment-badge"];
        switch (this.assignmentStatusValue(item)) {
          case "in_quiz":
            classes.push("assignment-badge--status-active");
            break;
          case "grading":
            classes.push("assignment-badge--status-grading");
            break;
          case "finished":
            classes.push("assignment-badge--status-finished");
            break;
          case "expired":
            classes.push("assignment-badge--status-expired");
            break;
          case "invited":
          case "verified":
            classes.push("assignment-badge--status-waiting");
            break;
          default:
            classes.push("assignment-badge--status-neutral");
            break;
        }
        return classes.join(" ");
      },

      assignmentHandlingBadgeClass(item) {
        return item?.needs_attention
          ? "assignment-badge assignment-badge--attention"
          : "assignment-badge assignment-badge--handled";
      },

      assignmentIgnoresTiming(item) {
        return Boolean(item?.ignore_timing);
      },

      canToggleAssignmentHandling(item) {
        return String(item?.status || "").trim() === "finished";
      },

      assignmentHandlingLabel(item) {
        if (!this.canToggleAssignmentHandling(item)) return "";
        return item?.needs_attention ? "未处理" : "已处理";
      },

      assignmentHandlingActionLabel(item) {
        return item?.needs_attention ? "标记已处理" : "取消已处理";
      },

      assignmentActionButtonClass(kind, item) {
        const classes = ["assignment-action"];
        if (kind === "detail") {
          classes.push("assignment-action--primary");
        } else if (kind === "danger") {
          classes.push("assignment-action--danger");
        } else if (kind === "handling" && item?.needs_attention) {
          classes.push("assignment-action--warning");
        } else {
          classes.push("assignment-action--secondary");
        }
        return classes.join(" ");
      },

      assignmentHandledMeta(item) {
        const handledAt = String(item?.handled_at || "").trim();
        if (!handledAt) return "";
        const parts = [];
        const handledBy = String(item?.handled_by || "").trim();
        if (handledBy) {
          parts.push(handledBy);
        }
        const displayTime = this.formatDateTime(handledAt);
        if (displayTime) {
          parts.push(displayTime);
        }
        return parts.join(" · ");
      },

      formatAnswerTime(seconds) {
        const value = Number(seconds || 0);
        if (!Number.isFinite(value) || value <= 0) {
          return "";
        }
        const totalSeconds = Math.max(0, Math.round(value));
        const hours = Math.floor(totalSeconds / 3600);
        const minutes = Math.floor((totalSeconds % 3600) / 60);
        const remainderSeconds = totalSeconds % 60;
        const parts = [];
        if (hours) {
          parts.push(`${hours}小时`);
        }
        if (minutes) {
          parts.push(`${minutes}分`);
        }
        if (remainderSeconds || !parts.length) {
          parts.push(`${remainderSeconds}秒`);
        }
        return parts.join("");
      },

      resumePhaseMeta(phase) {
        const key = String(phase || "").trim().toLowerCase();
        return RESUME_PHASE_META[key] || RESUME_PHASE_META.idle;
      },

      resumeStateLabel(phase) {
        return this.resumePhaseMeta(phase).label;
      },

      resumeStateBadgeStyle(phase) {
        const meta = this.resumePhaseMeta(phase);
        return {
          borderColor: meta.border,
          backgroundColor: meta.background,
          color: meta.text,
        };
      },

      resumeStatePanelStyle(phase) {
        const meta = this.resumePhaseMeta(phase);
        return {
          borderColor: meta.border,
          backgroundColor: meta.background,
        };
      },

      candidateResumeReparseDefaultMessage() {
        return this.candidateDetail?.candidate?.resume_filename
          ? "选择新简历后会先要求确认，再覆盖当前简历并重新解析。"
          : "当前候选人还没有简历，选择文件后会先要求确认并开始解析。";
      },

      resetCandidateResumeUploadState() {
        this.candidateResumeUploadState = createCandidateResumeUploadState();
      },

      resetCandidateResumeReparseState() {
        this.candidateResumeReparseState = createCandidateResumeReparseState(this.candidateResumeReparseDefaultMessage());
      },

      openFilePicker(refName) {
        const input = this.$refs?.[refName];
        if (!input) return;
        input.value = "";
        input.click();
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
        for (const question of this.quizQuestions()) {
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
        const configured = this.quizDetail?.selected_quiz_version?.trait?.dimensions || this.quizDetail?.quiz?.trait?.dimensions;
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

      statusConfigAlerts() {
        return Array.isArray(this.statusSummary?.config_alerts) ? this.statusSummary.config_alerts : [];
      },

      statusModuleConfigured(key) {
        const module = this.statusSummary?.[key];
        if (!module || typeof module.configured !== "boolean") {
          return true;
        }
        return Boolean(module.configured);
      },

      statusModuleMissingFields(key) {
        return Array.isArray(this.statusSummary?.[key]?.missing_fields) ? this.statusSummary[key].missing_fields : [];
      },

      statusModuleMissingText(key) {
        const fields = this.statusModuleMissingFields(key);
        return fields.length ? `缺少 ${fields.join("、")}` : "";
      },

      statusDailyRows() {
        const items = Array.isArray(this.statusRange?.data?.items) ? this.statusRange.data.items : [];
        return [...items].reverse();
      },

      statusDailyTotals() {
        const totals = {
          quizzes_new: 0,
          invites_new: 0,
          candidates_new: 0,
          llm_tokens: 0,
          sms_calls: 0,
        };
        for (const item of this.statusDailyRows()) {
          totals.quizzes_new += Number(item?.quizzes_new || 0);
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
        const value = String(text || "").trim();
        if (!value) return false;
        if (navigator.clipboard?.writeText) {
          await navigator.clipboard.writeText(value);
          this.showNotice(successMessage || "内容已复制");
          return true;
        }
        const input = document.createElement("textarea");
        input.value = value;
        input.setAttribute("readonly", "readonly");
        input.style.position = "fixed";
        input.style.opacity = "0";
        document.body.appendChild(input);
        input.select();
        input.setSelectionRange(0, input.value.length);
        const ok = document.execCommand("copy");
        document.body.removeChild(input);
        if (!ok) {
          throw new Error("复制失败，请手动复制");
        }
        this.showNotice(successMessage || "内容已复制");
        return true;
      },

      async copyAssignmentUrl(item) {
        await this.copyText(item?.url, "邀约链接已复制");
      },

      async copyAssignmentQr(item) {
        const qrPath = String(item?.qr_url || "").trim();
        if (!qrPath) return;
        const qrUrl = new URL(qrPath, window.location.origin).toString();
        try {
          if (!navigator.clipboard?.write || typeof window.ClipboardItem === "undefined") {
            throw new Error("image clipboard unsupported");
          }
          const response = await fetch(qrUrl, { credentials: "same-origin" });
          if (!response.ok) {
            throw new Error("qr fetch failed");
          }
          const blob = await response.blob();
          await navigator.clipboard.write([
            new window.ClipboardItem({
              [blob.type || "image/png"]: blob,
            }),
          ]);
          this.showNotice("二维码图片已复制");
        } catch (_error) {
          await this.copyText(qrUrl, "当前环境不支持复制图片，已复制二维码地址");
        }
      },

      canDeleteAssignment(item) {
        return Boolean(String(item?.token || "").trim());
      },

      async deleteAssignment(item) {
        if (!this.canDeleteAssignment(item)) return;
        const token = String(item?.token || "").trim();
        if (!token) return;
        const name = String(item?.candidate_name || "").trim() || "该邀约";
        if (!window.confirm(`确定删除 ${name} 的邀约吗？这会同时删除该次答题归档，不影响候选人和简历。`)) return;
        await this.api(`/api/admin/assignments/${encodeURIComponent(token)}`, { method: "DELETE" });
        this.showNotice("邀约已删除");
        const currentToken = String(this.attemptDetail?.quiz_paper?.token || this.attemptDetail?.assignment?.token || "").trim();
        if (currentToken === token) {
          await this.handleRoute("/admin/assignments");
          return;
        }
        await this.loadAssignments();
      },

      updateAssignmentSummaryCount(previousItem, nextItem) {
        const previousNeedsAttention = Boolean(previousItem?.needs_attention);
        const nextNeedsAttention = Boolean(nextItem?.needs_attention);
        if (previousNeedsAttention === nextNeedsAttention) return;
        if (!this.assignments.summary || typeof this.assignments.summary !== "object") {
          this.assignments.summary = { unhandled_finished_count: 0 };
        }
        const current = Number(this.assignments.summary.unhandled_finished_count || 0);
        this.assignments.summary.unhandled_finished_count = Math.max(0, current + (nextNeedsAttention ? 1 : -1));
      },

      applyAssignmentItemUpdate(updatedItem) {
        const token = String(updatedItem?.token || "").trim();
        if (!token) return;
        const items = Array.isArray(this.assignments?.items) ? this.assignments.items : [];
        const nextItems = items.map((item) => {
          if (String(item?.token || "").trim() !== token) {
            return item;
          }
          this.updateAssignmentSummaryCount(item, updatedItem);
          return { ...item, ...updatedItem };
        });
        this.assignments = {
          ...(this.assignments || {}),
          items: nextItems,
          summary: this.assignments?.summary || { unhandled_finished_count: 0 },
        };
        if (String(this.attemptDetail?.quiz_paper?.token || "").trim() === token) {
          this.attemptDetail = {
            ...(this.attemptDetail || {}),
            quiz_paper: { ...(this.attemptDetail?.quiz_paper || {}), ...updatedItem },
          };
        }
      },

      async toggleAssignmentHandling(item) {
        if (!this.canToggleAssignmentHandling(item)) return;
        const token = String(item?.token || "").trim();
        if (!token) return;
        const handled = Boolean(item?.needs_attention);
        const result = await this.api(`/api/admin/assignments/${encodeURIComponent(token)}/handling`, {
          method: "POST",
          body: JSON.stringify({ handled }),
          headers: { "Content-Type": "application/json" },
        });
        const updatedItem = result?.item;
        if (!updatedItem || typeof updatedItem !== "object") return;
        this.applyAssignmentItemUpdate(updatedItem);
        this.showNotice(handled ? "已标记为已处理" : "已取消处理标记");
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

      assignmentStatusValue(item) {
        return String(item?.status || "").trim().toLowerCase();
      },

      assignmentStatusSnapshotMap(items) {
        const out = {};
        for (const item of Array.isArray(items) ? items : []) {
          const token = String(item?.token || "").trim();
          if (!token) continue;
          out[token] = this.assignmentStatusValue(item);
        }
        return out;
      },

      notifyAssignmentTransitions(nextItems, previousSnapshot) {
        const startedGradingItems = [];
        const finishedItems = [];
        for (const item of Array.isArray(nextItems) ? nextItems : []) {
          const token = String(item?.token || "").trim();
          if (!token) continue;
          const previousStatus = String(previousSnapshot?.[token] || "").trim().toLowerCase();
          const nextStatus = this.assignmentStatusValue(item);
          if (previousStatus && previousStatus !== "grading" && previousStatus !== "finished" && nextStatus === "grading") {
            startedGradingItems.push(item);
            continue;
          }
          if (previousStatus === "grading" && nextStatus === "finished") {
            finishedItems.push(item);
          }
        }
        if (startedGradingItems.length === 1) {
          const candidateName = String(startedGradingItems[0]?.candidate_name || "").trim() || "该答题";
          this.showNotice(`${candidateName} 已结束答题，正在判卷`);
        } else if (startedGradingItems.length > 1) {
          this.showNotice(`${startedGradingItems.length} 条答题记录已结束，正在判卷`);
        }
        if (finishedItems.length === 1) {
          const candidateName = String(finishedItems[0]?.candidate_name || "").trim() || "该答题";
          this.showNotice(`${candidateName} 的判卷已结束`);
          return;
        }
        if (finishedItems.length > 1) {
          this.showNotice(`${finishedItems.length} 条答题记录已完成判卷`);
        }
      },

      stopAssignmentsPolling() {
        if (!this.assignmentsPollTimer) return;
        window.clearTimeout(this.assignmentsPollTimer);
        this.assignmentsPollTimer = null;
      },

      scheduleAssignmentsPolling() {
        if (this.assignmentsPollTimer || !this.session.authenticated) return;
        if (!["assignments", "attempt-detail"].includes(this.route.name)) return;
        this.assignmentsPollTimer = window.setTimeout(async () => {
          this.assignmentsPollTimer = null;
          if (!this.session.authenticated) return;
          if (this.route.name === "assignments") {
            await this.loadAssignments({ quiet: true, source: "assignments-poll" });
            return;
          }
          if (this.route.name === "attempt-detail") {
            await this.loadAttemptDetail(this.route.params.token, { quiet: true, source: "assignments-poll" });
          }
        }, this.assignmentsPollIntervalMs);
      },

      scheduleSyncPolling() {
        if (this.syncPollTimer || !this.isSyncBusy() || this.route.name !== "quizzes") return;
        this.syncPollTimer = window.setTimeout(async () => {
          this.syncPollTimer = null;
          if (this.route.name !== "quizzes" || !this.session.authenticated) return;
          const previousSyncStatus = this.syncStatus();
          const previousSyncJobId = String(this.syncState?.last_job_id || "").trim();
          await this.loadQuizzes({
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
          return;
        }
        const previousRouteName = String(this.route?.name || "").trim();
        const nextRoute = this.resolveRoute(pathname);
        if (previousRouteName === "logs" && nextRoute.name !== "logs") {
          this.destroyLogsChart();
        }
        if (previousRouteName && previousRouteName !== nextRoute.name) {
          this.resetAdminCompactTab(previousRouteName);
        }
        this.route = nextRoute;
        this.ensureAdminCompactTab(this.route.name);
        await this.$nextTick();
        if (this.route.name !== "quizzes") {
          this.stopSyncPolling();
        }
        if (!["assignments", "attempt-detail"].includes(this.route.name)) {
          this.stopAssignmentsPolling();
        }
        if (!replace) {
          history.pushState({}, "", this.route.path);
        }
        this.error = "";
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
          await this.handleRoute("/admin/quizzes");
        } catch (error) {
          this.error = error.message || "登录失败";
        }
      },

      async logout() {
        this.destroyLogsChart();
        this.stopSyncPolling();
        this.stopAssignmentsPolling();
        this.adminCompactTabsState = {};
        await this.api("/api/admin/session/logout", { method: "POST", quiet: true });
        this.session = { authenticated: false, username: "" };
        this.repoBinding = {};
        this.resetRebindForm();
        history.replaceState({}, "", "/admin/login");
        this.route = this.resolveRoute("/admin/login");
      },

      async loadQuizzes({ quiet = false, source = "manual", previousSyncStatus = "", previousSyncJobId = "" } = {}) {
        const query = new URLSearchParams();
        if (this.filters.quizzes.q) query.set("q", this.filters.quizzes.q);
        const data = await this.api(`/api/admin/quizzes?${query.toString()}`, { quiet });
        if (!data) return;
        this.quizzes = data;
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
        if (this.route.name === "quizzes" && this.isSyncBusy()) {
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
            this.showNotice(currentSyncStatus === "done" ? "测验同步完成，列表已刷新" : "测验同步失败");
          }
        }
      },

      async bindRepo() {
        if (this.isSyncBusy() || this.hasRepoBinding()) return;
        const result = await this.api("/api/admin/quizzes/binding", {
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
        await this.loadQuizzes({ quiet: true });
      },

      async syncQuizzes() {
        if (this.isSyncBusy() || !this.hasRepoBinding()) return;
        const result = await this.api("/api/admin/quizzes/sync", {
          method: "POST",
          body: JSON.stringify({}),
          headers: { "Content-Type": "application/json" },
        });
        this.showNotice(result.created ? "测验同步任务已创建" : "已复用正在运行的同步任务");
        await this.loadQuizzes({ quiet: true });
      },

      async confirmRebind() {
        if (this.isSyncBusy() || !this.hasRepoBinding()) return;
        const result = await this.api("/api/admin/quizzes/binding/rebind", {
          method: "POST",
          body: JSON.stringify({
            repo_url: this.rebindForm.repoUrl || "",
            confirmation_text: this.rebindForm.confirmationText || "",
          }),
          headers: { "Content-Type": "application/json" },
        });
        this.quizzes = { items: [], page: 1, per_page: 20, total: 0, total_pages: 1 };
        this.quizDetail = { quiz: {}, selected_quiz_version: {}, quiz_version_history: [], stats: {} };
        this.repoBinding = result.binding || {};
        this.resetRebindForm();
        if (result.sync?.error) {
          this.showNotice("仓库已重新绑定，现有测验数据已清空，但自动同步投递失败");
        } else {
          this.showNotice("仓库已重新绑定，现有测验数据已清空并开始同步");
        }
        await this.loadQuizzes({ quiet: true });
      },

      async loadQuizDetail(quizKey) {
        this.quizDetail = await this.api(`/api/admin/quizzes/${encodeURIComponent(quizKey)}`);
        await this.$nextTick();
        this.queueMathTypeset();
      },

      async loadQuizVersion(versionId) {
        this.quizDetail = await this.api(`/api/admin/quiz-versions/${versionId}`);
        if (this.route.name === "quiz-detail" && this.isAdminCompactLayout) {
          await this.setAdminCompactTab("quiz-detail", "content", { scroll: true });
        }
        await this.$nextTick();
        this.queueMathTypeset();
      },

      async togglePublicInvite() {
        const enabled = !Boolean(this.quizDetail.quiz?.public_invite_enabled);
        const result = await this.api(`/api/admin/quizzes/${encodeURIComponent(this.quizDetail.quiz.quiz_key)}/public-invite`, {
          method: "POST",
          body: JSON.stringify({ enabled }),
          headers: { "Content-Type": "application/json" },
        });
        this.quizDetail.quiz.public_invite_enabled = result.enabled;
        this.quizDetail.quiz.public_invite_token = result.token || "";
        this.quizDetail.quiz.public_invite_url = result.public_url;
        this.quizDetail.quiz.public_invite_qr_url = result.qr_url || "";
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

      openCandidateResumeUploadPicker() {
        if (this.candidateResumeUploadState.busy) return;
        this.openFilePicker("candidateResumeUpload");
      },

      async handleCandidateResumeUploadSelected(event) {
        const file = event?.target?.files?.[0];
        if (!file || this.candidateResumeUploadState.busy) return;
        this.candidateResumeUploadState = {
          ...createCandidateResumeUploadState(),
          phase: "running",
          busy: true,
          fileName: file.name,
          message: "正在上传并解析手机号、姓名和简历详情。",
        };
        const form = new FormData();
        form.append("file", file);
        try {
          const data = await this.api("/api/admin/candidates/resume/upload", {
            method: "POST",
            body: form,
            quiet: true,
          });
          if (!data) {
            this.resetCandidateResumeUploadState();
            return;
          }
          const created = Boolean(data?.created);
          const candidateName = String(data?.candidate?.name || "").trim();
          this.candidateResumeUploadState = {
            ...createCandidateResumeUploadState(),
            phase: "success",
            fileName: String(data?.candidate?.resume_filename || file.name),
            message: created ? "已创建候选人并写入简历。" : "已更新候选人并更新简历。",
            created,
            candidateName,
            candidateId: Number(data?.candidate?.id || 0),
          };
          this.showNotice(created ? "简历已入库并创建候选人" : "简历已入库并更新候选人");
          await this.loadCandidates({ quiet: true });
          if (data?.candidate?.id) {
            await this.handleRoute(`/admin/candidates/${data.candidate.id}`);
          }
        } catch (error) {
          this.candidateResumeUploadState = {
            ...createCandidateResumeUploadState(),
            phase: "error",
            fileName: file.name,
            message: "本次简历入库失败，请重新选择文件。",
            error: error.message || "简历入库失败",
          };
        }
      },

      async loadCandidateDetail(candidateId) {
        this.candidateDetail = await this.api(`/api/admin/candidates/${candidateId}`);
        this.candidateEvaluation = "";
        this.resetCandidateResumeReparseState();
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

      openCandidateResumeReparsePicker() {
        if (this.candidateResumeReparseState.busy) return;
        this.openFilePicker("candidateResumeReparse");
      },

      handleCandidateResumeReparseSelected(event) {
        const file = event?.target?.files?.[0];
        if (!file || this.candidateResumeReparseState.busy) return;
        this.candidateResumeReparseState = {
          ...createCandidateResumeReparseState(this.candidateResumeReparseDefaultMessage()),
          phase: "confirm",
          fileName: file.name,
          message: "确认后会覆盖当前简历并重算解析结果。",
          pendingFile: file,
        };
      },

      cancelCandidateResumeReparse() {
        if (this.candidateResumeReparseState.busy) return;
        this.resetCandidateResumeReparseState();
      },

      async confirmCandidateResumeReparse() {
        const file = this.candidateResumeReparseState.pendingFile;
        if (!file || this.candidateResumeReparseState.busy || !this.candidateDetail.candidate?.id) return;
        this.candidateResumeReparseState = {
          ...this.candidateResumeReparseState,
          phase: "running",
          busy: true,
          error: "",
          message: "正在上传新简历并重新解析。",
        };
        const form = new FormData();
        form.append("file", file);
        try {
          const data = await this.api(
            `/api/admin/candidates/${this.candidateDetail.candidate.id}/resume/reparse`,
            {
              method: "POST",
              body: form,
              quiet: true,
            },
          );
          if (!data) {
            this.resetCandidateResumeReparseState();
            return;
          }
          this.candidateDetail = data;
          this.candidateResumeReparseState = {
            ...createCandidateResumeReparseState(this.candidateResumeReparseDefaultMessage()),
            phase: "success",
            fileName: String(data?.candidate?.resume_filename || file.name),
            message: "新简历已覆盖，解析结果已刷新。",
          };
          this.showNotice("简历重新解析完成");
        } catch (error) {
          this.candidateResumeReparseState = {
            ...createCandidateResumeReparseState(this.candidateResumeReparseDefaultMessage()),
            phase: "error",
            fileName: file.name,
            message: "重新解析失败，请重新选择文件。",
            error: error.message || "简历重新解析失败",
          };
        }
      },

      async deleteCandidate() {
        if (!window.confirm("确定删除该候选人吗？")) return;
        await this.api(`/api/admin/candidates/${this.candidateDetail.candidate.id}`, { method: "DELETE" });
        this.showNotice("候选人已删除");
        await this.handleRoute("/admin/candidates");
      },

      async loadAssignments({ quiet = false, source = "manual" } = {}) {
        const query = new URLSearchParams();
        if (this.filters.assignments.q) query.set("q", this.filters.assignments.q);
        if (this.filters.assignments.start_from) query.set("start_from", this.filters.assignments.start_from);
        if (this.filters.assignments.end_to) query.set("end_to", this.filters.assignments.end_to);
        const previousSnapshot = { ...(this.assignmentStatusSnapshot || {}) };
        const data = await this.api(`/api/admin/assignments?${query.toString()}`, { quiet });
        if (!data) return;
        const nextItems = Array.isArray(data?.items) ? data.items : [];
        this.assignments = {
          items: nextItems,
          summary: data?.summary || { unhandled_finished_count: 0 },
          ...data,
        };
        this.assignmentStatusSnapshot = this.assignmentStatusSnapshotMap(nextItems);
        if (source === "assignments-poll") {
          this.notifyAssignmentTransitions(nextItems, previousSnapshot);
        }
        if (this.route.name === "assignments") {
          this.scheduleAssignmentsPolling();
        }
      },

      async createAssignment() {
        const payload = {
          ...this.assignmentForm,
          candidate_id: Number(this.assignmentForm.candidate_id),
          require_phone_verification: Boolean(this.assignmentForm.require_phone_verification),
          ignore_timing: Boolean(this.assignmentForm.ignore_timing),
        };
        const result = await this.api("/api/admin/assignments", {
          method: "POST",
          body: JSON.stringify(payload),
          headers: { "Content-Type": "application/json" },
        });
        this.assignmentForm.ignore_timing = false;
        this.resetAssignmentCandidateSelection();
        this.showNotice(`邀约已创建：${result.url}`);
        await this.loadAssignments();
      },

      async loadAttemptDetail(token, { quiet = false, source = "manual" } = {}) {
        const currentToken = String(token || "").trim();
        const previousStatus = this.assignmentStatusValue(this.attemptDetail?.quiz_paper);
        const data = await this.api(`/api/admin/attempts/${encodeURIComponent(currentToken)}`, { quiet });
        if (!data) return;
        this.attemptDetail = {
          assignment: data?.assignment || {},
          quiz_paper: data?.quiz_paper || {},
          archive: data?.archive || {},
          review: data?.review || { answers: [], evaluation: {} },
        };
        const nextStatus = this.assignmentStatusValue(this.attemptDetail?.quiz_paper);
        if (currentToken) {
          this.assignmentStatusSnapshot = {
            ...(this.assignmentStatusSnapshot || {}),
            [currentToken]: nextStatus,
          };
        }
        if (source === "assignments-poll") {
          const candidateName = String(this.attemptDetail?.quiz_paper?.candidate_name || "").trim() || "该答题";
          if (previousStatus && previousStatus !== "grading" && previousStatus !== "finished" && nextStatus === "grading") {
            this.showNotice(`${candidateName} 已结束答题，正在判卷`);
          } else if (previousStatus === "grading" && nextStatus === "finished") {
            this.showNotice(`${candidateName} 的判卷已结束`);
          }
        }
        if (this.route.name === "attempt-detail") {
          this.scheduleAssignmentsPolling();
        }
        await this.$nextTick();
        this.queueMathTypeset();
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
            priceFormatter: formatLogTrendCount,
            tickmarksPriceFormatter: (prices) => prices.map((price) => formatLogTrendCount(price)),
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
              priceFormat: {
                type: "price",
                precision: 0,
                minMove: 1,
              },
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
        if (this.shouldRenderLogsChart()) {
          this.renderLogsChart();
        } else {
          this.destroyLogsChart();
        }
      },

      async loadStatusSummary() {
        this.statusSummary = await this.api("/api/admin/system-status/summary", { quiet: true }) || {};
      },

      async loadSystemBootstrap() {
        this.systemBootstrap = await this.api("/api/system/bootstrap", { quiet: true }) || {};
      },

      async loadStatus() {
        const data = await this.api("/api/admin/system-status");
        this.statusRange = data || { data: {} };
        this.statusConfig = { ...(data?.config || {}) };
        this.statusSummary = data?.summary || {};
        if (!Object.keys(this.statusSummary || {}).length) {
          await this.loadStatusSummary();
        }
      },

      async loadMcpPage() {
        if (!this.systemBootstrap?.mcp) {
          await this.loadSystemBootstrap();
        }
      },

      mcpInfo() {
        return this.systemBootstrap?.mcp || {};
      },

      absoluteUrl(path) {
        const value = String(path || "").trim();
        if (!value) return "";
        if (/^https?:\/\//i.test(value)) return value;
        if (typeof window === "undefined") return value;
        return `${window.location.origin}${value.startsWith("/") ? value : `/${value}`}`;
      },

      mcpUrl() {
        return this.absoluteUrl(this.mcpInfo().path || "");
      },

      mcpDocsUrl() {
        return this.absoluteUrl(this.mcpInfo().docs_path || "");
      },

      async copyMcpUrl() {
        const value = this.mcpUrl();
        if (!value) return;
        await this.copyText(value);
        this.showNotice("MCP 地址已复制");
      },

      openMcpDocs() {
        const target = this.mcpDocsUrl();
        if (!target || typeof window === "undefined") return;
        window.open(target, "_blank", "noopener,noreferrer");
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
