"use client";

/** Every test case in a suite, as one table.
 *
 *  Written for someone who does not read Python: expanding a row gives a
 *  plain-English list of what the test does, in order. The code exists on disk
 *  for whoever wants it; this is the review surface for everyone else.
 *
 *  It used to be a card per case, grouped under a heading and a sentence of
 *  explanation per group. That reads well for three cases and turns into a wall
 *  at thirty — the same six facts restated in a different place on every card,
 *  so nothing could be compared down a column. A table puts each fact in one
 *  place, which is the entire reason tables exist. Category becomes a column
 *  rather than a section break, and the rows stay in category order, so the
 *  grouping is still visible without cutting the list into pieces.
 */

import { useState } from "react";
import { ChevronDown, ChevronRight, FileCode2, TriangleAlert } from "lucide-react";
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
  // The recording is not a test case, it is the session every case came from —
  // one row of 33 steps sitting above a list of focused three-step checks,
  // answering a different question and skewing every column it appears in. It
  // has its own place: the Recording link in the suite header.
  const testCases = cases.filter((c) => c.category !== "recorded");

  // One case is the one you came to read; a suite of fifteen is a list to scan.
  const [open, setOpen] = useState<Set<number>>(
    () => new Set(testCases.length === 1 ? testCases.map((c) => c.id) : []),
  );

  function toggle(id: number) {
    setOpen((current) => {
      const next = new Set(current);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  }

  if (testCases.length === 0) {
    return (
      <Card>
        <CardContent className="py-10 text-center text-sm text-muted-foreground">
          {cases.length > 0
            ? "No test cases yet — generate them from your recording above."
            : "No test cases yet."}
        </CardContent>
      </Card>
    );
  }

  // Category order carries meaning, so sorting by it keeps the grouping
  // visible without splitting the table up.
  const ordered = CATEGORY_ORDER.flatMap((category) =>
    testCases.filter((c) => c.category === category),
  );

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card shadow-xs">
      {/* The table needs a minimum width to stay readable; below that it
          scrolls inside its own box rather than squashing the page. */}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[46rem] border-collapse text-left">
          <thead>
            <tr className="border-b border-border bg-muted/50 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              <th scope="col" className="w-8" />
              <th scope="col" className="px-3 py-2.5 font-semibold">
                Test case
              </th>
              <th scope="col" className="px-3 py-2.5 font-semibold">
                Category
              </th>
              <th scope="col" className="px-3 py-2.5 font-semibold">
                Priority
              </th>
              <th scope="col" className="px-3 py-2.5 text-right font-semibold">
                Steps
              </th>
              <th scope="col" className="px-3 py-2.5 font-semibold">
                File
              </th>
            </tr>
          </thead>

          <tbody>
            {ordered.map((testCase) => (
              <CaseRows
                key={testCase.id}
                testCase={testCase}
                open={open.has(testCase.id)}
                onToggle={() => toggle(testCase.id)}
              />
            ))}
          </tbody>
        </table>
      </div>

      <Legend cases={ordered} />
    </div>
  );
}

function CaseRows({
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
    <>
      <tr
        onClick={onToggle}
        className={`cursor-pointer border-b border-border transition-colors hover:bg-accent/60 ${
          open ? "bg-accent/40" : ""
        }`}
      >
        <td className="pl-3">
          <button
            type="button"
            aria-expanded={open}
            aria-label={`${open ? "Hide" : "Show"} steps for ${testCase.name}`}
            className="flex size-5 items-center justify-center rounded text-muted-foreground"
          >
            {open ? (
              <ChevronDown className="size-4" />
            ) : (
              <ChevronRight className="size-4" />
            )}
          </button>
        </td>

        <td className="px-3 py-2.5">
          <span className="block text-[13px] font-medium">{testCase.name}</span>
          {testCase.description && (
            <span className="mt-0.5 block max-w-xl truncate text-xs text-muted-foreground">
              {testCase.description}
            </span>
          )}
          {!testCase.is_enabled && (
            <Badge className="mt-1">disabled</Badge>
          )}
        </td>

        <td className="px-3 py-2.5">
          <Badge tone={CATEGORY_TONE[testCase.category]}>
            {CATEGORY_LABEL[testCase.category]}
          </Badge>
        </td>

        <td className="px-3 py-2.5">
          <Badge tone={PRIORITY_TONE[testCase.priority]}>
            {testCase.priority}
          </Badge>
        </td>

        {/* Right-aligned and tabular, so counts line up down the column —
            which is the only reason to put a number in a table at all. */}
        <td className="tabular whitespace-nowrap px-3 py-2.5 text-right text-[13px]">
          {testCase.steps.length}
          {fragile.length > 0 && (
            <span
              className="ml-2 inline-flex items-center gap-1 text-xs text-warning"
              title={`${fragile.length} step(s) use a selector likely to break on a UI change`}
            >
              <TriangleAlert className="size-3" />
              {fragile.length}
            </span>
          )}
        </td>

        <td className="px-3 py-2.5">
          <span className="flex items-center gap-1.5 font-mono text-xs text-muted-foreground">
            <FileCode2 className="size-3 shrink-0" />
            <span className="max-w-[15rem] truncate" title={testCase.file_path}>
              {testCase.file_path.replace(/^tests\//, "")}
            </span>
          </span>
        </td>
      </tr>

      {open && (
        <tr className="border-b border-border bg-muted/30">
          <td colSpan={6} className="px-4 py-4">
            <Steps steps={testCase.steps} />
          </td>
        </tr>
      )}
    </>
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
                  ? "border-warning/30 bg-warning-subtle text-warning"
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

/** What each category is for.
 *
 *  This used to be repeated above every group. Once as a footnote is enough:
 *  it is read on the first visit and never again, so it belongs below the data
 *  rather than interrupting it. */
function Legend({ cases }: { cases: TestCase[] }) {
  const present = CATEGORY_ORDER.filter((category) =>
    cases.some((c) => c.category === category),
  );

  return (
    <dl className="flex flex-wrap gap-x-6 gap-y-2 border-t border-border bg-muted/30 px-4 py-3">
      {present.map((category) => (
        <div key={category} className="flex items-center gap-2">
          <dt>
            <Badge tone={CATEGORY_TONE[category]}>
              {CATEGORY_LABEL[category]}
            </Badge>
          </dt>
          <dd className="text-xs text-muted-foreground">
            {CATEGORY_BLURB[category]}
          </dd>
        </div>
      ))}
    </dl>
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
