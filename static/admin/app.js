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
      candidateResumeUploadState: createCandidateResumeUploadState(),
      candidateResumeReparseState: createCandidateResumeReparseState(),
      candidateEvaluation: "",
      assignmentForm: {
        exam_key: "",
        candidate_id: "",
        invite_start_date: new Date().toISOString().slice(0, 10),
        invite_end_date: new Date(Date.now() + 86400000).toISOString().slice(0, 10),
        time_limit_seconds: "7200",
      },
      assignmentSelect: {
        exam: { open: false, query: "" },
        candidate: { open: false, query: "" },
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

      selectedAssignmentExam() {
        const examKey = String(this.assignmentForm?.exam_key || "").trim();
        if (!examKey) return null;
        return (this.exams?.items || []).find((item) => String(item?.exam_key || "").trim() === examKey) || null;
      },

      selectedAssignmentCandidate() {
        const candidateId = String(this.assignmentForm?.candidate_id || "").trim();
        if (!candidateId) return null;
        return (this.candidates?.items || []).find((item) => String(item?.id || "").trim() === candidateId) || null;
      },

      filteredAssignmentExams() {
        const query = String(this.assignmentSelect?.exam?.query || "").trim().toLowerCase();
        const items = Array.isArray(this.exams?.items) ? this.exams.items : [];
        if (!query) return items;
        return items.filter((item) => {
          const haystacks = [
            String(item?.title || "").trim(),
            String(item?.exam_key || "").trim(),
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
        const target = kind === "candidate" ? "candidate" : "exam";
        if (this.assignmentSelect?.[target]?.open) {
          return String(this.assignmentSelect[target].query || "");
        }
        if (target === "exam") {
          const selected = this.selectedAssignmentExam();
          return selected ? String(selected.title || selected.exam_key || "") : "";
        }
        const selected = this.selectedAssignmentCandidate();
        return selected ? String(selected.name || "") : "";
      },

      openAssignmentSelect(kind) {
        const target = kind === "candidate" ? "candidate" : "exam";
        this.assignmentSelect.exam.open = false;
        this.assignmentSelect.candidate.open = false;
        this.assignmentSelect[target].open = true;
        this.assignmentSelect[target].query = "";
      },

      handleAssignmentSelectInput(kind, event) {
        const target = kind === "candidate" ? "candidate" : "exam";
        const value = String(event?.target?.value || "");
        this.assignmentSelect.exam.open = false;
        this.assignmentSelect.candidate.open = false;
        this.assignmentSelect[target].open = true;
        this.assignmentSelect[target].query = value;
        if (target === "exam" && this.assignmentForm.exam_key) {
          this.assignmentForm.exam_key = "";
        }
        if (target === "candidate" && this.assignmentForm.candidate_id) {
          this.assignmentForm.candidate_id = "";
        }
      },

      toggleAssignmentSelect(kind) {
        const target = kind === "candidate" ? "candidate" : "exam";
        const nextOpen = !Boolean(this.assignmentSelect?.[target]?.open);
        this.assignmentSelect.exam.open = false;
        this.assignmentSelect.candidate.open = false;
        this.assignmentSelect[target].open = nextOpen;
        if (!nextOpen) {
          this.assignmentSelect[target].query = "";
        }
      },

      closeAssignmentSelect(kind) {
        const target = kind === "candidate" ? "candidate" : "exam";
        if (!this.assignmentSelect?.[target]) return;
        this.assignmentSelect[target].open = false;
        this.assignmentSelect[target].query = "";
      },

      selectAssignmentExam(item) {
        this.assignmentForm.exam_key = String(item?.exam_key || "").trim();
        this.closeAssignmentSelect("exam");
      },

      clearAssignmentExam() {
        this.assignmentForm.exam_key = "";
        this.closeAssignmentSelect("exam");
      },

      selectAssignmentCandidate(item) {
        this.assignmentForm.candidate_id = String(item?.id || "").trim();
        this.closeAssignmentSelect("candidate");
      },

      clearAssignmentCandidate() {
        this.assignmentForm.candidate_id = "";
        this.closeAssignmentSelect("candidate");
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
