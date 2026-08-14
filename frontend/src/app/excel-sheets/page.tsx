"use client";

/** Every manual test-case spreadsheet anybody has uploaded.
 *
 *  A library rather than an upload form. Sheets are kept per project — that is
 *  where one is uploaded and where it becomes cases — and this is the flat view
 *  across all of them, for the question you have before you know which project
 *  to open: what have we got, and what is it built from.
 *
 *  Uploading happens inside a project, next to Record a session, because a
 *  sheet on its own cannot become a test. A recording says what is on the page;
 *  a sheet says what is worth testing. Both are needed, and only the project
 *  page has the other half.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { FileSpreadsheet, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import type { ExcelSheet, Project } from "@/lib/types";
import { AppShell } from "@/components/app-shell";
import { RequireAuth } from "@/components/auth-provider";
import { Button, buttonVariants } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export default function ExcelSheetsPage() {
  return (
    <RequireAuth>
      <AppShell wide>
        <Library />
      </AppShell>
    </RequireAuth>
  );
}

function Library() {
  const [sheets, setSheets] = useState<ExcelSheet[] | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [allSheets, allProjects] = await Promise.all([
        api.sheets.list(),
        api.projects.list(),
      ]);
      setSheets(allSheets);
      setProjects(allProjects);
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setSheets([]);
    }
  }, []);

  useEffect(() => {
    // Wrapped rather than called straight: setState in an effect body is a
    // cascading render, and the await puts it after this one has finished.
    void (async () => {
      await load();
    })();
  }, [load]);

  const projectName = useMemo(
    () => new Map(projects.map((project) => [project.id, project.name])),
    [projects],
  );

  async function remove(sheet: ExcelSheet) {
    setBusy(sheet.id);
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
    <div className="animate-in flex flex-col gap-6">
      <header>
        <h1 className="text-2xl font-bold leading-tight tracking-tight">
          Excel sheets
        </h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          The manual test-case spreadsheets your team has uploaded, kept so they
          can be built from more than once. Upload one inside a project, beside
          Record a session — a sheet says what is worth testing, and it needs a
          recording to say what is on the page.
        </p>
      </header>

      {error && (
        <p className="rounded-md border border-destructive/25 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      )}

      {sheets === null ? (
        <Skeleton className="h-32 w-full" />
      ) : sheets.length === 0 ? (
        <EmptyState
          icon={<FileSpreadsheet />}
          title="No sheets uploaded yet"
          description="Open a project and press Import Excel. The sheet is kept here, and turns into automated cases once that project has a recording."
          action={
            <Link href="/projects" className={buttonVariants({})}>
              Go to projects
            </Link>
          }
        />
      ) : (
        <ul className="flex flex-col divide-y divide-border rounded-lg border">
          {sheets.map((sheet) => (
            <li
              key={sheet.id}
              className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm"
            >
              <FileSpreadsheet className="size-4 shrink-0 text-muted-foreground" />
              <span className="flex-1 truncate font-medium">{sheet.filename}</span>

              {/* Which project it belongs to, and a way into it — the sheet is
                  only useful next to that project's recording, so the name is
                  the link rather than decoration. */}
              <Link
                href={`/projects/${sheet.project_id}`}
                className="text-xs text-primary hover:underline"
              >
                {projectName.get(sheet.project_id) ?? `Project ${sheet.project_id}`}
              </Link>

              <span className="tabular text-xs text-muted-foreground">
                {sheet.row_count} row{sheet.row_count === 1 ? "" : "s"}
              </span>
              <span className="tabular text-xs text-muted-foreground">
                {new Date(sheet.created_at).toLocaleDateString()}
              </span>

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
