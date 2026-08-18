"use client";

/** Asking "are you sure" without handing the question to the browser.
 *
 *  Every delete in the app used `window.confirm`. It works, and it is the one
 *  dialog we cannot style, cannot lay out, and cannot put the name of the thing
 *  being deleted into with any emphasis — Chrome renders it as a strip pinned
 *  under the address bar, a long way from the row that was clicked, in a
 *  typeface belonging to nothing else on the page. A message about permanently
 *  removing somebody's work should not look like a browser notification.
 *
 *  `window.confirm` is also synchronous: it blocks the whole tab, including the
 *  render that was mid-flight when it opened. This returns a promise instead,
 *  so the call site keeps reading exactly as it did:
 *
 *      if (!(await confirm({ title: "Delete this run?", body: "…" }))) return;
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";

export type ConfirmRequest = {
  title: string;
  /** Paragraphs, split on blank lines. Kept as one string so the wording that
   *  was already written for these prompts moved across unchanged. */
  body?: string;
  /** What the button does, in the words of the thing it does. "Delete run",
   *  not "OK" — the label is the last thing read before the click. */
  confirmLabel?: string;
  /** Destructive by default: everything asking through this removes something. */
  tone?: "danger" | "normal";
};

/** A confirm dialog and the promise-returning function that opens it.
 *
 *  Deliberately not a context provider. A provider would mean wrapping the app
 *  and threading a hook through every component that deletes anything; this is
 *  local state and one line of JSX in the four places that need it.
 */
export function useConfirm() {
  const [request, setRequest] = useState<ConfirmRequest | null>(null);
  const answer = useRef<((ok: boolean) => void) | null>(null);

  const confirm = useCallback(
    (options: ConfirmRequest) =>
      new Promise<boolean>((resolve) => {
        answer.current = resolve;
        setRequest(options);
      }),
    [],
  );

  const settle = useCallback((ok: boolean) => {
    setRequest(null);
    // Cleared before resolving: whatever runs next may open another dialog,
    // and it must not find this one's resolver still sitting here.
    const resolve = answer.current;
    answer.current = null;
    resolve?.(ok);
  }, []);

  const dialog = request ? (
    <ConfirmDialog request={request} onAnswer={settle} />
  ) : null;

  return { confirm, dialog };
}

function ConfirmDialog({
  request,
  onAnswer,
}: {
  request: ConfirmRequest;
  onAnswer: (ok: boolean) => void;
}) {
  const danger = request.tone !== "normal";

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onAnswer(false);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onAnswer]);

  const paragraphs = (request.body ?? "")
    .split(/\n{2,}/)
    .map((part) => part.replace(/\s*\n\s*/g, " ").trim())
    .filter(Boolean);

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-foreground/25 p-4 backdrop-blur-[2px] sm:p-8"
      onClick={(event) => {
        if (event.target === event.currentTarget) onAnswer(false);
      }}
    >
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        className="mt-24 w-full max-w-md overflow-hidden rounded-xl border border-border bg-card shadow-lg"
      >
        <div className="flex items-start gap-3 px-5 pb-4 pt-5">
          <span
            className={`flex size-10 shrink-0 items-center justify-center rounded-xl [&_svg]:size-5 ${
              danger
                ? "bg-destructive-subtle text-destructive"
                : "bg-primary-subtle text-primary"
            }`}
          >
            <AlertTriangle />
          </span>
          <div className="min-w-0">
            <h2
              id="confirm-title"
              className="text-base font-bold tracking-tight text-balance"
            >
              {request.title}
            </h2>
            {paragraphs.map((text, index) => (
              <p
                key={index}
                className="mt-1.5 text-sm leading-relaxed text-muted-foreground"
              >
                {text}
              </p>
            ))}
          </div>
        </div>

        <footer className="flex items-center justify-end gap-2 border-t border-border bg-surface/60 px-5 py-3">
          {/* Cancel takes the focus, not the destructive button. Enter is the
              reflex after reading a dialog, and it must not be the thing that
              deletes somebody's work. */}
          <Button
            autoFocus
            variant="ghost"
            size="sm"
            onClick={() => onAnswer(false)}
          >
            Cancel
          </Button>
          <Button
            variant={danger ? "destructive" : "default"}
            size="sm"
            onClick={() => onAnswer(true)}
          >
            {request.confirmLabel ?? "Delete"}
          </Button>
        </footer>
      </div>
    </div>
  );
}
