/* AutoQA Recorder — the page side of the bridge.
 *
 * Runs in the page's own JavaScript world, in every frame, before anything
 * else on the page. Its one job is to be `window.__autoqaBridge` for the
 * recorder.js that loads right after it, so the recorder runs in the same
 * "bridge" mode it runs in when Playwright injects it - unchanged.
 *
 * Playwright's binding is a function the page calls that resolves with the
 * backend's answer. This is the same function, built from two hops instead of
 * one: postMessage to the relay (content-relay.js, in the extension's own
 * world) and from there to the service worker, which talks to the API.
 *
 * Nothing is recorded until the service worker says this tab is recording.
 */
(() => {
  if (window.__autoqaBridge) return;

  const pending = new Map();      // id -> {resolve, reject}
  const queued = [];               // calls made before the relay answered
  let relayReady = false;
  let nextId = 1;

  const post = (payload) => window.postMessage({ __autoqa: "call", ...payload }, "*");

  function bridge(message) {
    return new Promise((resolve, reject) => {
      const id = nextId++;
      pending.set(id, { resolve, reject });
      if (relayReady) post({ id, message });
      else queued.push({ id, message });
    });
  }
  window.__autoqaBridge = bridge;

  /* The recorder starts as soon as the page has a body to hang its panel on -
   * the same rule recorder.js applies when Playwright injects it. */
  function startRecorder() {
    const begin = () => {
      const recorder = window.AutoQARecorder;
      if (!recorder) return;
      const state = recorder.getState();
      if (state && state.status !== "idle") return;   // already going
      recorder.start().catch((error) =>
        console.error(`[AutoQA] could not start on ${location.href}:`, error)
      );
    };
    if (document.body) begin();
    else document.addEventListener("DOMContentLoaded", begin, { once: true });
  }

  function stopRecorder() {
    const recorder = window.AutoQARecorder;
    if (!recorder) return;
    recorder.stop().catch((error) => console.error("[AutoQA] stop failed:", error));
  }

  window.addEventListener("message", (event) => {
    if (event.source !== window) return;
    const data = event.data;
    if (!data || typeof data !== "object") return;

    switch (data.__autoqa) {
      case "relay-ready": {
        if (!relayReady) {
          relayReady = true;
          for (const call of queued.splice(0)) post(call);
          // Is this document part of a recording? A page that reloaded, or a
          // tab opened from a recording tab, picks up where it was.
          bridge({ type: "status" })
            .then((status) => status && status.recording && startRecorder())
            .catch(() => { /* not recording; nothing to do */ });
        }
        break;
      }
      case "reply": {
        const waiter = pending.get(data.id);
        if (!waiter) return;
        pending.delete(data.id);
        if (data.ok) waiter.resolve(data.result);
        else waiter.reject(new Error(data.error || "bridge call failed"));
        break;
      }
      case "cmd": {
        if (data.cmd === "start") startRecorder();
        else if (data.cmd === "stop") stopRecorder();
        break;
      }
      default:
        break;
    }
  });

  // Either side may have loaded first; each announces itself and answers the
  // other, so the handshake completes whichever order Chrome ran them in.
  window.postMessage({ __autoqa: "main-ready" }, "*");
})();
