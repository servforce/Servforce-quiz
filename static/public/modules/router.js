import { createSessionId } from "./constants.js";

export function createPublicRouterModule() {
  return {
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

    async syncFromState() {
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
          await this.renderCurrentView();
          await this.$nextTick();
          if (this.state.step === "verify") {
            this.focusOtpInput(0);
          }
          this.queueMathTypeset();
        },

          async loadAttempt(token) {
            const data = await this.api(`/api/public/attempt/${encodeURIComponent(token)}`);
            this.state = data || this.state;
            await this.syncFromState();
          },
  };
}
