function currentRoute() {
  const hash = window.location.hash || "#/admin/login";
  return hash.replace(/^#/, "");
}

window.appShell = function appShell() {
  return {
    pageTitle: "新控制台概览",
    healthText: "系统启动中",
    legacyUrl: "/legacy/admin",
    session: { authenticated: false, username: null },
    navigation: [
      { href: "#/admin/login", label: "后台登录", title: "后台登录" },
      { href: "#/admin/overview", label: "新控制台概览", title: "新控制台概览" },
      { href: "#/admin/jobs", label: "任务系统", title: "任务系统" },
      { href: "#/public/entry", label: "候选人端入口", title: "候选人端入口" },
    ],
    async init() {
      window.__appShell = this;
      await this.refreshHealth();
      await this.refreshSession();
      await this.renderRoute();
      window.addEventListener("hashchange", () => {
        this.renderRoute();
      });
    },
    isActive(item) {
      return currentRoute() === item.href.replace(/^#/, "");
    },
    async refreshHealth() {
      try {
        const response = await fetch("/api/system/health");
        const data = await response.json();
        this.healthText = data.status === "ok" ? "运行正常" : "状态异常";
      } catch (error) {
        this.healthText = "无法连接 API";
      }
    },
    async refreshSession() {
      try {
        this.session = await fetch("/api/admin/session").then((response) => response.json());
      } catch (error) {
        this.session = { authenticated: false, username: null };
      }
    },
    async renderRoute() {
      let route = currentRoute();
      if (!this.session.authenticated && route.startsWith("/admin/") && route !== "/admin/login") {
        window.location.hash = "#/admin/login";
        route = "/admin/login";
      }
      const viewRoot = document.getElementById("view-root");
      const item = this.navigation.find((entry) => entry.href.replace(/^#/, "") === route);
      this.pageTitle = item?.title || "MD Quiz";
      let viewPath = "/static/app/views/admin-overview.html";
      if (route === "/admin/login") {
        viewPath = "/static/app/views/admin-login.html";
      } else if (route === "/admin/jobs") {
        viewPath = "/static/app/views/admin-jobs.html";
      } else if (route === "/public/entry") {
        viewPath = "/static/app/views/public-entry.html";
      }
      const html = await fetch(viewPath).then((response) => response.text());
      viewRoot.innerHTML = html;
      if (window.Alpine) {
        window.Alpine.initTree(viewRoot);
      }
    },
  };
};

window.adminLoginPage = function adminLoginPage() {
  return {
    form: { username: "", password: "" },
    error: "",
    pending: false,
    async submit() {
      this.pending = true;
      this.error = "";
      const response = await fetch("/api/admin/session/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(this.form),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        this.error = data.detail || "登录失败";
        this.pending = false;
        return;
      }
      await window.__appShell.refreshSession();
      window.location.hash = "#/admin/overview";
      this.pending = false;
    },
  };
};

window.adminOverviewPage = function adminOverviewPage() {
  return {
    cards: [],
    async init() {
      const response = await fetch("/api/system/bootstrap");
      const data = await response.json();
      this.cards = [
        { label: "品牌色", value: `${data.brand.primary} / ${data.brand.accent}` },
        { label: "Legacy Bridge", value: data.ui.legacy_path },
        { label: "运行主题", value: data.runtime_config.ui_theme_name },
      ];
    },
  };
};

window.adminJobsPage = function adminJobsPage() {
  return {
    jobs: [],
    async init() {
      await this.refresh();
    },
    async refresh() {
      const session = await fetch("/api/admin/session").then((r) => r.json());
      if (!session.authenticated) {
        this.jobs = [];
        return;
      }
      const response = await fetch("/api/admin/jobs");
      const data = await response.json();
      this.jobs = data.items || [];
    },
    async enqueue(kind) {
      await fetch("/api/admin/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind }),
      });
      await this.refresh();
    },
  };
};

window.publicEntryPage = function publicEntryPage() {
  return {
    flows: [],
    async init() {
      const response = await fetch("/api/public/bootstrap");
      const data = await response.json();
      this.flows = data.flows || [];
    },
  };
};
