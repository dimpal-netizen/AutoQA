"use client";

/** One suite, in the right-hand pane: run it, read the tests, find the files.
 *
 *  The same three sections the old detail page had, minus the page. It takes a
 *  suite it was given rather than fetching by id, so switching suites in the
 *  list is instant and never navigates.
 */

import { useState } from "react";
import {
  AlertTriangle,
  FlaskConical,
  FolderOpen,
  Play,
  RefreshCw,
  Video,
} from "lucide-react";
import Link from "next/link";
import { api } from "@/lib/api";
import {
  RELIABLE_RANK,
  SELECTOR_RANK,
  type TestSuiteDetail,
} from "@/lib/types";
import { GenerateCases } from "@/components/generate-cases";
import { RunPanel } from "@/components/run-panel";
import { ScriptLocation } from "@/components/script-location";
import { TestCaseList } from "@/components/test-case-list";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/card";
import { Tabs } from "@/components/ui/tabs";

export function SuiteWorkspace({
  suite,
  onChange,
}: {
  suite: TestSuiteDetail;
  onChange: (suite: TestSuiteDetail) => void;
}) {
  const [tab, setTab] = useState("run");
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
  const paths = [
    ...suite.cases.map((c) => c.file_path),
    ...suite.files.map((f) => f.path),
  ].sort();

  return (
    <section className="min-w-0">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="truncate text-lg font-semibold">{suite.name}</h2>
          <p className="mt-0.5 text-[13px] text-muted-foreground">
            {suite.cases.length} test case{suite.cases.length === 1 ? "" : "s"} ·{" "}
            {steps.length} steps
            {fragile.length > 0 && ` · ${fragile.length} fragile`}
          </p>
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

      {error && <Alert className="mt-3">{error}</Alert>}

      <Tabs
        className="mt-4"
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
          { id: "scripts", label: "Scripts", count: paths.length, icon: <FolderOpen /> },
        ]}
      />

      <div className="mt-4">
        {tab === "run" && (
          <RunPanel suiteId={suite.id} caseCount={suite.cases.length} />
        )}

        {tab === "cases" && (
          <div className="flex flex-col gap-5">
            <div className="rounded-lg border border-dashed border-border bg-muted/40 p-4">
              <GenerateCases
                suiteId={suite.id}
                hasGenerated={suite.cases.some((c) => c.category !== "recorded")}
                onGenerated={onChange}
              />
            </div>

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
    </section>
  );
}
