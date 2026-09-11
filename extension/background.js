/* AutoQA Recorder — service worker.
 *
 * This is the extension's counterpart to backend/app/services/browser_recorder.py.
 * There, Playwright launches a browser on the server and the Python thread
 * answers the recorder's three messages - hello, actions, stop - straight into
 * the database. Here the browser is the tester's own, and the same three
 * messages are answered by calling the API over HTTPS with the tester's login.
 * Everything the recorder does on the page is identical.
 *
 * What lives where:
 *   chrome.storage.local    the sign-in (tokens, user, API address) - survives
 *                           browser restarts, so a tester signs in once.
 *   chrome.storage.session  the recordings in progress - survives this worker
 *                           being put to sleep (Chrome does that after ~30s
 *                           idle) but not the browser closing, which ends the
 *                           recordings anyway.
 *
 * Chrome may stop this worker between any two messages, so nothing important
 * is held only in a variable: state is loaded on demand and written through.
 */

importScripts("config.js");

const CONFIG = self.AUTOQA_CONFIG || { apiUrl: "", version: "0.0.0" };
const VERSION = chrome.runtime.getManifest().version;
const EXTENSION_VERSION = `chrome-${VERSION}`;

/* Sequence numbers are handed to each page in blocks, so two live pages - a
 * link opened in a new tab, say - can never hand out the same one. Mirrors
 * SEQUENCE_BLOCK and _claim_block in browser_recorder.py; see the reasoning
 * there. */
const SEQUENCE_BLOCK = 100000;
const MAX_FRAME_DEPTH = 8;
const BADGE = { text: "REC", color: "#dc2626" };

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let stateCache = null;

/* One in-memory copy per worker lifetime, written through on every change.
 * All handlers mutate this object, so two frames saying hello at once cannot
 * lose each other's update the way a read-modify-write against storage could. */
async function getState() {
  if (stateCache) return stateCache;
  const stored = await chrome.storage.session.get(["sessions", "tabs", "frames"]);
  stateCache = {
    sessions: stored.sessions || {},   // sessionId -> session
    tabs: stored.tabs || {},           // tabId -> sessionId
    frames: stored.frames || {},       // "tabId:frameId" -> {name, url}
  };
  return stateCache;
}

async function saveState() {
  if (stateCache) await chrome.storage.session.set(stateCache);
}

async function getLocal() {
  const stored = await chrome.storage.local.get([
    "apiUrl", "accessToken", "refreshToken", "user", "appOrigin",
  ]);
  return { ...stored, apiUrl: stored.apiUrl || CONFIG.apiUrl };
}

