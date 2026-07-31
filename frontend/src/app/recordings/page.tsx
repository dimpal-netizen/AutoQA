"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { FlaskConical, Trash2, Video } from "lucide-react";
import { api } from "@/lib/api";
import type { RecordingSession } from "@/lib/types";
import { AppShell } from "@/components/app-shell";
import { RequireAuth } from "@/components/auth-provider";
import { LaunchRecording } from "@/components/launch-recording";
import { Button } from "@/components/ui/button";
import { Alert, Card, EmptyState, PageHeader } from "@/components/ui/card";
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

  const load = useCallback(async () => {
    try {
      setSessions(await api.recordings.list());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load recordings");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // `cancelled` guards against the response landing after unmount.
    let cancelled = false;
    void (async () => {
      try {
        const data = await api.recordings.list();
        if (!cancelled) setSessions(data);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Could not load recordings");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

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
        description="Every browser session you have captured. Each one becomes a runnable test the moment you stop recording."
      >
        <Link href="/demo">
          <Button variant="outline">Practice page</Button>
        </Link>
      </PageHeader>

      {error && <Alert className="mb-4">{error}</Alert>}

      <LaunchRecording onChanged={load} />

      {loading ? (
        <SkeletonRows count={2} />
      ) : sessions.length === 0 ? (
        <EmptyState
          icon={<Video />}
          title="No recordings yet"
          description="Enter a URL above and press Start. A browser opens, you use the site normally, and every interaction is captured."
        />
      ) : (
        <div className="flex flex-col gap-3">
          {sessions.map((session) => (
            <Card
              key={session.id}
              className="flex items-center gap-4 px-5 py-4 transition-all hover:border-border-strong hover:shadow-md"
            >
              <Link href={`/recordings/${session.id}`} className="min-w-0 flex-1">
                <span className="flex items-center gap-2">
                  {session.status === "recording" && (
                    <LiveDot className="text-destructive" />
                  )}
                  <span className="truncate text-sm font-medium">{session.name}</span>
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
                  <Link href={`/suites/${session.suite_id}`}>
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
