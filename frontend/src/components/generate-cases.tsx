"use client";

/** Ask the AI for the test cases a QA engineer would add around the recording.
 *
 *  This is the one feature that genuinely needs a model, so the failure case
 *  gets real estate: no key configured is an explanation, not a dead button.
 */

import { useState } from "react";
import { Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import type { GenerateCasesResult, TestSuiteDetail } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/card";

export function GenerateCases({
  suiteId,
  hasGenerated,
  onGenerated,
}: {
  suiteId: number;
  hasGenerated: boolean;
  onGenerated: (suite: TestSuiteDetail) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<GenerateCasesResult | null>(null);

  async function generate() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const response = await api.suites.generateCases(suiteId);
      setResult(response);
      onGenerated(response.suite);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not generate test cases");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={generate} disabled={busy} variant={hasGenerated ? "outline" : "default"}>
          <Sparkles className={busy ? "animate-pulse" : ""} />
          {busy
            ? "Writing test cases…"
            : hasGenerated
              ? "Regenerate cases"
              : "Generate test cases"}
        </Button>

        <p className="text-xs leading-relaxed text-muted-foreground">
          {hasGenerated
            ? "Replaces the generated cases. Your recorded test is never touched."
            : "Positive, negative, edge and security cases built around this recording."}
        </p>
      </div>

      {busy && (
        <p className="text-xs text-muted-foreground">
          Usually 15–30 seconds. Each suggestion is checked against elements that
          actually exist before it becomes a file.
        </p>
      )}

      {error && <Alert>{error}</Alert>}

      {result && (
        <Alert variant="info">
          Added {result.generated} test case{result.generated === 1 ? "" : "s"}
          {result.cost_usd > 0 && (
            <>
              {" "}
              · {result.tokens.toLocaleString()} tokens · $
              {result.cost_usd.toFixed(4)}
            </>
          )}
          {result.rejected.length > 0 && (
            <details className="mt-1.5">
              <summary className="cursor-pointer text-xs">
                {result.rejected.length} suggestion
                {result.rejected.length === 1 ? "" : "s"} rejected
              </summary>
              {/* Shown rather than swallowed: a case dropped for referencing a
                  missing element is a fact about the recording, not a defect
                  to hide. */}
              <ul className="mt-1 flex flex-col gap-0.5 text-xs opacity-80">
                {result.rejected.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            </details>
          )}
        </Alert>
      )}
    </div>
  );
}
