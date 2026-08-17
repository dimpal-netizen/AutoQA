"use client";

/** Ask the AI for the test cases a QA engineer would add around the recording.
 *
 *  This is the one feature that genuinely needs a model, so the failure case
 *  gets real estate: no key configured is an explanation, not a dead button.
 */

import { useEffect, useRef, useState } from "react";
import { MousePointerClick, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import type { TestSuiteDetail } from "@/lib/types";
import { Button } from "@/components/ui/button";

/** Matches the cap the API enforces, so the box cannot accept what the server
 *  would silently trim. */
const MAX_GUIDANCE = 1000;

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
   *  dismiss.
   *
   *  That holds for "these were built from the recording, not by a model" too.
   *  It was worth a line in theory and was a paragraph of blue prose in
   *  practice, sitting above a table that had just answered the question. */
  onOutcome?: (error: string | null) => void;
}) {
  const [busy, setBusy] = useState(false);
  // Asked for on the way in rather than sitting on the page. It describes one
  // batch, so it belongs to the press of the button - and a box left on screen
  // is a box somebody fills in once and then forgets is steering every
  // generation afterwards.
  const [asking, setAsking] = useState(false);

  async function generate(guidance: string) {
    setAsking(false);
    setBusy(true);
    onOutcome?.(null);
    try {
      const response = await api.suites.generateCases(suiteId, 12, guidance);
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
    <>
      {asking && (
        <AskWhatToCoverOn
          onCancel={() => setAsking(false)}
          onGenerate={(guidance) => void generate(guidance)}
        />
      )}
    <Button
      onClick={() => setAsking(true)}
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
    </>
  );
}


/** The brief behind "From what I did".
 *
 *  A sentence rather than a flag, because that is genuinely all the difference
 *  is. Both buttons run the same generation against the same elements — the
 *  recording only ever captured the ones somebody touched — so what separates
 *  them is which cases may be written, and that is a thing you say.
 *
 *  This one is a fence, not a hint. Every clause below closes a door the model
 *  would otherwise walk through: it may not add a step, may not touch an
 *  element the recording did not, may not think of a scenario of its own. What
 *  is left is the recorded journey with different values in it — which is
 *  exactly what somebody means by "test what I did", and nothing else.
 *
 *  The other button is where the model's own judgement belongs. Wanting both
 *  from one press is how you get a batch that claims to be your flow and is
 *  half invented.
 */
const FROM_MY_ACTIONS = [
  "HARD LIMIT: build every case only out of the steps in the recorded flow above.",
  "",
  "You may: reuse those steps, in the order they were recorded; stop the flow",
  "early; leave a field empty that was filled; and change the value typed into a",
  "field to one the application should refuse.",
  "",
  "You may NOT: add a step that is not in the recording; use an element the",
  "recorded steps did not use; reorder the steps; or invent a scenario of your",
  "own, however worthwhile it looks. Do not test anything the recording did not",
  "do. If that leaves fewer cases than asked for, write fewer.",
].join("\n");


/** Ask what this batch should be about, before spending a request on it.
 *
 *  Optional, and it says so: Generate with the box empty is the old behaviour
 *  exactly. But a recording cannot say which parts of an application matter,
 *  and the person pressing the button usually can - so this is the one moment
 *  they are certain to be there to say it.
 */
function AskWhatToCoverOn({
  onCancel,
  onGenerate,
}: {
  onCancel: () => void;
  onGenerate: (guidance: string) => void;
}) {
  const [text, setText] = useState("");
  const box = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    box.current?.focus();
  }, []);

  /** Short to read, full when used. Four sentence-long chips wrapped onto
   *  three lines and turned the dialog into a wall; two words each keeps them
   *  on one line, and clicking still fills the box with something worth
   *  sending rather than a heading to write under. */
  const examples: [string, string][] = [
    ["Validation rules", "The validation rules on every field - what each one accepts and rejects"],
    ["Required fields", "Fields that are required but easy to leave blank"],
    ["Expired session", "What happens when the session has expired"],
  ];

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-foreground/25 p-4 backdrop-blur-[2px] sm:p-8"
      onClick={(event) => {
        if (event.target === event.currentTarget) onCancel();
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") onCancel();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="What should these test cases cover?"
        className="mt-16 w-full max-w-xl overflow-hidden rounded-xl border border-border bg-card shadow-lg"
      >
        <header className="flex items-start gap-3 px-5 pb-4 pt-5">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary-subtle text-primary [&_svg]:size-5">
            <Sparkles />
          </span>
          <div className="min-w-0">
            <h2 className="text-base font-bold tracking-tight">
              What should these test cases cover?
            </h2>
            <p className="mt-0.5 text-sm text-muted-foreground">
              Optional — leave it empty and AutoQA decides for itself.
            </p>
          </div>
        </header>

        <div className="flex flex-col gap-2.5 px-5 pb-4">
          <div className="relative">
            <textarea
              ref={box}
              value={text}
              onChange={(event) => setText(event.target.value)}
              maxLength={MAX_GUIDANCE}
              rows={3}
              placeholder="In your own words — what matters, or what you already know breaks."
              className="w-full resize-y rounded-lg border border-border bg-background px-3 py-2.5 pb-7 text-sm leading-relaxed text-foreground placeholder:text-muted-foreground focus-visible:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/15"
            />
            {/* Inside the box, bottom right — a counter on its own line below
                would push the chips down and read as an error message. */}
            <span
              className={`pointer-events-none absolute bottom-2 right-3 text-[11px] tabular ${
                text.length > MAX_GUIDANCE - 100
                  ? "text-warning"
                  : "text-muted-foreground"
              }`}
            >
              {text.length ? `${text.length}/${MAX_GUIDANCE}` : ""}
            </span>
          </div>

          {/* Only until they start typing. Once there is a brief, four
              suggestions are four things to ignore. */}
          {!text.trim() && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-xs text-muted-foreground">Or start from:</span>
              {examples.map(([label, brief]) => (
                <button
                  key={label}
                  type="button"
                  onClick={() => {
                    setText(brief);
                    box.current?.focus();
                  }}
                  className="rounded-full border border-border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                >
                  {label}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Just the two buttons. The caveat that used to sit here - "steers
            which tests get written, not what they may do" - is reassurance
            nobody needs while deciding what to type, and it made a four-line
            dialog into a six-line one. */}
        <footer className="flex items-center justify-end gap-2 border-t border-border bg-surface/60 px-5 py-3">
          <Button variant="ghost" size="sm" onClick={onCancel}>
            Cancel
          </Button>
          {/* Two ways to generate, and the difference is the brief. This one
              fences the model into the recorded steps; the other lets it use
              its own judgement about what is worth testing.

              Always offered, including once something has been typed. What you
              wrote is added to the fence rather than replacing it, because
              "the phone rules, but only with what I recorded" is a sensible
              thing to want and hiding the button made it impossible to ask
              for. */}
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              onGenerate(
                text.trim()
                  ? `${FROM_MY_ACTIONS}\n\nWithin that, concentrate on: ${text.trim()}`
                  : FROM_MY_ACTIONS,
              )
            }
            title="Only the steps you recorded — reused, stopped early, or with values the application should refuse. Nothing added, nothing invented."
          >
            <MousePointerClick />
            From what I did
          </Button>
          <Button size="sm" onClick={() => onGenerate(text)}>
            <Sparkles />
            Generate
          </Button>
        </footer>
      </div>
    </div>
  );
}
