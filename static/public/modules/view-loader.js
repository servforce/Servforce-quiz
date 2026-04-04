import { clearFragmentMount, loadHtmlFragment, queueMathTypeset } from "/static/assets/js/shared/runtime.js";

export const PUBLIC_VIEW_FRAGMENTS = {
  unavailable: "/static/public/views/unavailable.html",
  start: "/static/public/views/start.html",
  resume: "/static/public/views/resume.html",
  question: "/static/public/views/question.html",
  done: "/static/public/views/done.html",
};

export function createPublicViewLoaderModule() {
  return {
    currentPublicViewFragment() {
      return PUBLIC_VIEW_FRAGMENTS[String(this.viewCard || "").trim()] || PUBLIC_VIEW_FRAGMENTS.unavailable;
    },

    async renderCurrentView() {
      const mount = this.$refs?.viewMount;
      await loadHtmlFragment({
        mount,
        path: this.currentPublicViewFragment(),
        cache: this.fragmentCache,
        alpine: window.Alpine,
      });
    },

    clearRenderedView() {
      clearFragmentMount(this.$refs?.viewMount, window.Alpine);
    },

    queueMathTypeset(root = null) {
      queueMathTypeset(root instanceof Element ? root : this.$root);
    },
  };
}
