(() => {
  const pendingRoots = new Set();
  let scheduled = false;

  const isElement = (value) => typeof Element !== "undefined" && value instanceof Element;

  const getMathJax = () => {
    if (!window.MathJax || typeof window.MathJax.typesetPromise !== "function") {
      return null;
    }
    return window.MathJax;
  };

  const flushTypeset = () => {
    scheduled = false;
    const mathjax = getMathJax();
    if (!mathjax) {
      return;
    }
    const roots = Array.from(pendingRoots).filter((root) => isElement(root) && root.isConnected);
    pendingRoots.clear();
    if (!roots.length) {
      return;
    }
    if (typeof mathjax.typesetClear === "function") {
      mathjax.typesetClear(roots);
    }
    mathjax.typesetPromise(roots).catch((error) => {
      console.error("MathJax typeset failed", error);
    });
  };

  const scheduleFlush = () => {
    if (scheduled) {
      return;
    }
    scheduled = true;
    const enqueue = typeof window.requestAnimationFrame === "function"
      ? window.requestAnimationFrame.bind(window)
      : (callback) => window.setTimeout(callback, 16);
    enqueue(flushTypeset);
  };

  window.mdQuizQueueMathTypeset = (root) => {
    pendingRoots.add(isElement(root) ? root : document.body);
    scheduleFlush();
  };

  window.MathJax = {
    tex: {
      inlineMath: [["$", "$"], ["\\(", "\\)"]],
      displayMath: [["$$", "$$"], ["\\[", "\\]"]],
      processEscapes: true,
    },
    svg: {
      fontCache: "global",
    },
    startup: {
      typeset: false,
      ready() {
        window.MathJax.startup.defaultReady();
        window.mdQuizQueueMathTypeset(document.body);
      },
    },
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      window.mdQuizQueueMathTypeset(document.body);
    }, { once: true });
  } else {
    window.mdQuizQueueMathTypeset(document.body);
  }
})();
