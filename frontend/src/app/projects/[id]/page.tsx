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
import { ArrowLeft, ChevronRight, FlaskConical, RefreshCw, Video } from "lucide-react";
import { api } from "@/lib/api";
import type { Project, TestSuite, TestSuiteDetail } from "@/lib/types";
import { AppShell } from "@/components/app-shell";
import { RequireAuth } from "@/components/auth-provider";
import { LaunchRecording } from "@/components/launch-recording";
import { SuiteWorkspace } from "@/components/suite-workspace";
import { Button } from "@/components/ui/button";
import { Alert, EmptyState } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

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
        const found = await api.suites.get(selected);
        if (!cancelled) setDetail(found);
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
      <Link
        href="/projects"
        className="inline-flex w-fit items-center gap-1.5 text-[13px] text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" />
        All projects
      </Link>

      <header className="flex flex-wrap items-center gap-3">
        <div className="min-w-0">
          <h1 className="truncate text-xl font-semibold">{project.name}</h1>
          <p className="truncate text-[13px] text-muted-foreground">
            {project.base_url}
          </p>
        </div>

        <Button className="ml-auto" onClick={() => setRecording((v) => !v)}>
          <Video />
          {recording ? "Close" : "Record a session"}
        </Button>
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
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,17rem)_minmax(0,1fr)]">
          <aside className="flex flex-col gap-1.5">
            <div className="flex items-center justify-between px-1 pb-1">
              <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                Test suites
              </span>
              <button
                type="button"
                onClick={() => void load()}
                className="rounded p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                aria-label="Refresh"
              >
                <RefreshCw className="size-3.5" />
              </button>
            </div>

            {suites.map((suite) => {
              const active = suite.id === selected;
              return (
                <button
                  key={suite.id}
                  type="button"
                  onClick={() => setSelected(suite.id)}
                  className={cn(
                    "group flex items-center gap-2.5 rounded-md border px-3 py-2.5 text-left transition-all",
                    active
                      ? "lit border-primary/35 bg-card ring-1 ring-primary/20"
                      : "border-transparent hover:border-border hover:bg-card/70",
                  )}
                >
                  <FlaskConical
                    className={cn(
                      "size-4 shrink-0",
                      active ? "text-primary" : "text-muted-foreground",
                    )}
                  />
                  <span className="block min-w-0 flex-1 truncate text-[13px] font-medium">
                    {suite.name}
                  </span>
                  <ChevronRight
                    className={cn(
                      "size-3.5 shrink-0 transition-opacity",
                      active
                        ? "text-primary"
                        : "text-muted-foreground opacity-0 group-hover:opacity-100",
                    )}
                  />
                </button>
              );
            })}
          </aside>

          {current ? (
            <SuiteWorkspace suite={current} onChange={setDetail} />
          ) : (
            <Skeleton className="h-96 w-full" />
          )}
        </div>
      )}
    </div>
  );
}
