"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, ArrowLeft } from "lucide-react";
import { api } from "@/lib/api";
import {
  RELIABLE_RANK,
  SELECTOR_RANK,
  playwrightFor,
  type RecordedAction,
  type RecordingSessionDetail,
  type Selector,
} from "@/lib/types";
import { AppShell } from "@/components/app-shell";
import { RequireAuth } from "@/components/auth-provider";
import { Alert, Card, CardContent } from "@/components/ui/card";
import { SkeletonRows } from "@/components/ui/skeleton";

export default function RecordingDetailPage({
  params,
}: {
  // Next 16: params is a Promise, unwrapped with React's use() in a client component.
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  return (
    <RequireAuth>
      <AppShell>
        <RecordingDetail id={Number(id)} />
      </AppShell>
    </RequireAuth>
  );
}

function RecordingDetail({ id }: { id: number }) {
  const [session, setSession] = useState<RecordingSessionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // `cancelled` guards against the response landing after unmount.
    let cancelled = false;
    void (async () => {
      try {
        const data = await api.recordings.get(id);
        if (!cancelled) setSession(data);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Could not load recording");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (error) {
    return (
      <div>
        <Alert>{error}</Alert>
      </div>
    );
  }
  if (!session) {
    return (
      <SkeletonRows count={3} />
    );
  }

  const fragile = session.actions.filter(
    (a) => a.selectors.length > 0 && SELECTOR_RANK[a.selectors[0].strategy] > RELIABLE_RANK,
  ).length;

  return (
    <div>
      <Link
        href="/recordings"
        className="mb-4 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" />
        All recordings
      </Link>

      <h1 className="text-2xl font-semibold">{session.name}</h1>
      <p className="mt-1 truncate text-sm text-muted-foreground">{session.start_url}</p>

      <div className="my-5 flex flex-wrap gap-6 text-sm">
        <Stat label="Actions" value={String(session.action_count)} />
        <Stat
          label="Duration"
          value={session.duration_ms != null ? `${(session.duration_ms / 1000).toFixed(1)}s` : "—"}
        />
        <Stat label="Status" value={session.status} />
        <Stat label="Recorder" value={session.extension_version ?? "—"} />
      </div>

      {fragile > 0 && (
        <Alert className="mb-5">
          <AlertTriangle className="mr-1 inline size-4" />
          {fragile} of {session.actions.length} actions fell back to a fragile selector
          (CSS, XPath, or position). Those steps are the most likely to break when the
          UI changes — adding <code className="font-mono text-xs">data-testid</code> to
          those elements would fix it.
        </Alert>
      )}

      <div className="flex flex-col gap-2">
        {session.actions.map((action) => (
          <ActionRow key={action.id} action={action} />
        ))}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="font-medium">{value}</p>
    </div>
  );
}

function ActionRow({ action }: { action: RecordedAction }) {
  const [open, setOpen] = useState(false);
  const best = action.selectors[0] as Selector | undefined;

  return (
    <Card>
      <CardContent className="py-3">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex w-full items-start gap-3 text-left"
        >
          <span className="w-8 shrink-0 pt-0.5 font-mono text-xs text-muted-foreground">
            {action.sequence}
          </span>

          <span className="min-w-0 flex-1">
            <span className="flex flex-wrap items-center gap-2">
              <code className="rounded bg-secondary px-1.5 py-0.5 font-mono text-xs">
                {action.action_type}
              </code>
              {best ? (
                <StrategyBadge selector={best} />
              ) : (
                <span className="text-xs text-muted-foreground">page-level</span>
              )}
              {action.frame_path.length > 0 && (
                <span className="rounded border border-border px-1.5 py-0.5 text-xs text-muted-foreground">
                  iframe
                </span>
              )}
            </span>

            <span className="mt-1 block truncate font-mono text-xs text-muted-foreground">
              {best ? playwrightFor(best) : summarisePayload(action)}
            </span>
          </span>

          <span className="shrink-0 pt-0.5 font-mono text-xs text-muted-foreground">
            {(action.timestamp_ms / 1000).toFixed(1)}s
          </span>
        </button>

        {open && (
          <div className="mt-3 border-t border-border pt-3 text-xs">
            {action.element && (
              <p className="mb-2 text-muted-foreground">
                <span className="font-medium text-foreground">
                  &lt;{action.element.tag}&gt;
                </span>
                {action.element.accessible_name && ` "${action.element.accessible_name}"`}
                {action.element.role && ` · role=${action.element.role}`}
              </p>
            )}

            {Object.keys(action.payload).length > 0 && (
              <pre className="mb-3 overflow-x-auto rounded bg-muted p-2 font-mono">
                {JSON.stringify(action.payload, null, 2)}
              </pre>
            )}

            {action.selectors.length > 0 && (
              <>
                <p className="mb-1 font-medium">
                  {action.selectors.length} selector candidates, best first
                </p>
                <p className="mb-2 text-muted-foreground">
                  The generator uses the first one. The rest are the fallbacks that make
                  self-healing possible when it breaks.
                </p>
                <div className="flex flex-col gap-1">
                  {action.selectors.map((selector, index) => (
                    <div key={index} className="flex items-center gap-2">
                      <StrategyBadge selector={selector} />
                      <code className="truncate font-mono text-muted-foreground">
                        {selector.value}
                      </code>
                      {!selector.unique && (
                        <span className="shrink-0 text-destructive">not unique</span>
                      )}
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function StrategyBadge({ selector }: { selector: Selector }) {
  const fragile = SELECTOR_RANK[selector.strategy] > RELIABLE_RANK;
  return (
    <span
      className={`shrink-0 rounded border px-1.5 py-0.5 font-mono text-xs ${
        fragile
          ? "border-destructive/40 bg-destructive/10 text-destructive"
          : "border-success/40 bg-success/10 text-success"
      }`}
      title={fragile ? "Brittle — likely to break when the UI changes" : "Reliable"}
    >
      {selector.strategy}
    </span>
  );
}

function summarisePayload(action: RecordedAction): string {
  const payload = action.payload as Record<string, unknown>;
  if (typeof payload.url === "string") return payload.url;
  if ("x" in payload && "y" in payload) return `scroll to ${payload.x}, ${payload.y}`;
  return JSON.stringify(payload);
}
