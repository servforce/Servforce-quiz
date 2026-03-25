(() => {
  const examQ = document.getElementById("exam_q");

  if (examQ && examQ.form) {
    let timer = null;
    examQ.addEventListener("input", () => {
      if (timer) window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        const form = examQ.form;
        if (form && typeof form.submit === "function") form.submit();
      }, 250);
    });
  }

  for (const tr of document.querySelectorAll("tr[data-href]")) {
    tr.addEventListener("click", (ev) => {
      const el = ev.target;
      if (el && (el.closest("a") || el.closest("button") || el.closest("form"))) return;
      const href = tr.getAttribute("data-href");
      if (href) window.location.href = href;
    });
  }
})();
