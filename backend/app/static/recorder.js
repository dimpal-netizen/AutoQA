/* AutoQA browser recorder.
 *
 * Runs in two modes:
 *
 * BRIDGE — the backend launches a real browser with Playwright and injects
 *   this file into every page. Actions go back through a Playwright binding
 *   (window.__autoqaBridge), so there is no cross-origin request and no token
 *   in the page. This is the mode that records an arbitrary URL, and because
 *   Playwright re-injects on every navigation, it survives page loads.
 *
 * FETCH — loaded by our own web app on its own origin, talking to the API
 *   directly. Used by the demo page.
 *
 * API: start(options) · pause() · resume() · stop() · getState() · subscribe(fn)
 *
 * Still not covered: shadow DOM, and cross-origin iframes in fetch mode.
 */
(() => {
  if (window.AutoQARecorder) return; // already loaded

  // Set by the backend via add_init_script before this file runs.
  const bridge = window.__autoqaBridge || null;
  const injected = window.__autoqaConfig || null;

  const API = window.__AUTOQA_API__ || "http://localhost:8000/api/v1";
  const AUTH_KEY = "autoqa-auth";
  const BATCH_MS = 2000;
  const HOVER_DWELL_MS = 700;
  const SCROLL_QUIET_MS = 400;
  const PANEL_ID = "__autoqa_recorder_panel__";

  /* Are we the page somebody is recording, or something embedded in it?
   *
   * The script is injected into every document in the browser, which is what
   * lets an action inside a payment or consent frame be captured at all. It
   * also means a page carrying ten embedded video players runs eleven
   * recorders: eleven handshakes, eleven blocks of sequence numbers, eleven
   * sets of timers, eleven panels - and eleven callers competing over the one
   * channel back to the backend. Observed on a real account page, where the
   * page's own recorder was crowded out by ten video players nobody touched and
   * the recording stopped growing.
   *
   * Reading `window.top` across an origin boundary throws, and a frame that
   * cannot see the top of the window is certainly not the top of it. */
  const isTop = (() => {
    try {
      return window.top === window;
    } catch {
      return false;
    }
  })();

  /* How long to wait before asking what the application said back.
   *
   * A recording of what somebody did is only half of what happened. The other
   * half is the application's answer - it navigated, or it put a message on the
   * screen - and without it every recorded value looks equally permanent. The
   * generator cannot tell an address that must be new each run from one that
   * must already exist, because from a list of clicks and keystrokes the two are
   * identical. The answer is the thing that tells them apart, and it is only
   * knowable here, at the moment it arrives.
   *
   * Long enough for a round trip to have rendered, short enough to be attached
   * before the batch goes up. Best-effort throughout: a click that navigates
   * unloads the page before this fires and the field is simply absent, which is
   * exactly how a recorder written before this behaves, and what every consumer
   * of it must go on handling. */
  const RESPONSE_MS = 900;

  /* Actions younger than this are held back by `flush`, so the answer above has
   * somewhere to be attached to. One extra tick of latency on the most recent
   * action, and nothing else changes. */
  const SETTLE_MS = 1200;

  /* Where applications put the sentence they want you to read. Deliberately
   * about the *shape* of a message and never about what it says: an alert role,
   * a live region, a class with error or message in it. Reading which of them
   * is a refusal happens later and elsewhere - here we only collect. */
  const MESSAGE_SELECTOR = [
    "[role=alert]", "[role=status]", "[aria-live]", "[aria-invalid=true]",
    "[class*=error]", "[class*=Error]", "[class*=alert]", "[class*=Alert]",
    "[class*=message]", "[class*=Message]", "[class*=toast]", "[class*=Toast]",
    "[class*=notification]", "[class*=warning]", "[class*=invalid]",
    "[id*=error]", "[id*=message]",
  ].join(",");

  const MAX_MESSAGES = 12;
  const MAX_MESSAGE_CHARS = 300;

  /* Elements that are a dialog by declaration rather than by looking like one.
   * The ARIA roles and the HTML element, nothing else - a class called "modal"
   * is on half the pages on the internet whether anything is open or not. */
  const DIALOG_SELECTOR = "dialog[open],[role=dialog],[role=alertdialog]";

  /* A DOM that has stopped changing. Two polls at the same mutation count is
   * enough: the point is not to measure the page, only to notice that it has
   * finished doing whatever the click set off. */
  const QUIET_MS = 250;

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

  /* Uniqueness for the text-based strategies.
   *
   * These used to be hardcoded to 1 - claimed unique without ever looking -
   * which is how a recording ends up asserting that `get_by_role("link",
   * name="Home")` matches one element on a site with five of them. The test
   * then dies on a strict mode violation the first time it runs, and the
   * recording looked perfect right up until then.
   *
   * Playwright's real matcher walks the accessibility tree; this is an
   * approximation of it. Being approximately right is the whole point: an
   * over-count costs us a slightly worse selector, an under-count costs a
   * broken test.
   *
   * Stops at two matches - "more than one" is the only question being asked -
   * and caps the scan so a huge page cannot stall the recorder mid-click. */
  const SCAN_LIMIT = 5000;

  function countMatching(predicate) {
    const all = document.querySelectorAll("*");
    let seen = 0;
    let found = 0;
    for (const el of all) {
      if (++seen > SCAN_LIMIT) break;
      try {
        if (predicate(el)) {
          if (++found > 1) return found;  // two is enough to know
        }
      } catch {
        /* one hostile element must not abort the count */
      }
    }
    return found;
  }

  const countByRoleName = (role, name) =>
    countMatching((el) => roleOf(el) === role && accessibleName(el) === name);

  const countByText = (text) => countMatching((el) => visibleText(el) === text);

  const countByLabel = (label) => countMatching((el) => labelText(el) === label);

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
    const explicit = el.getAttribute?.("role");
    if (explicit) return explicit.trim().split(/\s+/)[0];
    const fn = IMPLICIT_ROLE[el.tagName?.toLowerCase()];
    return fn ? fn(el) : null;
  }

  function labelText(el) {
    if (el.id && !isGeneratedId(el.id)) {
      const forLabel = document.querySelector(`label[for="${cssEscape(el.id)}"]`);
      if (forLabel?.textContent?.trim()) return forLabel.textContent.trim();
    }
    const wrapping = el.closest?.("label");
    if (wrapping) {
      // Strip the control's own text so "Remember me" doesn't become "Remember me on".
      const clone = wrapping.cloneNode(true);
      clone.querySelectorAll("input, select, textarea").forEach((n) => n.remove());
      const text = clone.textContent?.trim();
      if (text) return text;
    }
    const labelledBy = el.getAttribute?.("aria-labelledby");
    if (labelledBy) {
      const target = document.getElementById(labelledBy);
      if (target?.textContent?.trim()) return target.textContent.trim();
    }
    return null;
  }

  function visibleText(el) {
    const text = (el.textContent || "").replace(/\s+/g, " ").trim();
    return text && text.length <= 120 ? text : null;
  }

  function accessibleName(el) {
    const ariaLabel = el.getAttribute?.("aria-label");
    if (ariaLabel?.trim()) return ariaLabel.trim();
    const label = labelText(el);
    if (label) return label;
    if (el.tagName === "IMG") return el.getAttribute("alt")?.trim() || null;
    return visibleText(el);
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
      parts.unshift(`${node.tagName.toLowerCase()}[${siblings.indexOf(node) + 1}]`);
      node = parent;
    }
    return `//body/${parts.join("/")}`;
  }

  const RANK = {
    test_id: 1, role_name: 2, label: 3, placeholder: 4,
    text: 5, css_id: 6, css: 7, xpath: 8, nth_child: 9,
  };

  /** Ranked candidates for one element, best first. */
  function buildSelectors(el) {
    const out = [];
    const push = (strategy, value, matchCount, score) => {
      if (!value) return;
      out.push({ strategy, value, unique: matchCount === 1, score });
    };

    const testId =
      el.getAttribute?.("data-testid") ||
      el.getAttribute?.("data-test-id") ||
      el.getAttribute?.("data-test") ||
      el.getAttribute?.("data-cy");
    if (testId) {
      push("test_id", testId, countMatches(`[data-testid="${cssEscape(testId)}"]`), 99);
    }

    const role = roleOf(el);
    const name = accessibleName(el);
    if (role && name) push("role_name", `${role}|${name}`, countByRoleName(role, name), 95);

    const label = labelText(el);
    if (label) push("label", label, countByLabel(label), 90);

    const placeholder = el.getAttribute?.("placeholder");
    if (placeholder) {
      push("placeholder", placeholder,
        countMatches(`[placeholder="${cssEscape(placeholder)}"]`), 84);
    }

    const text = visibleText(el);
    if (text && text.length <= 60) push("text", text, countByText(text), 78);

    if (el.id && !isGeneratedId(el.id)) {
      push("css_id", `#${cssEscape(el.id)}`, countMatches(`#${cssEscape(el.id)}`), 70);
    }

    const css = cssPath(el);
    if (css) push("css", css, countMatches(css), 55);

    // These two are unique by construction - an absolute path addresses one
    // node - so 1 here is a fact, not the assumption it was for the others.
    push("xpath", xPath(el), 1, 35);
    push("nth_child", nthChildPath(el), 1, 15);

    // The backend re-sorts anyway; sorting here keeps the panel readable.
    return out.sort((a, b) => RANK[a.strategy] - RANK[b.strategy] || b.score - a.score);
  }

  /* What the page is saying right now, as a list of sentences.
   *
   * Collected before an action and again after it, so that only what *appeared*
   * is reported. A form that already shows "Required" on three fields would
   * otherwise report them as the answer to every keystroke after it. */
  function messagesOnScreen() {
    const seen = new Set();
    try {
      for (const el of document.querySelectorAll(MESSAGE_SELECTOR)) {
        const text = (el.innerText || "").trim().replace(/\s+/g, " ");
        if (!text || text.length > MAX_MESSAGE_CHARS) continue;
        seen.add(text);
        if (seen.size >= MAX_MESSAGES) break;
      }
    } catch {
      /* A selector the browser dislikes is not worth failing a recording for. */
    }
    return seen;
  }

  /* How much the page has changed since the recorder started watching.
   *
   * One observer for the whole document, started once, counting. Comparing a
   * count before an action with the count after it says whether the click did
   * anything at all - which is the difference between an outcome worth waiting
   * for and one there is nothing to wait for. */
  let mutations = 0;
  let watcher = null;

  function watchMutations() {
    if (watcher || typeof MutationObserver !== "function") return;
    try {
      watcher = new MutationObserver((records) => { mutations += records.length; });
      watcher.observe(document.documentElement, {
        childList: true, subtree: true, attributes: true, characterData: true,
      });
    } catch {
      watcher = null;   /* An observer we cannot start is one outcome we cannot see. */
    }
  }

  function dialogsOpen() {
    try {
      return Array.from(document.querySelectorAll(DIALOG_SELECTOR))
        .filter((el) => {
          const box = el.getBoundingClientRect?.();
          return box && box.width > 0 && box.height > 0;
        }).length;
    } catch {
      return 0;
    }
  }

  /* Everything about the page an action could change, as one small object.
   * Taken before the action and again after it; the difference is the outcome.
   *
   * `pageSnapshot`, not `snapshot`: this file already had a `snapshot()`, which
   * returns the recorder's own status for the panel and for subscribers. Two
   * declarations of the same name in one scope, and the later one wins - so
   * `record` was handing the recorder's status to the outcome comparison, which
   * threw on every single action and left every outcome unrecorded. */
  function pageSnapshot() {
    return {
      url: location.href,
      title: document.title || "",
      mutations,
      dialogs: dialogsOpen(),
      messages: messagesOnScreen(),
    };
  }

  /* What actually happened, in the vocabulary the generator waits on.
   *
   * Ordered by how specific the answer is, because a click that navigates also
   * mutates the DOM and a modal that opens also changes the message count -
   * so the most decisive observation wins and the rest are recorded as detail.
   * `quiet` is a real answer and not a failure to find one: plenty of actions
   * genuinely change nothing a browser can see, and a test that insists on
   * waiting for something is a test that waits for ever. */
  function outcomeOf(before, after, startedAt) {
    const appeared = [...after.messages].filter((text) => !before.messages.has(text));
    const detail = {
      url: after.url,
      navigated: after.url !== before.url,
      title_changed: after.title !== before.title,
      dialog_opened: after.dialogs > before.dialogs,
      dialog_closed: after.dialogs < before.dialogs,
      mutations: Math.max(0, after.mutations - before.mutations),
      messages: appeared,
      settled_ms: Date.now() - startedAt,
    };

    if (detail.navigated) detail.kind = "navigated";
    else if (detail.dialog_opened) detail.kind = "dialog_opened";
    else if (detail.dialog_closed) detail.kind = "dialog_closed";
    else if (appeared.length) detail.kind = "messages";
    else if (detail.mutations > 0 || detail.title_changed) detail.kind = "dom_changed";
    else detail.kind = "quiet";

    return detail;
  }

  function describeElement(el, wasOnScreen) {
    const attributes = {};
    // The last five say what the *field* requires, which is the deterministic
    // half of deciding whether a recorded value can be replayed as it stands.
    // See `dataroles.py`: a field carrying autocomplete="email" is describing
    // itself, and describing itself in a way that is the same on every site.
    for (const attr of [
      "id", "name", "class", "type", "href", "data-testid", "placeholder",
      "autocomplete", "pattern", "required", "maxlength", "minlength",
    ]) {
      const v = el.getAttribute?.(attr);
      if (v) attributes[attr] = String(v).slice(0, 200);
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
        ? { x: +box.x.toFixed(1), y: +box.y.toFixed(1),
            width: +box.width.toFixed(1), height: +box.height.toFixed(1) }
        : null,
      // False means the previous step revealed this - see `wasOnScreen`.
      was_on_screen: wasOnScreen !== false,
    };
  }

  // ==== state =============================================================
  const IDLE = "idle", RECORDING = "recording", PAUSED = "paused", STOPPING = "stopping";

  let state = null;
  const listeners = new Set();

  function freshState() {
    return {
      status: IDLE,
      token: null,
      projectId: null,
      projectName: null,
      sessionId: null,
      sessionName: null,
      sequence: 0,
      /* How many actions this recording has captured, which is no longer the
       * same thing as the next sequence number.
       *
       * They were one field until pages started being given their own block of
       * sequence numbers, so that two live pages could not hand out the same
       * one. The panel then read "captured 200001" after two clicks - a true
       * statement about a number nobody wanted, in the place where somebody
       * was looking for a count. */
      captured: 0,
      startedAt: 0,
      pausedAt: 0,
      pausedMs: 0,     // subtracted from timestamps so a pause is not a giant wait
      pending: [],
      uploaded: 0,
      assertMode: false,
      showPanel: true,
      error: null,
      lastAction: null,
      lastInput: new Map(),
      // What we last recorded per field. Tab/Enter flush the buffer, and the
      // browser then fires `change` for the same edit — without this the field
      // would be recorded twice.
      recordedValues: new WeakMap(),
      // What a person could act on when we last looked, and where. See
      // `wasOnScreen`.
      onScreen: null,
      onScreenUrl: null,
      hoverTimer: null,
      lastHovered: null,
      scrollTimer: null,
      lastClick: { el: null, at: 0 },
      dragSource: null,
      uploadTimer: null,
      urlTimer: null,
    };
  }

  function snapshot() {
    if (!state) return { status: IDLE, captured: 0, uploaded: 0 };
    return {
      status: state.status,
      captured: state.captured,
      uploaded: state.uploaded,
      pending: state.pending.length,
      sessionId: state.sessionId,
      sessionName: state.sessionName,
      projectId: state.projectId,
      projectName: state.projectName,
      assertMode: state.assertMode,
      lastAction: state.lastAction,
      error: state.error,
    };
  }

  function notify() {
    const snap = snapshot();
    listeners.forEach((fn) => {
      try {
        fn(snap);
      } catch (error) {
        console.error("[AutoQA] listener failed:", error);
      }
    });
    // The panel is a convenience; the capture is the point. A page with a
    // Content-Security-Policy that refuses inline styles, or Trusted Types
    // refusing an innerHTML assignment, must cost us the panel and nothing
    // else - and it has to say so, because a panel that quietly stops
    // appearing is exactly the failure nobody can describe afterwards.
    try {
      paint();
    } catch (error) {
      console.error("[AutoQA] panel failed, still recording:", error);
    }
  }

  const insidePanel = (el) =>
    !!el?.closest?.(`#${PANEL_ID}, [data-autoqa-ignore]`);

  const capturing = () => state && state.status === RECORDING;

  /* Every listener goes through here, so nothing a page can do reaches the
   * event loop as an unhandled throw.
   *
   * A recorder that stops part-way through is the worst failure this thing has,
   * because it looks like nothing: the panel is simply not there any more, the
   * session is shorter than the journey, and there is no error anywhere to
   * explain it. One element with a hostile `className` getter, one selector the
   * page's own CSS engine rejects, one property that throws on access - any of
   * them used to be enough, and the cost was the rest of the session.
   *
   * The action being recorded is lost; every action after it is not. And the
   * reason is written to the console with a marker the backend picks up, so a
   * recording that came out short can be explained instead of guessed at. */
  function guard(name, fn) {
    return (...args) => {
      try {
        return fn(...args);
      } catch (error) {
        console.error(`[AutoQA] ${name} failed, still recording:`, error);
        return undefined;
      }
    };
  }

  /* Never throws, and that is load-bearing rather than tidy.
   *
   * `start` records the opening navigation *before* it attaches the listeners
   * and builds the panel. So a page holding one element that throws when asked
   * about itself - a framework proxy, a getter with a side effect, a custom
   * element mid-upgrade - took the whole recorder down with it on that page:
   * no panel, no listeners, nothing captured, and no error anywhere that a
   * person could connect to what they saw. Which is exactly what "the recorder
   * disappeared" looks like from the outside.
   *
   * The action being recorded is lost. Everything after it is not. */
  function record(actionType, el, payload = {}) {
    try {
      capture(actionType, el, payload);
    } catch (error) {
      console.error("[AutoQA] record failed, still recording:", error);
    }
  }

  function capture(actionType, el, payload = {}) {
    if (!capturing()) return;
    if (el && insidePanel(el)) return;

    const selectors = el ? buildSelectors(el) : [];
    const pageLevel = ["navigate", "scroll"].includes(actionType);
    if (!pageLevel && actionType !== "key_press" && selectors.length === 0) return;

    const before = pageSnapshot();
    const startedAt = Date.now();
    const action = {
      // null until this frame has introduced itself; `flush` numbers them
      // from the block it is given. See `join`.
      sequence: state.sessionId ? state.sequence++ : null,
      action_type: actionType,
      timestamp_ms: Date.now() - state.startedAt - state.pausedMs,
      url: location.href,
      frame_path: [],
      selectors,
      element: el ? describeElement(el, wasOnScreen(el)) : null,
      payload,
      // Stripped by `flush`. Only here so the batch knows not to leave without
      // the answer below.
      _recordedAt: Date.now(),
    };
    state.pending.push(action);
    state.captured++;

    // What the application did in reply, attached to the action that provoked
    // it. Never awaited and never allowed to fail: on a click that navigates
    // this does not run at all, and `onPageHide` records the navigation
    // instead. An action with no answer is what every recording made before
    // this looks like, and everything downstream still has to handle it.
    setTimeout(() => {
      try {
        if (action.response) return;   // `onPageHide` already answered
        action.response = outcomeOf(before, pageSnapshot(), startedAt);
      } catch {
        /* Nothing here is worth interrupting a recording for. */
      }
    }, RESPONSE_MS);

    state.lastAction = `${actionType} → ${selectors[0]?.strategy ?? "page"}`;
    state.capturedAt = Date.now();
    rememberWhatIsOnScreen();
    notify();
  }

  /**
   * Was this already on screen before the previous thing the person did?
   *
   * The one fact a recording cannot be made to give up afterwards, and the one
   * that decides whether an invented test case can use the element at all.
   * `home.close_video_button` and `properties.back_to_search` look no different
   * from a nav link in a finished recording - same tag, same good accessible
   * name, both clicked once. But one is on the page when it loads and the other
   * only exists after a video is playing or a property has been opened, so a
   * case that goes straight to it waits thirty seconds and reports a bug in a
   * page that is fine.
   *
   * Nothing has to be inferred: the answer is knowable at the moment of the
   * click, and only then. `false` means the step before this one revealed it.
   */
  function wasOnScreen(el) {
    // A different page than the one we looked at. Everything on it is new, and
    // none of that is evidence about anything, so say nothing. Without this,
    // the first click after every navigation reads as "the last step revealed
    // it" and the element is withheld from test cases for no reason.
    if (!state.onScreen || state.onScreenUrl !== location.href) return true;
    return state.onScreen.has(el);
  }

  /**
   * Snapshot what a person could act on right now.
   *
   * Taken after every recorded action and on every load, so the next action can
   * be compared against the page as it stood before it. A WeakSet holds no node
   * alive, which matters on a single-page app that replaces its DOM constantly.
   */
  function rememberWhatIsOnScreen() {
    if (!state) return;
    const seen = new WeakSet();
    for (const node of document.querySelectorAll(INTERACTIVE)) {
      const box = node.getBoundingClientRect();
      if (box.width > 0 && box.height > 0) seen.add(node);
    }
    state.onScreen = seen;
    state.onScreenUrl = location.href;
  }

  // ==== event capture =====================================================
  function onClick(event) {
    const el = event.target;
    if (!capturing() || insidePanel(el)) return;

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
        state.lastAction = "double_click";
        notify();
        return;
      }
    }
    state.lastClick = { el, at: now };

    const type = (el.getAttribute?.("type") || "").toLowerCase();
    if (el.tagName === "INPUT" && (type === "checkbox" || type === "radio")) return;
    record("click", targetOf(el));
  }

  //: Things a person can operate. A click inside one of these is a click on it.
  const INTERACTIVE = "a, button, summary, label, select, textarea, input, " +
    "[role=button], [role=link], [role=tab], [role=menuitem], [role=option], " +
    "[role=checkbox], [role=radio], [role=switch]";

  /**
   * The element a person would say they clicked.
   *
   * `event.target` is the deepest node under the cursor, which is routinely not
   * the thing anyone means. Clicking the site logo gives you the <svg> inside
   * `<a aria-label="Homeske home">`; clicking a play button gives you the <img>
   * inside the <button>. Neither inner node has a name, so the only way left to
   * describe it is where it sits:
   *
   *     html body header.Navbar-module__Sl14ZG__navbar a...logo svg
   *
   * which is both unreadable and wrong the moment anything above it moves. The
   * <a> and the <button> around them have accessible names, are what the person
   * pressed, and keep working after a redesign.
   *
   * Two passes, in this order:
   *
   *   1. If the node is not something you can operate and has no name of its
   *      own, use the nearest ancestor that is. Four levels: an icon sits one or
   *      two inside its button, while a whole card wrapped in a link is a
   *      different element and should not be swallowed.
   *   2. If what we have still has no size — a marker overlay stretched to zero
   *      height, an <area> in an image map — use the nearest ancestor with one.
   *      Playwright refuses to act on an element nobody can see, and waits the
   *      full thirty seconds before saying so.
   *
   * Neither pass is a guess. The click landed inside both ancestors, so a click
   * on either lands in the same place.
   */
  function targetOf(el) {
    let node = el;

    if (!node.matches?.(INTERACTIVE) && !accessibleName(node)) {
      for (let up = node, depth = 0; up?.nodeType === 1 && depth < 4; depth++) {
        if (up.matches?.(INTERACTIVE)) { node = up; break; }
        up = up.parentElement;
      }
    }

    for (let up = node, depth = 0; up?.nodeType === 1 && depth < 4; depth++) {
      const box = up.getBoundingClientRect?.();
      if (box && box.width > 0 && box.height > 0) return up;
      up = up.parentElement;
    }
    return node;
  }

  function onInput(event) {
    const el = event.target;
    if (!capturing() || insidePanel(el)) return;
    if (!["INPUT", "TEXTAREA"].includes(el.tagName)) return;
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
    if (!state) return;
    for (const [el, value] of state.lastInput) {
      if (el === except) continue;
      state.lastInput.delete(el);
      if (document.contains(el)) recordInput(el, value);
    }
  }

  function onChange(event) {
    const el = event.target;
    if (!capturing() || insidePanel(el)) return;
    const type = (el.getAttribute?.("type") || "").toLowerCase();

    if (el.tagName === "SELECT") {
      record("select", el, { values: Array.from(el.selectedOptions).map((o) => o.value) });
    } else if (type === "checkbox" || type === "radio") {
      record(el.checked ? "check" : "uncheck", el);
    } else if (type === "file") {
      record("upload", el, { files: Array.from(el.files || []).map((f) => f.name) });
    } else if (["INPUT", "TEXTAREA"].includes(el.tagName)) {
      state.lastInput.delete(el);
      recordInput(el, el.value);
    }
  }

  function onKeyDown(event) {
    if (!capturing() || insidePanel(event.target)) return;

    if (event.altKey && event.key.toLowerCase() === "a") {
      event.preventDefault();
      setAssertMode(!state.assertMode);
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
    if (!capturing() || insidePanel(el)) return;
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
    if (capturing()) state.dragSource = event.target;
  }

  function onDrop(event) {
    if (!capturing()) return;
    const source = state.dragSource;
    const target = event.target;
    state.dragSource = null;
    if (!source || insidePanel(source) || insidePanel(target)) return;

    const targetSelectors = buildSelectors(target);
    if (targetSelectors.length) {
      record("drag_drop", source, { target_selectors: targetSelectors });
    }
  }

  function onScroll() {
    if (!capturing()) return;
    clearTimeout(state.scrollTimer);
    // One action per scroll gesture, recorded when it settles.
    state.scrollTimer = setTimeout(() => {
      record("scroll", null, { x: Math.round(scrollX), y: Math.round(scrollY) });
    }, SCROLL_QUIET_MS);
  }

  function onPopState() {
    record("navigate", null, { url: location.href });
  }

  /* The page is going away, and everything still in `pending` goes with it.
   *
   * There was no handler here at all, and the cost was invisible: actions are
   * uploaded on a two-second tick, so a click that navigated took itself and
   * anything else waiting with it out of the recording. The action most likely
   * to be lost was the one that mattered most, and the recording simply came
   * out shorter than the journey - which reads as the tester having done less,
   * not as the recorder having dropped something.
   *
   * It also answers the outcome question for free. An action still waiting to
   * hear back when the page is torn away *navigated* - that is what a
   * navigation looks like from inside the page it leaves. The timer above never
   * gets to run, so this is the only chance to say so.
   *
   * `pagehide` rather than `beforeunload`: it fires for a back/forward cache
   * eviction too, and it does not ask the browser to show a leave-this-page
   * prompt. */
  function onPageHide({ flushOnly = false } = {}) {
    if (!state?.pending?.length) return;
    if (!flushOnly) {
      for (const action of state.pending) {
        if (!action.response) {
          action.response = {
            url: location.href, navigated: true, kind: "navigated", messages: [],
          };
        }
      }
    }
    // The dispatch is what matters, not the reply: the binding call is on its
    // way to the backend before this frame is torn down, and a reply nobody is
    // left to receive costs nothing.
    try { flush(); } catch { /* going away regardless */ }
  }

  // `true` = capture phase, so we see events even if the page stops propagation.
  const LISTENERS = [
    ["click", guard("click", onClick), true],
    ["input", guard("input", onInput), true],
    ["change", guard("change", onChange), true],
    ["keydown", guard("keydown", onKeyDown), true],
    ["mouseover", guard("mouseover", onMouseOver), true],
    ["dragstart", guard("dragstart", onDragStart), true],
    ["drop", guard("drop", onDrop), true],
    ["scroll", guard("scroll", onScroll), true],
    ["popstate", guard("popstate", onPopState), true],
    ["pagehide", guard("pagehide", onPageHide), true],
    // Some browsers skip `pagehide` when a tab is discarded, and fire this
    // instead. Flushing twice is free: uploads are idempotent by sequence.
    //
    // `flushOnly`, because this also fires every time somebody switches tab or
    // minimises the window - and marking everything pending as "navigated"
    // then would record an outcome that never happened.
    ["visibilitychange", () => {
      if (document.visibilityState === "hidden") onPageHide({ flushOnly: true });
    }, true],
  ];

  const attach = () => {
    watchMutations();
    LISTENERS.forEach(([t, fn, c]) => document.addEventListener(t, fn, c));
    // `pagehide` and `visibilitychange` are delivered to the window and the
    // document respectively; listening on both costs nothing and misses
    // neither.
    window.addEventListener("pagehide", onPageHide, true);
  };
  const detach = () => {
    LISTENERS.forEach(([t, fn, c]) => document.removeEventListener(t, fn, c));
    window.removeEventListener("pagehide", onPageHide, true);
  };

  // ==== upload ============================================================
  async function api(path, body, method = "POST") {
    const response = await fetch(`${API}${path}`, {
      method,
      headers: {
        "Content-Type": "application/json",
        ...(state?.token ? { Authorization: `Bearer ${state.token}` } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await response.text();
    if (!response.ok) {
      let detail = text;
      try {
        detail = JSON.parse(text).detail ?? text;
      } catch {
        /* not JSON */
      }
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return text ? JSON.parse(text) : {};
  }

  /* Everything ready to go up, leaving behind anything still waiting to hear
   * back. Held actions go on the next tick two seconds later, so the cost is a
   * little latency on the newest action and nothing at all on the rest.
   *
   * `stopping` overrides it: the recording is over, nothing more is coming, and
   * a held action would be lost rather than delayed. */
  function readyToSend() {
    if (state.status === STOPPING) return state.pending.length;
    const now = Date.now();
    let count = 0;
    for (const action of state.pending) {
      if (action.response === undefined && now - (action._recordedAt ?? 0) < SETTLE_MS) break;
      count++;
    }
    return count;
  }

  /* Introduce this frame to the backend, once it has something to say. */
  async function join() {
    const hello = await bridge({ type: "hello" });
    state.sessionId = hello.sessionId;
    state.sessionName = hello.sessionName;
    state.projectId = hello.projectId;
    state.projectName = hello.projectName;
    state.sequence = hello.nextSequence;
    state.captured = Math.max(state.captured, hello.actionCount);
    state.uploaded = hello.actionCount;
    state.startedAt = Date.now() - hello.elapsedMs;
  }

  async function flush() {
    if (!state || !state.pending.length) return;
    const ready = readyToSend();
    if (!ready) return;

    // An embedded frame has not introduced itself until now, because until now
    // it had nothing to introduce. Everything it recorded meanwhile is waiting
    // without a number.
    if (!state.sessionId) {
      if (!bridge) return;
      try {
        await join();
      } catch (error) {
        state.error = `Could not join the recording: ${error.message}`;
        return;
      }
    }

    const batch = state.pending.splice(0, ready).map(({ _recordedAt, ...action }) => ({
      ...action,
      sequence: action.sequence === null ? state.sequence++ : action.sequence,
    }));
    try {
      const result = bridge
        ? await bridge({ type: "actions", actions: batch })
        : await api(`/recordings/${state.sessionId}/actions`, { actions: batch });
      state.uploaded = result.action_count;
      // The server is the only thing that knows the whole session. Seeding the
      // count at `hello` undercounts by whatever the previous page still had in
      // flight, so every successful batch corrects it: what is stored, plus
      // what is still waiting to go.
      state.captured = Math.max(state.captured, state.uploaded + state.pending.length);
      state.error = null;
      notify();
    } catch (error) {
      // Put them back and retry on the next tick — upload is idempotent, so a
      // partially-applied batch cannot duplicate.
      state.pending.unshift(...batch);
      state.error = `Upload failed, retrying: ${error.message}`;
      notify();
    }
  }

  // ==== built-in panel (console use; the React bar passes panel:false) =====
  /* Put the panel back if the page has taken it away.
   *
   * It is built once, when recording starts, and appended to `document.body`.
   * Plenty of applications then replace that body wholesale - a router
   * rendering a new view, a framework mounting over the server's markup, a
   * `body.innerHTML =` in some widget - and the panel goes with it. The
   * recorder carries on capturing perfectly happily, and the only thing the
   * person recording can see is that it vanished, mid-session, for no reason
   * they can name.
   *
   * Cheap to check and cheap to fix: it is one `getElementById` on a path that
   * already runs after every action. */
  function keepPanel() {
    if (!state || !state.showPanel || state.status === IDLE) return null;

    const existing = document.getElementById(PANEL_ID);
    if (existing) return existing;
    if (!document.body) return null;

    buildPanel();
    return document.getElementById(PANEL_ID);
  }

  function paint() {
    if (!state) return;
    const panel = keepPanel();
    if (!panel) return;
    panel.querySelector("[data-count]").textContent = String(state.captured);
    panel.querySelector("[data-uploaded]").textContent = String(state.uploaded);
    panel.querySelector("[data-last]").textContent = state.lastAction ?? "…";
    panel.querySelector("[data-status]").textContent = state.status;

    const assertBtn = panel.querySelector("[data-assert]");
    assertBtn.textContent = state.assertMode ? "Click a target" : "Assert (Alt+A)";
    assertBtn.style.background = state.assertMode ? "#f59e0b" : "#334155";

    const pauseBtn = panel.querySelector("[data-pause]");
    pauseBtn.textContent = state.status === PAUSED ? "Resume" : "Pause";
  }

  function buildPanel() {
    // There is one panel. `start` builds it, and `keepPanel` builds it again
    // when a page has taken it away - and those two can race on a fast first
    // paint, so the invariant lives here rather than at either call site.
    if (document.getElementById(PANEL_ID)) return;

    const panel = document.createElement("div");
    panel.id = PANEL_ID;
    panel.style.cssText = `
      position:fixed;bottom:16px;right:16px;z-index:2147483647;
      font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;
      background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:10px;
      padding:12px 14px;min-width:240px;box-shadow:0 8px 24px rgba(0,0,0,.4)`;
    panel.innerHTML = `
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
        <span style="width:8px;height:8px;border-radius:50%;background:#ef4444;
                     animation:autoqaPulse 1.2s infinite"></span>
        <strong style="color:#f8fafc">AutoQA</strong>
        <span data-status style="color:#94a3b8">recording</span>
      </div>
      <div>captured <b data-count style="color:#38bdf8">0</b> ·
           uploaded <b data-uploaded style="color:#4ade80">0</b></div>
      <div style="color:#94a3b8;margin:4px 0 10px" data-last>…</div>
      <div style="display:flex;gap:6px">
        <button data-assert style="flex:1;background:#334155;color:#e2e8f0;border:0;
                border-radius:6px;padding:6px;cursor:pointer;font:inherit">Assert (Alt+A)</button>
        <button data-pause style="background:#475569;color:#fff;border:0;border-radius:6px;
                padding:6px 10px;cursor:pointer;font:inherit">Pause</button>
        <button data-stop style="background:#dc2626;color:#fff;border:0;border-radius:6px;
                padding:6px 10px;cursor:pointer;font:inherit">Stop</button>
      </div>
      <style>@keyframes autoqaPulse{50%{opacity:.25}}</style>`;
    panel.querySelector("[data-stop]").addEventListener("click", () => stop());
    panel.querySelector("[data-pause]").addEventListener("click", () =>
      state?.status === PAUSED ? resume() : pause()
    );
    panel.querySelector("[data-assert]").addEventListener("click", () =>
      setAssertMode(!state.assertMode)
    );
    document.body.appendChild(panel);
  }

  function setAssertMode(on) {
    if (!state) return;
    state.assertMode = on;
    document.body.style.cursor = on ? "crosshair" : "";
    notify();
  }

  function readToken() {
    try {
      const raw = localStorage.getItem(AUTH_KEY);
      return raw ? (JSON.parse(raw)?.state?.accessToken ?? null) : null;
    } catch {
      return null;
    }
  }

  // ==== public API ========================================================
  async function start(options = {}) {
    if (state && state.status !== IDLE) {
      throw new Error("Already recording");
    }
    state = freshState();
    // One panel per recording, and it belongs to the page - not to each of
    // the video players embedded in it.
    state.showPanel = options.panel !== false && isTop;

    if (bridge) {
      // The backend already created the session and authorised it; this page
      // never sees a token and never talks to the API directly.
      //
      // Ask the backend where we are rather than trusting anything baked into
      // the injected script: this file is re-injected on every navigation, so
      // a static sequence number would restart at 0 on the second page and
      // collide with actions already stored.
      // An embedded frame waits. It attaches its listeners and records
      // nothing until somebody actually does something inside it, at which
      // point `flush` introduces it - see `join`. A video player nobody
      // touches therefore costs one injected script and not one recorder.
      if (!isTop) {
        state.status = RECORDING;
        attach();
        state.uploadTimer = setInterval(guard("upload tick", flush), BATCH_MS);
        return snapshot();
      }

      const hello = await bridge({ type: "hello" });
      state.sessionId = hello.sessionId;
      state.sessionName = hello.sessionName;
      state.projectId = hello.projectId;
      state.projectName = hello.projectName;
      state.sequence = hello.nextSequence;
      // Continuing a recording that already has actions in it: the count picks
      // up where the session left off, while the sequence continues from this
      // page's own block.
      state.captured = hello.actionCount;
      state.uploaded = hello.actionCount;
      state.startedAt = Date.now() - hello.elapsedMs;
    } else {
      state.token = options.token || window.__AUTOQA_TOKEN__ || readToken();
      if (!state.token) {
        state = null;
        throw new Error("Not signed in — open http://localhost:3000 and log in first");
      }

      const projects = await api("/projects", undefined, "GET");
      if (!projects.length) {
        state = null;
        throw new Error("No projects yet — create one first");
      }

      const project = projects.find((p) => p.id === options.projectId) ?? projects[0];
      state.projectId = project.id;
      state.projectName = project.name;
      state.sessionName =
        options.name?.trim() || `Recording ${new Date().toLocaleTimeString()}`;

      const session = await api(`/projects/${project.id}/recordings`, {
        name: state.sessionName,
        start_url: location.href,
        extension_version: "web-0.2.0",
        browser_info: {
          user_agent: navigator.userAgent,
          viewport: { width: innerWidth, height: innerHeight },
          device_pixel_ratio: devicePixelRatio,
          platform: navigator.platform,
        },
      });
      state.sessionId = session.id;
      state.startedAt = Date.now();
    }

    state.status = RECORDING;

    // On a fresh start this is the opening navigation. After a page load,
    // Playwright re-injects this file, so it records where we landed.
    record("navigate", null, { url: location.href });

    attach();
    state.uploadTimer = setInterval(guard("upload tick", () => {
      flush();
      // The page may have removed the panel while nothing was being recorded.
      try {
        keepPanel();
      } catch (error) {
        console.error("[AutoQA] panel failed, still recording:", error);
      }
    }), BATCH_MS);

    // Single-page apps change the URL without a load event.
    let lastUrl = location.href;
    state.urlTimer = setInterval(guard("url watch", () => {
      if (location.href !== lastUrl) {
        lastUrl = location.href;
        record("navigate", null, { url: location.href });
      }
    }), 400);

    if (state.showPanel) buildPanel();
    notify();
    return snapshot();
  }

  function pause() {
    if (!state || state.status !== RECORDING) return snapshot();
    flushInput(null);
    detach();
    clearTimeout(state.hoverTimer);
    clearTimeout(state.scrollTimer);
    state.pausedAt = Date.now();
    state.status = PAUSED;
    setAssertMode(false);
    notify();
    return snapshot();
  }

  function resume() {
    if (!state || state.status !== PAUSED) return snapshot();
    // Discount the paused span so generated tests do not inherit a long wait.
    state.pausedMs += Date.now() - state.pausedAt;
    state.pausedAt = 0;
    state.status = RECORDING;
    attach();
    notify();
    return snapshot();
  }

  async function stop() {
    if (!state || state.status === IDLE || state.status === STOPPING) {
      return snapshot();
    }

    const wasPaused = state.status === PAUSED;
    if (!wasPaused) flushInput(null);
    detach();
    clearInterval(state.uploadTimer);
    clearInterval(state.urlTimer);
    clearTimeout(state.hoverTimer);
    clearTimeout(state.scrollTimer);
    document.body.style.cursor = "";
    state.status = STOPPING;
    notify();

    await flush();

    let session = null;
    try {
      if (wasPaused) state.pausedMs += Date.now() - state.pausedAt;
      const durationMs = Date.now() - state.startedAt - state.pausedMs;
      session = bridge
        ? await bridge({ type: "stop", duration_ms: durationMs })
        : await api(`/recordings/${state.sessionId}/stop`, { duration_ms: durationMs });
    } catch (error) {
      state.error = `Could not stop cleanly: ${error.message}`;
      notify();
    }

    document.getElementById(PANEL_ID)?.remove();

    const result = {
      ...snapshot(),
      status: IDLE,
      sessionId: state.sessionId,
      captured: session?.action_count ?? state.captured,
      durationMs: session?.duration_ms ?? null,
    };
    state = null;
    notify();
    return result;
  }

  window.AutoQARecorder = {
    start,
    pause,
    resume,
    stop,
    setAssertMode: (on) => setAssertMode(on),
    getState: snapshot,
    /* Which selectors this element would produce, and whether each is
     * actually unique. A diagnostic hook: "why did it pick that selector"
     * is otherwise unanswerable from outside, and uniqueness is measured
     * here rather than guessed, so it is worth being able to check. */
    selectorsFor: (el) => buildSelectors(el),
    subscribe(listener) {
      listeners.add(listener);
      listener(snapshot());
      return () => listeners.delete(listener);
    },
  };

  // In bridge mode there is no UI on the target site to press Start, and this
  // file is re-injected on every navigation, so start as soon as the page has
  // a <body> to attach the panel to.
  if (bridge && injected) {
    const begin = () =>
      start().catch((error) =>
        // The one failure that leaves no panel and captures nothing on this
        // page. Named so the backend log says which document it was.
        console.error(`[AutoQA] could not start on ${location.href}:`, error)
      );
    if (document.body) begin();
    else document.addEventListener("DOMContentLoaded", begin, { once: true });
  }
})();
