"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Circle, Crosshair, Pause, Play, Square } from "lucide-react";
import { api } from "@/lib/api";
import type { Project } from "@/lib/types";
import { useAuthStore } from "@/stores/auth-store";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/** Shape exposed by public/recorder.js on window. */
type RecorderStatus = "idle" | "recording" | "paused" | "stopping";

interface RecorderSnapshot {
  status: RecorderStatus;
  captured: number;
  uploaded: number;
  pending?: number;
  sessionId?: number | null;
  lastAction?: string | null;
  assertMode?: boolean;
  error?: string | null;
}

interface RecorderApi {
  start(options?: {
    projectId?: number;
    name?: string;
    panel?: boolean;
  }): Promise<RecorderSnapshot>;
  pause(): RecorderSnapshot;
  resume(): RecorderSnapshot;
  stop(): Promise<RecorderSnapshot & { sessionId?: number | null }>;
  setAssertMode(on: boolean): void;
  getState(): RecorderSnapshot;
  subscribe(fn: (s: RecorderSnapshot) => void): () => void;
}

declare global {
  interface Window {
    AutoQARecorder?: RecorderApi;
  }
}

// Served by the backend so Playwright and the web app share one copy — the
// two injection paths must never drift apart.
const RECORDER_SRC = (
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1"
).replace(/\/api\/v1\/?$/, "/static/recorder.js");

/** Floating recorder controls.
 *
 *  The recorder has to run in the page being tested, so this only works on
 *  pages served from this origin (the demo page). Recording a third-party site
 *  is what the Phase 9 Chrome extension is for. */
export function RecorderBar() {
  const [ready, setReady] = useState(false);
  const [snapshot, setSnapshot] = useState<RecorderSnapshot>({
    status: "idle",
    captured: 0,
    uploaded: 0,
  });
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [finished, setFinished] = useState<{ id: number; count: number } | null>(null);
  const unsubscribe = useRef<(() => void) | null>(null);

  // The auth store uses skipHydration, so the token is not in memory on the
  // first render. Fetching before this flips would send an unauthenticated
  // request and leave the bar permanently disabled.
  const hydrated = useAuthStore((s) => s.hydrated);
  const signedIn = useAuthStore((s) => Boolean(s.accessToken));

  // Load recorder.js once, then subscribe to its state.
  useEffect(() => {
    let cancelled = false;

    function bind() {
      if (cancelled || !window.AutoQARecorder) return;
      unsubscribe.current = window.AutoQARecorder.subscribe(setSnapshot);
      setReady(true);
    }

    if (window.AutoQARecorder) {
      bind();
    } else {
      const script = document.createElement("script");
      script.src = RECORDER_SRC;
      script.onload = bind;
      script.onerror = () => !cancelled && setError("Could not load recorder.js");
      document.head.appendChild(script);
    }

    return () => {
      cancelled = true;
      unsubscribe.current?.();
    };
  }, []);

  useEffect(() => {
    if (!hydrated || !signedIn) return;
    api.projects
      .list()
      .then((list) => {
        setProjects(list);
        setProjectId((current) => current ?? list[0]?.id ?? null);
      })
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Could not load projects"),
      );
  }, [hydrated, signedIn]);

  const handleStart = useCallback(async () => {
    setError(null);
    setFinished(null);
    try {
      // panel:false — this bar is the UI, so suppress the recorder's own panel.
      await window.AutoQARecorder!.start({
        projectId: projectId ?? undefined,
        name: name.trim() || undefined,
        panel: false,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start recording");
    }
  }, [projectId, name]);

  const handleStop = useCallback(async () => {
    try {
      const result = await window.AutoQARecorder!.stop();
      if (result.sessionId) {
        setFinished({ id: result.sessionId, count: result.captured });
      }
      setName("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not stop recording");
    }
  }, []);

  const idle = snapshot.status === "idle";
  const paused = snapshot.status === "paused";
  const busy = snapshot.status === "stopping";

  return (
    // data-autoqa-ignore stops the recorder capturing clicks on its own controls.
    <div
      data-autoqa-ignore
      className="fixed bottom-4 left-1/2 z-50 w-[min(680px,calc(100vw-2rem))] -translate-x-1/2 rounded-xl border border-border bg-card p-3 shadow-lg"
    >
      {(error || snapshot.error) && (
        <p className="mb-2 rounded-md border border-destructive/40 bg-destructive/10 px-2 py-1 text-xs text-destructive">
          {error ?? snapshot.error}
        </p>
      )}

      {finished && idle && (
        <p className="mb-2 rounded-md border border-success/40 bg-success/10 px-2 py-1 text-xs text-success">
          Saved {finished.count} actions.{" "}
          <Link
            href={`/recordings/${finished.id}`}
            className="underline underline-offset-4"
          >
            View recording →
          </Link>
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {!hydrated ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : !signedIn ? (
          <p className="text-sm text-muted-foreground">
            <Link href="/login" className="text-foreground underline underline-offset-4">
              Sign in
            </Link>{" "}
            to record.
          </p>
        ) : projects.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            <Link href="/projects" className="text-foreground underline underline-offset-4">
              Create a project
            </Link>{" "}
            before recording.
          </p>
        ) : idle ? (
          <>
            <select
              aria-label="Project"
              value={projectId ?? ""}
              onChange={(e) => setProjectId(Number(e.target.value))}
              className="h-9 min-w-32 rounded-md border border-input bg-background px-2 text-sm"
            >
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>

            <Input
              aria-label="Recording name"
              placeholder="Recording name (optional)"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="h-9 flex-1"
            />

            <Button
              onClick={handleStart}
              disabled={!ready}
              className="bg-destructive text-destructive-foreground"
            >
              <Circle className="size-3 fill-current" />
              Start recording
            </Button>
          </>
        ) : (
          <>
            <span className="flex items-center gap-2 text-sm font-medium">
              <span
                className={`size-2.5 rounded-full ${
                  paused ? "bg-muted-foreground" : "animate-pulse bg-destructive"
                }`}
              />
              {paused ? "Paused" : "Recording"}
            </span>

            <span className="text-sm text-muted-foreground">
              <b className="text-foreground">{snapshot.captured}</b> captured ·{" "}
              <b className="text-foreground">{snapshot.uploaded}</b> saved
            </span>

            <span className="min-w-0 flex-1 truncate font-mono text-xs text-muted-foreground">
              {snapshot.lastAction ?? "…"}
            </span>

            <Button
              variant={snapshot.assertMode ? "default" : "outline"}
              size="sm"
              disabled={paused || busy}
              onClick={() => window.AutoQARecorder!.setAssertMode(!snapshot.assertMode)}
              title="Record an assertion instead of a click (Alt+A)"
            >
              <Crosshair className="size-4" />
              {snapshot.assertMode ? "Click a target" : "Assert"}
            </Button>

            <Button
              variant="outline"
              size="sm"
              disabled={busy}
              onClick={() =>
                paused ? window.AutoQARecorder!.resume() : window.AutoQARecorder!.pause()
              }
            >
              {paused ? <Play className="size-4" /> : <Pause className="size-4" />}
              {paused ? "Resume" : "Pause"}
            </Button>

            <Button variant="destructive" size="sm" disabled={busy} onClick={handleStop}>
              <Square className="size-4 fill-current" />
              {busy ? "Saving…" : "Stop"}
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
