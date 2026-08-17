"use client";

/** A project's manual test-case spreadsheets.
 *
 *  Uploading one is a way into a project alongside recording a session, and the
 *  two are not alternatives — they answer different halves of the same
 *  question. A recording is the only thing that can say *what is on the page*:
 *  which box is the email field, which button submits. A sheet is the only
 *  thing that says *what your team cares about testing*. Neither makes a test
 *  on its own.
 *
 *  Neither of which means a sheet has to wait for somebody to record the same
 *  journeys first. With no recording, AutoQA opens the project's own URL and
 *  reads the pages itself — the address was always there, and nothing used it
 *  to look. What that cannot reach is anything behind a sign-in, because it
 *  arrives as a stranger; a recording gets past one because a person did.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { FileUp, Loader2, Sparkles, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import type { ExcelSheet, GenerateCasesResult, TestSuite } from "@/lib/types";
import { Button } from "@/components/ui/button";

export function ProjectSheets({
  projectId,
  suites,
  onGenerated,
}: {
  projectId: number;
  /** Recordings to build against. Empty is fine — then the site is read. */
  suites: TestSuite[];
  onGenerated: (result: GenerateCasesResult) => void;
}) {
  const [sheets, setSheets] = useState<ExcelSheet[] | null>(null);
  const [busy, setBusy] = useState<number | "upload" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<number | null>(null);
  const picker = useRef<HTMLInputElement>(null);

  // Derived rather than synchronised by an effect. A suite recorded while this
  // panel is open changes `suites` underneath us, and an effect that copies it
  // into state renders once with the stale value first. Working it out here
  // means there is no moment where the two disagree.
  const into =
    picked !== null && suites.some((suite) => suite.id === picked)
      ? picked
      : (suites[0]?.id ?? null);

  const load = useCallback(async () => {
    try {
      setSheets(await api.sheets.list(projectId));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setSheets([]);
    }
  }, [projectId]);

  useEffect(() => {
    // Wrapped rather than called straight: setState in an effect body is a
    // cascading render, and the await puts it after this one has finished.
    void (async () => {
      await load();
    })();
  }, [load]);

  async function upload(file: File) {
    setBusy("upload");
    setError(null);
    try {
      await api.sheets.upload(projectId, file);
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(null);
      if (picker.current) picker.current.value = ""; // so the same file re-reads
    }
  }

  async function generate(sheet: ExcelSheet) {
    setBusy(sheet.id);
    setError(null);
    try {
      onGenerated(await api.sheets.generate(sheet.id, into));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(null);
    }
  }

  async function remove(sheet: ExcelSheet) {
    setBusy(sheet.id);
    setError(null);
    try {
      await api.sheets.remove(sheet.id);
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-col gap-3 rounded-lg border p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-sm font-semibold">
          {sheets && sheets.length > 0
            ? `${sheets.length} sheet${sheets.length === 1 ? "" : "s"}`
            : "Sheets"}
        </h3>

        <div className="flex flex-wrap items-center gap-3">
          {suites.length > 1 && (
            <label className="flex items-center gap-2 text-sm">
              <span className="text-muted-foreground">Build against</span>
              <select
                aria-label="Suite"
                value={into ?? ""}
                onChange={(event) => setPicked(Number(event.target.value) || null)}
                className="h-8.5 rounded-md border border-input bg-background px-2 text-sm"
              >
                {suites.map((suite) => (
                  <option key={suite.id} value={suite.id}>
                    {suite.name}
                  </option>
                ))}
              </select>
            </label>
          )}

          {/* Another one, for when this panel is already open. The first
              upload came straight from Import Excel, which opens the file
              dialog itself - there is no Upload button standing between the
              press and the thing it promised. */}
          <input
            ref={picker}
            type="file"
            accept=".xlsx,.xlsm,.csv"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void upload(file);
            }}
          />
          <Button
            variant="outline"
            size="sm"
            disabled={busy !== null}
            onClick={() => picker.current?.click()}
            title="Another .xlsx or .csv, in whatever layout your team already writes them in"
          >
            {busy === "upload" ? <Loader2 className="animate-spin" /> : <FileUp />}
            {busy === "upload" ? "Reading…" : "Add another"}
          </Button>
        </div>
      </div>

      {/* Not a warning any more. With no recording AutoQA opens the project's
          own URL and reads the pages itself, so the only thing left to say is
          that this takes a little longer than building against a recording
          somebody already made. */}
      {suites.length === 0 && sheets && sheets.length > 0 && (
        <p className="rounded-md border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
          Nothing has been recorded here, so generating will open your site and
          read its pages first — about a minute. Pages behind a sign-in will not
          be seen; record a session to cover those.
        </p>
      )}

      {error && (
        <p className="rounded-md border border-destructive/25 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      )}

      {sheets !== null && sheets.length === 0 && !error && (
        <p className="text-sm text-muted-foreground">
          Nothing uploaded yet. Sheets are kept, so you can build from one again
          without finding the file a second time.
        </p>
      )}

      {sheets && sheets.length > 0 && (
        <ul className="flex flex-col divide-y divide-border">
          {sheets.map((sheet) => (
            <li
              key={sheet.id}
              className="flex flex-wrap items-center gap-3 py-2 text-sm"
            >
              <span className="flex-1 truncate font-medium">{sheet.filename}</span>
              <span className="tabular text-xs text-muted-foreground">
                {sheet.row_count} row{sheet.row_count === 1 ? "" : "s"}
              </span>

              <Button
                variant="outline"
                size="sm"
                disabled={busy !== null}
                title={
                  into === null
                    ? "Opens your site, reads what is on its pages, and writes cases covering what this sheet describes"
                    : "Write automated cases covering what this sheet describes"
                }
                onClick={() => void generate(sheet)}
              >
                {busy === sheet.id ? (
                  <Loader2 className="animate-spin" />
                ) : (
                  <Sparkles />
                )}
                Generate cases
              </Button>

              <Button
                variant="ghost"
                size="sm"
                disabled={busy !== null}
                aria-label={`Delete ${sheet.filename}`}
                onClick={() => void remove(sheet)}
              >
                <Trash2 />
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
