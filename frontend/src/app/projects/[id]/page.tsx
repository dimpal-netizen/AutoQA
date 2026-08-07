"use client";

/** One project: record into it, and work on the tests it produced.
 *
 *  The entry point is the project list, and everything after that happens in
 *  here. That ordering is not decoration — it is what lets the record panel
 *  drop the "which project?" dropdown, because by the time you can press
 *  Record the answer is already on screen.
 */

import { use, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Bug, ExternalLink, Pencil, Video } from "lucide-react";
import { api, downloadBugReport } from "@/lib/api";
import type { Project, TestSuite, TestSuiteDetail } from "@/lib/types";
import { useAuthStore } from "@/stores/auth-store";
import { AppShell } from "@/components/app-shell";
import { RequireAuth } from "@/components/auth-provider";
import { LaunchRecording } from "@/components/launch-recording";
import { SuiteWorkspace } from "@/components/suite-workspace";
import { Button } from "@/components/ui/button";
import { Alert, EmptyState } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export default function ProjectPage({
  params,
}: {
  // Next 16: params is a Promise, unwrapped with React's use().
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  return (
    <RequireAuth>
      <AppShell wide>
        <ProjectWorkspace id={Number(id)} />
      </AppShell>
    </RequireAuth>
  );
}

/** The project name, renameable in place.
 *
 *  In place rather than in a settings form: the name is the first thing on the
 *  page and the only thing anyone renames, so a whole form to change one field
 *  is a page nobody would visit twice.
 *
 *  Shown as editable only to whoever the API would actually let through —
 *  owner or admin, mirroring `_assert_can_edit`. Offering a control that always
 *  returns 403 is worse than not offering it.
 */
function ProjectName({
  project,
  onRenamed,
}: {
  project: Project;
  onRenamed: (project: Project) => void;
}) {
  const user = useAuthStore((s) => s.user);
  const canRename = user
    ? project.owner_id === user.id || user.role === "admin"
    : false;

  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(project.name);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    const name = draft.trim();

    // Nothing to do, and an empty name would leave the project unfindable.
    if (!name || name === project.name) {
      setDraft(project.name);
      setEditing(false);
      setError(null);
      return;
    }

    setSaving(true);
    setError(null);
    try {
      onRenamed(await api.projects.update(project.id, { name }));
      setEditing(false);
    } catch (err) {
      // Renaming onto a name you already have is the common failure, and the
      // API says so precisely. Stay in the field so the name can be fixed
      // rather than retyped.
      setError(err instanceof Error ? err.message : "Could not rename");
    } finally {
      setSaving(false);
    }
  }

  if (!editing) {
    return (
      <h1 className="group flex min-w-0 items-center gap-2 text-2xl font-bold leading-tight tracking-tight">
        <span className="truncate">{project.name}</span>
        {canRename && (
          <button
            type="button"
            onClick={() => {
              setDraft(project.name);
              setEditing(true);
            }}
            aria-label={`Rename ${project.name}`}
            title="Rename"
            className="shrink-0 rounded-full p-1 text-muted-foreground opacity-0 transition-opacity hover:bg-accent hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100"
          >
            <Pencil className="size-4" />
          </button>
        )}
      </h1>
    );
  }

  return (
    <div className="min-w-0">
      <input
        autoFocus
        value={draft}
        disabled={saving}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => void save()}
        onKeyDown={(e) => {
          if (e.key === "Enter") void save();
          // Escape restores the original. A rename you did not mean to start
          // should cost nothing to abandon.
          if (e.key === "Escape") {
            setDraft(project.name);
            setEditing(false);
            setError(null);
          }
        }}
        aria-label="Project name"
        className="w-full min-w-0 rounded-lg border border-input bg-card px-2 py-1 text-2xl font-bold leading-tight tracking-tight outline-none focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-ring/40"
      />
      {error && <p className="mt-1.5 text-[13px] text-destructive">{error}</p>}
    </div>
  );
}

/** Download every bug in the project as one workbook.
 *
 *  Every *failing test*, not every drafted report. The first version exported
 *  only what somebody had clicked "Draft a bug report" on, so a project with
 *  sixteen red tests and no clicks exported nothing and the button answered
 *  "draft one from a failed test first" — which made the register a reward for
 *  filing rather than a view of the project. A bug register that leaves out
 *  bugs is the one thing it must never be.
 *
 *  Sits on the project rather than the suite because bugs belong to the
 *  project. A tester chasing "everything outstanding" does not want to visit
 *  four suites and join the results up by hand.
 */
