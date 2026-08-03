"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, FolderKanban, Plus, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import {
  BROWSER_LABEL,
  hasRole,
  type Browser,
  type Project,
  type TestRun,
  type TestSuite,
} from "@/lib/types";
import { useAuthStore } from "@/stores/auth-store";
import { RequireAuth } from "@/components/auth-provider";
import { AppShell } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Input, Label, Textarea } from "@/components/ui/input";
import {
  Alert,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  EmptyState as Empty,
  PageHeader,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SearchBox, matches } from "@/components/ui/search";
import { Meter } from "@/components/ui/stat";
import { SkeletonRows } from "@/components/ui/skeleton";

const ALL_BROWSERS: Browser[] = ["chromium", "firefox", "webkit"];

/** What a project card can say about itself beyond its name.
 *
 *  This is the page you land on to choose what to work on, so a card that
 *  carries only a name and a URL makes you open all of them to find the one
 *  that needs you. */
interface Activity {
  suites: number;
  runs: number;
  passRate: number | null;
  lastRun: TestRun | null;
}

function activityFor(
  project: Project,
  suites: TestSuite[],
  runs: TestRun[],
): Activity {
  const mine = runs.filter((r) => r.project_id === project.id);
  const finished = mine.filter((r) => r.total > 0);
  const passed = finished.reduce((sum, r) => sum + r.passed, 0);
  const total = finished.reduce((sum, r) => sum + r.total, 0);

  return {
    suites: suites.filter((s) => s.project_id === project.id).length,
    runs: mine.length,
    passRate: total ? Math.round((passed / total) * 100) : null,
    // The list arrives newest first, so the first match is the latest.
    lastRun: mine[0] ?? null,
  };
}

function toneFor(passRate: number | null) {
  if (passRate === null) return "muted" as const;
  if (passRate === 100) return "success" as const;
  return passRate >= 80 ? ("warning" as const) : ("danger" as const);
}

export default function ProjectsPage() {
  return (
    <RequireAuth>
      <AppShell>
        <ProjectsView />
      </AppShell>
    </RequireAuth>
  );
}