const setLocal = (values) => chrome.storage.local.set(values);

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------
class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function rawRequest(apiUrl, path, { method = "GET", body, token } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  let response;
  try {
    response = await fetch(`${apiUrl}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (error) {
    throw new ApiError(`Could not reach ${apiUrl}: ${error.message}`, 0);
  }
  const text = await response.text();
  if (!response.ok) {
    let detail = text;
    try {
      const parsed = JSON.parse(text);
      detail = parsed.detail ?? text;
      if (Array.isArray(detail)) {
        detail = detail.map((e) => `${(e.loc || []).slice(-1)[0] ?? ""}: ${e.msg}`).join(", ");
      }
    } catch { /* not JSON */ }
    throw new ApiError(typeof detail === "string" ? detail : JSON.stringify(detail), response.status);
  }
  return text ? JSON.parse(text) : {};
}

/* A signed-in request. On a 401 the refresh token is tried once, exactly as
 * the web app does, so an hour-long recording outlives the access token. */
async function api(path, options = {}) {
  const local = await getLocal();
  if (!local.apiUrl) throw new ApiError("The AutoQA server address is not set", 0);
  if (!local.accessToken) throw new ApiError("Not signed in to AutoQA", 401);

  try {
    return await rawRequest(local.apiUrl, path, { ...options, token: local.accessToken });
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 401 || !local.refreshToken) throw error;
  }

  let tokens;
  try {
    tokens = await rawRequest(local.apiUrl, "/auth/refresh", {
      method: "POST",
      body: { refresh_token: local.refreshToken },
    });
  } catch {
    await setLocal({ accessToken: null, refreshToken: null, user: null });
    throw new ApiError("Your AutoQA sign-in has expired - sign in again", 401);
  }
  await setLocal({
    accessToken: tokens.access_token,
    refreshToken: tokens.refresh_token,
    user: tokens.user,
  });
  return rawRequest(local.apiUrl, path, { ...options, token: tokens.access_token });
}

// ---------------------------------------------------------------------------
// Sessions
// ---------------------------------------------------------------------------
async function sessionForTab(tabId) {
  const state = await getState();
  const sessionId = state.tabs[tabId];
  return sessionId ? state.sessions[sessionId] : null;
}

async function registerTab(session, tabId) {
  const state = await getState();
  if (!session.tabIds.includes(tabId)) session.tabIds.push(tabId);
  state.tabs[tabId] = session.id;
  await saveState();
  showBadge(tabId, true);
}

function showBadge(tabId, on) {
  chrome.action.setBadgeText({ tabId, text: on ? BADGE.text : "" }).catch(() => {});
  if (on) chrome.action.setBadgeBackgroundColor({ tabId, color: BADGE.color }).catch(() => {});
}

/* Create the session on the server and remember it here. The tab is attached
 * by the caller: a popup start already has one, an app start opens one. */
async function createSession({ projectId, name, url, tab }) {
  const projects = await api("/projects");
  const project = projects.find((p) => p.id === Number(projectId));
  if (!project) throw new ApiError("That project is not available to you", 404);

  const sessionName = (name || "").trim() || project.name;
  const created = await api(`/projects/${project.id}/recordings`, {
    method: "POST",
    body: {
      name: sessionName,
      start_url: url,
      extension_version: EXTENSION_VERSION,
      browser_info: {
        user_agent: navigator.userAgent,
        platform: navigator.platform || null,
        viewport: tab && tab.width && tab.height ? { width: tab.width, height: tab.height } : null,
      },
    },
  });

  const state = await getState();
  const session = {
    id: created.id,
    projectId: project.id,
    projectName: project.name,
    name: sessionName,
    startUrl: url,
    tabIds: [],
    highWater: -1,
    blockStart: null,
    startedAt: Date.now(),
    stopped: null,
  };
  state.sessions[session.id] = session;
  await saveState();
  return session;
}

/* The first sequence a page starting now may use - see _claim_block in
 * browser_recorder.py for why it is always a fresh block. */
function claimBlock(session) {
  const after = Math.max(
    session.highWater + 1,
    session.blockStart === null ? 0 : session.blockStart + SEQUENCE_BLOCK,
  );
  const start = after ? Math.ceil(after / SEQUENCE_BLOCK) * SEQUENCE_BLOCK : 0;
  session.blockStart = start;
  return start;
}

const finishing = new Map(); // sessionId -> Promise, so two stops become one

/* Mark the recording complete on the server. Reached from Stop in the page
 * panel, Stop in the popup, Stop in the web app, and the last tab closing -
 * so it has to be safe to reach twice. */
function finish(sessionId, durationMs) {
  if (finishing.has(sessionId)) return finishing.get(sessionId);

  const task = (async () => {
    const state = await getState();
    const session = state.sessions[sessionId];
    if (!session) throw new ApiError(`Recording ${sessionId} is not open in this browser`, 404);
    if (session.stopped) return session.stopped;

    let result;
    try {
      result = await api(`/recordings/${sessionId}/stop`, {
        method: "POST",
        body: { duration_ms: durationMs ?? null },
      });
    } catch (error) {
      // Already stopped from somewhere else - the web app, say. Not a failure.
      if (!(error instanceof ApiError && error.status === 400)) throw error;
      result = await api(`/recordings/${sessionId}`);
    }

    session.stopped = {
      id: sessionId,
      action_count: result.action_count,
      duration_ms: result.duration_ms,
      suite_id: result.suite_id ?? null,
    };
    for (const tabId of session.tabIds) {
      delete state.tabs[tabId];
      showBadge(tabId, false);
    }
    session.tabIds = [];
    await saveState();
    return session.stopped;
  })();

  finishing.set(sessionId, task);
  task.finally(() => finishing.delete(sessionId));
  return task;
}

/* Ask the page to stop itself, so its last actions are flushed and its own
 * clock sets the duration. If no page answers - tabs closed, script not there
 * - stop it from here. */
async function stopSession(sessionId) {
  const state = await getState();
  const session = state.sessions[sessionId];
  if (!session) throw new ApiError(`Recording ${sessionId} is not open in this browser`, 404);
  if (session.stopped) return session.stopped;

  let asked = false;
  for (const tabId of session.tabIds) {
    try {
      await chrome.tabs.sendMessage(tabId, { kind: "cmd", cmd: "stop" });
      asked = true;
    } catch { /* tab gone, or no content script in it */ }
  }

  if (asked) {
    const deadline = Date.now() + 15000;
    while (Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 250));
      const current = (await getState()).sessions[sessionId];
      if (current && current.stopped) return current.stopped;
    }
  }
  return finish(sessionId, null);
}

// ---------------------------------------------------------------------------
// Frames
// ---------------------------------------------------------------------------
/* The frames between the page and the one an action came from, outermost
 * first - the same chain _describe_frames builds with Playwright. Chrome
 * tells us the tree and each frame's URL; the frame's name came from the
 * frame itself when it loaded (see content-relay.js). */
async function frameChain(tabId, frameId) {
  const state = await getState();
  let all;
  try {
    all = (await chrome.webNavigation.getAllFrames({ tabId })) || [];
  } catch {
    return [];
  }
  const byId = new Map(all.map((f) => [f.frameId, f]));
  const chain = [];
  let current = byId.get(frameId);

  for (let depth = 0; current && current.parentFrameId !== -1 && depth < MAX_FRAME_DEPTH; depth++) {
    const known = state.frames[`${tabId}:${current.frameId}`] || {};
    const siblings = all
      .filter((f) => f.parentFrameId === current.parentFrameId)
      .sort((a, b) => a.frameId - b.frameId);
    const described = {
      name: known.name ? String(known.name).slice(0, 256) : undefined,
      url: String(known.url || current.url || "").slice(0, 2048) || undefined,
      index: siblings.indexOf(current) >= 0 ? siblings.indexOf(current) : undefined,
    };
    chain.push(Object.fromEntries(Object.entries(described).filter(([, v]) => v !== undefined)));
    current = byId.get(current.parentFrameId);
  }
  chain.reverse();
  return chain;
}

// ---------------------------------------------------------------------------
// Messages from the recorder (through content-relay.js)
// ---------------------------------------------------------------------------
async function handleBridge(message, sender) {
  const tabId = sender.tab && sender.tab.id;
  const frameId = sender.frameId || 0;
  const kind = message && message.type;

  if (kind === "status") {
    const session = await sessionForTab(tabId);
    return { recording: Boolean(session && !session.stopped), sessionId: session ? session.id : null };
  }

  const session = await sessionForTab(tabId);
  if (!session || session.stopped) {
    if (kind === "stop") return { id: null, action_count: 0, duration_ms: null };
    throw new ApiError("This tab is not being recorded", 409);
  }

  if (kind === "hello") {
    const progress = await api(`/recordings/${session.id}/progress`);
    if (progress.max_sequence !== null && progress.max_sequence !== undefined) {
      session.highWater = Math.max(session.highWater, progress.max_sequence);
    }
    const nextSequence = claimBlock(session);
    await saveState();
    return {
      sessionId: session.id,
      sessionName: session.name,
      projectId: session.projectId,
      projectName: session.projectName,
      actionCount: progress.action_count,
      nextSequence,
      elapsedMs: progress.max_timestamp_ms || 0,
    };
  }

  if (kind === "actions") {
    const actions = Array.isArray(message.actions) ? message.actions : [];
    if (frameId !== 0) {
      const chain = await frameChain(tabId, frameId);
      if (chain.length) {
        for (const action of actions) {
          if (!action.frame_path || !action.frame_path.length) action.frame_path = chain;
        }
      }
    }
    for (const action of actions) {
      const sequence = Number(action.sequence);
      if (Number.isFinite(sequence)) session.highWater = Math.max(session.highWater, sequence);
    }
    await saveState();
    return api(`/recordings/${session.id}/actions`, { method: "POST", body: { actions } });
  }

  if (kind === "stop") {
    return finish(session.id, message.duration_ms ?? null);
  }

  throw new ApiError(`Unknown message ${kind}`, 400);
}

// ---------------------------------------------------------------------------
// Requests from the AutoQA web app (an ordinary page, through the relay)
// ---------------------------------------------------------------------------
const originOf = (sender) => {
  if (sender.origin) return sender.origin;
  try {
    return new URL(sender.url).origin;
  } catch {
    return null;
  }
};

async function handleApp(request, sender) {
  const local = await getLocal();
  const origin = originOf(sender);
  const type = request && request.type;

  if (type === "ping") {
    return {
      version: VERSION,
      apiUrl: local.apiUrl,
      signedIn: Boolean(local.accessToken),
      user: local.user || null,
    };
  }

  if (type === "start") {
    // The app hands over its own sign-in. Accepted only for the server this
    // extension is configured for: a page cannot point it somewhere else.
    const apiUrl = String(request.apiUrl || "").replace(/\/+$/, "");
    if (!apiUrl || apiUrl !== local.apiUrl) {
      throw new ApiError(
        `This extension is set up for ${local.apiUrl || "no server yet"}, not ${apiUrl || "this page"}. ` +
          "Download the extension from the AutoQA server you are using.",
        403,
      );
    }
    if (!request.accessToken) throw new ApiError("The app did not send a sign-in", 401);

    const user = await rawRequest(apiUrl, "/auth/me", { token: request.accessToken });
    await setLocal({
      accessToken: request.accessToken,
      refreshToken: request.refreshToken || null,
      user,
      appOrigin: origin,
    });

    const url = String(request.url || "").trim();
    if (!/^https?:\/\//i.test(url)) throw new ApiError("Enter an http(s) URL to record", 400);

    const session = await createSession({ projectId: request.projectId, name: request.name, url });
    const tab = await chrome.tabs.create({ url, active: true });
    await registerTab(session, tab.id);
    return { sessionId: session.id, tabId: tab.id };
  }

  // Everything below reports on or changes recordings. Only the app that
  // started them may - identified by the origin it handed its sign-in from.
  if (!local.appOrigin || origin !== local.appOrigin) {
    if (type === "status") return { sessions: [] };
    throw new ApiError("Not allowed from this page", 403);
  }

  if (type === "status") {
    const state = await getState();
    return {
      sessions: Object.values(state.sessions).map((s) => ({
        id: s.id,
        open: !s.stopped && s.tabIds.length > 0,
        stopped: s.stopped,
      })),
    };
  }

  if (type === "stop") return stopSession(Number(request.sessionId));

  if (type === "focus") {
    const state = await getState();
    const session = state.sessions[Number(request.sessionId)];
    const tabId = session && session.tabIds[0];
    if (!tabId) throw new ApiError("That recording has no open tab", 404);
    const tab = await chrome.tabs.update(tabId, { active: true });
    if (tab && tab.windowId !== undefined) {
      await chrome.windows.update(tab.windowId, { focused: true }).catch(() => {});
    }
    return { ok: true };
  }

  throw new ApiError(`Unknown request ${type}`, 400);
}

// ---------------------------------------------------------------------------
// Requests from the popup
// ---------------------------------------------------------------------------
async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  return tab || null;
}

async function handlePopup(request) {
  const type = request && request.type;
  const local = await getLocal();

  if (type === "get-state") {
    const state = await getState();
    const tab = await activeTab();
    const tabSession = tab ? state.tabs[tab.id] : null;
    return {
      version: VERSION,
      apiUrl: local.apiUrl,
      appOrigin: local.appOrigin || null,
      signedIn: Boolean(local.accessToken),
      user: local.user || null,
      tab: tab ? { id: tab.id, url: tab.url || "", title: tab.title || "" } : null,
      tabSessionId: tabSession || null,
      sessions: Object.values(state.sessions)
        .filter((s) => !s.stopped)
        .map((s) => ({ id: s.id, name: s.name, startUrl: s.startUrl, open: s.tabIds.length > 0 })),
    };
  }

  if (type === "sign-in") {
    const apiUrl = String(request.apiUrl || local.apiUrl || "").trim().replace(/\/+$/, "");
    if (!/^https?:\/\//i.test(apiUrl)) throw new ApiError("Enter the AutoQA server address", 400);
    const tokens = await rawRequest(apiUrl, "/auth/login", {
      method: "POST",
      body: { email: request.email, password: request.password },
    });
    await setLocal({
      apiUrl,
      accessToken: tokens.access_token,
      refreshToken: tokens.refresh_token,
      user: tokens.user,
    });
    return { user: tokens.user };
  }

  if (type === "sign-out") {
    await setLocal({ accessToken: null, refreshToken: null, user: null });
    return { ok: true };
  }

  if (type === "projects") return api("/projects");

  if (type === "progress") return api(`/recordings/${Number(request.sessionId)}/progress`);

  if (type === "start") {
    const tab = await activeTab();
    if (!tab || !/^https?:\/\//i.test(tab.url || "")) {
      throw new ApiError("Open the website you want to record first - Chrome's own pages cannot be recorded", 400);
    }
    if ((await getState()).tabs[tab.id]) throw new ApiError("This tab is already being recorded", 409);

    const session = await createSession({ projectId: request.projectId, name: request.name, url: tab.url, tab });
    await registerTab(session, tab.id);
    try {
      await chrome.tabs.sendMessage(tab.id, { kind: "cmd", cmd: "start" });
    } catch {
      // The page was open before the extension was installed, so nothing is
      // listening in it. Reloading injects the recorder, which starts itself.
      await chrome.tabs.reload(tab.id);
    }
    return { sessionId: session.id };
  }

  if (type === "stop") return stopSession(Number(request.sessionId));

  throw new ApiError(`Unknown request ${type}`, 400);
}

// ---------------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------------
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  const kind = message && message.kind;
  let task;
  if (kind === "bridge") task = handleBridge(message.message, sender);
  else if (kind === "app") task = handleApp(message.request, sender);
  else if (kind === "popup") task = handlePopup(message.request);
  else if (kind === "frame") {
    task = (async () => {
      if (!sender.tab) return { ok: true };
      const state = await getState();
      state.frames[`${sender.tab.id}:${sender.frameId}`] = { name: message.name, url: message.url };
      await saveState();
      return { ok: true };
    })();
  } else return false;

  task
    .then((result) => sendResponse({ ok: true, result }))
    .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
  return true; // answered asynchronously
});

/* A recording follows its links. A page opened from a recording tab - a
 * popup window, a target=_blank link - is part of the same recording, as it is
 * in a Playwright context. */
async function adoptTab(newTabId, openerTabId) {
  if (newTabId === undefined || openerTabId === undefined) return;
  const session = await sessionForTab(openerTabId);
  if (session && !session.stopped) await registerTab(session, newTabId);
}

chrome.tabs.onCreated.addListener((tab) => {
  adoptTab(tab.id, tab.openerTabId).catch(() => {});
});

chrome.webNavigation.onCreatedNavigationTarget.addListener((details) => {
  adoptTab(details.tabId, details.sourceTabId).catch(() => {});
});

/* Closing the window is how most recordings end. When the last tab of a
 * recording goes, the recording is finished from here; anything still in the
 * page's queue was flushed by its pagehide handler on the way out. */
chrome.tabs.onRemoved.addListener((tabId) => {
  (async () => {
    const state = await getState();
    const sessionId = state.tabs[tabId];
    if (!sessionId) return;
    const session = state.sessions[sessionId];
    delete state.tabs[tabId];
    for (const key of Object.keys(state.frames)) {
      if (key.startsWith(`${tabId}:`)) delete state.frames[key];
    }
    if (session) session.tabIds = session.tabIds.filter((id) => id !== tabId);
    await saveState();
    if (session && !session.stopped && session.tabIds.length === 0) {
      await finish(sessionId, null);
    }
  })().catch((error) => console.error("[AutoQA] tab close:", error));
});

/* Frames are re-registered when their document changes; drop the old entry so
 * a navigated frame does not keep its previous name. */
chrome.webNavigation.onCommitted.addListener((details) => {
  if (details.frameId === 0) return;
  (async () => {
    const state = await getState();
    delete state.frames[`${details.tabId}:${details.frameId}`];
    await saveState();
  })().catch(() => {});
});
