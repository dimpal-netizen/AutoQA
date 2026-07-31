"use client";

import { useEffect, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { hasRole, type Browser, type Project } from "@/lib/types";
import { useAuthStore } from "@/stores/auth-store";
import { RequireAuth } from "@/components/auth-provider";
import { AppHeader } from "@/components/app-header";
import { Button } from "@/components/ui/button";
import { Input, Label, Textarea } from "@/components/ui/input";
import {
  Alert,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

const ALL_BROWSERS: Browser[] = ["chromium", "firefox", "webkit"];

export default function ProjectsPage() {
  return (
    <RequireAuth>
      <AppHeader />
      <ProjectsView />
    </RequireAuth>
  );
}

function ProjectsView() {
  const user = useAuthStore((s) => s.user);
  const canCreate = hasRole(user, "qa_engineer");

  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  useEffect(() => {
    // `cancelled` stops a slow response from setting state after unmount, and
    // keeps every setState inside an async callback rather than the effect body.
    let cancelled = false;

    (async () => {
      try {
        const data = await api.projects.list();
        if (!cancelled) setProjects(data);
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
    <main className="mx-auto max-w-5xl px-4 py-8">
      <div className="mb-6 flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Projects</h1>
          <p className="text-sm text-muted-foreground">
            Each project is one web application you want to test.
          </p>
        </div>

        {canCreate && (
          <Button onClick={() => setShowForm((v) => !v)}>
            <Plus className="size-4" />
            {showForm ? "Cancel" : "New project"}
          </Button>
        )}
      </div>

      {error && <Alert className="mb-4">{error}</Alert>}

      {showForm && (
        <NewProjectForm
          onCreated={(project) => {
            setProjects((current) => [project, ...current]);
            setShowForm(false);
          }}
        />
      )}

      {loading ? (
        <p className="text-sm text-muted-foreground">Loading projects…</p>
      ) : projects.length === 0 ? (
        <EmptyState canCreate={canCreate} />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {projects.map((project) => (
            <ProjectCard
              key={project.id}
              project={project}
              onDelete={() => handleDelete(project)}
            />
          ))}
        </div>
      )}
    </main>
  );
}

function ProjectCard({
  project,
  onDelete,
}: {
  project: Project;
  onDelete: () => void;
}) {
  return (
    <Card>
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
          >
            <Trash2 className="size-4 text-destructive" />
          </Button>
        </div>
      </CardHeader>

      <CardContent className="flex flex-col gap-3">
        {project.description && (
          <p className="text-sm text-muted-foreground">{project.description}</p>
        )}
        <div className="flex flex-wrap gap-1.5">
          {project.default_browsers.map((browser) => (
            <span
              key={browser}
              className="rounded-full bg-secondary px-2.5 py-0.5 text-xs text-secondary-foreground"
            >
              {browser}
            </span>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function EmptyState({ canCreate }: { canCreate: boolean }) {
  return (
    <Card>
      <CardContent className="py-10 text-center">
        <p className="font-medium">No projects yet</p>
        <p className="mt-1 text-sm text-muted-foreground">
          {canCreate
            ? "Create your first project to start recording tests."
            : "Ask a QA Engineer or Test Manager to create one for you."}
        </p>
      </CardContent>
    </Card>
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
