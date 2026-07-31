"use client";

/** A bug report drafted from a failure, ready to paste into a tracker.
 *
 *  Sits below the analysis, because that is the order the work happens in:
 *  first work out what broke, then write it up for whoever fixes it. Copy is
 *  the primary action — until integrations exist, the report gets out of here
 *  through the clipboard.
 */

import { useEffect, useState } from "react";
import { Check, ClipboardCopy, FileText } from "lucide-react";
import { api } from "@/lib/api";
import {
  BUG_STATUS_TONE,
  SEVERITY_TONE,
  bugAsText,
  type BugReport as Bug,
} from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/card";

export function BugReport({ resultId }: { resultId: number }) {
  const [bug, setBug] = useState<Bug | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void api.bugs
      .forResult(resultId)
      .then((found) => {
        if (!cancelled) setBug(found);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [resultId]);

  async function draft() {
    setBusy(true);
    setError(null);
    try {
      setBug(await api.bugs.draft(resultId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not draft a bug report");
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    if (!bug) return;
    try {
      await navigator.clipboard.writeText(bugAsText(bug));
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* clipboard blocked - the text is selectable anyway */
    }
  }

  if (!loaded) return null;

  if (!bug) {
    return (
      <div className="flex flex-col gap-2">
        <div>
          <Button size="sm" variant="outline" onClick={draft} disabled={busy}>
            <FileText className={busy ? "animate-pulse" : ""} />
            {busy ? "Writing it up…" : "Draft a bug report"}
          </Button>
        </div>
        {error && <Alert>{error}</Alert>}
      </div>
    );
  }

  return (
    <div className="rounded-md border border-border bg-card p-3.5">
      <div className="flex flex-wrap items-start gap-2">
        <p className="min-w-0 flex-1 text-sm font-medium">{bug.title}</p>
        <Button size="sm" variant="outline" onClick={copy}>
          {copied ? <Check /> : <ClipboardCopy />}
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Badge tone={SEVERITY_TONE[bug.severity]}>{bug.severity}</Badge>
        <Badge tone={BUG_STATUS_TONE[bug.status]}>{bug.status}</Badge>
        <span className="text-xs text-muted-foreground">
          {String(bug.environment.browser ?? "")}
        </span>
      </div>

      <p className="mt-3 text-[13px] leading-relaxed">{bug.description}</p>

      <p className="mt-3 text-xs font-medium text-muted-foreground">
        Steps to reproduce
      </p>
      <ol className="mt-1 flex list-decimal flex-col gap-1 pl-5 text-[13px] leading-relaxed">
        {bug.steps_to_reproduce.map((step, i) => (
          <li key={i}>{step}</li>
        ))}
      </ol>

      <dl className="mt-3 grid gap-2 text-[13px] leading-relaxed sm:grid-cols-2">
        <div>
          <dt className="text-xs font-medium text-muted-foreground">Expected</dt>
          <dd className="mt-0.5">{bug.expected}</dd>
        </div>
        <div>
          <dt className="text-xs font-medium text-muted-foreground">Actual</dt>
          <dd className="mt-0.5">{bug.actual}</dd>
        </div>
      </dl>
    </div>
  );
}
