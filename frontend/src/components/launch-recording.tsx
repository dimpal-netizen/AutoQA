"use client";

import { useEffect, useState } from "react";
import { Circle, ExternalLink, Loader2, Square } from "lucide-react";
import { api } from "@/lib/api";
import type { Project, RecordingSession } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import {
  Alert,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

/** Enter a URL, get a browser window with the recorder already running.
 *
 *  The recorder cannot be injected across origins from this page, so the
 *  backend launches Chromium with Playwright and injects it from outside. */
export function LaunchRecording({ onChanged }: { onChanged: () => void }) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<number | null>(null);
  const [url, setUrl] = useState("");
  const [name, setName] = useState("");
  const [live, setLive] = useState<RecordingSession | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.projects
      .list()
      .then((list) => {
        setProjects(list);
        setProjectId((current) => current ?? list[0]?.id ?? null);
        // Pre-fill with the project's own URL — usually what you want to record.
        setUrl((current) => current || (list[0]?.base_url ?? ""));
      })
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Could not load projects"),
      );
  }, []);

  // While a window is open, poll so the action count ticks up here too, and so
  // we notice the user closing the browser window directly.
  useEffect(() => {
    if (!live) return;
    const timer = setInterval(async () => {
      try {
        const sessions = await api.recordings.list();
        const current = sessions.find((s) => s.id === live.id);
        onChanged();
        if (!current?.browser_open) setLive(null);
        else setLive(current);
      } catch {
        /* transient — keep polling */
      }
    }, 1500);
    return () => clearInterval(timer);
  }, [live, onChanged]);

  async function start() {
    if (!projectId) return;
    setBusy(true);
    setError(null);
    try {
      const session = await api.recordings.launch(projectId, {
        url: url.trim(),
        name: name.trim() || undefined,
      });
      setLive(session);
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
      await api.recordings.close(live.id);
      setLive(null);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not stop the recording");
    } finally {
      setBusy(false);
    }
  }

  if (live) {
    return (
      <Card className="mb-6 border-destructive/40">
        <CardContent className="flex flex-wrap items-center gap-4 py-4">
          <span className="flex items-center gap-2 font-medium">
            <span className="size-2.5 animate-pulse rounded-full bg-destructive" />
            Recording
          </span>

          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{live.name}</p>
            <p className="truncate text-xs text-muted-foreground">{live.start_url}</p>
          </div>

          <span className="text-sm text-muted-foreground">
            <b className="text-foreground">{live.action_count}</b> actions
          </span>

          <Button variant="destructive" size="sm" disabled={busy} onClick={stop}>
            <Square className="size-4 fill-current" />
            Stop
          </Button>
        </CardContent>

        <CardContent className="pt-0 text-xs text-muted-foreground">
          A browser window is open — switch to it and use the site normally.
          Everything you do is captured. You can also press Stop in the panel
          inside that window, or just close it.
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="mb-6">
      <CardHeader>
        <CardTitle className="text-base">Record a new session</CardTitle>
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
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="launch-project">Project</Label>
            <select
              id="launch-project"
              value={projectId ?? ""}
              onChange={(e) => setProjectId(Number(e.target.value))}
              className="h-10 min-w-40 rounded-md border border-input bg-background px-2 text-sm"
            >
              {projects.length === 0 && <option value="">No projects</option>}
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
          </div>

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
            disabled={busy || !projectId || !url.trim()}
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
          The browser opens on this machine, where the backend runs.
        </p>
      </CardContent>
    </Card>
  );
}
