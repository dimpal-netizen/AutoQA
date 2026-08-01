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
import { ArrowLeft, Video } from "lucide-react";
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
      <Link
        href="/projects"
        className="inline-flex w-fit items-center gap-1.5 text-[13px] text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" />
        All projects
      </Link>

      {/* Sized and weighted like every other page title, and given room below —
          it used to sit at text-xl directly against the suite header, so the
          two read as one confused block. */}
      <header className="flex flex-wrap items-center gap-3 border-b border-border pb-5">
        <div className="min-w-0">
          <h1 className="truncate text-[30px] font-extrabold leading-tight tracking-tight">
            {project.name}
          </h1>
          <p className="mt-1 truncate text-sm text-muted-foreground">
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
        />
      ) : (
        <Skeleton className="h-96 w-full" />
      )}
    </div>
  );
}
