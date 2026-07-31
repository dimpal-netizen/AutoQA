"use client";

import { useEffect, useState } from "react";
import { FolderKanban, Plus, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { BROWSER_LABEL, hasRole, type Browser, type Project } from "@/lib/types";
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
import { SkeletonRows } from "@/components/ui/skeleton";

const ALL_BROWSERS: Browser[] = ["chromium", "firefox", "webkit"];

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
    <div className="animate-in">
      <PageHeader
        title="Projects"
        description="Each project is one web application you want to test."
      >
        {canCreate && (
          <Button onClick={() => setShowForm((v) => !v)}>
            <Plus />
            {showForm ? "Cancel" : "New project"}
          </Button>
        )}
      </PageHeader>

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
        <SkeletonRows count={2} />
      ) : projects.length === 0 ? (
        <EmptyState canCreate={canCreate} />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {projects.map((project) => (
            <ProjectCard
              key={project.id}
              project={project}
              onDelete={() => handleDelete(project)}
            />
          ))}
        </div>
      )}
    </div>
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
    <Card className="group transition-all hover:border-border-strong hover:shadow-md">
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
            className="opacity-0 transition-opacity hover:text-destructive focus-visible:opacity-100 group-hover:opacity-100"
          >
            <Trash2 />
          </Button>
        </div>
      </CardHeader>

      <CardContent className="flex flex-col gap-3">
        {project.description && (
          <p className="text-sm text-muted-foreground">{project.description}</p>
        )}
        <div className="flex flex-wrap gap-1.5">
          {project.default_browsers.map((browser) => (
            <Badge key={browser} tone="outline">
              {BROWSER_LABEL[browser as Browser] ?? browser}
            </Badge>
          ))}
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