function ExportBugs({
  project,
  onError,
}: {
  project: Project;
  onError: (message: string | null) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function away(event: PointerEvent) {
      if (!box.current?.contains(event.target as Node)) setOpen(false);
    }
    function escape(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", away);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  async function download(format: "xlsx" | "docx") {
    setOpen(false);
    setBusy(true);
    onError(null);
    try {
      const stem =
        project.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") ||
        "project";
      await downloadBugReport(project.id, `${stem}-bug-report.${format}`, format);
    } catch (err) {
      onError(
        err instanceof Error ? err.message : "Could not build the bug report",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div ref={box} className="relative">
      <Button
        variant="outline"
        onClick={() => setOpen((v) => !v)}
        disabled={busy}
        aria-expanded={open}
        aria-haspopup="menu"
        title="Every failing test in this project, in one file. No drafting needed."
      >
        <Bug />
        {busy ? "Building…" : "Bug report"}
      </Button>

      {open && (
        <div
          role="menu"
          // z-30 rather than 20: the workspace below has its own z-20 layers,
          // and a later sibling wins a tie. Still under the z-50 editor panel,
          // which should cover this rather than the other way round.
          className="absolute right-0 z-30 mt-1 w-72 overflow-hidden rounded-xl border border-border bg-card p-1 shadow-lg"
        >
          {/* Not two formats of one file — two different questions. One is a
              register you sort and count; the other is a document you attach to
              a ticket, and only it can carry the screenshots. */}
          <ExportChoice
            title="Excel spreadsheet"
            detail="One row per bug. Sort, filter and count."
            onClick={() => void download("xlsx")}
          />
          <ExportChoice
            title="Word document"
            detail="Each bug written out, with the screenshot of the failure."
            onClick={() => void download("docx")}
          />
        </div>
      )}
    </div>
  );
}

function ExportChoice({
  title,
  detail,
  onClick,
}: {
  title: string;
  detail: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className="w-full rounded-lg px-3 py-2 text-left transition-colors hover:bg-accent"
    >
      <span className="block text-[13px] font-medium">{title}</span>
      <span className="block text-xs text-muted-foreground">{detail}</span>
    </button>
  );
}

function ProjectWorkspace({ id }: { id: number }) {
  const [project, setProject] = useState<Project | null>(null);
  const [suites, setSuites] = useState<TestSuite[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<TestSuiteDetail | null>(null);
  const [recording, setRecording] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [found, list] = await Promise.all([
        api.projects.get(id),
        api.suites.list(id),
      ]);
      setProject(found);
      setSuites(list);
      setSelected((current) => current ?? list[0]?.id ?? null);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load this project");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    void (async () => {
      await load();
    })();
  }, [load]);

  useEffect(() => {
    if (selected === null) return;
    let cancelled = false;
    void (async () => {
      try {
        // The run list was fetched here only to show "last run 2h ago" above
        // the table. That line is gone, and the run panel loads its own
        // history, so this is one request per suite selection that nobody was
        // waiting for.
        const found = await api.suites.get(selected);
        if (cancelled) return;
        setDetail(found);
      } catch {
        /* keep what is on screen; the id check below hides a stale one */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selected]);

  const current = detail && detail.id === selected ? detail : null;

  if (loading) return <Skeleton className="h-96 w-full" />;
  if (!project) return <Alert>{error ?? "Project not found"}</Alert>;

  return (
    <div className="animate-in flex flex-col gap-4">
      {/* Above the panel, not inside it. The panel is this project — its name,
          its URL, the button that records into it. A link that leaves the
          project is not part of the project, and putting it in the same box
          made the box mean two things. */}
      <Link
        href="/projects"
        className="inline-flex w-fit items-center gap-1.5 text-[13px] font-medium text-muted-foreground transition-colors hover:text-primary"
      >
        <ArrowLeft className="size-3.5" />
        All projects
      </Link>

      {/* No `overflow-hidden` here, deliberately. It was clipping the gradient
          below to the rounded corners, and clipping the export menu along with
          it — the second choice was cut off by the edge of the card. The
          gradient is the only thing that needed the rounding, so it carries it
          itself and the header stops cropping its own children. */}
      <header className="relative rounded-2xl border border-border bg-card px-6 py-6 shadow-xs sm:px-8">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 rounded-2xl"
          style={{
            background:
              "linear-gradient(120deg, var(--primary-subtle) 0%, transparent 62%)",
          }}
        />

        <div className="relative flex flex-wrap items-start gap-4">
          <div className="min-w-0 flex-1">
            <ProjectName
              project={project}
              onRenamed={(renamed) => setProject(renamed)}
            />

            <a
              href={project.base_url}
              target="_blank"
              rel="noreferrer noopener"
              className="mt-1.5 inline-flex max-w-full items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-primary"
            >
              <span className="truncate">{project.base_url}</span>
              <ExternalLink className="size-3.5 shrink-0" />
            </a>
          </div>

          {/* Only once there is something to record bugs against. On an empty
              project it would offer a download of nothing. */}
          {suites.length > 0 && (
            <ExportBugs project={project} onError={setError} />
          )}

          <Button variant="secondary" onClick={() => setRecording((v) => !v)}>
            <Video />
            {/* "Record a session" on a project that already has several reads
                like nothing has been done yet, and hides that this adds to
                them rather than replacing them. */}
            {recording
              ? "Close"
              : suites.length > 0
                ? "Record another session"
                : "Record a session"}
          </Button>
        </div>
      </header>

      {error && <Alert>{error}</Alert>}

      {recording && (
        <LaunchRecording
          project={project}
          onChanged={() => {
            void load();
          }}
          // The recording is over, so the panel offering to start one closes.
          // Leaving it open put an empty "Record a new session" form at the top
          // of the page at the moment the answer is "no — show me what I just
          // recorded".
          onFinished={() => setRecording(false)}
        />
      )}

      {suites.length === 0 ? (
        <EmptyState
          icon={<Video />}
          title="Nothing recorded yet"
          description="Press Record a session. A browser opens on this project's URL — use the site normally, and the tests are written when you stop."
          action={
            <Button onClick={() => setRecording(true)}>
              <Video />
              Record a session
            </Button>
          }
        />
      ) : current ? (
        <SuiteWorkspace
          suite={current}
          suites={suites}
          onSelect={setSelected}
          onChange={(updated) => {
            setDetail(updated);
            void load();
          }}
          onDeleted={() => {
            // Clear the selection before reloading. `load` only fills it in
            // when it is null, so leaving it pointing at the deleted suite
            // would leave the workspace stuck on a suite that is gone.
            setSelected(null);
            setDetail(null);
            void load();
          }}
        />
      ) : (
        <Skeleton className="h-96 w-full" />
      )}
    </div>
  );
}
