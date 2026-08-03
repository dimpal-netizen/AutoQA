"use client";

/** One suite: how it is doing, then run it, read the tests, find the files.
 *
 *  Rewritten after the two-column version left half the screen blank. Three
 *  things changed and they are all about density:
 *
 *  - The suite picker is a row of pills above the content, not a 17rem column
 *    beside it. A column that holds one truncated name is spending a sixth of
 *    the width to say less than a tab would.
 *  - A stat strip answers "how is this doing" without expanding anything. The
 *    old detail page had this and the workspace lost it.
 *  - Failures are open by default. Someone looking at a red run came to read
 *    the error; making them click for it is the one interaction this screen
 *    should not have.
 */

import { useState } from "react";
import {
  AlertTriangle,
  Download,
  FileSpreadsheet,
  FlaskConical,
  FolderOpen,
  RefreshCw,
  Video,
} from "lucide-react";
import Link from "next/link";
import { api, downloadTestCaseSheet } from "@/lib/api";
import {
  RELIABLE_RANK,
  SELECTOR_RANK,
  formatDuration,
  type TestRun,
  type TestSuite,
  type TestSuiteDetail,
} from "@/lib/types";
import { GenerateCases } from "@/components/generate-cases";
import { RunPanel } from "@/components/run-panel";
import { ScriptLocation } from "@/components/script-location";
import { TestCaseList } from "@/components/test-case-list";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/card";
import { Tabs } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

