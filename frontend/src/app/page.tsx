"use client";

/** Overview: what state your testing is in, and what to do next.
 *
 *  This replaced a redirect straight to Projects, which dropped you into a
 *  list with no indication that recording came next, then generating, then
 *  running. The pipeline is the product; the pages are just where its parts
 *  live.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  FlaskConical,
  FolderKanban,
  Play,
  Video,
} from "lucide-react";
import { api } from "@/lib/api";
import {
  RUN_BADGE,
  formatDuration,
  type Project,
  type RecordingSession,
  type TestRun,
  type TestSuite,
} from "@/lib/types";
import { useAuthStore } from "@/stores/auth-store";
import { AppShell } from "@/components/app-shell";
import { RequireAuth } from "@/components/auth-provider";
import { Pipeline, type Step } from "@/components/pipeline";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, PageHeader } from "@/components/ui/card";
import { SkeletonRows } from "@/components/ui/skeleton";

export default function HomePage() {
  return (
    <RequireAuth>
      <AppShell>
        <Overview />
      </AppShell>
    </RequireAuth>
  );
}

function Overview() {
  const user = useAuthStore((s) => s.user);
  const [projects, setProjects] = useState<Project[]>([]);
  const [recordings, setRecordings] = useState<RecordingSession[]>([]);
  const [suites, setSuites] = useState<TestSuite[]>([]);
  const [runs, setRuns] = useState<TestRun[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      // One shot for everything the overview needs. A failure falls back to an
      // empty list rather than blanking the page: a missing run history is no
      // reason to hide the pipeline.
      const [p, r, s, ru] = await Promise.all([
        api.projects.list().catch(() => [] as Project[]),
        api.recordings.list().catch(() => [] as RecordingSession[]),
        api.suites.list().catch(() => [] as TestSuite[]),
        api.runs.list().catch(() => [] as TestRun[]),
      ]);
      if (cancelled) return;
      setProjects(p);
      setRecordings(r);
      setSuites(s);
      setRuns(ru);
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) return <SkeletonRows count={3} />;

  const latestSuite = suites[0];
  const firstName = (user?.full_name || user?.email || "").split(/[\s@]/)[0];

  const steps: Step[] = [
    {
      id: "project",
      label: "1 · Add a project",
      detail: "The web application you want to test.",
      icon: <FolderKanban />,
      href: "/projects",
      done: projects.length > 0,
    },
    {
      id: "record",
      label: "2 · Record a session",
      detail: "A browser opens; use the site normally.",
      icon: <Video />,
      href: "/recordings",
      done: recordings.length > 0,
    },
    {
      id: "tests",
      label: "3 · Review the tests",
      detail: "Written for you the moment you stop.",
      icon: <FlaskConical />,
      href: latestSuite ? `/suites/${latestSuite.id}` : "/suites",
      done: suites.length > 0,
    },
    {
      id: "run",
      label: "4 · Run them",
      detail: "Chrome, Firefox and Safari at once.",
      icon: <Play />,
      href: latestSuite ? `/suites/${latestSuite.id}` : "/suites",
      done: runs.length > 0,
    },
  ];

  return (
    <div className="animate-in">
      <PageHeader
        title={firstName ? `Hello, ${firstName}` : "Overview"}
        description="Record what a tester would do, and AutoQA writes and runs the tests."
      >
        <Link href="/recordings">
          <Button>
            <Video />
            Record a session
          </Button>
        </Link>
      </PageHeader>

      <Pipeline steps={steps} />

      <div className="mt-8 grid gap-4 lg:grid-cols-2">
        <RecentSuites suites={suites} />
        <RecentRuns runs={runs} />
      </div>
    </div>
  );
}

function RecentSuites({ suites }: { suites: TestSuite[] }) {
  return (
    <section>
      <h2 className="mb-2.5 text-sm font-semibold">Your tests</h2>
      {suites.length === 0 ? (
        <Card className="px-4 py-6 text-center text-[13px] text-muted-foreground">
          Nothing yet — record a session and a suite appears here.
        </Card>
      ) : (
        <div className="flex flex-col gap-2">
          {suites.slice(0, 4).map((suite) => (
            <Link key={suite.id} href={`/suites/${suite.id}`} className="group">
              <Card className="flex items-center gap-3 px-4 py-3 transition-all hover:border-border-strong hover:shadow-md">
                <FlaskConical className="size-4 shrink-0 text-primary" />
                <span className="min-w-0 flex-1 truncate text-[13px] font-medium">
                  {suite.name}
                </span>
                <ArrowRight className="size-3.5 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
              </Card>
            </Link>
          ))}
        </div>
      )}
    </section>
  );
}

function RecentRuns({ runs }: { runs: TestRun[] }) {
  return (
    <section>
      <h2 className="mb-2.5 text-sm font-semibold">Recent runs</h2>
      {runs.length === 0 ? (
        <Card className="px-4 py-6 text-center text-[13px] text-muted-foreground">
          No runs yet. Open a suite and press Run tests.
        </Card>
      ) : (
        <div className="flex flex-col gap-2">
          {runs.slice(0, 4).map((run) => (
            <Link
              key={run.id}
              href={run.suite_id ? `/suites/${run.suite_id}` : "/suites"}
              className="group"
            >
              <Card className="flex items-center gap-3 px-4 py-3 transition-all hover:border-border-strong hover:shadow-md">
                <Badge tone={RUN_BADGE[run.status]}>{run.status}</Badge>
                <span className="tabular text-[13px]">
                  <span className="font-medium text-success">{run.passed}</span>
                  {run.failed > 0 && (
                    <>
                      {" / "}
                      <span className="font-medium text-destructive">
                        {run.failed}
                      </span>
                    </>
                  )}
                  <span className="text-muted-foreground"> of {run.total}</span>
                </span>
                <span className="tabular ml-auto text-xs text-muted-foreground">
                  {formatDuration(run.duration_ms)}
                </span>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </section>
  );
}