function ProjectsView() {
  const user = useAuthStore((s) => s.user);
  const canCreate = hasRole(user, "qa_engineer");

  const [projects, setProjects] = useState<Project[]>([]);
  const [suites, setSuites] = useState<TestSuite[]>([]);
  const [runs, setRuns] = useState<TestRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [query, setQuery] = useState("");

  useEffect(() => {
    // `cancelled` stops a slow response from setting state after unmount, and
    // keeps every setState inside an async callback rather than the effect body.
    let cancelled = false;

    (async () => {
      try {
        // Suites and runs only decorate the cards, so a failure there must not
        // take the page down with it — the list of projects is the point.
        const [data, s, r] = await Promise.all([
          api.projects.list(),
          api.suites.list().catch(() => [] as TestSuite[]),
          api.runs.list().catch(() => [] as TestRun[]),
        ]);
        if (!cancelled) {
          setProjects(data);
          setSuites(s);
          setRuns(r);
        }
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : "Could not load projects",
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  const visible = projects.filter((project) =>
    matches(query, project.name, project.base_url, project.description),
  );

  async function handleDelete(project: Project) {
    if (!confirm(`Delete "${project.name}"? This cannot be undone.`)) return;

    try {
      await api.projects.remove(project.id);
      setProjects((current) => current.filter((p) => p.id !== project.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete project");
    }
  }

  return (
    <div className="animate-in">
      <PageHeader
        title="Projects"
        description="Pick a project to record and run its tests. Each project is one web application."
      >
        {canCreate && (
          <Button onClick={() => setShowForm((v) => !v)}>
            <Plus />
            {showForm ? "Cancel" : "New project"}
          </Button>
        )}
      </PageHeader>

      {error && <Alert className="mb-4">{error}</Alert>}

      {/* Creating a project replaces the list rather than pushing it down.
          The form is the whole task while it is open — a search box and a grid
          of projects underneath are things to do instead of finishing it, and
          neither is any use until it is finished. Cancel brings them back. */}
      {showForm ? (
        <NewProjectForm
          onCreated={(project) => {
            setProjects((current) => [project, ...current]);
            setShowForm(false);
          }}
        />
      ) : loading ? (
        <SkeletonRows count={2} />
      ) : projects.length === 0 ? (
        <EmptyState canCreate={canCreate} />
      ) : (
        <>
          {/* Always, once there is anything to search. An earlier version
              hid it under four items, which meant the person who asked for a
              search box could not find one. */}
          <SearchBox
            className="mb-4"
            value={query}
            onChange={setQuery}
            placeholder="Search projects by name or URL…"
            count={visible.length}
            total={projects.length}
          />

          {visible.length === 0 ? (
            <Card className="px-4 py-10 text-center text-sm text-muted-foreground">
              No project matches “{query}”.
            </Card>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {visible.map((project) => (
                <ProjectCard
                  key={project.id}
                  project={project}
                  activity={activityFor(project, suites, runs)}
                  onDelete={() => handleDelete(project)}
                />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function ProjectCard({
  project,
  activity,
  onDelete,
}: {
  project: Project;
  activity: Activity;
  onDelete: () => void;
}) {
  const { suites, runs, passRate, lastRun } = activity;
  const tone = toneFor(passRate);
  const never = runs === 0;

  return (
    <Card className="group relative flex flex-col transition-all hover:border-primary/40 hover:shadow-md">
      {/* The whole card opens the project; the delete button sits above it. */}
      <Link
        href={`/projects/${project.id}`}
        className="absolute inset-0 rounded-lg"
        aria-label={`Open ${project.name}`}
      />
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <CardTitle className="truncate">{project.name}</CardTitle>
            <CardDescription className="truncate">
              {project.base_url}
            </CardDescription>
          </div>
          <Button
            variant="ghost"
            size="icon"
            aria-label={`Delete ${project.name}`}
            onClick={onDelete}
            className="relative opacity-0 transition-opacity hover:text-destructive focus-visible:opacity-100 group-hover:opacity-100"
          >
            <Trash2 />
          </Button>
        </div>
      </CardHeader>

      <CardContent className="flex flex-1 flex-col gap-4">
        {project.description && (
          <p className="line-clamp-2 text-[13px] leading-relaxed text-muted-foreground">
            {project.description}
          </p>
        )}

        {/* The health of the project, which is the reason you came to this
            page. A project that has never run says so plainly rather than
            showing a 0% that reads as failure. */}
        <div className="rounded-lg border border-border bg-muted/50 px-3.5 py-3">
          {never ? (
            <p className="text-[13px] text-muted-foreground">
              Not run yet — record a session to create its first tests.
            </p>
          ) : (
            <>
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  Pass rate
                </span>
                <span
                  className={`text-lg font-extrabold leading-none ${
                    {
                      muted: "text-muted-foreground",
                      success: "text-success",
                      warning: "text-warning",
                      danger: "text-destructive",
                    }[tone]
                  }`}
                >
                  {passRate === null ? "—" : `${passRate}%`}
                </span>
              </div>
              <Meter className="mt-2" value={passRate ?? 0} tone={tone} />
              {lastRun && (
                <p className="mt-2 text-xs text-muted-foreground">
                  Last run {lastRun.passed}/{lastRun.total}
                  {lastRun.failed > 0 && (
                    <span className="text-destructive">
                      {" "}
                      · {lastRun.failed} failed
                    </span>
                  )}
                </p>
              )}
            </>
          )}
        </div>

        <div className="mt-auto flex flex-wrap items-center gap-1.5">
          {project.default_browsers.map((browser) => (
            <Badge key={browser} tone="outline">
              {BROWSER_LABEL[browser as Browser] ?? browser}
            </Badge>
          ))}
          <span className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
            <span className="tabular">
              {suites} suite{suites === 1 ? "" : "s"} · {runs} run
              {runs === 1 ? "" : "s"}
            </span>
            <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" />
          </span>
        </div>
      </CardContent>
    </Card>
  );
}

function EmptyState({ canCreate }: { canCreate: boolean }) {
  return (
    <Empty
      icon={<FolderKanban />}
      title="No projects yet"
      description={
        canCreate
          ? "A project is one web application under test. Create one to start recording."
          : "Ask a QA Engineer or Test Manager to create one for you."
      }
    />
  );
}

function NewProjectForm({
  onCreated,
}: {
  onCreated: (project: Project) => void;
}) {
  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [description, setDescription] = useState("");
  const [browsers, setBrowsers] = useState<Browser[]>(["chromium"]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function toggleBrowser(browser: Browser) {
    setBrowsers((current) =>
      current.includes(browser)
        ? current.filter((b) => b !== browser)
        : [...current, browser],
    );
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);

    if (browsers.length === 0) {
      setError("Pick at least one browser");
      return;
    }

    setBusy(true);
    try {
      onCreated(
        await api.projects.create({
          name,
          base_url: baseUrl,
          description: description || null,
          default_browsers: browsers,
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create project");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="mb-6">
      <CardHeader>
        <CardTitle>New project</CardTitle>
      </CardHeader>

      <CardContent>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          {error && <Alert>{error}</Alert>}

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="flex flex-col gap-2">
              <Label htmlFor="name">Name</Label>
              <Input
                id="name"
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Checkout flow"
              />
            </div>

            <div className="flex flex-col gap-2">
              <Label htmlFor="base_url">Application URL</Label>
              <Input
                id="base_url"
                type="url"
                required
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder="https://shop.example.com"
              />
            </div>
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="description">Description</Label>
            <Textarea
              id="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What does this project cover?"
            />
          </div>

          <div className="flex flex-col gap-2">
            <Label>Default browsers</Label>
            <div className="flex flex-wrap gap-4">
              {ALL_BROWSERS.map((browser) => (
                <label
                  key={browser}
                  className="flex cursor-pointer items-center gap-2 text-sm"
                >
                  <input
                    type="checkbox"
                    checked={browsers.includes(browser)}
                    onChange={() => toggleBrowser(browser)}
                    className="size-4 accent-current"
                  />
                  {browser}
                </label>
              ))}
            </div>
          </div>

          <Button type="submit" disabled={busy} className="self-start">
            {busy ? "Creating…" : "Create project"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
