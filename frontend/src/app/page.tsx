"use client";

/** The workspace: everything you do, on one screen.
 *
 *  This replaced four pages — Projects, Recordings, Tests, and a suite detail
 *  page — that were peers in the navigation but steps in a single loop. The
 *  loop is: record something, read the tests, run them, read the failures. Any
 *  of that costing a page load meant losing your place in it.
 *
 *  So: suites down the left, the selected one filling the rest, recording as a
 *  button rather than a destination. Projects still exist — they are just not
 *  something you visit to get work done.
 */

import { useCallback, useEffect, useState } from "react";
import {
  ChevronRight,
  FlaskConical,
  FolderKanban,
  RefreshCw,
  Video,
} from "lucide-react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { TestSuite, TestSuiteDetail } from "@/lib/types";
import { AppShell } from "@/components/app-shell";
import { RequireAuth } from "@/components/auth-provider";
import { LaunchRecording } from "@/components/launch-recording";
import { SuiteWorkspace } from "@/components/suite-workspace";
import { Button } from "@/components/ui/button";
import { Alert, EmptyState } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

export default function WorkspacePage() {
  return (
    <RequireAuth>
      <AppShell wide>
        <Workspace />
      </AppShell>
    </RequireAuth>
  );
}

function Workspace() {
  const [suites, setSuites] = useState<TestSuite[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<TestSuiteDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [recording, setRecording] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadSuites = useCallback(async () => {
    try {
      const list = await api.suites.list();
      setSuites(list);
      // Default to the newest suite: it is almost always the one you just
      // made, and an empty right-hand pane teaches nobody anything.
      setSelected((current) => current ?? list[0]?.id ?? null);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load your tests");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Awaited inside the IIFE rather than called directly, which keeps the
    // state updates asynchronous — and avoids duplicating loadSuites here,
    // which is what the first version of this did.
    void (async () => {
      await loadSuites();
    })();
  }, [loadSuites]);

  useEffect(() => {
    if (selected === null) return;
    let cancelled = false;
    void (async () => {
      try {
        const found = await api.suites.get(selected);
        if (!cancelled) setDetail(found);
      } catch {
        /* keep what is on screen; the id check below hides a stale one */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selected]);

  // Derived rather than cleared in the effect: while a new suite is loading,
  // the previous one is still in state, and showing it under the wrong name
  // would be worse than a moment of skeleton.
  const current = detail && detail.id === selected ? detail : null;

  return (
    <div className="animate-in flex flex-col gap-4">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">Tests</h1>
        <span className="tabular text-sm text-muted-foreground">
          {suites.length} suite{suites.length === 1 ? "" : "s"}
        </span>

        <div className="ml-auto flex items-center gap-2">
          <Link href="/projects">
            <Button variant="ghost" size="sm">
              <FolderKanban />
              Projects
            </Button>
          </Link>
          <Button size="sm" onClick={() => setRecording((v) => !v)}>
            <Video />
            {recording ? "Close" : "Record a session"}
          </Button>
        </div>
      </header>

      {error && <Alert>{error}</Alert>}

      {/* Recording is a panel that drops in here rather than its own page, so
          starting one never costs you the suite you were looking at. */}
      {recording && (
        <LaunchRecording
          onChanged={() => {
            void loadSuites();
          }}
        />
      )}

      {loading ? (
        <Skeleton className="h-96 w-full" />
      ) : suites.length === 0 ? (
        <EmptyState
          icon={<FlaskConical />}
          title="No tests yet"
          description="Record a session and AutoQA writes a runnable test the moment you stop."
          action={
            <Button onClick={() => setRecording(true)}>
              <Video />
              Record a session
            </Button>
          }
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,17rem)_minmax(0,1fr)]">
          <SuiteList
            suites={suites}
            selected={selected}
            onSelect={setSelected}
            onRefresh={() => void loadSuites()}
          />

          {current ? (
            <SuiteWorkspace suite={current} onChange={setDetail} />
          ) : (
            <Skeleton className="h-96 w-full" />
          )}
        </div>
      )}
    </div>
  );
}

function SuiteList({
  suites,
  selected,
  onSelect,
  onRefresh,
}: {
  suites: TestSuite[];
  selected: number | null;
  onSelect: (id: number) => void;
  onRefresh: () => void;
}) {
  return (
    <aside className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between px-1 pb-1">
        <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          Suites
        </span>
        <button
          type="button"
          onClick={onRefresh}
          className="rounded p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          aria-label="Refresh"
        >
          <RefreshCw className="size-3.5" />
        </button>
      </div>

      {suites.map((suite) => {
        const active = suite.id === selected;
        return (
          <button
            key={suite.id}
            type="button"
            onClick={() => onSelect(suite.id)}
            className={cn(
              "group flex items-center gap-2.5 rounded-md border px-3 py-2.5 text-left transition-all",
              active
                ? "lit border-primary/35 bg-card ring-1 ring-primary/20"
                : "border-transparent hover:border-border hover:bg-card/70",
            )}
          >
            <FlaskConical
              className={cn(
                "size-4 shrink-0",
                active ? "text-primary" : "text-muted-foreground",
              )}
            />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[13px] font-medium">
                {suite.name}
              </span>
            </span>
            <ChevronRight
              className={cn(
                "size-3.5 shrink-0 transition-opacity",
                active ? "text-primary" : "text-muted-foreground opacity-0 group-hover:opacity-100",
              )}
            />
          </button>
        );
      })}
    </aside>
  );
}
