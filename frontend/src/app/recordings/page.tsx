"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { CircleDot, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import type { RecordingSession } from "@/lib/types";
import { AppHeader } from "@/components/app-header";
import { RequireAuth } from "@/components/auth-provider";
import { Button } from "@/components/ui/button";
import { Alert, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function RecordingsPage() {
  return (
    <RequireAuth>
      <AppHeader />
      <Recordings />
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
    void load();
  }, [load]);

  async function remove(id: number) {
    try {
      await api.recordings.remove(id);
      setSessions((prev) => prev.filter((s) => s.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete");
    }
  }

  return (
    <main className="mx-auto max-w-5xl p-6">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Recordings</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Captured browser sessions. Phase 3 turns these into Playwright tests.
          </p>
        </div>
        <Link href="/demo">
          <Button variant="outline">Practice page</Button>
        </Link>
      </div>

      {error && <Alert className="mb-4">{error}</Alert>}

      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="text-base">How to record</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          <ol className="ml-4 list-decimal space-y-1">
            <li>
              Open the{" "}
              <Link href="/demo" className="text-foreground underline underline-offset-4">
                practice page
              </Link>{" "}
              (or any page on this origin).
            </li>
            <li>Open DevTools → Console.</li>
            <li>
              Paste{" "}
              <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">
                await import(&quot;http://localhost:3000/recorder.js&quot;)
              </code>
            </li>
            <li>Click around, then press Stop on the red panel.</li>
          </ol>
        </CardContent>
      </Card>

      {loading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : sessions.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            No recordings yet.
          </CardContent>
        </Card>
      ) : (
        <div className="flex flex-col gap-3">
          {sessions.map((session) => (
            <Card key={session.id}>
              <CardContent className="flex items-center justify-between gap-4 py-4">
                <Link href={`/recordings/${session.id}`} className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    {session.status === "recording" && (
                      <CircleDot className="size-4 shrink-0 animate-pulse text-destructive" />
                    )}
                    <span className="truncate font-medium">{session.name}</span>
                  </div>
                  <p className="mt-0.5 truncate text-xs text-muted-foreground">
                    {session.start_url}
                  </p>
                </Link>

                <div className="flex shrink-0 items-center gap-4 text-sm">
                  <span className="text-muted-foreground">
                    {session.action_count} actions
                  </span>
                  {session.duration_ms != null && (
                    <span className="text-muted-foreground">
                      {(session.duration_ms / 1000).toFixed(1)}s
                    </span>
                  )}
                  <StatusBadge status={session.status} />
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={`Delete ${session.name}`}
                    onClick={() => remove(session.id)}
                  >
                    <Trash2 className="size-4" />
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </main>
  );
}

function StatusBadge({ status }: { status: RecordingSession["status"] }) {
  const styles: Record<string, string> = {
    recording: "border-destructive/40 bg-destructive/10 text-destructive",
    completed: "border-success/40 bg-success/10 text-success",
    discarded: "border-border bg-muted text-muted-foreground",
  };
  return (
    <span className={`rounded-full border px-2 py-0.5 text-xs ${styles[status]}`}>
      {status}
    </span>
  );
}
