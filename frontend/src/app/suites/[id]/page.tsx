"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowLeft,
  Check,
  Copy,
  FolderOpen,
  RefreshCw,
  Video,
} from "lucide-react";
import { api } from "@/lib/api";
import { RELIABLE_RANK, SELECTOR_RANK, type TestSuiteDetail } from "@/lib/types";
import { AppHeader } from "@/components/app-header";
import { RequireAuth } from "@/components/auth-provider";
import { RunPanel } from "@/components/run-panel";
import { TestCaseList } from "@/components/test-case-list";
import { Button } from "@/components/ui/button";
import {
  Alert,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export default function SuiteDetailPage({
  params,
}: {
  // Next 16: params is a Promise, unwrapped with React's use().
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  return (
    <RequireAuth>
      <AppHeader />
      <SuiteDetail id={Number(id)} />
    </RequireAuth>
  );
}

function SuiteDetail({ id }: { id: number }) {
  const [suite, setSuite] = useState<TestSuiteDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [regenerating, setRegenerating] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const data = await api.suites.get(id);
        if (!cancelled) setSuite(data);
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
      <main className="mx-auto max-w-4xl p-6">
        <Alert>{error}</Alert>
      </main>
    );
  }
  if (!suite) {
    return <main className="mx-auto max-w-4xl p-6 text-sm text-muted-foreground">Loading…</main>;
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
    <main className="mx-auto max-w-4xl p-6">
      <Link
        href="/suites"
        className="mb-4 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" />
        All tests
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold">{suite.name}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{suite.description}</p>
        </div>

        {suite.recording_id && (
          <div className="flex items-center gap-2">
            <Link href={`/recordings/${suite.recording_id}`}>
              <Button variant="outline" size="sm">
                <Video className="size-4" />
                Recording
              </Button>
            </Link>
            <Button variant="outline" size="sm" disabled={regenerating} onClick={regenerate}>
              <RefreshCw className={`size-4 ${regenerating ? "animate-spin" : ""}`} />
              {regenerating ? "Regenerating…" : "Regenerate"}
            </Button>
          </div>
        )}
      </div>

      {error && <Alert className="mt-4">{error}</Alert>}

      <RunPanel suiteId={suite.id} caseCount={suite.cases.length} />

      <ScriptLocation outputDir={suite.output_dir} paths={paths} />

      {fragile.length > 0 && (
        <Alert className="mt-4">
          <AlertTriangle className="mr-1 inline size-4" />
          {fragile.length} of {steps.length} steps rely on a fragile selector. Those
          are the ones most likely to break when the UI changes — adding a{" "}
          <code className="font-mono text-xs">data-testid</code> to those elements
          would fix it.
        </Alert>
      )}

      <h2 className="mt-8 text-lg font-semibold">
        Test cases{suite.cases.length > 1 && ` (${suite.cases.length})`}
      </h2>
      <p className="mb-3 mt-1 text-sm text-muted-foreground">
        What each test does, in order. No code needed to review it.
      </p>

      <TestCaseList cases={suite.cases} />
    </main>
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
      <Alert className="mt-5">
        The scripts could not be written to disk. They are still stored and will
        run, but there is no folder to open.
      </Alert>
    );
  }

  return (
    <Card className="mt-5">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
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
