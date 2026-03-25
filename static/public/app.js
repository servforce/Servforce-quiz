(() => {
  const register = () => {
    if (!window.Alpine) return;
    window.Alpine.data("publicApp", () => ({
    booting: true,
    error: "",
    state: { step: "", assignment: {}, exam: {}, result: {}, resume: {}, verify: {}, unavailable: {} },
    route: { kind: "", token: "" },
    heroTitle: "正在准备答题流程",
    heroDescription: "系统会根据当前链接和会话状态自动恢复到正确的步骤。",
    remainingText: "-",
    forms: {
      verify: { name: "", phone: "", sms_code: "" },
    },

    async init() {
      try {
        await this.syncRoute(location.pathname);
      } catch (error) {
        this.error = error.message || "页面初始化失败";
      } finally {
        this.booting = false;
      }
      window.addEventListener("popstate", () => this.syncRoute(location.pathname));
    },

    pretty(value) {
      return JSON.stringify(value || {}, null, 2);
    },

    async syncRoute(pathname) {
      this.error = "";
      this.route = this.parseRoute(pathname);
      if (this.route.kind === "invite") {
        await this.ensureInvite(this.route.token);
        return;
      }
      if (!this.route.token) {
        throw new Error("无效链接");
      }
      await this.loadAttempt(this.route.token);
    },

    parseRoute(pathname) {
      let match = pathname.match(/^\/p\/([^/]+)$/);
      if (match) return { kind: "invite", token: decodeURIComponent(match[1]) };
      match = pathname.match(/^\/(?:t|resume|exam|done|a)\/([^/]+)$/);
      if (match) return { kind: "attempt", token: decodeURIComponent(match[1]) };
      return { kind: "invalid", token: "" };
    },

    async ensureInvite(publicToken) {
      const result = await this.api(`/api/public/invites/${encodeURIComponent(publicToken)}/ensure`, {
        method: "POST",
      });
      history.replaceState({}, "", result.redirect);
      this.route = { kind: "attempt", token: result.token };
      await this.loadAttempt(result.token);
    },

    async loadAttempt(token) {
      const data = await this.api(`/api/public/attempt/${encodeURIComponent(token)}`);
      this.state = data || this.state;
      this.syncHero();
      this.syncVerifyForm();
    },

    syncHero() {
      const step = this.state.step;
      if (step === "verify") {
        this.heroTitle = "先完成身份验证";
        this.heroDescription = "输入姓名、手机号并通过短信验证码，系统会为你恢复到下一步。";
      } else if (step === "resume") {
        this.heroTitle = "上传简历完成建档";
        this.heroDescription = "公开邀约场景下，需先上传简历，再进入正式答题。";
      } else if (step === "exam") {
        this.heroTitle = this.state.exam?.title || "在线答题";
        this.heroDescription = "开始答题后会启动倒计时，请及时保存并提交答案。";
      } else if (step === "done") {
        this.heroTitle = "答题已完成";
        this.heroDescription = "如果判卷还在处理中，页面会保留当前状态，稍后刷新即可查看。";
      } else if (step === "unavailable") {
        this.heroTitle = this.state.unavailable?.title || "链接不可用";
        this.heroDescription = this.state.unavailable?.message || "";
      } else {
        this.heroTitle = "正在准备答题流程";
        this.heroDescription = "系统会根据当前链接和会话状态自动恢复到正确的步骤。";
      }
      const remaining = Number(this.state.exam?.remaining_seconds || 0);
      this.remainingText = remaining > 0 ? this.formatDuration(remaining) : "-";
    },

    syncVerifyForm() {
      this.forms.verify.name = this.state.verify?.name || "";
      this.forms.verify.phone = this.state.verify?.phone || "";
      this.forms.verify.sms_code = "";
    },

    formatDuration(totalSeconds) {
      const seconds = Math.max(0, Number(totalSeconds || 0));
      const h = Math.floor(seconds / 3600);
      const m = Math.floor((seconds % 3600) / 60);
      const s = seconds % 60;
      return [h, m, s].map((value) => String(value).padStart(2, "0")).join(":");
    },

    async sendSms() {
      await this.api("/api/public/sms/send", {
        method: "POST",
        body: JSON.stringify({
          token: this.route.token,
          name: this.forms.verify.name,
          phone: this.forms.verify.phone,
        }),
        headers: { "Content-Type": "application/json" },
      });
      this.error = "验证码已发送，请查收短信";
    },

    async verify() {
      const result = await this.api("/api/public/verify", {
        method: "POST",
        body: JSON.stringify({
          token: this.route.token,
          name: this.forms.verify.name,
          phone: this.forms.verify.phone,
          sms_code: this.forms.verify.sms_code,
        }),
        headers: { "Content-Type": "application/json" },
      });
      history.replaceState({}, "", result.redirect);
      await this.syncRoute(result.redirect);
    },

    async uploadResume() {
      const file = this.$refs.resumeFile?.files?.[0];
      if (!file) {
        this.error = "请先选择简历文件";
        return;
      }
      const form = new FormData();
      form.append("file", file);
      const result = await this.api(`/api/public/resume/upload?token=${encodeURIComponent(this.route.token)}`, {
        method: "POST",
        body: form,
      });
      history.replaceState({}, "", result.redirect);
      await this.syncRoute(result.redirect);
    },

    async enterExam() {
      const data = await this.api(`/api/public/attempt/${encodeURIComponent(this.route.token)}/enter`, {
        method: "POST",
      });
      this.state = data;
      this.syncHero();
    },

    answerText(questionId) {
      const answers = this.state.assignment?.answers || {};
      return typeof answers[questionId] === "string" ? answers[questionId] : "";
    },

    isOptionChecked(questionId, type, optionKey) {
      const answers = this.state.assignment?.answers || {};
      const current = answers[questionId];
      if (type === "single") return current === optionKey;
      return Array.isArray(current) && current.includes(optionKey);
    },

    toggleOption(question, optionKey, checked) {
      const qid = question.qid;
      const answers = this.state.assignment.answers || (this.state.assignment.answers = {});
      if (question.type === "single") {
        answers[qid] = optionKey;
      } else {
        const current = Array.isArray(answers[qid]) ? [...answers[qid]] : [];
        if (checked && !current.includes(optionKey)) current.push(optionKey);
        if (!checked) answers[qid] = current.filter((item) => item !== optionKey);
        else answers[qid] = current;
      }
    },

    setAnswer(questionId, value) {
      const answers = this.state.assignment.answers || (this.state.assignment.answers = {});
      answers[questionId] = value;
    },

    async saveAnswers() {
      await this.api(`/api/public/answers_bulk/${encodeURIComponent(this.route.token)}`, {
        method: "POST",
        body: JSON.stringify({ answers: this.state.assignment?.answers || {} }),
        headers: { "Content-Type": "application/json" },
      });
      this.error = "答案已保存";
    },

    async submitExam() {
      const result = await this.api(`/api/public/submit/${encodeURIComponent(this.route.token)}`, {
        method: "POST",
      });
      history.replaceState({}, "", result.redirect);
      await this.syncRoute(result.redirect);
    },

    async api(url, options = {}) {
      const response = await fetch(url, {
        credentials: "same-origin",
        ...options,
      });
      const text = await response.text();
      const data = text ? JSON.parse(text) : {};
      if (!response.ok) {
        const message = data.detail || data.error || "请求失败";
        this.error = message;
        throw new Error(message);
      }
      this.error = "";
      return data;
    },
    }));
  };

  if (window.Alpine) {
    register();
  } else {
    document.addEventListener("alpine:init", register, { once: true });
  }
})();
