"use client";

/** Ask the AI for the test cases a QA engineer would add around the recording.
 *
 *  This is the one feature that genuinely needs a model, so the failure case
 *  gets real estate: no key configured is an explanation, not a dead button.
 */

import { useState } from "react";
import { Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import type { TestSuiteDetail } from "@/lib/types";
import { Button } from "@/components/ui/button";

/** Just the button.
 *
 *  It used to carry its own progress line, error and result underneath, which
 *  was fine when it sat in a box of its own. It now lives in a row of buttons
 *  above the table, and anything it renders below itself makes that row two
 *  lines tall and pushes the table down — while generating, which is exactly
 *  when you are watching the table.
 *
 *  So it reports outcomes upward and the parent decides where they go. What it
 *  had to say while busy is gone entirely: the button already reads "Writing
 *  test cases…", is disabled, and its icon is pulsing. A sentence explaining
 *  that it usually takes 15-30 seconds is read once and then in the way.
 */
export function GenerateCases({
  suiteId,
  hasGenerated,
  onGenerated,
  onOutcome,
}: {
  suiteId: number;
  hasGenerated: boolean;
  onGenerated: (suite: TestSuiteDetail) => void;
  /** Why it failed, or null when it did not. Success says nothing: the table
   *  fills with the new cases and the tab badge changes to match, so a banner
   *  announcing it is the same news a third time and the only copy you have to
   *  dismiss. */
  onOutcome?: (error: string | null) => void;
}) {
  const [busy, setBusy] = useState(false);

  async function generate() {
    setBusy(true);
    onOutcome?.(null);
    try {
      const response = await api.suites.generateCases(suiteId);
      onGenerated(response.suite);
    } catch (err) {
      onOutcome?.(
        err instanceof Error ? err.message : "Could not generate test cases",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Button
      onClick={generate}
      disabled={busy}
      size="sm"
      variant={hasGenerated ? "outline" : "default"}
      title={
        hasGenerated
          ? "Rebuilds every case except your recording — including any you wrote by hand. An unchanged recording rebuilds the same cases. Usually 15-30 seconds."
          : "Positive, negative, edge and security cases built around this recording. Usually 15-30 seconds."
      }
    >
      <Sparkles className={busy ? "animate-pulse" : ""} />
      {busy
        ? "Writing test cases…"
        : hasGenerated
          ? "Regenerate cases"
          : "Generate test cases"}
    </Button>
  );
}
