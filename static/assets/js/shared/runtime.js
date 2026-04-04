export async function loadHtmlFragment({ mount, path, cache = {}, alpine = globalThis.Alpine } = {}) {
  if (!(mount instanceof HTMLElement) || !path) {
    return;
  }
  let html = cache[path];
  if (typeof html !== "string") {
    const response = await fetch(path, { credentials: "same-origin" });
    if (!response.ok) {
      throw new Error(`片段加载失败: ${path}`);
    }
    html = await response.text();
    cache[path] = html;
  }
  mutateFragmentDom(alpine, () => {
    destroyFragmentChildren(mount, alpine);
    mount.innerHTML = html;
    mount.dataset.fragmentPath = path;
    initFragmentChildren(mount, alpine);
  });
}

export function clearFragmentMount(mount, alpine = globalThis.Alpine) {
  if (!(mount instanceof HTMLElement)) {
    return;
  }
  mutateFragmentDom(alpine, () => {
    destroyFragmentChildren(mount, alpine);
    mount.innerHTML = "";
    delete mount.dataset.fragmentPath;
  });
}

function mutateFragmentDom(alpine, callback) {
  if (typeof callback !== "function") {
    return;
  }
  if (typeof alpine?.mutateDom === "function") {
    alpine.mutateDom(callback);
    return;
  }
  callback();
}

function destroyFragmentChildren(mount, alpine) {
  if (!(mount instanceof HTMLElement) || typeof alpine?.destroyTree !== "function") {
    return;
  }
  for (const child of Array.from(mount.children)) {
    alpine.destroyTree(child);
  }
}

function initFragmentChildren(mount, alpine) {
  if (!(mount instanceof HTMLElement) || typeof alpine?.initTree !== "function") {
    return;
  }
  mount._x_ignoreSelf = true;
  alpine.initTree(mount);
  delete mount._x_ignoreSelf;
}

export function queueMathTypeset(root = null) {
  const target = root instanceof Element ? root : document.body;
  if (target && typeof globalThis.mdQuizQueueMathTypeset === "function") {
    globalThis.mdQuizQueueMathTypeset(target);
  }
}

export async function copyTextToClipboard(value) {
  const text = String(value || "").trim();
  if (!text) {
    return false;
  }
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return true;
  }
  const input = document.createElement("textarea");
  input.value = text;
  input.setAttribute("readonly", "readonly");
  input.style.position = "fixed";
  input.style.opacity = "0";
  document.body.appendChild(input);
  input.select();
  input.setSelectionRange(0, input.value.length);
  const ok = document.execCommand("copy");
  document.body.removeChild(input);
  if (!ok) {
    throw new Error("复制失败，请手动复制");
  }
  return true;
}

export function absoluteUrl(value) {
  const text = String(value || "").trim();
  if (!text) {
    return "";
  }
  if (/^https?:\/\//i.test(text)) {
    return text;
  }
  if (typeof window === "undefined") {
    return text;
  }
  return `${window.location.origin}${text.startsWith("/") ? text : `/${text}`}`;
}
