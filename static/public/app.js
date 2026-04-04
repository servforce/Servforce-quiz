(() => {
  const SESSION_HEADER = "X-Public-Session-Id";
  const OTP_LENGTH = 4;

  const createSessionId = () => {
    if (window.crypto?.randomUUID) return window.crypto.randomUUID();
    return `sess_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
  };

  const register = () => {
    if (!window.Alpine) return;
    window.Alpine.data("publicApp", () => ({
      booting: true,
      loading: false,
      actionBusy: false,
      timeoutSubmitting: false,
      error: "",
      smsSending: false,
      smsFeedback: { kind: "", message: "" },
      smsCooldownRemaining: 0,
      smsCooldownDeadline: 0,
      smsCooldownTimer: null,
      verifySubmitting: false,
      viewCard: "unavailable",
      route: { kind: "", token: "" },
      sessionId: "",
      state: { step: "", assignment: {}, quiz: {}, result: {}, resume: {}, verify: {}, unavailable: {} },
      forms: {
        verify: { name: "", phone: "", sms_code: "", sms_code_digits: Array(OTP_LENGTH).fill("") },
      },
      textDraft: "",
      selectedMultiple: [],
      autosaveMessage: "",
      autosaveTimer: null,
      questionTimer: null,
      questionRemainingSeconds: 0,
      questionRemainingMs: 0,
      touchStart: null,

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

      async syncRoute(pathname) {
        this.error = "";
        this.resetSmsState();
        this.route = this.parseRoute(pathname);
        if (this.route.kind === "invite") {
          await this.ensureInvite(this.route.token);
          return;
        }
        if (!this.route.token) {
          throw new Error("无效链接");
        }
        this.ensureSession(this.route.token);
        await this.loadAttempt(this.route.token);
      },

      parseRoute(pathname) {
        let match = pathname.match(/^\/p\/([^/]+)$/);
        if (match) return { kind: "invite", token: decodeURIComponent(match[1]) };
        match = pathname.match(/^\/(?:t|resume|quiz|exam|done|a)\/([^/]+)$/);
        if (match) return { kind: "attempt", token: decodeURIComponent(match[1]) };
        return { kind: "invalid", token: "" };
      },

      sessionStorageKey(token) {
        return `md-quiz-public-session:${token}`;
      },

      ensureSession(token) {
        if (!token) return "";
        const key = this.sessionStorageKey(token);
        let sessionId = window.sessionStorage.getItem(key) || "";
        if (!sessionId) {
          sessionId = createSessionId();
          window.sessionStorage.setItem(key, sessionId);
        }
        this.sessionId = sessionId;
        return sessionId;
      },

      async ensureInvite(publicToken) {
        const result = await this.api(`/api/public/invites/${encodeURIComponent(publicToken)}/ensure`, {
          method: "POST",
        });
        history.replaceState({}, "", result.redirect);
        this.route = { kind: "attempt", token: result.token };
        this.ensureSession(result.token);
        await this.loadAttempt(result.token);
      },

      async loadAttempt(token) {
        const data = await this.api(`/api/public/attempt/${encodeURIComponent(token)}`);
        this.state = data || this.state;
        this.syncFromState();
      },

      syncFromState() {
        this.clearAutosaveTimer();
        this.stopQuestionTimer();
        this.verifySubmitting = false;
        if (this.state.step !== "verify") {
          this.resetSmsState();
        }

        if (this.state.step === "verify") {
          this.viewCard = "start";
          if (this.state.verify?.mode !== "direct_phone") {
            this.forms.verify.name = this.state.verify?.name || "";
            this.forms.verify.phone = this.state.verify?.phone || "";
          }
          this.resetVerifyCode();
          this.focusOtpInput(0);
        } else if (this.state.step === "resume") {
          this.viewCard = "resume";
        } else if (this.state.step === "quiz") {
          this.viewCard = this.state.quiz?.entered_at ? "question" : "start";
        } else if (this.state.step === "done") {
          this.viewCard = "done";
        } else {
          this.viewCard = "unavailable";
        }

        const question = this.currentQuestion();
        const answer = this.currentAnswer();
        if (question?.type === "short") {
          this.textDraft = typeof answer === "string" ? answer : "";
          this.selectedMultiple = [];
        } else if (question?.type === "multiple") {
          this.selectedMultiple = Array.isArray(answer) ? [...answer] : [];
          this.textDraft = "";
        } else {
          this.textDraft = "";
          this.selectedMultiple = [];
        }

        this.autosaveMessage = this.state.quiz?.entered_at ? this.deferredSaveText(question) : "";
        this.syncQuestionTimer();
      },

      clearAutosaveTimer() {
        if (this.autosaveTimer) {
          window.clearTimeout(this.autosaveTimer);
          this.autosaveTimer = null;
        }
      },

      stopQuestionTimer() {
        if (this.questionTimer) {
          window.clearInterval(this.questionTimer);
          this.questionTimer = null;
        }
      },

      clearSmsCooldownTimer() {
        if (this.smsCooldownTimer) {
          window.clearInterval(this.smsCooldownTimer);
          this.smsCooldownTimer = null;
        }
      },

      resetSmsFeedback() {
        this.smsFeedback = { kind: "", message: "" };
      },

      resetSmsState() {
        this.smsSending = false;
        this.resetSmsFeedback();
        this.smsCooldownRemaining = 0;
        this.smsCooldownDeadline = 0;
        this.clearSmsCooldownTimer();
        this.verifySubmitting = false;
        this.resetVerifyCode();
      },

      resetVerifyCode() {
        this.forms.verify.sms_code = "";
        this.forms.verify.sms_code_digits = Array(OTP_LENGTH).fill("");
      },

      syncVerifyCode() {
        const digits = Array.isArray(this.forms.verify.sms_code_digits)
          ? this.forms.verify.sms_code_digits
          : Array(OTP_LENGTH).fill("");
        this.forms.verify.sms_code = digits.map((item) => String(item || "").trim()).join("");
        return this.forms.verify.sms_code;
      },

      isVerifyCodeComplete() {
        return /^\d{4}$/.test(this.syncVerifyCode());
      },

      focusOtpInput(index) {
        const targetIndex = Math.max(0, Math.min(Number(index || 0), OTP_LENGTH - 1));
        this.$nextTick(() => {
          const input = this.$root.querySelector(`[data-otp-input="${targetIndex}"]`);
          if (!input) return;
          input.focus();
          if (typeof input.select === "function") input.select();
        });
      },

      otpInputDisabled() {
        return this.verifySubmitting;
      },

      applyOtpDigits(index, rawValue) {
        const startIndex = Math.max(0, Math.min(Number(index || 0), OTP_LENGTH - 1));
        const digits = String(rawValue || "").replace(/\D/g, "");
        const nextDigits = Array.from({ length: OTP_LENGTH }, (_, currentIndex) => (
          String(this.forms.verify.sms_code_digits?.[currentIndex] || "")
        ));

        if (!digits) {
          nextDigits[startIndex] = "";
          this.forms.verify.sms_code_digits = nextDigits;
          this.syncVerifyCode();
          return startIndex;
        }

        if (digits.length > 1) {
          for (let currentIndex = startIndex; currentIndex < OTP_LENGTH; currentIndex += 1) {
            nextDigits[currentIndex] = "";
          }
        }

        const nextChunk = digits.slice(0, OTP_LENGTH - startIndex).split("");
        nextChunk.forEach((digit, offset) => {
          nextDigits[startIndex + offset] = digit;
        });

        this.forms.verify.sms_code_digits = nextDigits;
        this.syncVerifyCode();
        return Math.min(startIndex + nextChunk.length, OTP_LENGTH - 1);
      },

      async maybeAutoSubmitVerify() {
        if (!this.isVerifyCodeComplete() || this.verifySubmitting) return;
        await this.verify();
      },

      async handleOtpInput(index, event) {
        if (this.otpInputDisabled()) return;
        const nextIndex = this.applyOtpDigits(index, event?.target?.value || "");
        if (this.isVerifyCodeComplete()) {
          await this.maybeAutoSubmitVerify();
          return;
        }
        if (String(event?.target?.value || "").replace(/\D/g, "")) {
          this.focusOtpInput(nextIndex);
        }
      },

      handleOtpKeydown(index, event) {
        if (this.otpInputDisabled()) return;
        const currentIndex = Math.max(0, Math.min(Number(index || 0), OTP_LENGTH - 1));
        const digits = Array.isArray(this.forms.verify.sms_code_digits)
          ? [...this.forms.verify.sms_code_digits]
          : Array(OTP_LENGTH).fill("");

        if (event.key === "Backspace") {
          event.preventDefault();
          if (digits[currentIndex]) {
            digits[currentIndex] = "";
            this.forms.verify.sms_code_digits = digits;
            this.syncVerifyCode();
            return;
          }
          if (currentIndex <= 0) return;
          digits[currentIndex - 1] = "";
          this.forms.verify.sms_code_digits = digits;
          this.syncVerifyCode();
          this.focusOtpInput(currentIndex - 1);
          return;
        }

        if (event.key === "ArrowLeft" && currentIndex > 0) {
          event.preventDefault();
          this.focusOtpInput(currentIndex - 1);
          return;
        }

        if (event.key === "ArrowRight" && currentIndex < OTP_LENGTH - 1) {
          event.preventDefault();
          this.focusOtpInput(currentIndex + 1);
          return;
        }

        if (event.key === "Enter") {
          event.preventDefault();
          this.maybeAutoSubmitVerify().catch(() => {});
          return;
        }

        if (event.key.length === 1 && !/\d/.test(event.key)) {
          event.preventDefault();
        }
      },

      async handleOtpPaste(index, event) {
        if (this.otpInputDisabled()) return;
        const pastedText = event?.clipboardData?.getData("text") || "";
        if (!String(pastedText).replace(/\D/g, "")) return;
        event.preventDefault();
        const nextIndex = this.applyOtpDigits(index, pastedText);
        if (this.isVerifyCodeComplete()) {
          await this.maybeAutoSubmitVerify();
          return;
        }
        this.focusOtpInput(nextIndex);
      },

      syncSmsCooldown() {
        if (!this.smsCooldownDeadline) {
          this.smsCooldownRemaining = 0;
          return;
        }
        const leftMs = Math.max(0, this.smsCooldownDeadline - Date.now());
        this.smsCooldownRemaining = Math.ceil(leftMs / 1000);
        if (leftMs > 0) return;
        this.smsCooldownDeadline = 0;
        this.smsCooldownRemaining = 0;
        this.clearSmsCooldownTimer();
        if (this.smsFeedback.kind === "warning") {
          this.resetSmsFeedback();
        }
      },

      startSmsCooldown(totalSeconds) {
        const seconds = Math.max(0, Math.ceil(Number(totalSeconds || 0)));
        this.clearSmsCooldownTimer();
        if (!seconds) {
          this.smsCooldownDeadline = 0;
          this.smsCooldownRemaining = 0;
          return;
        }
        this.smsCooldownDeadline = Date.now() + (seconds * 1000);
        this.syncSmsCooldown();
        if (!this.smsCooldownRemaining) return;
        this.smsCooldownTimer = window.setInterval(() => {
          this.syncSmsCooldown();
        }, 250);
      },

      parseSmsCooldownSeconds(message) {
        const match = String(message || "").match(/请\s*(\d+)\s*秒后再试/);
        return match ? Math.max(0, Number(match[1] || 0)) : 0;
      },

      smsSendButtonDisabled() {
        return this.smsSending || this.smsCooldownRemaining > 0 || this.verifySubmitting;
      },

      smsSendButtonText() {
        if (this.smsSending) return "发送中...";
        if (this.smsCooldownRemaining > 0) return `${this.smsCooldownRemaining} 秒后重发`;
        return "发送验证码";
      },

      smsSendButtonClasses() {
        if (this.smsSendButtonDisabled()) {
          return "cursor-not-allowed border-white/10 bg-white/5 text-slate-500";
        }
        return "border-emerald-400/30 bg-emerald-400/10 text-emerald-100 hover:bg-emerald-400/18";
      },

      smsFeedbackClasses() {
        if (this.smsFeedback.kind === "success") {
          return "border-emerald-400/30 bg-emerald-400/10 text-emerald-100";
        }
        if (this.smsFeedback.kind === "warning") {
          return "border-amber-400/30 bg-amber-400/10 text-amber-100";
        }
        return "border-rose-400/30 bg-rose-400/10 text-rose-100";
      },

      isVerifyStep() {
        return this.state.step === "verify";
      },

      startLeadEyebrow() {
        return this.isVerifyStep() ? "开始前验证" : "开始作答前";
      },

      startLeadText() {
        if (!this.isVerifyStep()) {
          return "请按页面提示完成答题，确认开始后进入正式作答。";
        }
        if (this.state.verify?.mode === "direct_phone") {
          return "先完成短信验证，验证成功后将直接进入题目。";
        }
        return "先完成短信验证，验证成功后继续下一步。";
      },

      verifyTitle() {
        return this.state.verify?.mode === "direct_phone" ? "手机号验证" : "公开邀约验证";
      },

      verifyHintText() {
        if (this.state.verify?.mode === "direct_phone") {
          return "验证码将发送到目标手机号，输入 4 位数字后会自动验证。";
        }
        return "请输入姓名与手机号，收到验证码后输入 4 位数字，系统会自动完成校验。";
      },

      verifyAutoHintText() {
        if (this.state.verify?.mode === "direct_phone") {
          return "填满 4 位后自动验证，验证成功后将直接进入第 1 题。";
        }
        return "填满 4 位后自动验证，验证成功后继续上传简历或进入下一步。";
      },

      timingIgnored() {
        return Boolean(this.state.assignment?.ignore_timing);
      },

      syncQuestionTimer() {
        if (this.viewCard !== "question" || this.timingIgnored()) {
          this.questionRemainingSeconds = 0;
          this.questionRemainingMs = 0;
          return;
        }
        this.questionRemainingMs = this.computeCurrentRemainingMs();
        this.questionRemainingSeconds = Math.ceil(this.questionRemainingMs / 1000);
        this.questionTimer = window.setInterval(() => {
          if (this.viewCard !== "question") return;
          this.questionRemainingMs = this.computeCurrentRemainingMs();
          this.questionRemainingSeconds = Math.ceil(this.questionRemainingMs / 1000);
          if (this.questionRemainingMs > 0 || this.timeoutSubmitting || this.actionBusy) return;
          this.timeoutSubmitting = true;
          const isLast = this.isLastQuestion();
          this.performAnswerAction({ advance: !isLast, submit: isLast, forceTimeout: true })
            .catch(() => {})
            .finally(() => {
              this.timeoutSubmitting = false;
            });
        }, 80);
      },

      computeCurrentRemainingMs() {
        if (this.timingIgnored()) return 0;
        const question = this.currentQuestion();
        const startedAt = this.state.quiz?.question_flow?.current_started_at || "";
        if (!question) return 0;
        const durationSeconds = Number(question.answer_time_seconds || this.state.quiz?.question_flow?.current_question_seconds || 0);
        const durationMs = Math.max(0, durationSeconds * 1000);
        if (!startedAt || durationMs <= 0) return durationMs;
        const startedMs = Date.parse(startedAt);
        if (Number.isNaN(startedMs)) return durationMs;
        const elapsedMs = Math.max(0, Date.now() - startedMs);
        return Math.max(0, durationMs - elapsedMs);
      },

      cardBackgroundStyle() {
        let image = "";
        let position = "center center";
        if (this.viewCard === "done") {
          image = this.state.quiz?.spec?.end_image || "";
        } else {
          image = this.state.quiz?.spec?.welcome_image || "";
          position = "center top";
        }
        return image
          ? `background-image:url('${image}');background-position:${position};background-size:cover;`
          : "";
      },

      quizTitle() {
        return this.state.quiz?.title || this.state.assignment?.quiz_key || "在线测验";
      },

      quizQuestionCount() {
        return Number(this.state.quiz?.question_count || this.state.quiz?.stats?.total_questions || 0);
      },

      quizDurationSeconds() {
        return Number(this.state.quiz?.answer_time_total_seconds || this.state.quiz?.time_limit_seconds || 0);
      },

      quizDurationText() {
        if (this.timingIgnored()) return "不限时";
        const totalSeconds = this.quizDurationSeconds();
        if (totalSeconds <= 0) return "-";
        const totalMinutes = Math.ceil(totalSeconds / 60);
        return `${totalMinutes} 分钟`;
      },

      quizDurationLabel() {
        return this.timingIgnored() ? "答题时长" : "预计时长";
      },

      doneMessage() {
        if (this.state.result?.status === "done") {
          return "答案已经提交并完成判卷，这个链接不会再重新开放答题。";
        }
        return "答案已经提交，系统正在判卷或整理结果。这个链接再次访问也只会显示当前结束状态。";
      },

      currentQuestionIndex() {
        return Number(this.state.quiz?.question_flow?.current_index || 0);
      },

      questionNumber() {
        return this.currentQuestionIndex() + 1;
      },

      currentQuestion() {
        const questions = this.state.quiz?.spec?.questions || [];
        if (!questions.length) return null;
        const index = Math.max(0, Math.min(this.currentQuestionIndex(), questions.length - 1));
        return questions[index];
      },

      isLastQuestion() {
        return this.questionNumber() >= this.quizQuestionCount();
      },

      currentAnswer() {
        const qid = this.currentQuestion()?.qid;
        if (!qid) return null;
        return this.state.assignment?.answers?.[qid] ?? null;
      },

      currentAnswerPayload() {
        const question = this.currentQuestion();
        if (!question) return null;
        if (question.type === "short") return this.textDraft;
        if (question.type === "multiple") return [...this.selectedMultiple];
        return this.currentAnswer();
      },

      isSingleSelected(optionKey) {
        return String(this.currentAnswer() || "") === String(optionKey || "");
      },

      isMultipleSelected(optionKey) {
        return this.selectedMultiple.includes(String(optionKey || ""));
      },

      optionBadgeClasses(optionKey, selected) {
        const key = String(optionKey || "").trim().toUpperCase();
        const palette = {
          A: selected
            ? "border-teal-300/55 bg-teal-300/18 text-teal-100"
            : "border-teal-400/35 bg-teal-400/10 text-teal-200",
          B: selected
            ? "border-sky-300/55 bg-sky-300/18 text-sky-100"
            : "border-sky-400/35 bg-sky-400/10 text-sky-200",
          C: selected
            ? "border-amber-300/55 bg-amber-300/18 text-amber-100"
            : "border-amber-400/35 bg-amber-400/10 text-amber-200",
          D: selected
            ? "border-rose-300/55 bg-rose-300/18 text-rose-100"
            : "border-rose-400/35 bg-rose-400/10 text-rose-200",
          E: selected
            ? "border-lime-300/55 bg-lime-300/18 text-lime-100"
            : "border-lime-400/35 bg-lime-400/10 text-lime-200",
        };
        return palette[key] || (selected
          ? "border-emerald-300/55 bg-emerald-300/18 text-emerald-100"
          : "border-white/15 bg-white/5 text-slate-200");
      },

      canAdvanceCurrent() {
        const question = this.currentQuestion();
        if (!question) return false;
        if (question.type === "single") return Boolean(String(this.currentAnswer() || "").trim());
        if (question.type === "multiple") return this.selectedMultiple.length > 0;
        return Boolean(String(this.textDraft || "").trim());
      },

      deferredSaveText(question = this.currentQuestion()) {
        if (!question) return "";
        if (question.type === "short") {
          return this.isLastQuestion() ? "简答题在点击“完成并提交”后保存" : "简答题在点击“完成本题”后保存";
        }
        if (question.type === "multiple") {
          return this.isLastQuestion() ? "多选题在点击“提交测验”后保存" : "多选题在点击“下一题”后保存";
        }
        return "";
      },

      questionProgressPercent() {
        if (this.timingIgnored()) return 0;
        const question = this.currentQuestion();
        if (!question) return 0;
        const totalMs = Math.max(0, Number(question.answer_time_seconds || 0) * 1000);
        if (totalMs <= 0) return 0;
        return Math.max(0, Math.min(100, (this.questionRemainingMs / totalMs) * 100));
      },

      formatDuration(totalSeconds) {
        const seconds = Math.max(0, Number(totalSeconds || 0));
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = seconds % 60;
        return [h, m, s].map((value) => String(value).padStart(2, "0")).join(":");
      },

      autosaveText() {
        return this.autosaveMessage || "";
      },

      async performAnswerAction(action, options = {}) {
        const question = this.currentQuestion();
        if (!question || !this.route.token) return;
        this.actionBusy = true;
        try {
          const data = await this.api(`/api/public/answers/${encodeURIComponent(this.route.token)}`, {
            method: "POST",
            body: JSON.stringify({
              question_id: question.qid,
              answer: this.currentAnswerPayload(),
              advance: Boolean(action.advance),
              submit: Boolean(action.submit),
              session_id: this.sessionId,
              force_timeout: Boolean(action.forceTimeout),
            }),
            headers: { "Content-Type": "application/json" },
          });
          this.state = data;
          this.syncFromState();
        } catch (error) {
          const detail = String(error?.message || "");
          if (["question_locked", "already_submitted", "not_last_question"].includes(detail) && this.route.token) {
            await this.loadAttempt(this.route.token);
          }
          throw error;
        } finally {
          this.actionBusy = false;
        }
      },

      async sendSms() {
        if (this.smsSendButtonDisabled()) return;
        this.smsSending = true;
        this.resetSmsFeedback();
        try {
          const result = await this.api("/api/public/sms/send", {
            method: "POST",
            body: JSON.stringify({
              token: this.route.token,
              name: this.forms.verify.name,
              phone: this.forms.verify.phone,
            }),
            headers: { "Content-Type": "application/json" },
            manageState: false,
          });
          const cooldown = Number(result?.cooldown || 0) > 0 ? Number(result.cooldown) : 60;
          this.startSmsCooldown(cooldown);
          this.resetVerifyCode();
          this.focusOtpInput(0);
          this.smsFeedback = { kind: "success", message: "验证码已发送，请查收短信" };
          this.error = "";
        } catch (error) {
          const message = String(error?.message || "发送验证码失败");
          const cooldown = this.parseSmsCooldownSeconds(message);
          if (cooldown > 0) {
            this.startSmsCooldown(cooldown);
            this.smsFeedback = { kind: "warning", message };
          } else {
            this.smsFeedback = { kind: "error", message };
          }
          this.error = "";
        } finally {
          this.smsSending = false;
        }
      },

      async verify() {
        const smsCode = this.syncVerifyCode();
        if (!/^\d{4}$/.test(smsCode)) {
          this.smsFeedback = { kind: "error", message: "请输入 4 位数字验证码" };
          this.resetVerifyCode();
          this.focusOtpInput(0);
          return;
        }
        if (this.verifySubmitting) return;

        this.verifySubmitting = true;
        this.resetSmsFeedback();
        const shouldAutoEnter = this.state.verify?.mode === "direct_phone";
        let verified = false;
        try {
          const result = await this.api("/api/public/verify", {
            method: "POST",
            body: JSON.stringify({
              token: this.route.token,
              name: this.forms.verify.name,
              phone: this.forms.verify.phone,
              sms_code: smsCode,
            }),
            headers: { "Content-Type": "application/json" },
            manageState: false,
          });
          verified = true;
          history.replaceState({}, "", result.redirect);
          await this.syncRoute(result.redirect);
          if (shouldAutoEnter && this.state.step === "quiz" && !this.state.quiz?.entered_at) {
            await this.enterQuiz();
          }
          this.error = "";
        } catch (error) {
          const message = String(error?.message || "验证码校验失败，请重试");
          if (!verified) {
            this.smsFeedback = { kind: "error", message };
            this.error = "";
            this.resetVerifyCode();
            this.focusOtpInput(0);
          } else {
            this.error = message;
          }
        } finally {
          this.verifySubmitting = false;
        }
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

      async enterQuiz() {
        const data = await this.api(`/api/public/attempt/${encodeURIComponent(this.route.token)}/enter`, {
          method: "POST",
        });
        this.state = data;
        this.syncFromState();
      },

      async selectSingleOption(optionKey) {
        if (this.actionBusy) return;
        const qid = this.currentQuestion()?.qid;
        if (!qid) return;
        if (!this.state.assignment.answers) this.state.assignment.answers = {};
        this.state.assignment.answers[qid] = String(optionKey || "");
        await this.performAnswerAction({ advance: true, submit: this.isLastQuestion(), forceTimeout: false });
      },

      toggleMultipleOption(optionKey) {
        const value = String(optionKey || "");
        if (!value) return;
        if (this.selectedMultiple.includes(value)) {
          this.selectedMultiple = this.selectedMultiple.filter((item) => item !== value);
        } else {
          this.selectedMultiple = [...this.selectedMultiple, value];
        }
        this.clearAutosaveTimer();
        this.autosaveMessage = this.deferredSaveText();
      },

      onTextInput() {
        this.clearAutosaveTimer();
        this.autosaveMessage = this.deferredSaveText();
      },

      async goNext() {
        if (!this.canAdvanceCurrent() || this.actionBusy) return;
        await this.performAnswerAction({ advance: true, submit: false, forceTimeout: false });
      },

      async submitLastQuestion() {
        if (!this.canAdvanceCurrent() || this.actionBusy) return;
        await this.performAnswerAction({ advance: false, submit: true, forceTimeout: false });
      },

      onQuestionTouchStart(event) {
        const touch = event.changedTouches?.[0];
        if (!touch) return;
        this.touchStart = { x: touch.clientX, y: touch.clientY };
      },

      onQuestionTouchEnd(event) {
        if (!this.touchStart || !this.canAdvanceCurrent() || this.actionBusy) {
          this.touchStart = null;
          return;
        }
        const touch = event.changedTouches?.[0];
        if (!touch) {
          this.touchStart = null;
          return;
        }
        const dx = touch.clientX - this.touchStart.x;
        const dy = touch.clientY - this.touchStart.y;
        this.touchStart = null;
        if (!(dx < -60 || dy < -60)) return;
        if (this.isLastQuestion()) {
          this.submitLastQuestion();
        } else {
          this.goNext();
        }
      },

      async api(url, options = {}) {
        const { manageState = true, ...requestOptions } = options;
        const headers = new Headers(requestOptions.headers || {});
        if (this.sessionId) headers.set(SESSION_HEADER, this.sessionId);
        const response = await fetch(url, {
          credentials: "same-origin",
          ...requestOptions,
          headers,
        });
        const text = await response.text();
        const data = text ? JSON.parse(text) : {};
        if (!response.ok) {
          const message = data.detail || data.error || "请求失败";
          if (manageState) {
            this.error = message;
          }
          throw new Error(message);
        }
        if (manageState) {
          this.error = "";
        }
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
