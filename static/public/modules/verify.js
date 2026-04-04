import { OTP_LENGTH } from "./constants.js";

export function createPublicVerifyModule() {
  return {
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
  };
}
