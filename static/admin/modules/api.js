export function createAdminApiModule() {
  return {
    async api(url, options = {}) {
      const { quiet = false, ...fetchOptions } = options;
      try {
        const response = await fetch(url, {
          credentials: "same-origin",
          ...fetchOptions,
        });
        if (response.status === 401) {
          this.session = { authenticated: false, username: "" };
          this.destroyLogsChart();
          this.stopSyncPolling();
          this.stopAssignmentsPolling();
          if (!quiet) {
            this.error = "登录状态已失效";
            this.showNotice("登录状态已失效");
          }
          history.replaceState({}, "", "/admin/login");
          this.route = this.resolveRoute("/admin/login");
          if (typeof this.renderCurrentRoute === "function") {
            await this.renderCurrentRoute();
          }
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
  };
}
