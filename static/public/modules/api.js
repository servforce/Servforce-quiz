import { SESSION_HEADER } from "./constants.js";

export function createPublicApiModule() {
  return {
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
  };
}
