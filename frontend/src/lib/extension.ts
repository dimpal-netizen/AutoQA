/** Talking to the AutoQA Recorder extension from the web app.
 *
 *  The extension's content script runs on this page like any other, and
 *  listens for `postMessage` requests tagged `__autoqa: "app"`. Nothing here
 *  needs the extension's id, which an unpacked install does not have a stable
 *  one of anyway.
 *
 *  A request that nobody answers - no extension installed - resolves to null
 *  after a short wait rather than rejecting, because "not installed" is the
 *  ordinary case and every caller has a plan for it.
 */

import { useAuthStore } from "@/stores/auth-store";

const BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:5022/api/v1";

export interface ExtensionPing {
  version: string;
  apiUrl: string;
  signedIn: boolean;
  user: { id: number; email: string } | null;
}

export interface ExtensionSessionState {
  id: number;
  open: boolean;
  stopped: { action_count: number; duration_ms: number | null; suite_id: number | null } | null;
}

interface AppReply {
  __autoqa: "app-reply";
  id: number;
  ok: boolean;
  result?: unknown;
  error?: string;
}

let nextId = 1;

function ask<T>(request: Record<string, unknown>, timeoutMs: number): Promise<T | null> {
  if (typeof window === "undefined") return Promise.resolve(null);

  return new Promise((resolve, reject) => {
    const id = nextId++;
    const timer = setTimeout(() => {
      window.removeEventListener("message", onMessage);
      resolve(null);
    }, timeoutMs);

    function onMessage(event: MessageEvent) {
      if (event.source !== window) return;
      const data = event.data as AppReply | undefined;
      if (!data || data.__autoqa !== "app-reply" || data.id !== id) return;
      clearTimeout(timer);
      window.removeEventListener("message", onMessage);
      if (data.ok) resolve(data.result as T);
      else reject(new Error(data.error ?? "The extension refused the request"));
    }

    window.addEventListener("message", onMessage);
    window.postMessage({ __autoqa: "app", id, request }, "*");
  });
}

export const extension = {
  /** The API address this app uses - what a downloaded extension is told. */
  apiUrl: BASE_URL,

  /** Is the extension installed on this browser? Null when it is not.
   *
   *  Chrome puts the extension's worker to sleep after ~30s idle, and waking
   *  it for the first ping can take longer than a page expects an answer to
   *  take - so the wait is generous and a silence is asked about twice. */
  detect: async () => {
    const first = await ask<ExtensionPing>({ type: "ping" }, 2_500);
    if (first) return first;
    return ask<ExtensionPing>({ type: "ping" }, 2_500);
  },

  /** Open `url` in a new tab and record it. Hands over this app's sign-in so
   *  the tester is not asked for it again. */
  start: (data: { projectId: number; url: string; name?: string }) => {
    const store = useAuthStore.getState();
    return ask<{ sessionId: number; tabId: number }>(
      {
        type: "start",
        apiUrl: BASE_URL,
        accessToken: store.accessToken,
        refreshToken: store.refreshToken,
        ...data,
      },
      20_000,
    );
  },

  /** The recordings the extension has open in this browser. */
  status: () => ask<{ sessions: ExtensionSessionState[] }>({ type: "status" }, 1_000),

  /** Stop a recording the extension is making. Waits for the page to flush
   *  and the server to generate the suite, which can take a while. */
  stop: (sessionId: number) =>
    ask<{ action_count: number }>({ type: "stop", sessionId }, 120_000),

  /** Bring the recording tab to the front. */
  focus: (sessionId: number) => ask<{ ok: true }>({ type: "focus", sessionId }, 1_000),
};

/** Where the app links testers to download the extension. */
export function extensionDownloadUrl(): string {
  return `${BASE_URL}/extension/download?api_url=${encodeURIComponent(BASE_URL)}`;
}
