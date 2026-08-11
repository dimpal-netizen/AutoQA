"use client";

/** One failure, on a page of its own.
 *
 *  It used to live in an expanded row of the run's table, and everything about
 *  it had to fit there: the error, the explanation, the bug draft, the
 *  screenshot, the recording, the trace, and a box for asking questions. Six
 *  panels stacked inside a table row, with the rest of the run's tests pushed
 *  off the screen below them. Every one of those is worth having and none of
 *  them belongs in a row.
 *
 *  So the row says what failed and this page says why. The evidence gets width,
 *  the trace gets room, and the run it came from is one click away rather than
 *  scrolled past.
 */

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Clock } from "lucide-react";
import { api } from "@/lib/api";
import {
  BROWSER_LABEL,
  BLOCKED_MEANS,
  RESULT_BADGE,
  RESULT_LABEL,
  formatDuration,
  plainError,
  type TestResultDetail,
} from "@/lib/types";
import { AppShell } from "@/components/app-shell";
import { RequireAuth } from "@/components/auth-provider";
import { AskFailure } from "@/components/ask-failure";
import { BugReport } from "@/components/bug-report";
import { Evidence } from "@/components/result-matrix";
import { FailureAnalysis } from "@/components/failure-analysis";
import { Badge } from "@/components/ui/badge";
import { Alert } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export default function ResultPage({
  params,
}: {
  // Next 16: params is a Promise, unwrapped with React's use().
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  return (
    <RequireAuth>
      <AppShell wide>
        <Failure id={Number(id)} />
      </AppShell>
    </RequireAuth>
  );
}

function Failure({ id }: { id: number }) {
  const [result, setResult] = useState<TestResultDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setResult(await api.runs.result(id));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load this result");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-8 w-80" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }

  if (error || !result) {
    return <Alert>{error ?? "This result no longer exists."}</Alert>;
  }

  const readable = result.error_message
    ? plainError(result.error_message)
    : null;

  return (
    <div className="flex flex-col gap-5">
      {/* Back to the run, not to the browser's history. Someone arrives here
          from a link as often as from a click, and "wherever you were before"
          is not a place on a page that has one obvious parent. */}
      <Link
        href={`/projects/${result.project_id}`}
        className="inline-flex w-fit items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-primary"
      >
        <ArrowLeft className="size-4" />
        {result.suite_name || result.project_name || "Back"}
      </Link>

      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold leading-tight tracking-tight">
          {result.case_name}
        </h1>
        <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          <Badge tone={RESULT_BADGE[result.status] ?? "neutral"}>
            {RESULT_LABEL[result.status] ?? result.status}
          </Badge>
          <span>{BROWSER_LABEL[result.browser] ?? result.browser}</span>
          {result.duration_ms !== null && (
            <span className="flex items-center gap-1">
              <Clock className="size-3.5" />
              {formatDuration(result.duration_ms)}
            </span>
          )}
          {result.failed_step !== null && <span>stopped at step {result.failed_step}</span>}
        </div>

        {/* Said here rather than left to the reader. Someone opening a red row
            is deciding whether to raise a defect, and this is the sentence that
            decides it. */}
        {result.status === "error" && (
          <p className="rounded-md border border-warning/25 bg-warning-subtle px-3 py-2 text-sm text-warning">
            {BLOCKED_MEANS}
          </p>
        )}

        {/* The same test elsewhere. "Passes in Chrome, fails in WebKit" points
            at the application; failing everywhere usually points at the test —
            and neither is visible from one result on its own. */}
        {result.siblings.length > 0 && (
          <p className="text-sm text-muted-foreground">
            Other browsers:{" "}
            {result.siblings.map((sibling, index) => (
              <span key={sibling.id}>
                {index > 0 && ", "}
                <Link
                  href={`/results/${sibling.id}`}
                  className="underline-offset-2 hover:text-primary hover:underline"
                >
                  {BROWSER_LABEL[sibling.browser] ?? sibling.browser}{" "}
                  {sibling.status}
                </Link>
              </span>
            ))}
          </p>
        )}
      </header>

      {result.error_message && (
        <div className="rounded-md border border-destructive/25 bg-destructive-subtle px-3 py-2.5">
          {readable && (
            <p className="text-sm leading-relaxed text-destructive">{readable}</p>
          )}
          <p
            className={`font-mono text-xs leading-relaxed text-destructive ${
              readable ? "mt-2 opacity-70" : ""
            }`}
          >
            {result.error_message}
          </p>
        </div>
      )}

      <FailureAnalysis resultId={result.id} />

      <BugReport resultId={result.id} />

      {result.artifacts.length > 0 && <Evidence artifacts={result.artifacts} />}

      <AskFailure resultId={result.id} />

      {result.stack_trace && (
        <details>
          <summary className="cursor-pointer text-sm text-muted-foreground">
            Full trace
          </summary>
          <pre className="mt-2 max-h-[32rem] overflow-auto rounded-md bg-[#0b1220] p-4 font-mono text-xs leading-relaxed text-slate-200">
            {result.stack_trace}
          </pre>
        </details>
      )}
    </div>
  );
}
