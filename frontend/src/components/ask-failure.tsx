"use client";

/** Ask a question about one failure.
 *
 *  Sits under the screenshot, at the bottom of the expanded row, and that
 *  position is the feature. The project-wide box answers "what is failing, and
 *  since when"; by the time you are here you know what failed and you are
 *  looking at the picture of it. The questions that come next are specific —
 *  "is this the app or my test?", "why did it stop there?", "what would you
 *  check first?" — and they only make sense with the evidence in view.
 *
 *  The answer is allowed to say it does not know, and says so where it cannot
 *  tell: a tester acting on a confident wrong answer debugs the wrong thing for
 *  an afternoon.
 */

import { useState } from "react";
import { MessageCircleQuestion } from "lucide-react";
import { api } from "@/lib/api";
import type { AskAnswer, AskTurn } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Alert } from "@/components/ui/card";

/** One question and what came back. Kept in the component: an exchange about a
 *  failure is worth having while you are looking at it and worth nothing
 *  tomorrow, so storing it would mean a table and a retention policy for
 *  something nobody will open twice. */
type Exchange = { question: string; answer: AskAnswer };

/** Starting points, for the blank-box problem. Someone who has never asked a
 *  tool a question does not know what it can answer, and an empty field with a
 *  placeholder is not an answer to that. */
const SUGGESTIONS = [
  "Is this the application or my test?",
  "What should I check first?",
  "Why did it stop at that step?",
];

export function AskFailure({ resultId }: { resultId: number }) {
  const [question, setQuestion] = useState("");
  const [thread, setThread] = useState<Exchange[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Shut until asked for. An expanded failure already carries the error, two
  // action buttons, the screenshot, the recording and the trace — a text field
  // and three suggestion chips sitting open underneath all of that is a row of
  // furniture for a thing most people will not do on most failures.
  const [open, setOpen] = useState(false);

  async function ask(asked: string) {
    const text = asked.trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);
    try {
      // What has been said so far, so "and if that is fine?" means something.
      const history: AskTurn[] = thread.map((turn) => ({
        question: turn.question,
        answer: turn.answer.answer,
      }));
      const answer = await api.analysis.askAboutFailure(resultId, text, history);
      setThread((current) => [...current, { question: text, answer }]);
      // Cleared only on success. A question that failed is still in the box to
      // try again, which beats retyping it.
      setQuestion("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not answer that");
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      // Right-aligned, and `outline` rather than `ghost`. Ghost is
      // `text-muted-foreground`, which reads as a caption rather than a
      // control — someone who has never used this had no reason to think it
      // was clickable. It now matches the other two actions on the page.
      <div className="flex justify-end">
        <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
          <MessageCircleQuestion />
          Ask about this failure
        </Button>
      </div>
    );
  }

  return (
    <div className="rounded-md border border-border bg-card p-3">
      {thread.length > 0 && (
        <div className="mb-2.5 flex flex-col gap-2.5">
          {thread.map((turn, index) => (
            <div
              key={index}
              className={index > 0 ? "border-t border-border pt-2.5" : undefined}
            >
              <p className="text-[13px] font-medium">{turn.question}</p>
              <p className="mt-1 whitespace-pre-line text-[13px] leading-relaxed">
                {turn.answer.answer}
              </p>

              {!turn.answer.confident && (
                <p className="mt-1 text-xs text-warning">
                  The evidence here does not really settle this — treat it as a
                  hint, not an answer.
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Input
          // The box was opened deliberately, so the cursor belongs in it.
          autoFocus
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void ask(question);
            // Opened it and changed your mind. Only while nothing has been
            // asked — once there is a thread, Escape would throw it away.
            if (e.key === "Escape" && !thread.length && !question) setOpen(false);
          }}
          disabled={busy}
          maxLength={500}
          aria-label="Ask a question about this failure"
          placeholder={
            thread.length ? "Ask a follow-up…" : "Ask about this failure…"
          }
          className="min-w-0 flex-1"
        />
        <Button
          size="sm"
          variant="outline"
          onClick={() => void ask(question)}
          disabled={busy || !question.trim()}
        >
          <MessageCircleQuestion className={busy ? "animate-pulse" : ""} />
          {busy ? "Looking…" : "Ask"}
        </Button>
      </div>

      {/* Only before the first question. Once there is a thread these compete
          with the follow-up you were about to type, and the useful next
          question is one this list could not have guessed. */}
      {thread.length === 0 && !busy && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {SUGGESTIONS.map((suggestion) => (
            <button
              key={suggestion}
              type="button"
              onClick={() => void ask(suggestion)}
              className="rounded-full border border-border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              {suggestion}
            </button>
          ))}
        </div>
      )}

      {error && <Alert className="mt-2">{error}</Alert>}
    </div>
  );
}
