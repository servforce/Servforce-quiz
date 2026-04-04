import { absoluteUrl } from "/static/assets/js/shared/runtime.js";

export function createAdminStatusModule() {
  return {
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
      return absoluteUrl(path);
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
      await this.copyText(value, "MCP 地址已复制");
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
  };
}
