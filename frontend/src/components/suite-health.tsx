"use client";

/** Two things about a suite that are only visible from above it.
 *
 *  **What only the happy path touches.** A recording walks one route and
 *  everything on it works — that is what a recording is. The value of the suite
 *  is in the cases written around it, so what is worth knowing is which parts
 *  of the flow have no test except the one that was always going to pass.
 *
 *  **What cannot make its mind up.** A test that always fails is useful. A test
 *  that fails one run in five is poison: nobody can tell whether it found a bug
 *  or had a bad morning, so the habit becomes "run it again" — and that habit
 *  gets applied to every red test, including the ones that were right.
 *
 *  Silent when there is nothing to say. A strip reporting "0 flaky, 100%
 *  covered" on every suite is furniture, and this page has enough of that.
 */

import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Repeat, Target } from "lucide-react";
import { api } from "@/lib/api";
import type { Coverage, FlakyTest } from "@/lib/types";

export function SuiteHealth({ suiteId }: { suiteId: number }) {
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [flaky, setFlaky] = useState<FlakyTest[]>([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setOpen(false);
    void Promise.all([api.suites.coverage(suiteId), api.suites.flaky(suiteId)])
      .then(([found, unreliable]) => {
        if (cancelled) return;
        setCoverage(found);
        setFlaky(unreliable);
      })
      // Neither of these is why anyone opened the page. If they cannot be
      // worked out, they are simply not mentioned.
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [suiteId]);

  const gaps = coverage?.untouched.length ?? 0;
  if (!gaps && !flaky.length) return null;

  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2 text-[13px]">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-3 text-left"
      >
        {open ? (
          <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" />
        )}

        {gaps > 0 && (
          <span className="flex items-center gap-1.5">
            <Target className="size-3.5 text-muted-foreground" />
            {gaps} {gaps === 1 ? "element has" : "elements have"} no test but the
            recording
          </span>
        )}

        {flaky.length > 0 && (
          <span className="flex items-center gap-1.5 text-warning">
            <Repeat className="size-3.5" />
            {flaky.length} unreliable {flaky.length === 1 ? "test" : "tests"}
          </span>
        )}
      </button>

      {open && (
        <div className="mt-2.5 flex flex-col gap-3 border-t border-border pt-2.5">
          {flaky.length > 0 && (
            <div>
              <p className="text-xs font-medium text-muted-foreground">
                Passing and failing without the test changing
              </p>
              <ul className="mt-1 flex flex-col gap-1">
                {flaky.map((test) => (
                  <li key={`${test.test_case_id}-${test.browser}`}>
                    {test.case_name}
                    <span className="text-muted-foreground"> — {test.summary}</span>
                  </li>
                ))}
              </ul>
              <p className="mt-1.5 text-xs text-muted-foreground">
                Usually timing: the test looks before the page has finished. One
                of these makes every other red test easier to dismiss.
              </p>
            </div>
          )}

          {gaps > 0 && coverage && (
            <div>
              <p className="text-xs font-medium text-muted-foreground">
                Driven only by the recorded run — {coverage.touched} of{" "}
                {coverage.total} have a test around them
              </p>
              <ul className="mt-1 flex flex-col gap-1">
                {coverage.untouched.map((item) => (
                  <li key={item.element}>
                    {item.label}
                    <span className="text-muted-foreground"> · {item.page}</span>
                    {item.fragile && (
                      <span className="text-warning"> · brittle selector</span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
