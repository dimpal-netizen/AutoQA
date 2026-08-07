"use client";

/** What the AI worked out about one failure.
 *
 *  Sits inside the expanded failure row, next to the error and the screenshot,
 *  because that is where the question is being asked. The verdict comes first:
 *  is this the application or the test? Everything else is detail.
 */

import { useEffect, useState } from "react";
import { Bug, FlaskConical, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import {
  CATEGORY_TEXT,
  SEVERITY_TONE,
  type Analysis,
} from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/card";

export function FailureAnalysis({ resultId }: { resultId: number }) {
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  // Show an existing analysis without spending anything to find out there is one.
  useEffect(() => {
    let cancelled = false;
    void api.analysis
      .get(resultId)
      .then((found) => {
        if (!cancelled) setAnalysis(found);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [resultId]);

  async function explain() {
    setBusy(true);
    setError(null);
    try {
      setAnalysis(await api.analysis.forResult(resultId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not analyse this failure");
    } finally {
      setBusy(false);
    }
  }

  if (!loaded) return null;

  if (!analysis) {
    return (
      <div className="flex flex-col gap-2">
        <div>
          <Button size="sm" variant="outline" onClick={explain} disabled={busy}>
            <Sparkles className={busy ? "animate-pulse" : ""} />
            {busy ? "Working it out…" : "Explain this failure"}
          </Button>
        </div>
        {error && <Alert>{error}</Alert>}
      </div>
    );
  }

  return (
    <div className="rounded-md border border-border bg-card p-3.5">
      <div className="flex flex-wrap items-center gap-2">
        {/* The verdict first — it decides what the reader does next. */}
        <Badge tone={analysis.is_product_bug ? "danger" : "neutral"}>
          {analysis.is_product_bug ? <Bug /> : <FlaskConical />}
          {analysis.is_product_bug ? "Application bug" : "Test problem"}
        </Badge>
        <Badge tone="outline">{CATEGORY_TEXT[analysis.category]}</Badge>
        <Badge tone={SEVERITY_TONE[analysis.severity]}>
          {analysis.severity}
        </Badge>

        <span
          className="tabular ml-auto text-xs text-muted-foreground"
          title="How sure the model is. Treat anything under 60% as a hint, not an answer."
        >
          {Math.round(analysis.confidence * 100)}% confident
        </span>
      </div>

      {/* Expected against actual, side by side. The pair is the whole question
          a failure asks, and reading it as two columns answers it faster than
          any sentence can — which is why it sits above the explanation rather
          than inside it. Absent on analyses written before it was asked for, so
          the block is conditional rather than showing two empty labels. */}
      {(analysis.expected || analysis.actual) && (
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          <div className="rounded-md border border-border bg-muted/40 p-2.5">
            <p className="text-xs font-medium text-muted-foreground">Expected</p>
            <p className="mt-0.5 text-[13px] leading-relaxed">
              {analysis.expected ?? "—"}
            </p>
          </div>
          <div className="rounded-md border border-destructive/25 bg-destructive-subtle p-2.5">
            <p className="text-xs font-medium text-destructive">Actual</p>
            <p className="mt-0.5 text-[13px] leading-relaxed">
              {analysis.actual ?? "—"}
            </p>
          </div>
        </div>
      )}

      <dl className="mt-3 flex flex-col gap-2.5 text-[13px] leading-relaxed">
        <div>
          <dt className="text-xs font-medium text-muted-foreground">Why</dt>
          <dd className="mt-0.5">{analysis.root_cause}</dd>
        </div>
        <div>
          <dt className="text-xs font-medium text-muted-foreground">
            What to do about it
          </dt>
          <dd className="mt-0.5">{analysis.suggested_fix}</dd>
        </div>
      </dl>
    </div>
  );
}
