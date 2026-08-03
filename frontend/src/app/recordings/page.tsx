"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { FlaskConical, FolderKanban, Trash2, Video } from "lucide-react";
import { api } from "@/lib/api";
import type { RecordingSession } from "@/lib/types";
import { AppShell } from "@/components/app-shell";
import { RequireAuth } from "@/components/auth-provider";
import { Button } from "@/components/ui/button";
import { Alert, Card, EmptyState, PageHeader } from "@/components/ui/card";
import { SearchBox, matches } from "@/components/ui/search";
import { Badge, LiveDot } from "@/components/ui/badge";
import { SkeletonRows } from "@/components/ui/skeleton";

export default function RecordingsPage() {
  return (
    <RequireAuth>
      <AppShell>
        <Recordings />
      </AppShell>
    </RequireAuth>
  );
}

function Recordings() {
  const [sessions, setSessions] = useState<RecordingSession[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");

  useEffect(() => {
    // `cancelled` guards against the response landing after unmount.
    let cancelled = false;
    void (async () => {
      try {
        const data = await api.recordings.list();
        if (!cancelled) setSessions(data);
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : "Could not load recordings",
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

  const visible = sessions.filter((session) =>
    matches(query, session.name, session.start_url, session.status),
  );

  async function remove(id: number) {
    try {
      await api.recordings.remove(id);
      setSessions((prev) => prev.filter((s) => s.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete");
    }
  }

  return (
    <div className="animate-in">
      <PageHeader
        title="Recordings"
        description="Every browser session you have captured, across all projects. Each one becomes a runnable test the moment you stop recording."
      />

      {error && <Alert className="mb-4">{error}</Alert>}

      {loading ? (
        <SkeletonRows count={2} />
      ) : sessions.length === 0 ? (
        <EmptyState
          icon={<Video />}
          title="No recordings yet"
          description="Recording starts inside a project. Open one and press Record a session — a browser opens, you use the site normally, and every interaction is captured."
          action={
            <Link href="/projects">
              <Button>
                <FolderKanban />
                Go to projects
              </Button>
            </Link>
          }
        />
      ) : (
        <>
          {/* Always, once there is anything to search. An earlier version
              hid it under four items, which meant the person who asked for a
              search box could not find one. */}
          <SearchBox
            className="mb-4"
            value={query}
            onChange={setQuery}
            placeholder="Search recordings by name or URL…"
            count={visible.length}
            total={sessions.length}
          />

          {visible.length === 0 ? (
            <Card className="px-4 py-10 text-center text-sm text-muted-foreground">
              No recording matches “{query}”.
            </Card>
          ) : (
            <div className="flex flex-col gap-3">
              {visible.map((session) => (
                <Card
                  key={session.id}
                  className="flex items-center gap-4 px-5 py-4 transition-all hover:border-border-strong hover:shadow-md"
                >
                  <Link
                    href={`/recordings/${session.id}`}
                    className="min-w-0 flex-1"
                  >
                    <span className="flex items-center gap-2">
                      {session.status === "recording" && (
                        <LiveDot className="text-destructive" />
                      )}
                      <span className="truncate text-sm font-medium">
                        {session.name}
                      </span>
                    </span>
                    <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                      {session.start_url}
                    </span>
                  </Link>

                  <div className="flex shrink-0 items-center gap-3">
                    <span className="tabular hidden text-xs text-muted-foreground sm:inline">
                      {session.action_count} actions
                    </span>
                    {session.duration_ms != null && (
                      <span className="tabular hidden text-xs text-muted-foreground sm:inline">
                        {(session.duration_ms / 1000).toFixed(1)}s
                      </span>
                    )}

                    <StatusBadge status={session.status} />

                    {session.suite_id && (
                      <Link href={`/projects/${session.project_id}`}>
                        <Button variant="outline" size="sm">
                          <FlaskConical />
                          Tests
                        </Button>
                      </Link>
                    )}

                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Delete ${session.name}`}
                      onClick={() => remove(session.id)}
                      className="hover:text-destructive"
                    >
                      <Trash2 />
                    </Button>
                  </div>
                </Card>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: RecordingSession["status"] }) {
  const tone = {
    recording: "danger",
    completed: "success",
    discarded: "neutral",
  }[status] as "danger" | "success" | "neutral";

  return <Badge tone={tone}>{status}</Badge>;
}
