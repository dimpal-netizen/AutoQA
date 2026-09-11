"use client";

import { useEffect, useRef, useState } from "react";
import { Circle, ExternalLink, Loader2, Square } from "lucide-react";
import { api } from "@/lib/api";
import { extension } from "@/lib/extension";
import type { Project, RecordingSession } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { LiveDot } from "@/components/ui/badge";
import { Input, Label, Select } from "@/components/ui/input";
import {
  Alert,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ExtensionSetup, useExtension } from "@/components/extension-setup";

/** Enter a URL, get a browser window with the recorder already running.
 *
 *  The recorder cannot be injected across origins from this page, so
 *  something outside the page has to do it. Two things can:
 *
 *  - The AutoQA Recorder extension, in the tester's own Chrome. This is how a
 *    deployed AutoQA records: the tab opens on the tester's machine, and the
 *    server runs nothing but the API.
 *  - The backend, launching Chromium with Playwright. The window opens
 *    wherever the backend runs - fine on a developer's laptop, invisible on a
 *    server - so it is offered only in development, and only when the
 *    extension is not installed.
 */
export function LaunchRecording({
  onChanged,
  onFinished,
  project,
}: {
  onChanged: () => void;
  /** The recording is over — by the Stop button or by closing the browser
   *  window. The panel invites you to start another one, which is not what
   *  anyone wants at the moment they finished the first. */
  onFinished?: () => void;
  /** When recording from inside a project, the project is context rather than
   *  a choice — asking again is a question with one answer. */
  project?: Project;
}) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<number | null>(project?.id ?? null);
  const [url, setUrl] = useState("");
  const [name, setName] = useState("");
  const [live, setLive] = useState<RecordingSession | null>(null);
  const [liveVia, setLiveVia] = useState<"extension" | "server">("extension");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { installed, recheck } = useExtension();
  // The server-side browser is a development convenience: it opens on the
  // machine running the backend, which in development is this one.
  const serverAvailable = process.env.NODE_ENV !== "production";
  const [preferServer, setPreferServer] = useState(false);
  const via: "extension" | "server" =
    installed && !preferServer ? "extension" : "server";

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      if (project) {
        // Given a project there is nothing to fetch and nothing to pick; just
        // pre-fill the URL, which is nearly always what you want to record.
        if (!cancelled) setUrl((current) => current || project.base_url || "");
        return;
      }
      try {
        const list = await api.projects.list();
        if (cancelled) return;
        setProjects(list);
        setProjectId((current) => current ?? list[0]?.id ?? null);
        setUrl((current) => current || (list[0]?.base_url ?? ""));
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Could not load projects");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [project]);

  // In a ref so the polling effect below keeps the dependencies it already has.
  // The parent passes a fresh arrow on every render, and adding that to the
  // deps would tear down and rebuild the interval each time.
  const notifyFinished = useRef(onFinished);
  useEffect(() => {
    notifyFinished.current = onFinished;
  }, [onFinished]);

  // While a window is open, poll so the action count ticks up here too, and so
  // we notice the user closing the browser window directly.
  useEffect(() => {
    if (!live) return;
    const timer = setInterval(async () => {
      try {
        const sessions = await api.recordings.list();
        const current = sessions.find((s) => s.id === live.id);
        onChanged();

        let open: boolean;
        if (liveVia === "extension") {
          // The server cannot see a tab in somebody's Chrome; the extension
          // can. Either one saying it is over is enough.
          const status = await extension.status().catch(() => null);
          const mine = status?.sessions.find((s) => s.id === live.id);
          open = Boolean(mine?.open) && current?.status === "recording";
        } else {
          open = Boolean(current?.browser_open);
        }

        if (!open) {
          setLive(null);
          // Closing the window is how most recordings end — the Stop button is
          // the other one, and both mean the same thing to whoever is watching.
          notifyFinished.current?.();
        } else if (current) setLive(current);
      } catch {
        /* transient — keep polling */
      }
    }, 1500);
    return () => clearInterval(timer);
  }, [live, liveVia, onChanged]);

  async function start() {
    if (!projectId) return;
    setBusy(true);
    setError(null);
    try {
      const target = url.trim();
      const label = name.trim() || undefined;

      if (via === "extension") {
        const started = await extension.start({ projectId, url: target, name: label });
        if (!started) {
          throw new Error(
            "The extension did not answer. Check it is enabled in chrome://extensions, then try again.",
          );
        }
        const sessions = await api.recordings.list(projectId);
        const session = sessions.find((s) => s.id === started.sessionId);
        if (!session) throw new Error("The recording started but could not be found");
        setLiveVia("extension");
        setLive(session);
      } else {
        const session = await api.recordings.launch(projectId, { url: target, name: label });
        setLiveVia("server");
        setLive(session);
      }
      setName("");
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not launch the browser");
    } finally {
      setBusy(false);
    }
  }

  async function stop() {
    if (!live) return;
    setBusy(true);
    try {
      if (liveVia === "extension") await extension.stop(live.id);
      else await api.recordings.close(live.id);
      setLive(null);
      onChanged();
      onFinished?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not stop the recording");
    } finally {
      setBusy(false);
    }
  }

  if (live) {
    return (
      <Card className="mb-6 border-destructive/30 bg-destructive-subtle/40 shadow-md">
        <CardContent className="flex flex-wrap items-center gap-4 px-5 pt-5">
          <span className="flex items-center gap-2 text-sm font-semibold text-destructive">
            <LiveDot />
            Recording
          </span>

          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{live.name}</p>
            <p className="truncate text-xs text-muted-foreground">{live.start_url}</p>
          </div>

          <span className="tabular text-sm text-muted-foreground">
            <b className="text-foreground">{live.action_count}</b> actions
          </span>

          {liveVia === "extension" && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => void extension.focus(live.id)}
            >
              <ExternalLink />
              Show tab
            </Button>
          )}

          <Button variant="destructive" size="sm" disabled={busy} onClick={stop}>
            {busy ? <Loader2 className="animate-spin" /> : <Square className="fill-current" />}
            {busy ? "Stopping…" : "Stop"}
          </Button>
        </CardContent>

        <CardContent className="pt-3 text-xs leading-relaxed text-muted-foreground">
          {liveVia === "extension"
            ? "A Chrome tab is open with the recorder — switch to it and use the site normally. Everything you do is captured, including in tabs it opens. You can also press Stop in the panel inside that tab, or just close it."
            : "A browser window is open — switch to it and use the site normally. Everything you do is captured. You can also press Stop in the panel inside that window, or just close it."}
        </CardContent>
      </Card>
    );
  }

  // Nothing in this browser can open a recording tab. Say how to fix that -
  // and in development, offer the backend's own browser as a way round it.
  if (installed === null && !preferServer) {
    return (
      <>
        <ExtensionSetup installed={installed} onRecheck={recheck} />
        {serverAvailable && (
          <p className="-mt-3 mb-6 text-xs text-muted-foreground">
            Developing locally?{" "}
            <button
              type="button"
              className="text-primary underline-offset-4 hover:underline"
              onClick={() => setPreferServer(true)}
            >
              Open the browser from the backend instead
            </button>
            .
          </p>
        )}
      </>
    );
  }

  return (
    <Card className="mb-6 shadow-md">
      <CardHeader>
        <CardTitle>Record a new session</CardTitle>
        <CardDescription>
          Enter a URL. A browser opens with the recorder running — use the site
          normally and every interaction is captured.
        </CardDescription>
      </CardHeader>

      <CardContent>
        {error && <Alert className="mb-3">{error}</Alert>}

        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            void start();
          }}
        >
          {!project && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="launch-project">Project</Label>
              <Select
                id="launch-project"
                value={projectId ?? ""}
                onChange={(e) => setProjectId(Number(e.target.value))}
                className="min-w-40"
              >
                {projects.length === 0 && <option value="">No projects</option>}
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </Select>
            </div>
          )}

          <div className="flex min-w-64 flex-1 flex-col gap-1.5">
            <Label htmlFor="launch-url">URL to record</Label>
            <Input
              id="launch-url"
              type="url"
              required
              placeholder="https://your-app.example.com/login"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
          </div>

          <div className="flex min-w-48 flex-1 flex-col gap-1.5">
            <Label htmlFor="launch-name">Name (optional)</Label>
            <Input
              id="launch-name"
              placeholder="Checkout flow"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>

          <Button
            type="submit"
            disabled={busy || !projectId || !url.trim() || installed === undefined}
            className="bg-destructive text-destructive-foreground"
          >
            {busy ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Circle className="size-3 fill-current" />
            )}
            {busy ? "Opening…" : "Start recording"}
          </Button>
        </form>

        <p className="mt-3 flex items-center gap-1.5 text-xs text-muted-foreground">
          <ExternalLink className="size-3" />
          {via === "extension" ? (
            <>
              Opens in a new Chrome tab on this computer, through the AutoQA
              Recorder extension (v{installed?.version}).
            </>
          ) : (
            <>
              The browser opens on the machine where the backend runs.
              {installed && (
                <>
                  {" "}
                  <button
                    type="button"
                    className="text-primary underline-offset-4 hover:underline"
                    onClick={() => setPreferServer(false)}
                  >
                    Use the extension instead
                  </button>
                  .
                </>
              )}
            </>
          )}
        </p>
      </CardContent>
    </Card>
  );
}
