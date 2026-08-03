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
import {
  ChevronDown,
  ChevronRight,
  FileCode2,
  LoaderCircle,
  Play,
  TriangleAlert,
} from "lucide-react";
import {
  BROWSER_LABEL,
  CATEGORY_BLURB,
  CATEGORY_LABEL,
  CATEGORY_ORDER,
  CATEGORY_TONE,
  PRIORITY_TONE,
  RELIABLE_RANK,
  RESULT_BADGE,
  SELECTOR_RANK,
  type CaseCategory,
  type TestCase,
  type TestResult,
  type TestStep,
} from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";

export function TestCaseList({
  cases,
  onRunCase,
  runningCaseIds = null,
  statusByCase,
}: {
  cases: TestCase[];
  /** Run this one case on its own. Absent where the list is read-only. */
  onRunCase?: (caseId: number) => void;
  /** Where each case currently stands — its newest result, from any run. */
  statusByCase?: Map<number, TestResult[]>;
  /** null when nothing is running; the ids of a running run otherwise, with
   *  an empty array meaning the whole suite. */
  runningCaseIds?: number[] | null;
}) {
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

  // Back to sections. A Category column repeated the same word down eight
  // consecutive rows, which is a column spending its width to say "still the
  // same as the row above". A heading says it once and separates the groups
  // at the same time.
  const groups = CATEGORY_ORDER.map((category) => ({
    category,
    items: testCases.filter((c) => c.category === category),
  })).filter((group) => group.items.length > 0);

  const columns = onRunCase ? 5 : 4;

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
                Status
              </th>
              <th scope="col" className="px-3 py-2.5 font-semibold">
                Priority
              </th>
              <th scope="col" className="px-3 py-2.5 font-semibold">
                File
              </th>
              {onRunCase && <th scope="col" className="w-14" />}
            </tr>
          </thead>

          {groups.map(({ category, items }) => (
            <tbody key={category}>
              <tr>
                <th
                  scope="colgroup"
                  colSpan={columns}
                  className="border-b border-border bg-muted/30 px-3 py-2 text-left font-normal"
                >
                  <span className="flex flex-wrap items-baseline gap-2.5">
                    <Badge tone={CATEGORY_TONE[category]}>
                      {CATEGORY_LABEL[category]}
                    </Badge>
                    <span className="tabular text-xs text-muted-foreground">
                      {items.length}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {CATEGORY_BLURB[category]}
                    </span>
                  </span>
                </th>
              </tr>

              {items.map((testCase) => (
              <CaseRows
                key={testCase.id}
                testCase={testCase}
                columns={columns}
                results={statusByCase?.get(testCase.id) ?? []}
                open={open.has(testCase.id)}
                onToggle={() => toggle(testCase.id)}
                onRun={onRunCase && (() => onRunCase(testCase.id))}
                // Empty means the whole suite is running, so every row is.
                running={
                  runningCaseIds !== null &&
                  (runningCaseIds.length === 0 ||
                    runningCaseIds.includes(testCase.id))
                }
                // One run at a time: starting a second while the first is
                // going would queue a run against files the first is using.
                busy={runningCaseIds !== null}
              />
              ))}
            </tbody>
          ))}
        </table>
      </div>
    </div>
  );
}

function CaseRows({
  testCase,
  open,
  onToggle,
  onRun,
  running = false,
  busy = false,
  columns,
  results,
}: {
  testCase: TestCase;
  columns: number;
  results: TestResult[];
  open: boolean;
  onToggle: () => void;
  onRun?: () => void;
  running?: boolean;
  busy?: boolean;
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
          <span className="flex items-center gap-2">
            <span className="text-[13px] font-medium">{testCase.name}</span>
            {/* The fragile count lost its column, not its meaning — it warns
                that this case is built on selectors likely to break, which is
                worth knowing before you trust the row. */}
            {fragile.length > 0 && (
              <span
                className="inline-flex shrink-0 items-center gap-1 text-xs text-warning"
                title={`${fragile.length} of ${testCase.steps.length} steps use a selector likely to break on a UI change`}
              >
                <TriangleAlert className="size-3" />
                {fragile.length}
              </span>
            )}
          </span>
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
          <CaseStatus results={results} />
        </td>

        <td className="px-3 py-2.5">
          <Badge tone={PRIORITY_TONE[testCase.priority]}>
            {testCase.priority}
          </Badge>
        </td>

        <td className="px-3 py-2.5">
          <span className="flex items-center gap-1.5 font-mono text-xs text-muted-foreground">
            <FileCode2 className="size-3 shrink-0" />
            <span className="max-w-[15rem] truncate" title={testCase.file_path}>
              {testCase.file_path.replace(/^tests\//, "")}
            </span>
          </span>
        </td>

        {/* Run this one case. It replaced a column of checkboxes: ticking
            boxes and then finding the button is two steps and a scroll for
            what is nearly always "run this one". The click must not also
            expand the row. */}
        {onRun && (
          <td className="pr-3 text-right" onClick={(e) => e.stopPropagation()}>
            <button
              type="button"
              onClick={onRun}
              disabled={busy}
              aria-label={
                running ? `${testCase.name} is running` : `Run ${testCase.name}`
              }
              title={running ? "Running…" : "Run this test case"}
              className="inline-flex size-8 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:pointer-events-none disabled:opacity-40"
            >
              {running ? (
                <LoaderCircle className="size-4 animate-spin text-primary" />
              ) : (
                <Play className="size-4" />
              )}
            </button>
          </td>
        )}
      </tr>

      {open && (
        <tr className="border-b border-border bg-muted/30">
          <td colSpan={columns} className="px-4 py-4">
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

/** Where a case stands, from its newest result on each browser.
 *
 *  Answers the question the table could not: did this pass? Without a run
 *  behind it a case is "not run" rather than anything green or red — silence
 *  is not a pass, and showing it as one would be the most misleading thing on
 *  the page. */
function CaseStatus({ results }: { results: TestResult[] }) {
  if (results.length === 0) {
    return <span className="text-xs text-muted-foreground">Not run</span>;
  }

  // One badge when every browser agrees, which is the common case. When they
  // disagree the worst one leads, because a case red anywhere has not passed.
  const worst =
    results.find((r) => r.status === "failed" || r.status === "error") ??
    results.find((r) => r.status === "flaky") ??
    results.find((r) => r.status === "skipped") ??
    results[0];

  const others = results.filter((r) => r.status !== worst.status);

  return (
    <span className="flex flex-wrap items-center gap-1.5">
      <Badge tone={RESULT_BADGE[worst.status]}>{worst.status}</Badge>
      {others.length > 0 && (
        <span
          className="text-xs text-muted-foreground"
          title={results
            .map((r) => `${BROWSER_LABEL[r.browser] ?? r.browser}: ${r.status}`)
            .join(", ")}
        >
          +{others.length}
        </span>
      )}
    </span>
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
