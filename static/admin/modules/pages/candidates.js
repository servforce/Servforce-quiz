import { RESUME_PARSE_META, RESUME_PHASE_META, createCandidateResumeUploadState, createCandidateResumeReparseState } from "../constants.js";
export function createAdminCandidatesModule() {
  return {
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

  };
}
