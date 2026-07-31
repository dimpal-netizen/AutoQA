"use client";

/** Every test case in a suite, grouped by what it checks.
 *
 *  Written for someone who does not read Python: each case is a plain-English
 *  list of what it does, in order. The code exists on disk for whoever wants
 *  it; this is the review surface for everyone else.
 *
 *  Grouped rather than a flat list because the categories answer different
 *  questions — "does the happy path still work" and "does the app reject a SQL
 *  fragment" are read by different people, at different times.
 */

import { useState } from "react";
import { ChevronDown, ChevronRight, FileCode2 } from "lucide-react";
import {
  CATEGORY_BLURB,
  CATEGORY_LABEL,
  CATEGORY_ORDER,
  CATEGORY_TONE,
  PRIORITY_TONE,
  RELIABLE_RANK,
  SELECTOR_RANK,
  type CaseCategory,
  type TestCase,
  type TestStep,
} from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";

export function TestCaseList({ cases }: { cases: TestCase[] }) {
  // One case is the one you came to read; a suite of fifteen is a list to scan.
  const [open, setOpen] = useState<Set<number>>(
    () => new Set(cases.length === 1 ? cases.map((c) => c.id) : []),
  );

  function toggle(id: number) {
    setOpen((current) => {
      const next = new Set(current);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  }

  if (cases.length === 0) {
    return (
      <Card>
        <CardContent className="py-10 text-center text-sm text-muted-foreground">
          No test cases yet.
        </CardContent>
      </Card>
    );
  }

  const groups = CATEGORY_ORDER.map((category) => ({
    category,
    items: cases.filter((c) => c.category === category),
  })).filter((group) => group.items.length > 0);

  return (
    <div className="flex flex-col gap-7">
      {groups.map(({ category, items }) => (
        <section key={category}>
          <div className="mb-2.5 flex items-baseline gap-2.5">
            <Badge tone={CATEGORY_TONE[category]}>{CATEGORY_LABEL[category]}</Badge>
            <span className="tabular text-xs text-muted-foreground">
              {items.length}
            </span>
            <span className="text-xs text-muted-foreground">
              {CATEGORY_BLURB[category]}
            </span>
          </div>

          <div className="flex flex-col gap-2">
            {items.map((testCase) => (
              <CaseRow
                key={testCase.id}
                testCase={testCase}
                open={open.has(testCase.id)}
                onToggle={() => toggle(testCase.id)}
              />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function CaseRow({
  testCase,
  open,
  onToggle,
}: {
  testCase: TestCase;
  open: boolean;
  onToggle: () => void;
}) {
  const fragile = testCase.steps.filter(isFragile);

  return (
    <Card className="overflow-hidden transition-colors hover:border-border-strong">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-start gap-2.5 px-4 py-3.5 text-left transition-colors hover:bg-muted/40"
      >
        {open ? (
          <ChevronDown className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        )}

        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium">{testCase.name}</span>
            {testCase.priority !== "medium" && (
              <Badge tone={PRIORITY_TONE[testCase.priority]}>
                {testCase.priority}
              </Badge>
            )}
            {!testCase.is_enabled && <Badge>disabled</Badge>}
          </span>

          {testCase.description && (
            <span className="mt-1 block text-[13px] leading-relaxed text-muted-foreground">
              {testCase.description}
            </span>
          )}

          <span className="mt-1.5 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
            <span className="tabular">
              {testCase.steps.length} {testCase.steps.length === 1 ? "step" : "steps"}
            </span>
            {fragile.length > 0 && (
              <span className="text-destructive">{fragile.length} fragile</span>
            )}
            <span className="flex items-center gap-1 font-mono">
              <FileCode2 className="size-3" />
              {testCase.file_path.replace(/^tests\//, "")}
            </span>
          </span>
        </span>
      </button>

      {open && (
        <CardContent className="border-t border-border bg-muted/25 pt-4">
          <Steps steps={testCase.steps} />
        </CardContent>
      )}
    </Card>
  );
}

function isFragile(step: TestStep): boolean {
  return Boolean(
    step.selector_strategy && SELECTOR_RANK[step.selector_strategy] > RELIABLE_RANK,
  );
}

function Steps({ steps }: { steps: TestStep[] }) {
  if (steps.length === 0) {
    return <p className="text-sm text-muted-foreground">No steps recorded.</p>;
  }

  return (
    <ol className="flex flex-col gap-2.5">
      {steps.map((step) => (
        <li key={step.id} className="flex items-start gap-3">
          <span className="tabular mt-px w-5 shrink-0 text-right text-xs text-muted-foreground">
            {step.sequence}
          </span>

          <span className="min-w-0 flex-1">
            <span className="block text-[13px] leading-relaxed">
              {step.description}
            </span>
            {step.input_data && (
              <span className="mt-1 inline-block max-w-full truncate rounded border border-border bg-card px-1.5 py-0.5 font-mono text-xs text-muted-foreground">
                {step.input_data || "(empty)"}
              </span>
            )}
          </span>

          {step.selector_strategy && (
            <span
              className={`shrink-0 rounded border px-1.5 py-0.5 font-mono text-[11px] ${
                isFragile(step)
                  ? "border-destructive/30 bg-destructive-subtle text-destructive"
                  : "border-border bg-card text-muted-foreground"
              }`}
              title={
                isFragile(step)
                  ? "Brittle - likely to break when the UI changes"
                  : "Reliable selector"
              }
            >
              {step.selector_strategy}
            </span>
          )}
        </li>
      ))}
    </ol>
  );
}

/** Counts per category, for the page header. */
export function categoryCounts(cases: TestCase[]): [CaseCategory, number][] {
  return CATEGORY_ORDER.map(
    (category) =>
      [category, cases.filter((c) => c.category === category).length] as [
        CaseCategory,
        number,
      ],
  ).filter(([, count]) => count > 0);
}