export function SuiteWorkspace({
  suite,
  suites,
  onSelect,
  onChange,
  lastRun,
}: {
  suite: TestSuiteDetail;
  suites: TestSuite[];
  onSelect: (id: number) => void;
  onChange: (suite: TestSuiteDetail) => void;
  lastRun: TestRun | null;
}) {
  const [tab, setTab] = useState("cases");
  const [regenerating, setRegenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function regenerate() {
    if (!suite.recording_id) return;
    setRegenerating(true);
    setError(null);
    try {
      onChange(await api.suites.regenerate(suite.recording_id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not regenerate");
    } finally {
      setRegenerating(false);
    }
  }

  const steps = suite.cases.flatMap((c) => c.steps);
  const fragile = steps.filter(
    (s) => s.selector_strategy && SELECTOR_RANK[s.selector_strategy] > RELIABLE_RANK,
  );
  const generated = suite.cases.filter((c) => c.category !== "recorded").length;
  const paths = [
    ...suite.cases.map((c) => c.file_path),
    ...suite.files.map((f) => f.path),
  ].sort();

  return (
    <section className="flex min-w-0 flex-col gap-5">
      {/* Only worth showing when there is a choice to make. */}
      {suites.length > 1 && (
        <div className="flex flex-wrap items-center gap-1.5">
          {suites.map((option) => {
            const active = option.id === suite.id;
            return (
              <button
                key={option.id}
                type="button"
                onClick={() => onSelect(option.id)}
                className={cn(
                  "max-w-xs truncate rounded-md border px-3 py-1.5 text-[13px] font-medium transition-all",
                  active
                    ? "lit border-primary/35 bg-card text-primary"
                    : "border-border bg-card/60 text-muted-foreground hover:border-border-strong hover:text-foreground",
                )}
              >
                {option.name}
              </button>
            );
          })}
        </div>
      )}

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="truncate text-xl font-extrabold tracking-tight">
            {suite.name}
          </h2>
          {suite.description && (
            <p className="mt-1 text-[13px] text-muted-foreground">
              {suite.description}
            </p>
          )}
        </div>

        {suite.recording_id && (
          <div className="flex shrink-0 items-center gap-2">
            <Link href={`/recordings/${suite.recording_id}`}>
              <Button variant="ghost" size="sm">
                <Video />
                Recording
              </Button>
            </Link>
            <Button
              variant="outline"
              size="sm"
              disabled={regenerating}
              onClick={regenerate}
            >
              <RefreshCw className={regenerating ? "animate-spin" : ""} />
              {regenerating ? "Regenerating…" : "Regenerate"}
            </Button>
          </div>
        )}
      </div>

      {/* One banded row of figures rather than four separate boxes. Four
          equally-weighted cards is four things shouting at the same volume;
          hairline dividers group them as one reading instead. */}
      <div className="sheen grid grid-cols-2 divide-border rounded-xl border border-border bg-card sm:divide-x lg:grid-cols-4">
        <Figure
          label="Test cases"
          value={suite.cases.length}
          hint={generated ? `1 recorded · ${generated} generated` : "from your recording"}
        />
        <Figure label="Steps" value={steps.length} hint="across every case" />
        <Figure
          label="Last run"
          value={lastRun ? `${lastRun.passed}/${lastRun.total}` : "—"}
          tone={
            !lastRun || lastRun.status === "cancelled"
              ? "muted"
              : lastRun.failed > 0
                ? "danger"
                : "success"
          }
          hint={
            lastRun
              ? `${lastRun.status}${lastRun.duration_ms ? ` · ${formatDuration(lastRun.duration_ms)}` : ""}`
              : "not run yet"
          }
        />
        <Figure
          label="Fragile steps"
          value={fragile.length}
          tone={fragile.length ? "warning" : "success"}
          hint={fragile.length ? "may break on a UI change" : "all reliable selectors"}
        />
      </div>

      {error && <Alert>{error}</Alert>}

      <div>
        <Tabs
          active={tab}
          onChange={setTab}
          tabs={[
            {
              id: "cases",
              label: "Test cases",
              // The generated cases, matching the rows in the table. The
              // recording is counted in the stat strip above, not here.
              count: generated,
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

        <div className="mt-4">
          {tab === "cases" && (
            <div className="flex flex-col gap-5">
              {/* Running belongs with the tests being run. It was its own tab,
                  which meant generating cases and then running them was two
                  places for one continuous thought. */}
              <RunPanel suiteId={suite.id} caseCount={suite.cases.length} />

              <div className="rounded-lg border border-dashed border-border bg-muted/40 p-4">
                <GenerateCases
                  suiteId={suite.id}
                  hasGenerated={generated > 0}
                  onGenerated={onChange}
                />
              </div>

              <ExportSheet suite={suite} />

              {fragile.length > 0 && (
                <Alert variant="warning">
                  <AlertTriangle className="mr-1 inline size-4" />
                  {fragile.length} of {steps.length} steps rely on a fragile
                  selector — the ones most likely to break when the UI changes.
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
    </section>
  );
}

/** One figure in the banded row. Blue by default, like the reference's stat
 *  strip — the status colours are kept for the two figures that carry a
 *  verdict, so a colour here always means something. */
function Figure({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
  tone?: "default" | "success" | "danger" | "warning" | "muted";
}) {
  const colour = {
    default: "text-primary",
    success: "text-success",
    danger: "text-destructive",
    warning: "text-warning",
    muted: "text-muted-foreground",
  }[tone];

  return (
    <div className="px-5 py-4">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className={cn("mt-1.5 text-3xl font-extrabold leading-none tracking-tight", colour)}>
        {value}
      </p>
      {hint && (
        <p className="mt-1.5 truncate text-xs text-muted-foreground">{hint}</p>
      )}
    </div>
  );
}

/** Hand the suite to whoever keeps the test-case sheet.
 *
 *  QA teams track cases in Excel and are asked for that sheet by people who
 *  will never open this app. AutoQA already holds every column it wants, so
 *  making them retype it would be absurd. */
function ExportSheet({ suite }: { suite: TestSuiteDetail }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleExport() {
    setBusy(true);
    setError(null);
    try {
      const stem =
        suite.name.replace(/[^a-z0-9]+/gi, "_").replace(/^_+|_+$/g, "") ||
        `suite_${suite.id}`;
      await downloadTestCaseSheet(suite.id, `test_cases_${stem}.csv`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not export the sheet");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-card px-4 py-3">
      <FileSpreadsheet className="size-4 shrink-0 text-primary" />
      <div className="min-w-0 flex-1">
        <p className="text-[13px] font-semibold">Test case sheet</p>
        <p className="text-xs text-muted-foreground">
          All {suite.cases.length} cases as a spreadsheet — ID, priority,
          positive/negative, steps, expected result. The execution columns are
          filled in from the latest run.
        </p>
      </div>
      {error && <span className="text-xs text-destructive">{error}</span>}
      <Button
        variant="outline"
        size="sm"
        onClick={handleExport}
        disabled={busy || suite.cases.length === 0}
      >
        <Download />
        {busy ? "Exporting…" : "Export CSV"}
      </Button>
    </div>
  );
}
