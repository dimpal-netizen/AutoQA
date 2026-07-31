"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowLeft,
  Check,
  Copy,
  FlaskConical,
  FolderOpen,
  Play,
  RefreshCw,
  Video,
} from "lucide-react";
import { api } from "@/lib/api";
import {
  RELIABLE_RANK,
  SELECTOR_RANK,
  formatDuration,
  type TestRun,
  type TestSuiteDetail,
} from "@/lib/types";
import { AppShell } from "@/components/app-shell";
import { RequireAuth } from "@/components/auth-provider";
import { RunPanel } from "@/components/run-panel";
import { GenerateCases } from "@/components/generate-cases";
import { TestCaseList } from "@/components/test-case-list";
import { Button } from "@/components/ui/button";
import {
  Alert,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  PageHeader,
} from "@/components/ui/card";
import { SkeletonRows } from "@/components/ui/skeleton";
import { Tabs } from "@/components/ui/tabs";
import { Stat, StatRow } from "@/components/ui/stat";

export default function SuiteDetailPage({
  params,
}: {
  // Next 16: params is a Promise, unwrapped with React's use().
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  return (
    <RequireAuth>
      <AppShell>
        <SuiteDetail id={Number(id)} />
      </AppShell>
    </RequireAuth>
  );
}

function SuiteDetail({ id }: { id: number }) {
  const [suite, setSuite] = useState<TestSuiteDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [regenerating, setRegenerating] = useState(false);
  const [tab, setTab] = useState("run");
  const [lastRun, setLastRun] = useState<TestRun | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [data, runs] = await Promise.all([
          api.suites.get(id),
          api.runs.list({ suiteId: id }).catch(() => [] as TestRun[]),
        ]);
        if (!cancelled) {
          setSuite(data);
          setLastRun(runs[0] ?? null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Could not load this suite");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id]);

  async function regenerate() {
    if (!suite?.recording_id) return;
    setRegenerating(true);
    setError(null);
    try {
      setSuite(await api.suites.regenerate(suite.recording_id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not regenerate");
    } finally {
      setRegenerating(false);
    }
  }

  if (error && !suite) {
    return (
      <div>
        <Alert>{error}</Alert>
      </div>
    );
  }
  if (!suite) {
    return <SkeletonRows count={3} />;
  }

  const steps = suite.cases.flatMap((c) => c.steps);
  const fragile = steps.filter(
    (s) => s.selector_strategy && SELECTOR_RANK[s.selector_strategy] > RELIABLE_RANK,
  );
  // Paths only — the scripts are reviewed in VS Code, not here.
  const paths = [
    ...suite.cases.map((c) => c.file_path),
    ...suite.files.map((f) => f.path),
  ].sort();

  return (
    <div className="animate-in">
      <Link
        href="/suites"
        className="mb-5 inline-flex items-center gap-1.5 text-[13px] text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" />
        All tests
      </Link>

      <PageHeader title={suite.name} description={suite.description}>
        {suite.recording_id && (
          <>
            <Link href={`/recordings/${suite.recording_id}`}>
              <Button variant="outline">
                <Video />
                Recording
              </Button>
            </Link>
            <Button variant="outline" disabled={regenerating} onClick={regenerate}>
              <RefreshCw className={regenerating ? "animate-spin" : ""} />
              {regenerating ? "Regenerating…" : "Regenerate"}
            </Button>
          </>
        )}
      </PageHeader>

      {error && <Alert className="mt-4">{error}</Alert>}

      <SuiteStats
        suite={suite}
        steps={steps.length}
        fragile={fragile.length}
        run={lastRun}
      />

      <Tabs
        className="mt-8"
        active={tab}
        onChange={setTab}
        tabs={[
          { id: "run", label: "Run", icon: <Play /> },
          {
            id: "cases",
            label: "Test cases",
            count: suite.cases.length,
            icon: <FlaskConical />,
          },
          {
            id: "scripts",
            label: "Scripts",
            count: paths.length,
            icon: <FolderOpen />,
          },
        ]}
      />

      <div className="mt-6">
        {tab === "run" && (
          <RunPanel suiteId={suite.id} caseCount={suite.cases.length} />
        )}

        {tab === "cases" && (
          <div className="flex flex-col gap-6">
            <div className="rounded-lg border border-dashed border-border bg-muted/30 p-4">
              <GenerateCases
                suiteId={suite.id}
                hasGenerated={suite.cases.some((c) => c.category !== "recorded")}
                onGenerated={setSuite}
              />
            </div>

            {fragile.length > 0 && (
              <Alert variant="warning">
                <AlertTriangle className="mr-1 inline size-4" />
                {fragile.length} of {steps.length} steps rely on a fragile
                selector — the ones most likely to break when the UI changes.
                Adding a <code className="font-mono text-xs">data-testid</code>{" "}
                to those elements would fix it.
              </Alert>
            )}

            <TestCaseList cases={suite.cases} />
          </div>
        )}

        {tab === "scripts" && (
          <ScriptLocation outputDir={suite.output_dir} paths={paths} />
        )}
      </div>
    </div>
  );
}

/** The numbers worth knowing before reading anything else. */
function SuiteStats({
  suite,
  steps,
  fragile,
  run,
}: {
  suite: TestSuiteDetail;
  steps: number;
  fragile: number;
  run: TestRun | null;
}) {
  const generated = suite.cases.filter((c) => c.category !== "recorded").length;

  return (
    <StatRow className="mt-6">
      <Stat
        label="Test cases"
        value={suite.cases.length}
        hint={
          generated
            ? `1 recorded · ${generated} generated`
            : "from your recording"
        }
      />
      <Stat label="Steps" value={steps} hint={`across ${suite.cases.length} case(s)`} />
      <Stat
        label="Last run"
        value={run ? `${run.passed}/${run.total}` : "—"}
        // A cancelled run passed everything it got to, which is not the same
        // as passing. Green there would read as "all good" on a run the user
        // stopped after two of thirteen.
        tone={
          !run || run.status === "cancelled"
            ? "muted"
            : run.failed > 0
              ? "danger"
              : "success"
        }
        hint={
          run
            ? `${run.status}${run.duration_ms ? ` · ${formatDuration(run.duration_ms)}` : ""}`
            : "not run yet"
        }
      />
      <Stat
        label="Fragile steps"
        value={fragile}
        tone={fragile ? "warning" : "success"}
        hint={fragile ? "may break on a UI change" : "all reliable selectors"}
      />
    </StatRow>
  );
}

/** Where the scripts live, and how to open them. */
function ScriptLocation({
  outputDir,
  paths,
}: {
  outputDir: string | null;
  paths: string[];
}) {
  const [copied, setCopied] = useState<string | null>(null);

  async function copy(text: string, key: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(key);
      setTimeout(() => setCopied(null), 1500);
    } catch {
      /* clipboard blocked - the text is selectable anyway */
    }
  }

  if (!outputDir) {
    return (
      <Alert>
        The scripts could not be written to disk. They are still stored and will
        run, but there is no folder to open.
      </Alert>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FolderOpen className="size-4" />
          Scripts
        </CardTitle>
        <CardDescription>
          Written to disk. Open the folder in VS Code to review or edit them.
        </CardDescription>
      </CardHeader>

      <CardContent className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <code className="min-w-0 flex-1 truncate rounded bg-muted px-2 py-1.5 font-mono text-xs">
            {outputDir}
          </code>
          <Button
            variant="outline"
            size="sm"
            onClick={() => copy(outputDir, "path")}
            className="shrink-0"
          >
            {copied === "path" ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
            Path
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => copy(`code "${outputDir}"`, "cmd")}
            className="shrink-0"
            title="Copy a terminal command that opens this folder in VS Code"
          >
            {copied === "cmd" ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
            code command
          </Button>
        </div>

        <ul className="flex flex-col gap-0.5">
          {paths.map((path) => (
            <li key={path} className="font-mono text-xs text-muted-foreground">
              {path}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
