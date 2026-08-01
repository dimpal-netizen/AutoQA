"use client";

/** The dashboard: how testing is going, and what needs attention.
 *
 *  An earlier attempt at this page showed the four steps of the product with
 *  ticks against them, which is onboarding — useless the second time you see
 *  it. This shows data instead: the numbers, the trend, and the failures that
 *  are actually waiting for someone.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  CircleAlert,
  FlaskConical,
  FolderKanban,
  Video,
} from "lucide-react";
import { api } from "@/lib/api";
import {
  BROWSER_LABEL,
  RUN_BADGE,
  type Browser,
  type Project,
  type TestResult,
  type TestRun,
  type TestSuite,
} from "@/lib/types";
import { AppShell } from "@/components/app-shell";
import { RequireAuth } from "@/components/auth-provider";
import { RunTrend, type TrendPoint } from "@/components/run-trend";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, EmptyState } from "@/components/ui/card";
import { Hero, Meter } from "@/components/ui/stat";
import { SkeletonRows } from "@/components/ui/skeleton";

export default function DashboardPage() {
  return (
    <RequireAuth>
      <AppShell wide>
        <Dashboard />
      </AppShell>
    </RequireAuth>
  );
}

interface Failure {
  result: TestResult;
  run: TestRun;
}

function Dashboard() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [suites, setSuites] = useState<TestSuite[]>([]);
  const [runs, setRuns] = useState<TestRun[]>([]);
  const [failures, setFailures] = useState<Failure[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [p, s, r] = await Promise.all([
          api.projects.list().catch(() => [] as Project[]),
          api.suites.list().catch(() => [] as TestSuite[]),
          api.runs.list().catch(() => [] as TestRun[]),
        ]);
        if (cancelled) return;
        setProjects(p);
        setSuites(s);
        setRuns(r);

        // Failures come from the most recent finished runs only. Every run
        // ever would be a list of things already fixed, which is noise
        // dressed as a to-do list.
        const recent = r.filter((run) => run.failed > 0).slice(0, 3);
        const detailed = await Promise.all(
          recent.map((run) =>
            api.runs
              .get(run.id)
              .then((full) =>
                full.results
                  .filter((x) => x.status === "failed" || x.status === "error")
                  .map((result) => ({ result, run })),
              )
              .catch(() => [] as Failure[]),
          ),
        );
        if (!cancelled) setFailures(detailed.flat().slice(0, 8));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) return <SkeletonRows count={4} />;

  const finished = runs.filter((r) => r.total > 0);
  const totalPassed = finished.reduce((sum, r) => sum + r.passed, 0);
  const totalTests = finished.reduce((sum, r) => sum + r.total, 0);
  const passRate = totalTests ? Math.round((totalPassed / totalTests) * 100) : null;
  const latest = runs[0];

  // Oldest first, so the trend reads left to right like time does.
  const trend: TrendPoint[] = finished
    .slice(0, 12)
    .reverse()
    .map((run) => ({
      id: run.id,
      label: `Run ${run.id}`,
      passed: run.passed,
      failed: run.failed,
    }));

  if (projects.length === 0) {
    return (
      <EmptyState
        icon={<FolderKanban />}
        title="Nothing to show yet"
        description="Add the web application you want to test, then record a session. The dashboard fills in from there."
        action={
          <Link href="/projects">
            <Button>
              <FolderKanban />
              Add a project
            </Button>
          </Link>
        }
      />
    );
  }

  return (
    <div className="animate-in flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">Dashboard</h1>
        <Link href="/projects">
          <Button>
            <Video />
            Record a session
          </Button>
        </Link>
      </div>

      {/* One hero, and the supporting numbers deliberately smaller. Five
          equal tiles is five things shouting at the same volume, which is the
          same as none of them being important. */}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
        <Card className="flex flex-col justify-between gap-6 p-5">
          <Hero
            label="Pass rate"
            value={passRate === null ? "—" : `${passRate}%`}
            tone={
              passRate === null
                ? "muted"
                : passRate === 100
                  ? "success"
                  : passRate >= 80
                    ? "warning"
                    : "danger"
            }
            hint={
              totalTests
                ? `${totalPassed} of ${totalTests} tests across ${finished.length} run${finished.length === 1 ? "" : "s"}`
                : "nothing run yet"
            }
          >
            <Meter
              className="mt-4"
              value={passRate ?? 0}
              tone={
                passRate === null
                  ? "muted"
                  : passRate === 100
                    ? "success"
                    : passRate >= 80
                      ? "warning"
                      : "danger"
              }
            />
          </Hero>

          <dl className="grid grid-cols-3 gap-3 border-t border-border pt-4">
            <Mini label="Suites" value={suites.length} />
            <Mini
              label="Last run"
              value={latest ? `${latest.passed}/${latest.total}` : "—"}
              tone={latest && latest.failed > 0 ? "danger" : "default"}
            />
            <Mini
              label="To triage"
              value={failures.length}
              tone={failures.length ? "danger" : "success"}
            />
          </dl>
        </Card>

        <Card className="flex flex-col">
          <CardHeader>
            <CardTitle>Runs over time</CardTitle>
          </CardHeader>
          <CardContent className="flex-1">
            <RunTrend points={trend} />
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,20rem)]">
      <section>
        <h2 className="mb-2.5 flex items-center gap-2 text-sm font-semibold">
          <CircleAlert className="size-4 text-destructive" />
          Needs attention
          {failures.length > 0 && (
            <span className="tabular text-muted-foreground">{failures.length}</span>
          )}
        </h2>

        {failures.length === 0 ? (
          <Card className="px-4 py-8 text-center text-[13px] text-muted-foreground">
            Nothing is failing. {runs.length === 0 && "Run a suite to find out for sure."}
          </Card>
        ) : (
          <div className="flex flex-col gap-2">
            {failures.map(({ result, run }) => (
              <Link
                key={`${run.id}-${result.id}`}
                href={`/projects/${run.project_id}`}
                className="group"
              >
                <Card className="flex flex-wrap items-center gap-3 px-4 py-3 transition-all hover:border-border-strong hover:shadow-md">
                  <Badge tone={RUN_BADGE[run.status]}>{result.status}</Badge>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] font-medium">
                      {result.case_name}
                    </span>
                    {result.error_message && (
                      <span className="mt-0.5 block truncate font-mono text-xs text-muted-foreground">
                        {result.error_message}
                      </span>
                    )}
                  </span>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {BROWSER_LABEL[result.browser as Browser] ?? result.browser}
                  </span>
                  <ArrowRight className="size-3.5 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
                </Card>
              </Link>
            ))}
          </div>
        )}
      </section>

      <section>
        <h2 className="mb-2.5 text-sm font-semibold">Projects</h2>
        <div className="flex flex-col gap-2">
          {projects.slice(0, 6).map((project) => (
            <Link key={project.id} href={`/projects/${project.id}`} className="group">
              <Card className="flex items-center gap-2.5 px-4 py-3 transition-all hover:border-border-strong hover:shadow-md">
                <FolderKanban className="size-4 shrink-0 text-primary" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-medium">
                    {project.name}
                  </span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {project.base_url}
                  </span>
                </span>
                <ArrowRight className="size-3.5 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
              </Card>
            </Link>
          ))}
        </div>
      </section>
      </div>

      {suites.length === 0 && (
        <EmptyState
          icon={<FlaskConical />}
          title="No tests yet"
          description="Open a project and record a session — the tests are written when you stop."
        />
      )}
    </div>
  );
}

/** A supporting number under the hero — deliberately quiet. */
function Mini({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: React.ReactNode;
  tone?: "default" | "success" | "danger";
}) {
  const colour = {
    default: "text-foreground",
    success: "text-success",
    danger: "text-destructive",
  }[tone];

  return (
    <div>
      <dt className="text-[11px] uppercase tracking-wide text-muted-foreground">
        {label}
      </dt>
      <dd className={`mt-0.5 text-lg font-semibold leading-none ${colour}`}>
        {value}
      </dd>
    </div>
  );
}
