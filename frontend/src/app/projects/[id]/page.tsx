"use client";

/** One project: record into it, and work on the tests it produced.
 *
 *  The entry point is the project list, and everything after that happens in
 *  here. That ordering is not decoration — it is what lets the record panel
 *  drop the "which project?" dropdown, because by the time you can press
 *  Record the answer is already on screen.
 */

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, ExternalLink, Video } from "lucide-react";
import { api } from "@/lib/api";
import type { Project, TestRun, TestSuite, TestSuiteDetail } from "@/lib/types";
import { AppShell } from "@/components/app-shell";
import { RequireAuth } from "@/components/auth-provider";
import { LaunchRecording } from "@/components/launch-recording";
import { SuiteWorkspace } from "@/components/suite-workspace";
import { Button } from "@/components/ui/button";
import { Alert, EmptyState } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export default function ProjectPage({
  params,
}: {
  // Next 16: params is a Promise, unwrapped with React's use().
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  return (
    <RequireAuth>
      <AppShell wide>
        <ProjectWorkspace id={Number(id)} />
      </AppShell>
    </RequireAuth>
  );
}

function ProjectWorkspace({ id }: { id: number }) {
  const [project, setProject] = useState<Project | null>(null);
  const [suites, setSuites] = useState<TestSuite[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<TestSuiteDetail | null>(null);
  const [lastRun, setLastRun] = useState<TestRun | null>(null);
  const [recording, setRecording] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [found, list] = await Promise.all([
        api.projects.get(id),
        api.suites.list(id),
      ]);
      setProject(found);
      setSuites(list);
      setSelected((current) => current ?? list[0]?.id ?? null);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load this project");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    void (async () => {
      await load();
    })();
  }, [load]);

  useEffect(() => {
    if (selected === null) return;
    let cancelled = false;
    void (async () => {
      try {
        const [found, runs] = await Promise.all([
          api.suites.get(selected),
          api.runs.list({ suiteId: selected }).catch(() => [] as TestRun[]),
        ]);
        if (cancelled) return;
        setDetail(found);
        setLastRun(runs[0] ?? null);
      } catch {
        /* keep what is on screen; the id check below hides a stale one */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selected]);

  const current = detail && detail.id === selected ? detail : null;

  if (loading) return <Skeleton className="h-96 w-full" />;
  if (!project) return <Alert>{error ?? "Project not found"}</Alert>;

  return (
    <div className="animate-in flex flex-col gap-4">
      {/* Above the panel, not inside it. The panel is this project — its name,
          its URL, the button that records into it. A link that leaves the
          project is not part of the project, and putting it in the same box
          made the box mean two things. */}
      <Link
        href="/projects"
        className="inline-flex w-fit items-center gap-1.5 text-[13px] font-medium text-muted-foreground transition-colors hover:text-primary"
      >
        <ArrowLeft className="size-3.5" />
        All projects
      </Link>

      <header className="relative overflow-hidden rounded-2xl border border-border bg-card px-6 py-6 shadow-xs sm:px-8">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              "linear-gradient(120deg, var(--primary-subtle) 0%, transparent 62%)",
          }}
        />

        <div className="relative flex flex-wrap items-start gap-4">
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-[30px] font-extrabold leading-tight tracking-tight">
              {project.name}
            </h1>

            <a
              href={project.base_url}
              target="_blank"
              rel="noreferrer noopener"
              className="mt-1.5 inline-flex max-w-full items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-primary"
            >
              <span className="truncate">{project.base_url}</span>
              <ExternalLink className="size-3.5 shrink-0" />
            </a>
          </div>

          <Button size="lg" onClick={() => setRecording((v) => !v)}>
            <Video />
            {recording ? "Close" : "Record a session"}
          </Button>
        </div>
      </header>

      {error && <Alert>{error}</Alert>}

      {recording && (
        <LaunchRecording
          project={project}
          onChanged={() => {
            void load();
          }}
        />
      )}

      {suites.length === 0 ? (
        <EmptyState
          icon={<Video />}
          title="Nothing recorded yet"
          description="Press Record a session. A browser opens on this project's URL — use the site normally, and the tests are written when you stop."
          action={
            <Button onClick={() => setRecording(true)}>
              <Video />
              Record a session
            </Button>
          }
        />
      ) : current ? (
        <SuiteWorkspace
          suite={current}
          suites={suites}
          lastRun={lastRun}
          onSelect={setSelected}
          onChange={(updated) => {
            setDetail(updated);
            void load();
          }}
          onDeleted={() => {
            // Clear the selection before reloading. `load` only fills it in
            // when it is null, so leaving it pointing at the deleted suite
            // would leave the workspace stuck on a suite that is gone.
            setSelected(null);
            setDetail(null);
            setLastRun(null);
            void load();
          }}
        />
      ) : (
        <Skeleton className="h-96 w-full" />
      )}
    </div>
  );
}
