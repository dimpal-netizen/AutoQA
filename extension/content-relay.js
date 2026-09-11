/* AutoQA Recorder — the relay between a page and the service worker.
 *
 * Runs in the extension's isolated world, in every frame. A page cannot talk
 * to a service worker and a service worker cannot talk to a page; this is the
 * piece in the middle that can do both. It carries:
 *
 *  - bridge calls from recorder.js (via content-main.js) up to the worker and
 *    the worker's answers back down;
 *  - commands from the worker ("start", "stop") down to the page;
 *  - requests from the AutoQA web app itself - is the extension installed,
 *    start a recording on this URL, stop it - up to the worker. The app is an
 *    ordinary page to the extension; what makes it special is that it holds a
 *    signed-in session, which it hands over with the request.
 *
 * It also tells the worker what this frame is called, because that is the one
 * fact about a frame nobody outside it can read across an origin boundary.
 */
(() => {
  const send = (message) =>
    new Promise((resolve, reject) => {
      let settled = false;
      try {
        chrome.runtime.sendMessage(message, (reply) => {
          settled = true;
          if (chrome.runtime.lastError) {
            reject(new Error(chrome.runtime.lastError.message));
          } else if (reply && reply.ok === false) {
            reject(new Error(reply.error || "request failed"));
          } else {
            resolve(reply ? reply.result : undefined);
          }
        });
      } catch (error) {
        if (!settled) reject(error);
      }
    });

  const toPage = (payload) => window.postMessage({ __autoqa: "reply", ...payload }, "*");
  const toApp = (payload) => window.postMessage({ __autoqa: "app-reply", ...payload }, "*");

  window.addEventListener("message", (event) => {
    if (event.source !== window) return;
    const data = event.data;
    if (!data || typeof data !== "object") return;

    switch (data.__autoqa) {
      case "main-ready":
        window.postMessage({ __autoqa: "relay-ready" }, "*");
        break;

      case "call":
        send({ kind: "bridge", message: data.message })
          .then((result) => toPage({ id: data.id, ok: true, result }))
          .catch((error) => toPage({ id: data.id, ok: false, error: error.message }));
        break;

      case "app":
        send({ kind: "app", request: data.request })
          .then((result) => toApp({ id: data.id, ok: true, result }))
          .catch((error) => toApp({ id: data.id, ok: false, error: error.message }));
        break;

      default:
        break;
    }
  });

  chrome.runtime.onMessage.addListener((message) => {
    if (message && message.kind === "cmd") {
      window.postMessage({ __autoqa: "cmd", cmd: message.cmd }, "*");
    }
    // Nothing to answer; returning undefined closes the channel.
  });

  // In case the page side loaded first and its announcement went unheard.
  window.postMessage({ __autoqa: "relay-ready" }, "*");

  // An embedded frame introduces itself. Its name is the one thing worth
  // knowing about it that the worker cannot find out on its own.
  if (window !== window.top) {
    send({
      kind: "frame",
      name: window.name || null,
      url: location.href,
    }).catch(() => { /* the worker was busy restarting; the chain falls back to URLs */ });
  }
})();
