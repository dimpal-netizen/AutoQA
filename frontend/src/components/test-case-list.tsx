"use client";

/** Every test case in a suite, with its steps.
 *
 *  Written for someone who does not read Python: each case is a plain-English
 *  list of what it does, in order. The code exists on disk for whoever wants
 *  it; this is the review surface for everyone else.
 */

import { useState } from "react";
import { ChevronDown, ChevronRight, FileCode2 } from "lucide-react";
import {
  RELIABLE_RANK,
  SELECTOR_RANK,
  type TestCase,
  type TestStep,
} from "@/lib/types";
import { Card, CardContent } from "@/components/ui/card";

export function TestCaseList({ cases }: { cases: TestCase[] }) {
  // A single case is almost always the one you came to read, so open it.
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
        <CardContent className="py-8 text-center text-sm text-muted-foreground">
          No test cases yet.
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {cases.map((testCase) => {
        const isOpen = open.has(testCase.id);
        const fragile = testCase.steps.filter(isFragile);

        return (
          <Card key={testCase.id}>
            <button
              type="button"
              onClick={() => toggle(testCase.id)}
              className="flex w-full items-start gap-2 p-4 text-left hover:bg-muted/40"
            >
              {isOpen ? (
                <ChevronDown className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
              ) : (
                <ChevronRight className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
              )}

              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{testCase.name}</span>
                  {!testCase.is_enabled && (
                    <span className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-xs text-slate-600">
                      disabled
                    </span>
                  )}
                  {testCase.tags.map((tag) => (
                    <span
                      key={tag}
                      className="rounded border border-input px-1.5 py-0.5 text-xs text-muted-foreground"
                    >
                      {tag}
                    </span>
                  ))}
                </span>

                {testCase.description && (
                  <span className="mt-0.5 block text-sm text-muted-foreground">
                    {testCase.description}
                  </span>
                )}

                <span className="mt-1 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                  <span>
                    {testCase.steps.length}{" "}
                    {testCase.steps.length === 1 ? "step" : "steps"}
                  </span>
                  {fragile.length > 0 && (
                    <span className="text-destructive">
                      {fragile.length} fragile
                    </span>
                  )}
                  <span className="flex items-center gap-1 font-mono">
                    <FileCode2 className="size-3" />
                    {testCase.file_path}
                  </span>
                </span>
              </span>
            </button>

            {isOpen && (
              <CardContent className="border-t pt-3">
                <Steps steps={testCase.steps} />
              </CardContent>
            )}
          </Card>
        );
      })}
    </div>
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
    <ol className="flex flex-col gap-2">
      {steps.map((step) => (
        <li key={step.id} className="flex items-start gap-3">
          <span className="w-5 shrink-0 pt-0.5 text-right font-mono text-xs text-muted-foreground">
            {step.sequence}
          </span>

          <span className="min-w-0 flex-1">
            <span className="block text-sm">{step.description}</span>
            {step.input_data && (
              <span className="mt-0.5 block font-mono text-xs text-muted-foreground">
                {step.input_data}
              </span>
            )}
            {step.expected_result && (
              <span className="mt-0.5 block text-xs text-muted-foreground">
                Expected: {step.expected_result}
              </span>
            )}
          </span>

          {step.selector_strategy && (
            <span
              className={`shrink-0 rounded border px-1.5 py-0.5 font-mono text-xs ${
                isFragile(step)
                  ? "border-destructive/40 bg-destructive/10 text-destructive"
                  : "border-success/40 bg-success/10 text-success"
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
