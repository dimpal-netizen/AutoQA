"use client";

/** Add the assertions the recorded test is missing.
 *
 *  A recording captures what somebody did, not what should have been true
 *  afterwards. The test it produces replays the clicks faithfully and checks
 *  nothing, so it passes as long as every click found something to click — add
 *  an item to a cart that stays empty and it still reports green.
 *
 *  That test is the baseline every other case in the suite is written around,
 *  which makes it the worst one to have no opinion.
 *
 *  Nothing is saved until somebody ticks it. A check nobody agreed to is how a
 *  suite acquires assertions it does not believe, and those are worse than no
 *  assertions at all: they go green and look like cover.
 */

import { useState } from "react";
import { Check, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import type { SuggestedCheck, TestSuiteDetail } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/card";

export function SuggestChecks({
  suiteId,
  onSaved,
}: {
  suiteId: number;
  onSaved: (suite: TestSuiteDetail) => void;
}) {
  const [suggested, setSuggested] = useState<SuggestedCheck[] | null>(null);
  const [chosen, setChosen] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  async function suggest() {
    setBusy(true);
    setError(null);
    setSaved(null);
    try {
      const found = await api.suites.suggestChecks(suiteId);
      setSuggested(found);
      // All ticked. Somebody who asked for checks wants checks; unticking the
      // one they disagree with is less work than ticking the five they want.
      setChosen(new Set(found.map((_, index) => index)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not suggest checks");
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!suggested) return;
    setSaving(true);
    setError(null);
    try {
      const keep = suggested.filter((_, index) => chosen.has(index));
      onSaved(await api.suites.saveChecks(suiteId, keep));
      setSuggested(null);
      setSaved(
        `Added ${keep.length} check${keep.length === 1 ? "" : "s"} to the recorded test.`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save those");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div>
        <Button
          size="sm"
          variant="outline"
          onClick={() => void suggest()}
          disabled={busy}
          title="Your recorded test replays what you did and checks nothing. This proposes what it should be checking."
        >
          <ShieldCheck className={busy ? "animate-pulse" : ""} />
          {busy ? "Reading the recording…" : "Suggest checks"}
        </Button>
      </div>

      {error && <Alert>{error}</Alert>}
      {saved && <Alert variant="info">{saved}</Alert>}

      {suggested && (
        <div className="rounded-lg border border-border bg-card p-3.5">
          <p className="text-[13px] font-medium">
            {suggested.length} check{suggested.length === 1 ? "" : "s"} for the
            recorded test
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            It currently asserts nothing — it passes as long as every click found
            something to click.
          </p>

          <ul className="mt-3 flex flex-col gap-2">
            {suggested.map((check, index) => (
              <li key={index}>
                <label className="flex cursor-pointer items-start gap-2 rounded px-1 py-1 hover:bg-accent">
                  <input
                    type="checkbox"
                    checked={chosen.has(index)}
                    onChange={() =>
                      setChosen((current) => {
                        const next = new Set(current);
                        if (!next.delete(index)) next.add(index);
                        return next;
                      })
                    }
                    className="mt-1 shrink-0"
                  />
                  <span className="min-w-0 text-[13px]">
                    <span className="text-muted-foreground">
                      After {check.step || `step ${check.after}`} —{" "}
                    </span>
                    {check.kind === "text" && check.expected
                      ? `${label(check.target)} should show “${check.expected}”`
                      : `${label(check.target)} should be visible`}
                    {/* Why it is worth having, in terms of the application
                        rather than the test. This is the sentence somebody
                        actually decides on. */}
                    {check.why && (
                      <span className="block text-xs text-muted-foreground">
                        Without it: {check.why}
                      </span>
                    )}
                  </span>
                </label>
              </li>
            ))}
          </ul>

          <div className="mt-3.5 flex items-center gap-2 border-t border-border pt-3">
            <Button
              size="sm"
              onClick={() => void save()}
              disabled={saving || chosen.size === 0}
            >
              <Check />
              {saving ? "Saving…" : `Add ${chosen.size}`}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setSuggested(null)}
              disabled={saving}
            >
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

/** `inventory_html.cart_badge` reads as "cart badge" to everyone but a
 *  programmer, and the page half is noise once you are looking at one test. */
function label(target: string): string {
  return target.split(".").pop()?.replace(/_/g, " ") ?? target;
}
