"use client";

/** A team's own manual test-case sheet, read and drafted.
 *
 *  Every QA team keeps a spreadsheet of cases somebody walks through by hand,
 *  and no two of those sheets look alike. Getting them in here meant retyping
 *  each one through the step editor, and nobody was ever going to retype forty.
 *
 *  Split in two on purpose. The button belongs in the toolbar beside Export
 *  Excel — importing and exporting are the same thought, and a lone button on
 *  a row of its own underneath reads as an afterthought. But what it opens is
 *  a list of drafted cases with tickboxes, and anything that grows *under* a
 *  toolbar button knocks the buttons beside it out of line. So the button
 *  reports upward and the parent puts the panel where there is room, which is
 *  the arrangement `GenerateCases` already uses for its outcome.
 *
 *  Nothing is saved until it is ticked. The drafts come back in the same shape
 *  the editor sends, so keeping one goes through the identical path a typed
 *  case does — an imported case cannot do anything a hand-written one could
 *  not, which is the whole reason a file from outside is safe to accept.
 */

import { useRef, useState } from "react";
import { Check, FileUp, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import type { CaseWrite, ImportPreview } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export function ImportCasesButton({
  suiteId,
  onPreview,
  onError,
}: {
  suiteId: number;
  onPreview: (preview: ImportPreview) => void;
  /** Why it could not be read, or null when it could. */
  onError: (message: string | null) => void;
}) {
  const picker = useRef<HTMLInputElement>(null);
  const [reading, setReading] = useState(false);

  async function read(file: File) {
    onError(null);
    setReading(true);
    try {
      onPreview(await api.suites.importCases(suiteId, file));
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setReading(false);
      if (picker.current) picker.current.value = ""; // so the same file re-reads
    }
  }

  return (
    <>
      <input
        ref={picker}
        type="file"
        accept=".xlsx,.xlsm,.csv"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) void read(file);
        }}
      />
      <Button
        variant="outline"
        size="sm"
        disabled={reading}
        title="Your own manual test cases as .xlsx or .csv, in whatever layout they are already in"
        onClick={() => picker.current?.click()}
      >
        {reading ? <Loader2 className="animate-spin" /> : <FileUp />}
        {reading ? "Reading…" : "Import Excel"}
      </Button>
    </>
  );
}

export function ImportReview({
  suiteId,
  preview,
  onDone,
  onError,
}: {
  suiteId: number;
  preview: ImportPreview;
  /** Saved, or discarded — either way the panel goes. */
  onDone: (saved: boolean) => void;
  onError: (message: string | null) => void;
}) {
  const [saving, setSaving] = useState(false);
  // Everything readable starts ticked. The common case is "yes, all of them",
  // and making somebody tick forty boxes to get what they uploaded is the
  // retyping this feature exists to remove.
  const [keep, setKeep] = useState<Set<number>>(
    () => new Set(preview.cases.map((_, index) => index)),
  );

  async function save() {
    setSaving(true);
    onError(null);
    const wanted: CaseWrite[] = preview.cases.filter((_, index) => keep.has(index));
    try {
      // One at a time, through the ordinary create. Slower than a bulk endpoint
      // and worth it: each case is validated exactly as a typed one is.
      for (const testCase of wanted) {
        await api.cases.create(suiteId, testCase);
      }
      onDone(true);
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : String(cause));
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col gap-3 rounded-lg border p-4">
      {/* First, and deliberately. A sheet misread by one column produces
          confident nonsense, and naming the columns used is the only way
          anybody can catch that before it is saved. */}
      <p className="text-sm">
        <span className="text-muted-foreground">How it was read: </span>
        {preview.reading}
      </p>

      <p className="text-xs tabular text-muted-foreground">
        {preview.rows} row{preview.rows === 1 ? "" : "s"} · {preview.cases.length} can
        be automated · {preview.skipped.length} cannot
      </p>

      {preview.cases.length > 0 && (
        <ul className="flex flex-col gap-1">
          {preview.cases.map((testCase, index) => (
            <li key={index} className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                className="mt-1"
                checked={keep.has(index)}
                onChange={(event) => {
                  const next = new Set(keep);
                  if (event.target.checked) next.add(index);
                  else next.delete(index);
                  setKeep(next);
                }}
              />
              <span className="flex-1">
                {testCase.name}
                <span className="ml-2 text-xs text-muted-foreground">
                  {testCase.steps.length} step{testCase.steps.length === 1 ? "" : "s"}
                </span>
              </span>
              <Badge tone="neutral">{testCase.category}</Badge>
            </li>
          ))}
        </ul>
      )}

      {/* Never dropped silently. A sheet of forty coming back as eleven cases
          and nothing else looks like it lost twenty-nine; the same sheet with
          twenty-nine reasons is an afternoon somebody can plan. */}
      {preview.skipped.length > 0 && (
        <details className="text-sm">
          <summary className="cursor-pointer text-muted-foreground">
            {preview.skipped.length} row{preview.skipped.length === 1 ? "" : "s"} that
            cannot be automated yet
          </summary>
          <ul className="mt-2 flex flex-col gap-1.5 pl-4">
            {preview.skipped.map((row, index) => (
              <li key={index}>
                <span className="tabular text-muted-foreground">
                  {row.row ? `Row ${row.row}: ` : ""}
                </span>
                {row.scenario}
                <span className="block text-xs text-muted-foreground">{row.reason}</span>
              </li>
            ))}
          </ul>
        </details>
      )}

      <div className="flex items-center gap-2">
        <Button
          size="sm"
          disabled={saving || keep.size === 0}
          onClick={() => void save()}
        >
          {saving ? <Loader2 className="animate-spin" /> : <Check />}
          Keep {keep.size} case{keep.size === 1 ? "" : "s"}
        </Button>
        <Button variant="ghost" size="sm" disabled={saving} onClick={() => onDone(false)}>
          Discard
        </Button>
      </div>
    </div>
  );
}
