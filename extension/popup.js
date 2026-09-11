/* AutoQA Recorder — the popup.
 *
 * Three views, picked from what the service worker says: sign in, ready to
 * record this tab, recording this tab. Everything that talks to the API goes
 * through the worker, so the popup holds no tokens and no state of its own.
 */
const CONFIG = self.AUTOQA_CONFIG || { apiUrl: "" };

const view = document.getElementById("view");
const $ = (id) => document.getElementById(id);

function call(request) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage({ kind: "popup", request }, (reply) => {
      if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
      else if (!reply || reply.ok === false) reject(new Error((reply && reply.error) || "request failed"));
      else resolve(reply.result);
    });
  });
}

function render(templateId) {
  const template = document.getElementById(templateId);
  view.replaceChildren(template.content.cloneNode(true));
}

function showError(id, error) {
  const el = $(id);
  if (!el) return;
  el.textContent = error instanceof Error ? error.message : String(error);
  el.hidden = false;
}

let pollTimer = null;
function stopPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
}

/* The web app to link to. Known once the app has started a recording through
 * the extension; otherwise the API's own host, which is right wherever the
 * two are served together. */
function appUrl(state) {
  if (state.appOrigin) return state.appOrigin;
  try {
    return new URL(state.apiUrl).origin;
  } catch {
    return null;
  }
}

async function refresh() {
  stopPolling();
  let state;
  try {
    state = await call({ type: "get-state" });
  } catch (error) {
    view.innerHTML = "";
    const p = document.createElement("p");
    p.className = "error";
    p.textContent = `The extension is not responding: ${error.message}`;
    view.append(p);
    return;
  }

  $("version").textContent = `v${state.version}`;
  $("user").textContent = state.user ? state.user.email : "";
  $("signout").hidden = !state.signedIn;
  const link = $("open-app");
  const app = appUrl(state);
  link.hidden = !app;
  if (app) link.href = app;

  if (!state.signedIn) return renderSignIn(state);
  if (state.tabSessionId) return renderRecording(state);
  return renderReady(state);
}

function renderSignIn(state) {
  render("tpl-signin");
  const form = $("signin");
  form.elements.apiUrl.value = state.apiUrl || CONFIG.apiUrl || "";
  if (!form.elements.apiUrl.value) form.querySelector("details").open = true;

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector("button");
    button.disabled = true;
    $("signin-error").hidden = true;
    try {
      await call({
        type: "sign-in",
        apiUrl: form.elements.apiUrl.value,
        email: form.elements.email.value,
        password: form.elements.password.value,
      });
      await refresh();
    } catch (error) {
      showError("signin-error", error);
      button.disabled = false;
    }
  });
}

async function renderReady(state) {
  render("tpl-ready");
  const form = $("start");
  const select = form.elements.projectId;
  const button = form.querySelector("button");
  $("tab-url").textContent = state.tab ? state.tab.url : "";

  const recordable = state.tab && /^https?:\/\//i.test(state.tab.url || "");
  if (!recordable) {
    showError("start-error", "Open the website you want to record, then click the icon again.");
    button.disabled = true;
  }

  try {
    const projects = await call({ type: "projects" });
    select.replaceChildren(
      ...projects.map((p) => {
        const option = document.createElement("option");
        option.value = p.id;
        option.textContent = p.name;
        return option;
      }),
    );
    if (!projects.length) {
      showError("start-error", "No projects yet - create one in AutoQA first.");
      button.disabled = true;
    }
    // The project whose URL this tab is on, if there is one.
    const host = state.tab ? new URL(state.tab.url).host : "";
    const match = projects.find((p) => p.base_url && p.base_url.includes(host));
    if (match) select.value = String(match.id);
  } catch (error) {
    showError("start-error", error);
    button.disabled = true;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    button.disabled = true;
    $("start-error").hidden = true;
    try {
      await call({ type: "start", projectId: Number(select.value), name: form.elements.name.value });
      await refresh();
    } catch (error) {
      showError("start-error", error);
      button.disabled = false;
    }
  });
}

function renderRecording(state) {
  render("tpl-recording");
  const session = state.sessions.find((s) => s.id === state.tabSessionId);
  $("rec-name").textContent = session ? session.name : `Recording ${state.tabSessionId}`;

  const update = async () => {
    try {
      const progress = await call({ type: "progress", sessionId: state.tabSessionId });
      $("rec-count").textContent = String(progress.action_count);
    } catch { /* transient */ }
  };
  update();
  pollTimer = setInterval(update, 1500);

  $("stop").addEventListener("click", async () => {
    const button = $("stop");
    button.disabled = true;
    button.textContent = "Stopping…";
    $("stop-error").hidden = true;
    try {
      const result = await call({ type: "stop", sessionId: state.tabSessionId });
      stopPolling();
      view.innerHTML = "";
      const p = document.createElement("p");
      p.className = "lead";
      p.textContent = `Saved ${result.action_count} actions.`;
      const q = document.createElement("p");
      q.className = "muted";
      q.textContent = result.suite_id
        ? "Tests were generated - open AutoQA to review them."
        : "Open AutoQA to review the recording.";
      view.append(p, q);
    } catch (error) {
      showError("stop-error", error);
      button.disabled = false;
      button.textContent = "Stop and generate tests";
    }
  });
}

$("signout").addEventListener("click", async () => {
  await call({ type: "sign-out" }).catch(() => {});
  await refresh();
});

refresh();
