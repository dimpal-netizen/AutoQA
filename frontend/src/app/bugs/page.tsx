"use client";

/** Every bug, grouped by project.
 *
 *  Bugs were reachable two ways: open the failure that produced one, or export
 *  a spreadsheet per project. Both need you to already know where to look, and
 *  "what is outstanding" is the question you have before you know that.
 *
 *  Grouped by project because a bug means little without knowing what it is a
 *  bug in, and worst-first inside each group because that is the order a triage
 *  meeting reads them.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { Bug } from "lucide-react";
import { api } from "@/lib/api";
import {
  BUG_STATUS_LABEL,
  BUG_STATUS_TONE,
  SEVERITY_TONE,
  formatRelative,
  type BugReport,
  type Severity,
} from "@/lib/types";
import { AppShell } from "@/components/app-shell";
import { RequireAuth } from "@/components/auth-provider";
import { Badge } from "@/components/ui/badge";
import { Alert, EmptyState } from "@/components/ui/card";
import { SearchBox, matches } from "@/components/ui/search";
import { Skeleton } from "@/components/ui/skeleton";

/** Worst first — the order a triage meeting reads them. */
const RANK: Record<Severity, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};

export default function BugsPage() {
  return (
    <RequireAuth>
      <AppShell wide>
        <Bugs />
      </AppShell>
    </RequireAuth>
  );
}

function Bugs() {
  const [bugs, setBugs] = useState<BugReport[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void api.bugs
      .listAll()
      .then((found) => {
        if (!cancelled) setBugs(found);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Could not load bugs");
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

  // Severity and status are searchable, so "critical open" narrows to the
  // argument a triage meeting is actually about.
  const shown = bugs.filter((bug) =>
    matches(
      query,
      bug.title,
      bug.project_name,
      bug.case_name,
      bug.severity,
      bug.status,
    ),
  );

  const byProject = new Map<string, BugReport[]>();
  for (const bug of shown) {
    const key = bug.project_name || "Unknown project";
    byProject.set(key, [...(byProject.get(key) ?? []), bug]);
  }

  const open = bugs.filter(
    (b) => b.status === "draft" || b.status === "open",
  ).length;

  return (
    <div className="flex flex-col gap-5">
      <header>
        <h1 className="text-2xl font-bold leading-tight tracking-tight">Bugs</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {bugs.length === 0
            ? "Drafted from failed tests."
            : `${bugs.length} drafted · ${open} still open.`}
        </p>
      </header>

      {bugs.length > 0 && (
        <SearchBox
          value={query}
          onChange={setQuery}
          placeholder="Search by title, project, test, severity or status…"
          count={shown.length}
          total={bugs.length}
        />
      )}

      {bugs.length === 0 ? (
        <EmptyState
          icon={<Bug />}
          title="No bugs drafted yet"
          description="Open a failed test and choose “Draft a bug report”. Bugs from every project show up here."
        />
      ) : shown.length === 0 ? (
        <EmptyState
          icon={<Bug />}
          title="No bugs match that"
          description="Try a title, a project name, or a severity like “critical”."
        />
      ) : (
        <div className="flex flex-col gap-6">
          {[...byProject.entries()].map(([project, group]) => (
            <section key={project} className="flex flex-col gap-2">
              <h2 className="text-sm font-semibold">{project}</h2>
              <div className="overflow-hidden rounded-lg border border-border">
                {[...group]
                  .sort((a, b) => RANK[a.severity] - RANK[b.severity])
                  .map((bug) => (
                    <BugRow key={bug.id} bug={bug} />
                  ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}

function BugRow({ bug }: { bug: BugReport }) {
  // Links to the failure that produced it where that still exists. `result_id`
  // is nulled when a run is deleted — the bug outlives it, which is why its
  // steps were copied in when it was drafted.
  const body = (
    <>
      <Badge tone={SEVERITY_TONE[bug.severity]}>{bug.severity}</Badge>
      <Badge tone={BUG_STATUS_TONE[bug.status] ?? "neutral"}>
        {BUG_STATUS_LABEL[bug.status] ?? bug.status}
      </Badge>

      <span className="min-w-0 flex-1 truncate">{bug.title}</span>

      {bug.case_name && (
        <span className="hidden max-w-56 truncate text-muted-foreground sm:block">
          {bug.case_name}
        </span>
      )}

      <span className="w-24 text-right text-muted-foreground">
        {formatRelative(bug.created_at)}
      </span>
    </>
  );

  const shared =
    "flex flex-wrap items-center gap-3 border-b border-border px-3.5 py-2.5 text-[13px] last:border-b-0";

  if (!bug.result_id) {
    return <div className={shared}>{body}</div>;
  }

  return (
    <Link
      href={`/results/${bug.result_id}`}
      className={`${shared} transition-colors hover:bg-muted/50`}
    >
      {body}
    </Link>
  );
}
