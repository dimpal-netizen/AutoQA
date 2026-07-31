/* AutoQA browser recorder — a stand-in for the Phase 9 Chrome extension.
 *
 * Paste into the DevTools console of any page:
 *     await import("http://localhost:3000/recorder.js")
 *
 * It captures real interactions, builds ranked selectors exactly the way the
 * extension will, and uploads them to the backend in batches. The point is to
 * prove the selector engine works on real HTML before committing to it.
 *
 * Not covered here (the real extension will handle these): iframes, shadow DOM,
 * and surviving a full page navigation — a console script dies on reload.
 */
(() => {
  const API = window.__AUTOQA_API__ || "http://localhost:8000/api/v1";
  const AUTH_KEY = "autoqa-auth";
  const BATCH_MS = 2000;
  const HOVER_DWELL_MS = 700;
  const SCROLL_QUIET_MS = 400;
  const PANEL_ID = "__autoqa_recorder_panel__";

  if (window.__autoqaRecorder) {
    console.warn("[AutoQA] Recorder already running. Stop it first.");
    return;
  }

  // ==== selector engine ===================================================
  // Ranking must match backend/app/models/enums.py SELECTOR_RANK.

  // ids like ":r3:", "ember1234", "mui-42", or a long hash change on every
  // build, so they are worthless in a test. Treat them as unusable.
  const GENERATED_ID = [
    /^:.+:$/,
    /^(ember|mui|radix|headless|react|ui|aria)-?\d/i,
    /[0-9a-f]{8,}/i,
    /^\d/,
    /^[a-z]+_[a-z0-9]{6,}$/i,
  ];

  const isGeneratedId = (id) => !id || GENERATED_ID.some((re) => re.test(id));

  const cssEscape = (v) =>
    window.CSS && CSS.escape ? CSS.escape(v) : String(v).replace(/["\\]/g, "\\$&");

  const countMatches = (selector) => {
    try {
      return document.querySelectorAll(selector).length;
    } catch {
      return 0;
    }
  };

  const IMPLICIT_ROLE = {
    a: (el) => (el.hasAttribute("href") ? "link" : null),
    button: () => "button",
    select: () => "combobox",
    textarea: () => "textbox",
    h1: () => "heading",
    h2: () => "heading",
    h3: () => "heading",
    nav: () => "navigation",
    img: () => "img",
    input: (el) => {
      const t = (el.getAttribute("type") || "text").toLowerCase();
      if (t === "checkbox") return "checkbox";
      if (t === "radio") return "radio";
      if (["submit", "button", "reset"].includes(t)) return "button";
      if (t === "file") return null;
      return "textbox";
    },
  };

  function roleOf(el) {
    const explicit = el.getAttribute("role");
    if (explicit) return explicit.trim().split(/\s+/)[0];
    const fn = IMPLICIT_ROLE[el.tagName.toLowerCase()];
    return fn ? fn(el) : null;
  }

  function labelText(el) {
    if (el.id && !isGeneratedId(el.id)) {
      const forLabel = document.querySelector(`label[for="${cssEscape(el.id)}"]`);
      if (forLabel?.textContent?.trim()) return forLabel.textContent.trim();
    }
    const wrapping = el.closest("label");
    if (wrapping) {
      // Strip the control's own text so "Remember me" doesn't become "Remember me on".
      const clone = wrapping.cloneNode(true);
      clone.querySelectorAll("input, select, textarea").forEach((n) => n.remove());
      const text = clone.textContent?.trim();
      if (text) return text;
    }
    const labelledBy = el.getAttribute("aria-labelledby");
    if (labelledBy) {
      const target = document.getElementById(labelledBy);
      if (target?.textContent?.trim()) return target.textContent.trim();
    }
    return null;
  }

  function accessibleName(el) {
    const ariaLabel = el.getAttribute("aria-label");
    if (ariaLabel?.trim()) return ariaLabel.trim();
    const label = labelText(el);
    if (label) return label;
    if (el.tagName === "IMG") return el.getAttribute("alt")?.trim() || null;
    const text = visibleText(el);
    return text || null;
  }

  function visibleText(el) {
    const text = (el.textContent || "").replace(/\s+/g, " ").trim();
    return text && text.length <= 120 ? text : null;
  }

  function cssPath(el) {
    // Walk up until a stable ancestor, so the selector is scoped but not absolute.
    const parts = [];
    let node = el;
    for (let depth = 0; node && node.nodeType === 1 && depth < 5; depth++) {
      const tag = node.tagName.toLowerCase();
      if (node.id && !isGeneratedId(node.id)) {
        parts.unshift(`#${cssEscape(node.id)}`);
        break;
      }
      const classes = Array.from(node.classList)
        .filter((c) => !isGeneratedId(c) && c.length < 32)
        .slice(0, 2)
        .map((c) => `.${cssEscape(c)}`)
        .join("");
      const type = node.getAttribute?.("type");
      parts.unshift(tag + classes + (tag === "input" && type ? `[type="${type}"]` : ""));
      node = node.parentElement;
    }
    return parts.join(" ");
  }

  function nthChildPath(el) {
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && node !== document.body) {
      const parent = node.parentElement;
      if (!parent) break;
      const index = Array.from(parent.children).indexOf(node) + 1;
      parts.unshift(`${node.tagName.toLowerCase()}:nth-child(${index})`);
      node = parent;
    }
    return `body > ${parts.join(" > ")}`;
  }

  function xPath(el) {
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && node !== document.body) {
      const parent = node.parentElement;
      if (!parent) break;
      const siblings = Array.from(parent.children).filter((c) => c.tagName === node.tagName);
      const index = siblings.indexOf(node) + 1;
      parts.unshift(`${node.tagName.toLowerCase()}[${index}]`);
      node = parent;
    }
    return `//body/${parts.join("/")}`;
  }

  /** Ranked candidates for one element, best first. */
  function buildSelectors(el) {
    const out = [];
    const push = (strategy, value, matchCount, score) => {
      if (!value) return;
      out.push({ strategy, value, unique: matchCount === 1, score });
    };

    const testId =
      el.getAttribute("data-testid") ||
      el.getAttribute("data-test-id") ||
      el.getAttribute("data-test") ||
      el.getAttribute("data-cy");
    if (testId) {
      push("test_id", testId, countMatches(`[data-testid="${cssEscape(testId)}"]`), 99);
    }

    const role = roleOf(el);
    const name = accessibleName(el);
    if (role && name) push("role_name", `${role}|${name}`, 1, 95);

    const label = labelText(el);
    if (label) push("label", label, 1, 90);

    const placeholder = el.getAttribute("placeholder");
    if (placeholder) {
      push(
        "placeholder",
        placeholder,
        countMatches(`[placeholder="${cssEscape(placeholder)}"]`),
        84
      );
    }

    const text = visibleText(el);
    if (text && text.length <= 60) push("text", text, 1, 78);

    if (el.id && !isGeneratedId(el.id)) {
      push("css_id", `#${cssEscape(el.id)}`, countMatches(`#${cssEscape(el.id)}`), 70);
    }

    const css = cssPath(el);
    if (css) push("css", css, countMatches(css), 55);

    push("xpath", xPath(el), 1, 35);
    push("nth_child", nthChildPath(el), 1, 15);

    // The backend re-sorts anyway; sorting here keeps the panel readable.
    const RANK = {
      test_id: 1, role_name: 2, label: 3, placeholder: 4,
      text: 5, css_id: 6, css: 7, xpath: 8, nth_child: 9,
    };
    return out.sort((a, b) => RANK[a.strategy] - RANK[b.strategy] || b.score - a.score);
  }

  function describeElement(el) {
    const attributes = {};
    for (const attr of ["id", "name", "class", "type", "href", "data-testid", "placeholder"]) {
      const v = el.getAttribute?.(attr);
      if (v) attributes[attr] = v.slice(0, 200);
    }
    const box = el.getBoundingClientRect?.();
    return {
      tag: el.tagName.toLowerCase(),
      input_type: el.getAttribute?.("type") || null,
      role: roleOf(el),
      accessible_name: accessibleName(el)?.slice(0, 500) || null,
      text: visibleText(el)?.slice(0, 2000) || null,
      attributes,
      bounding_box: box
        ? { x: +box.x.toFixed(1), y: +box.y.toFixed(1), width: +box.width.toFixed(1), height: +box.height.toFixed(1) }
        : null,
    };
  }

  // ==== recorder state ====================================================
  const state = {
    token: null,
    projectId: null,
    sessionId: null,
    sequence: 0,
    startedAt: 0,
    pending: [],
    uploaded: 0,
    assertMode: false,
    stopped: false,
    lastInput: new Map(),
    // What we last recorded per field. Tab/Enter flush the buffer, and the
    // browser then fires `change` for the same edit — without this the field
    // would be recorded twice.
    recordedValues: new WeakMap(),
    hoverTimer: null,
    lastHovered: null,
    scrollTimer: null,
    lastClick: { el: null, at: 0 },
  };

  const insidePanel = (el) => !!el?.closest?.(`#${PANEL_ID}`);

  function record(actionType, el, payload = {}) {
    if (state.stopped) return;
    if (el && insidePanel(el)) return;

    const needsSelector = ![
      "navigate", "scroll",
    ].includes(actionType);

    const selectors = el ? buildSelectors(el) : [];
    if (needsSelector && actionType !== "key_press" && selectors.length === 0) return;

    state.pending.push({
      sequence: state.sequence++,
      action_type: actionType,
      timestamp_ms: Date.now() - state.startedAt,
      url: location.href,
      frame_path: [],
      selectors,
      element: el ? describeElement(el) : null,
      payload,
    });
    paint();
  }

  // ==== event capture =====================================================
  function onClick(event) {
    const el = event.target;
    if (insidePanel(el)) return;

    if (state.assertMode) {
      event.preventDefault();
      event.stopPropagation();
      const text = visibleText(el);
      record("assert", el, text
        ? { kind: "to_have_text", expected: text }
        : { kind: "to_be_visible", expected: true });
      setAssertMode(false);
      return;
    }

    flushInput(el);

    // A dblclick fires click twice first; collapse those into one double_click.
    const now = Date.now();
    if (state.lastClick.el === el && now - state.lastClick.at < 400) {
      const previous = state.pending[state.pending.length - 1];
      if (previous?.action_type === "click") {
        previous.action_type = "double_click";
        state.lastClick = { el: null, at: 0 };
        paint();
        return;
      }
    }
    state.lastClick = { el, at: now };

    const type = (el.getAttribute?.("type") || "").toLowerCase();
    if (el.tagName === "INPUT" && (type === "checkbox" || type === "radio")) return; // change handles it
    record("click", el);
  }

  function onInput(event) {
    const el = event.target;
    if (insidePanel(el) || !["INPUT", "TEXTAREA"].includes(el.tagName)) return;
    const type = (el.getAttribute("type") || "text").toLowerCase();
    if (["checkbox", "radio", "file"].includes(type)) return;
    // Buffer keystrokes — one fill() per field, not one per character.
    state.lastInput.set(el, el.value);
  }

  /** Record one `input` action per field, ignoring a repeat of the same value. */
  function recordInput(el, value) {
    if (state.recordedValues.get(el) === value) return;
    state.recordedValues.set(el, value);
    record("input", el, { value });
  }

  function flushInput(except) {
    for (const [el, value] of state.lastInput) {
      if (el === except) continue;
      state.lastInput.delete(el);
      if (document.contains(el)) recordInput(el, value);
    }
  }

  function onChange(event) {
    const el = event.target;
    if (insidePanel(el)) return;
    const type = (el.getAttribute?.("type") || "").toLowerCase();

    if (el.tagName === "SELECT") {
      const values = Array.from(el.selectedOptions).map((o) => o.value);
      record("select", el, { values });
    } else if (type === "checkbox" || type === "radio") {
      record(el.checked ? "check" : "uncheck", el);
    } else if (type === "file") {
      const files = Array.from(el.files || []).map((f) => f.name);
      record("upload", el, { files });
    } else if (["INPUT", "TEXTAREA"].includes(el.tagName)) {
      state.lastInput.delete(el);
      recordInput(el, el.value);
    }
  }

  function onKeyDown(event) {
    if (insidePanel(event.target)) return;

    if (event.altKey && event.key.toLowerCase() === "a") {
      event.preventDefault();
      setAssertMode(!state.assertMode);
      return;
    }
    if (event.altKey && event.key.toLowerCase() === "s") {
      event.preventDefault();
      stop();
      return;
    }

    // Printable characters are already captured as `input`; only record keys
    // that mean something on their own.
    const SPECIAL = ["Enter", "Tab", "Escape", "Backspace", "Delete",
                     "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"];
    if (!SPECIAL.includes(event.key)) return;

    if (event.key === "Tab" || event.key === "Enter") flushInput(null);

    const modifiers = ["Control", "Shift", "Alt", "Meta"]
      .filter((m) => event.getModifierState(m));
    record("key_press", event.target, { key: event.key, modifiers });
  }

  function onMouseOver(event) {
    const el = event.target;
    if (insidePanel(el)) return;
    clearTimeout(state.hoverTimer);

    // Only elements that plausibly react to hover, and only after a dwell —
    // otherwise every mouse movement across the page becomes an action.
    const interesting = el.closest?.(
      "a, button, [role='button'], [role='menuitem'], [aria-haspopup], .dropdown, .has-dropdown, [data-hover]"
    );
    if (!interesting || interesting === state.lastHovered) return;

    state.hoverTimer = setTimeout(() => {
      state.lastHovered = interesting;
      record("hover", interesting);
    }, HOVER_DWELL_MS);
  }

  function onDragStart(event) {
    state.dragSource = event.target;
  }

  function onDrop(event) {
    const source = state.dragSource;
    const target = event.target;
    state.dragSource = null;
    if (!source || insidePanel(source) || insidePanel(target)) return;

    const targetSelectors = buildSelectors(target);
    if (!targetSelectors.length) return;
    record("drag_drop", source, { target_selectors: targetSelectors });
  }

  function onScroll() {
    clearTimeout(state.scrollTimer);
    // One action per scroll gesture, recorded when it settles.
    state.scrollTimer = setTimeout(() => {
      record("scroll", null, { x: Math.round(scrollX), y: Math.round(scrollY) });
    }, SCROLL_QUIET_MS);
  }

  function onPopState() {
    record("navigate", null, { url: location.href });
  }

  // Single-page apps change the URL without a load event.
  let lastUrl = location.href;
  const urlWatcher = setInterval(() => {
    if (location.href !== lastUrl) {
      lastUrl = location.href;
      record("navigate", null, { url: location.href });
    }
  }, 400);

  // ==== upload ============================================================
  async function api(path, body, method = "POST") {
    const response = await fetch(`${API}${path}`, {
      method,
      headers: {
        "Content-Type": "application/json",
        ...(state.token ? { Authorization: `Bearer ${state.token}` } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await response.text();
    if (!response.ok) throw new Error(`${response.status} ${path}: ${text}`);
    return text ? JSON.parse(text) : {};
  }

  async function flush() {
    if (state.stopped || !state.pending.length || !state.sessionId) return;
    const batch = state.pending.splice(0, state.pending.length);
    try {
      const result = await api(`/recordings/${state.sessionId}/actions`, { actions: batch });
      state.uploaded = result.action_count;
      paint();
    } catch (error) {
      // Put them back and retry on the next tick — upload is idempotent, so a
      // partially-applied batch cannot duplicate.
      state.pending.unshift(...batch);
      console.warn("[AutoQA] upload failed, will retry:", error.message);
    }
  }

  const uploadTimer = setInterval(flush, BATCH_MS);

  // ==== panel =============================================================
  function paint() {
    const panel = document.getElementById(PANEL_ID);
    if (!panel) return;
    panel.querySelector("[data-count]").textContent = String(state.sequence);
    panel.querySelector("[data-uploaded]").textContent = String(state.uploaded);
    const last = state.pending[state.pending.length - 1];
    panel.querySelector("[data-last]").textContent = last
      ? `${last.action_type} → ${last.selectors[0]?.strategy ?? "page"}`
      : "…";
    const assertBtn = panel.querySelector("[data-assert]");
    assertBtn.textContent = state.assertMode ? "Assert: CLICK TARGET" : "Assert (Alt+A)";
    assertBtn.style.background = state.assertMode ? "#f59e0b" : "#334155";
  }

  function setAssertMode(on) {
    state.assertMode = on;
    document.body.style.cursor = on ? "crosshair" : "";
    paint();
  }

  function buildPanel() {
    const panel = document.createElement("div");
    panel.id = PANEL_ID;
    panel.style.cssText = `
      position:fixed;bottom:16px;right:16px;z-index:2147483647;
      font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;
      background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:10px;
      padding:12px 14px;min-width:230px;box-shadow:0 8px 24px rgba(0,0,0,.4)`;
    panel.innerHTML = `
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
        <span style="width:8px;height:8px;border-radius:50%;background:#ef4444;
                     animation:autoqaPulse 1.2s infinite"></span>
        <strong style="color:#f8fafc">AutoQA recording</strong>
      </div>
      <div>captured <b data-count style="color:#38bdf8">0</b> ·
           uploaded <b data-uploaded style="color:#4ade80">0</b></div>
      <div style="color:#94a3b8;margin:4px 0 10px" data-last>…</div>
      <div style="display:flex;gap:6px">
        <button data-assert style="flex:1;background:#334155;color:#e2e8f0;border:0;
                border-radius:6px;padding:6px;cursor:pointer;font:inherit">Assert (Alt+A)</button>
        <button data-stop style="background:#dc2626;color:#fff;border:0;border-radius:6px;
                padding:6px 10px;cursor:pointer;font:inherit">Stop</button>
      </div>
      <style>@keyframes autoqaPulse{50%{opacity:.25}}</style>`;
    panel.querySelector("[data-stop]").addEventListener("click", stop);
    panel.querySelector("[data-assert]").addEventListener("click", () =>
      setAssertMode(!state.assertMode)
    );
    document.body.appendChild(panel);
  }

  // ==== lifecycle =========================================================
  // `true` = capture phase, so we see events even if the page stops propagation.
  const LISTENERS = [
    ["click", onClick, true],
    ["input", onInput, true],
    ["change", onChange, true],
    ["keydown", onKeyDown, true],
    ["mouseover", onMouseOver, true],
    ["dragstart", onDragStart, true],
    ["drop", onDrop, true],
    ["scroll", onScroll, true],
    ["popstate", onPopState, true],
  ];

  async function stop() {
    if (state.stopped) return;
    state.stopped = true;

    clearInterval(uploadTimer);
    clearInterval(urlWatcher);
    clearTimeout(state.hoverTimer);
    clearTimeout(state.scrollTimer);
    LISTENERS.forEach(([type, fn, capture]) =>
      document.removeEventListener(type, fn, capture)
    );
    document.body.style.cursor = "";

    state.stopped = false;      // let the final flush through
    flushInput(null);
    await flush();
    state.stopped = true;

    try {
      const session = await api(`/recordings/${state.sessionId}/stop`, {
        duration_ms: Date.now() - state.startedAt,
      });
      console.log(
        `%c[AutoQA] Recorded ${session.action_count} actions in ${session.duration_ms}ms`,
        "color:#4ade80;font-weight:bold"
      );
      console.log(`View it: http://localhost:3000/recordings/${state.sessionId}`);
    } catch (error) {
      console.error("[AutoQA] stop failed:", error.message);
    }

    document.getElementById(PANEL_ID)?.remove();
    delete window.__autoqaRecorder;
  }

  function readToken() {
    try {
      const raw = localStorage.getItem(AUTH_KEY);
      return raw ? JSON.parse(raw)?.state?.accessToken ?? null : null;
    } catch {
      return null;
    }
  }

  async function start() {
    state.token = window.__AUTOQA_TOKEN__ || readToken();
    if (!state.token) {
      console.error(
        "[AutoQA] No access token. Sign in at http://localhost:3000 first, or set " +
          "window.__AUTOQA_TOKEN__ = '<token>' before importing on a third-party site."
      );
      return;
    }

    const projects = await api("/projects", undefined, "GET");
    if (!projects.length) {
      console.error("[AutoQA] No projects yet — create one at http://localhost:3000/projects");
      return;
    }
    state.projectId = window.__AUTOQA_PROJECT_ID__ || projects[0].id;
    const project = projects.find((p) => p.id === state.projectId) || projects[0];

    const name =
      window.__AUTOQA_NAME__ ||
      `Console recording ${new Date().toLocaleTimeString()}`;

    const session = await api(`/projects/${state.projectId}/recordings`, {
      name,
      start_url: location.href,
      extension_version: "console-0.1.0",
      browser_info: {
        user_agent: navigator.userAgent,
        viewport: { width: innerWidth, height: innerHeight },
        device_pixel_ratio: devicePixelRatio,
        platform: navigator.platform,
      },
    });

    state.sessionId = session.id;
    state.startedAt = Date.now();
    record("navigate", null, { url: location.href });

    LISTENERS.forEach(([type, fn, capture]) =>
      document.addEventListener(type, fn, capture)
    );
    buildPanel();
    paint();

    console.log(
      `%c[AutoQA] Recording #${session.id} into "${project.name}"`,
      "color:#38bdf8;font-weight:bold"
    );
    console.log("Interact with the page. Alt+A asserts an element, Alt+S stops.");
  }

  window.__autoqaRecorder = { stop, state };
  start().catch((error) => console.error("[AutoQA]", error));
})();
