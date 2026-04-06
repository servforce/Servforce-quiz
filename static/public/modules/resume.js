export function createPublicResumeModule() {
  return {
    resumeMode() {
      return String(this.state.resume?.mode || "upload_required").trim() || "upload_required";
    },

    canUseExistingResume() {
      return this.resumeMode() === "reuse_or_replace";
    },

    existingResume() {
      return this.state.resume?.existing_resume || {};
    },

    existingResumeFilename() {
      return String(this.existingResume().filename || "").trim() || "未命名简历";
    },

    formatResumeSize(size) {
      const value = Number(size || 0);
      if (!Number.isFinite(value) || value <= 0) return "未记录";
      if (value < 1024) return `${Math.round(value)} B`;
      if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
      return `${(value / (1024 * 1024)).toFixed(1)} MB`;
    },

    existingResumeSizeText() {
      return this.formatResumeSize(this.existingResume().size);
    },

    existingResumeParsedAtText() {
      const raw = String(this.existingResume().parsed_at || "").trim();
      if (!raw) return "未记录";
      const parsed = new Date(raw);
      if (Number.isNaN(parsed.getTime())) return raw;
      return parsed.toLocaleString("zh-CN", { hour12: false });
    },

    async useExistingResume() {
      if (!this.canUseExistingResume() || this.actionBusy) return;
      this.actionBusy = true;
      try {
        const result = await this.api("/api/public/resume/use-existing", {
          method: "POST",
          body: JSON.stringify({ token: this.route.token }),
          headers: { "Content-Type": "application/json" },
        });
        history.replaceState({}, "", result.redirect);
        await this.syncRoute(result.redirect);
      } finally {
        this.actionBusy = false;
      }
    },

    async uploadResume() {
      if (this.actionBusy) return;
      const file = this.$refs.resumeFile?.files?.[0];
      if (!file) {
        this.error = "请先选择简历文件";
        return;
      }
      this.actionBusy = true;
      try {
        const form = new FormData();
        form.append("file", file);
        const result = await this.api(`/api/public/resume/upload?token=${encodeURIComponent(this.route.token)}`, {
          method: "POST",
          body: form,
        });
        history.replaceState({}, "", result.redirect);
        await this.syncRoute(result.redirect);
      } finally {
        this.actionBusy = false;
      }
    },
  };
}
