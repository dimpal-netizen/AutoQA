"use client";

/** Every run, grouped by project.
 *
 *  Runs used to be reachable one way: pick a project, pick a suite, open the
 *  Runs tab. That answers "how did this suite do", which is a question you have
 *  after you already know where to look. The question you have first thing in
 *  the morning is "what ran and what broke", and nothing answered it.
 *
 *  Grouped rather than a flat list because a run means little without knowing
 *  what it ran against, and reading a project name on every row of forty is
 *  worse than reading it once per group.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { Play } from "lucide-react";
import { api } from "@/lib/api";
import {
  RUN_BADGE,
  formatDuration,
  formatRelative,
  isRunActive,
  type TestRun,
} from "@/lib/types";
import { AppShell } from "@/components/app-shell";
import { RequireAuth } from "@/components/auth-provider";
import { Badge, LiveDot } from "@/components/ui/badge";
import { Alert, EmptyState } from "@/components/ui/card";
import { SearchBox, matches } from "@/components/ui/search";
import { Skeleton } from "@/components/ui/skeleton";

export default function RunsPage() {
  return (
    <RequireAuth>
      <AppShell wide>
        <Runs />
      </AppShell>
    </RequireAuth>
  );
}

function Runs() {
  const [runs, setRuns] = useState<TestRun[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void api.runs
      .list()
      .then((found) => {
        if (!cancelled) setRuns(found);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Could not load runs");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (error) return <Alert>{error}</Alert>;

  // The status is searchable too, so "failed" narrows to what broke — the
  // commonest thing anyone comes to this page wanting.
  const shown = runs.filter((run) =>
    matches(query, run.project_name, run.suite_name, run.status),
  );

  // Grouped in the order they arrived, which is newest first — so the project
  // that ran most recently is the one at the top of the page.
  const byProject = new Map<string, TestRun[]>();
  for (const run of shown) {
    const key = run.project_name || "Unknown project";
    byProject.set(key, [...(byProject.get(key) ?? []), run]);
  }

  return (
    <div className="flex flex-col gap-5">
      <header>
        <h1 className="text-2xl font-bold leading-tight tracking-tight">Runs</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Everything that has run, newest first.
        </p>
      </header>

      {runs.length > 0 && (
        <SearchBox
          value={query}
          onChange={setQuery}
          placeholder="Search by project, suite or status…"
          count={shown.length}
          total={runs.length}
        />
      )}

      {runs.length === 0 ? (
        <EmptyState
          icon={<Play />}
          title="Nothing has run yet"
          description="Open a project, pick a suite and press Run tests. Runs from every project show up here."
        />
      ) : shown.length === 0 ? (
        <EmptyState
          icon={<Play />}
          title="No runs match that"
          description="Try a project name, a suite name, or a status like “failed”."
        />
      ) : (
        <div className="flex flex-col gap-6">
          {[...byProject.entries()].map(([project, group]) => (
            <section key={project} className="flex flex-col gap-2">
              <h2 className="text-sm font-semibold">{project}</h2>
              <div className="overflow-hidden rounded-lg border border-border">
                {group.map((run) => (
                  <RunRow key={run.id} run={run} />
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}

/** One run, in fixed columns.
 *
 *  Every column after the name has a width and a right edge, because the whole
 *  point of a list is reading down it. Laid out with `gap` alone, "1 failed"
 *  and "14 passed · 2 failed" start in different places on consecutive rows, and
 *  the eye has to find the number on every line instead of scanning one column.
 */
function RunRow({ run }: { run: TestRun }) {
  const active = isRunActive(run);

  return (
    <Link
      href={`/projects/${run.project_id}`}
      className="flex items-center gap-3 border-b border-border px-3.5 py-2.5 text-[13px] transition-colors last:border-b-0 hover:bg-muted/50"
    >
      <span className="w-20 shrink-0">
        <Badge tone={RUN_BADGE[run.status]}>
          {active && <LiveDot />}
          {run.status}
        </Badge>
      </span>

      {/* Empty once the suite is deleted. A run outlives what it ran, which is
          the point of keeping it — so it says so rather than showing nothing. */}
      <span className="min-w-0 flex-1 truncate">
        {run.suite_name || (
          <span className="text-muted-foreground">suite deleted</span>
        )}
      </span>

      {/* A dash rather than a blank when nothing ran at all — two empty columns
          read as a rendering fault. The badge beside it already says why. */}
      <span className="tabular w-16 shrink-0 text-right text-success">
        {run.passed > 0 ? (
          `${run.passed} passed`
        ) : run.failed === 0 ? (
          <span className="text-muted-foreground">—</span>
        ) : null}
      </span>

      <span className="tabular w-16 shrink-0 text-right font-medium text-destructive">
        {run.failed > 0 && `${run.failed} failed`}
      </span>

      <span className="tabular w-16 shrink-0 text-right text-muted-foreground">
        {run.duration_ms !== null ? formatDuration(run.duration_ms) : ""}
      </span>

      <span className="w-20 shrink-0 text-right text-muted-foreground">
        {formatRelative(run.finished_at ?? run.created_at)}
      </span>
    </Link>
  );
}
