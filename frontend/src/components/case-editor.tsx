"use client";

/** Write or fix a test case without writing Python.
 *
 *  A generated suite is where a tester starts, not where they finish. They know
 *  the application and will think of a case the model missed, or spot one it got
 *  subtly wrong — and until this existed the only answers were "regenerate and
 *  hope" or "abandon the tool and write Playwright by hand".
 *
 *  Every field here is a choice from a list the backend served: an action from
 *  the fixed vocabulary, an element the recording actually found, a value. There
 *  is deliberately no code box. Generated tests run in a subprocess on someone's
 *  machine, and the moment a person can type Python into this form, what runs
 *  there stops being something anybody reviewed.
 *
 *  The lists are fetched rather than hardcoded because the elements come from
 *  the recording — they differ per suite — and because a copy of the action list
 *  living in the browser would drift the day a verb is added to the backend.
 */

import { useEffect, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  Check,
  Info,
  Plus,
  TriangleAlert,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import {
  CATEGORY_LABEL,
  CATEGORY_ORDER,
  type CaseCategory,
  type CasePriority,
  type CaseStepWrite,
  type CaseVocabulary,
  type TestCase,
} from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/card";
import { Input, Label, Select, Textarea } from "@/components/ui/input";
import { cn } from "@/lib/utils";

const PRIORITIES: CasePriority[] = ["critical", "high", "medium", "low"];

/** Categories a person may file a case under. "recorded" is missing on purpose:
 *  it means "this is the session you walked", which is not something you can
 *  decide about a case you just wrote. */
const AUTHORABLE = CATEGORY_ORDER.filter((c) => c !== "recorded");

export function CaseEditor({
  suiteId,
  testCase,
  onClose,
  onSaved,
}: {
  suiteId: number;
  /** The case being edited, or null to write a new one. */
  testCase: TestCase | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [vocabulary, setVocabulary] = useState<CaseVocabulary | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [name, setName] = useState(testCase?.name ?? "");
  const [description, setDescription] = useState(testCase?.description ?? "");
  const [category, setCategory] = useState<CaseCategory>(
    testCase && testCase.category !== "recorded" ? testCase.category : "positive",
  );
  const [priority, setPriority] = useState<CasePriority>(
    testCase?.priority ?? "medium",
  );
  const [steps, setSteps] = useState<CaseStepWrite[]>(() => stepsOf(testCase));

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const loaded = await api.cases.vocabulary(suiteId);
        if (!cancelled) setVocabulary(loaded);
      } catch (err) {
        if (!cancelled) {
          setLoadError(
            err instanceof Error ? err.message : "Could not load the element list",
          );
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [suiteId]);

  // Escape closes, like every other overlay. Bound on the document because the
  // panel is not always what holds focus — a select inside it swallows the key.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  // A case built before the editor existed has no record of which check each of
  // its assertion steps was — "assert" covers seven different ones. Guessing
  // would quietly change what the test verifies, so it is refused instead.
  const unreadable = Boolean(testCase) && testCase!.steps.some((s) => !s.verb);

  function patch(index: number, values: Partial<CaseStepWrite>) {
    setSteps((current) =>
      current.map((step, i) => (i === index ? { ...step, ...values } : step)),
    );
  }

  function move(index: number, by: number) {
    setSteps((current) => {
      const to = index + by;
      if (to < 0 || to >= current.length) return current;
      const next = [...current];
      [next[index], next[to]] = [next[to], next[index]];
      return next;
    });
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const body = {
        name: name.trim(),
        description: description.trim() || null,
        category,
        priority,
        steps: steps.map((step) => ({
          action: step.action,
          target: step.target || null,
          value: step.value ?? null,
          description: step.description?.trim() || null,
        })),
      };

      if (testCase) await api.cases.update(testCase.id, body);
      else await api.cases.create(suiteId, body);

      onSaved();
    } catch (err) {
      // The backend's refusals are the useful ones — "step 3: unknown element",
      // "no assertion; the test would pass even when broken". Shown as written
      // rather than replaced with something vaguer.
      setError(err instanceof Error ? err.message : "Could not save this case");
    } finally {
      setSaving(false);
    }
  }

  const verbOf = (action: string) =>
    vocabulary?.verbs.find((v) => v.name === action) ?? null;

  const hasCheck = steps.some((s) => verbOf(s.action)?.is_assertion);
  const hasAction = steps.some(
    (s) => s.action && verbOf(s.action)?.is_assertion === false,
  );
  const full = Boolean(vocabulary && steps.length >= vocabulary.max_steps);
  const ready =
    name.trim().length > 0 && steps.length > 0 && !unreadable && !saving;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-foreground/25 p-4 backdrop-blur-[2px] sm:p-8"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={testCase ? `Edit ${testCase.name}` : "New test case"}
        className="w-full max-w-3xl rounded-xl border border-border bg-card shadow-lg"
      >
        <header className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
          <div className="min-w-0">
            <h2 className="text-base font-bold tracking-tight">
              {testCase ? "Edit test case" : "New test case"}
            </h2>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Pick an action and an element for each step. AutoQA writes the
              Python, exactly as it does for the generated cases.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="shrink-0 rounded-full p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <X className="size-4" />
          </button>
        </header>

        <div className="flex max-h-[70vh] flex-col gap-5 overflow-y-auto px-5 py-5">
          {loadError && <Alert>{loadError}</Alert>}

          {unreadable && (
            <Alert variant="warning">
              <TriangleAlert className="mr-1 inline size-4" />
              This case was generated before step editing existed, so which check
              each of its steps performs was never recorded. Regenerate the suite
              and it becomes editable.
            </Alert>
          )}

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <Label htmlFor="case-name">Name</Label>
              <Input
                id="case-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Rejects a password shorter than eight characters"
                className="mt-1.5"
              />
            </div>

            <div>
              <Label htmlFor="case-category">Category</Label>
              <Select
                id="case-category"
                value={category}
                onChange={(e) => setCategory(e.target.value as CaseCategory)}
                className="mt-1.5"
              >
                {AUTHORABLE.map((option) => (
                  <option key={option} value={option}>
                    {CATEGORY_LABEL[option]}
                  </option>
                ))}
              </Select>
            </div>

            <div>
              <Label htmlFor="case-priority">Priority</Label>
              <Select
                id="case-priority"
                value={priority}
                onChange={(e) => setPriority(e.target.value as CasePriority)}
                className="mt-1.5"
              >
                {PRIORITIES.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </Select>
            </div>

            <div className="sm:col-span-2">
              <Label htmlFor="case-description">
                Description{" "}
                <span className="font-normal text-muted-foreground">
                  — goes into the test-case sheet
                </span>
              </Label>
              <Textarea
                id="case-description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="What this case proves, in a sentence."
                className="mt-1.5 min-h-16"
              />
            </div>
          </div>

          <div>
            <div className="mb-2 flex items-baseline justify-between gap-3">
              <Label>Steps</Label>
              <span className="text-xs text-muted-foreground">
                {steps.length}
                {vocabulary ? ` of ${vocabulary.max_steps}` : ""}
              </span>
            </div>

            <div className="flex flex-col gap-2">
              {steps.map((step, index) => (
                <StepRow
                  key={index}
                  index={index}
                  step={step}
                  vocabulary={vocabulary}
                  first={index === 0}
                  last={index === steps.length - 1}
                  onChange={(values) => patch(index, values)}
                  onMove={(by) => move(index, by)}
                  onRemove={() =>
                    setSteps((current) => current.filter((_, i) => i !== index))
                  }
                />
              ))}
            </div>

            <Button
              variant="outline"
              size="sm"
              className="mt-3"
              disabled={!vocabulary || full}
              onClick={() =>
                setSteps((current) => [
                  ...current,
                  { action: "click", target: null, value: null },
                ])
              }
            >
              <Plus />
              {full ? `Limit is ${vocabulary?.max_steps} steps` : "Add step"}
            </Button>
          </div>

          {/* The two rules the backend will refuse on, said before the refusal
              rather than after it. Both are worth understanding rather than
              working around: a case that checks nothing reports green whether
              or not the feature works. */}
          {steps.length > 0 && !hasCheck && (
            <p className="flex items-start gap-2 text-xs text-warning">
              <Info className="mt-px size-3.5 shrink-0" />
              No check yet. A test with nothing to verify passes even when the
              feature is broken — add a &ldquo;Should&hellip;&rdquo; step.
            </p>
          )}
          {steps.length > 0 && hasCheck && !hasAction && (
            <p className="flex items-start gap-2 text-xs text-warning">
              <Info className="mt-px size-3.5 shrink-0" />
              Only checks so far. Without a step that opens a page or does
              something, this runs against a blank page.
            </p>
          )}

          {error && <Alert>{error}</Alert>}
        </div>

        <footer className="flex items-center justify-end gap-2 border-t border-border px-5 py-3.5">
          <Button variant="ghost" size="sm" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button size="sm" onClick={save} disabled={!ready}>
            <Check />
            {saving ? "Saving…" : testCase ? "Save changes" : "Create test case"}
          </Button>
        </footer>
      </div>
    </div>
  );
}

/** One step: what to do, what to do it to, and with what.
 *
 *  The element and value inputs appear only when the chosen action needs them,
 *  so a "Click" row is two controls and a "Type into" row is three. Showing all
 *  three always would mean most rows carry a box that must stay empty. */
function StepRow({
  index,
  step,
  vocabulary,
  first,
  last,
  onChange,
  onMove,
  onRemove,
}: {
  index: number;
  step: CaseStepWrite;
  vocabulary: CaseVocabulary | null;
  first: boolean;
  last: boolean;
  onChange: (values: Partial<CaseStepWrite>) => void;
  onMove: (by: number) => void;
  onRemove: () => void;
}) {
  const verb = vocabulary?.verbs.find((v) => v.name === step.action) ?? null;
  const element =
    vocabulary?.elements.find((e) => e.target === step.target) ?? null;

  const actions = vocabulary?.verbs.filter((v) => !v.is_assertion) ?? [];
  const checks = vocabulary?.verbs.filter((v) => v.is_assertion) ?? [];

  return (
    <div
      className={cn(
        "rounded-lg border border-border bg-muted/30 px-3 py-2.5",
        verb?.is_assertion && "border-l-2 border-l-primary/40",
      )}
    >
      <div className="flex items-start gap-2">
        <span className="tabular mt-2 w-4 shrink-0 text-right text-xs text-muted-foreground">
          {index + 1}
        </span>

        <div className="grid min-w-0 flex-1 gap-2 sm:grid-cols-[minmax(0,11rem)_1fr]">
          <Select
            aria-label={`Step ${index + 1} action`}
            value={step.action}
            onChange={(e) => {
              const next = vocabulary?.verbs.find(
                (v) => v.name === e.target.value,
              );
              // Clearing what the new action cannot use stops a hidden element
              // from being submitted with a verb that takes no target.
              onChange({
                action: e.target.value,
                target: next?.needs_target ? step.target : null,
                value: next?.needs_value ? step.value : null,
              });
            }}
          >
            <optgroup label="Do">
              {actions.map((v) => (
                <option key={v.name} value={v.name}>
                  {v.label}
                </option>
              ))}
            </optgroup>
            <optgroup label="Check">
              {checks.map((v) => (
                <option key={v.name} value={v.name}>
                  {v.label}
                </option>
              ))}
            </optgroup>
          </Select>

          <div className="grid min-w-0 gap-2">
            {verb?.needs_target && (
              <Select
                aria-label={`Step ${index + 1} element`}
                value={step.target ?? ""}
                onChange={(e) => onChange({ target: e.target.value })}
              >
                <option value="">Choose an element…</option>
                {(vocabulary?.elements ?? []).map((choice) => (
                  <option key={choice.target} value={choice.target}>
                    {choice.label} — {choice.page}
                  </option>
                ))}
              </Select>
            )}

            {verb?.needs_value && (
              <Input
                aria-label={`Step ${index + 1} value`}
                value={step.value ?? ""}
                onChange={(e) => onChange({ value: e.target.value })}
                placeholder={
                  verb.name === "goto"
                    ? "https://…"
                    : verb.name === "press"
                      ? "Enter"
                      : verb.allows_empty
                        ? "Leave blank to clear the field"
                        : "Value"
                }
              />
            )}

            {/* A literal address passes the first run and is red forever after,
                because the account now exists. The tester has no way to guess
                that, so the alternative is offered where the value is typed. */}
            {verb?.needs_value && verb.name === "fill" && (
              <div className="flex flex-wrap gap-1.5">
                {(vocabulary?.placeholders ?? []).map((placeholder) => (
                  <button
                    key={placeholder.token}
                    type="button"
                    title={placeholder.label}
                    onClick={() => onChange({ value: placeholder.token })}
                    className="rounded border border-border bg-card px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground transition-colors hover:border-primary hover:text-primary"
                  >
                    {placeholder.token}
                  </button>
                ))}
              </div>
            )}

            {element?.fragile && (
              <p className="flex items-start gap-1.5 text-[11px] text-warning">
                <TriangleAlert className="mt-px size-3 shrink-0" />
                Found by {element.strategy} — the kind of selector most likely to
                break when the UI changes.
              </p>
            )}
          </div>
        </div>

        <div className="flex shrink-0 items-center">
          <IconButton
            label={`Move step ${index + 1} up`}
            disabled={first}
            onClick={() => onMove(-1)}
          >
            <ArrowUp className="size-3.5" />
          </IconButton>
          <IconButton
            label={`Move step ${index + 1} down`}
            disabled={last}
            onClick={() => onMove(1)}
          >
            <ArrowDown className="size-3.5" />
          </IconButton>
          <IconButton label={`Remove step ${index + 1}`} onClick={onRemove}>
            <X className="size-3.5" />
          </IconButton>
        </div>
      </div>
    </div>
  );
}

function IconButton({
  label,
  disabled,
  onClick,
  children,
}: {
  label: string;
  disabled?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className="rounded p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:pointer-events-none disabled:opacity-30"
    >
      {children}
    </button>
  );
}

/** A stored case, back in the shape the editor works in.
 *
 *  `verb` is what makes this possible at all: seven different checks are stored
 *  as the same action, so without it a loaded step would come back as whichever
 *  of them happened to be listed first. */
function stepsOf(testCase: TestCase | null): CaseStepWrite[] {
  if (!testCase) return [];

  return testCase.steps.map((step) => ({
    action: step.verb ?? "",
    target: step.locator,
    // Exactly one of the two holds the value: an action puts it in input_data,
    // a check in expected_result. `??` rather than `||` so an intentionally
    // empty fill — clearing a required field — survives the round trip.
    value: step.input_data ?? step.expected_result,
    description: step.description,
  }));
}
