"use client";

/** Run a suite and watch the results arrive.
 *
 *  Polls while a run is active rather than holding a socket open. Phase 6
 *  replaces the polling with a WebSocket; keeping the fetch behind one
 *  `refresh()` here means that swap touches this file only.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Play, RefreshCw, Square } from "lucide-react";
import { api } from "@/lib/api";
import {
  BROWSER_LABEL,
  RUN_TONE,
  formatDuration,
  isRunActive,
  type Browser,
  type TestRun,
  type TestRunDetail,
} from "@/lib/types";
import { Button } from "@/components/ui/button";
import {
  Alert,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ResultMatrix } from "@/components/result-matrix";

const ALL_BROWSERS: Browser[] = ["chromium", "firefox", "webkit"];
const POLL_MS = 2000;

export function RunPanel({ suiteId, caseCount }: { suiteId: number; caseCount: number }) {
  const [browsers, setBrowsers] = useState<Browser[]>(["chromium"]);
  const [headless, setHeadless] = useState(true);
  const [run, setRun] = useState<TestRunDetail | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<TestRun[]>([]);

  // Held in a ref so the polling effect doesn't restart on every tick.
  const runId = run?.id ?? null;
  const active = run ? isRunActive(run) : false;
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const loadHistory = useCallback(async () => {
    try {
      const runs = await api.runs.list({ suiteId });
      if (mounted.current) setHistory(runs);
    } catch {
      /* the history is a nicety - never block the page on it */
    }
  }, [suiteId]);

  // Show the most recent run on arrival, so a page refresh mid-run does not
  // lose track of it.
  useEffect(() => {
    void (async () => {
      const runs = await api.runs.list({ suiteId }).catch(() => [] as TestRun[]);
      if (!mounted.current) return;
      setHistory(runs);
      if (runs[0]) {
        const detail = await api.runs.get(runs[0].id).catch(() => null);
        if (mounted.current && detail) setRun(detail);
      }
    })();
  }, [suiteId]);

  useEffect(() => {
    if (!runId || !active) return;

    const timer = setInterval(async () => {
      try {
        const detail = await api.runs.get(runId);
        if (!mounted.current) return;
        setRun(detail);
        if (!isRunActive(detail)) void loadHistory();
      } catch {
        /* a dropped poll is not worth an error banner - the next one retries */
      }
    }, POLL_MS);

    return () => clearInterval(timer);
  }, [runId, active, loadHistory]);

  async function start() {
    setStarting(true);
    setError(null);
    try {
      const started = await api.runs.start(suiteId, { browsers, headless });
      setRun({ ...started, results: [] });
      void loadHistory();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start the run");
    } finally {
      setStarting(false);
    }
  }

  async function cancel() {
    if (!runId) return;
    try {
      await api.runs.cancel(runId);
      setRun(await api.runs.get(runId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not cancel");
    }
  }

  function toggle(browser: Browser) {
    setBrowsers((current) =>
      current.includes(browser)
        ? current.filter((b) => b !== browser)
        : [...current, browser],
    );
  }

  return (
    <Card className="mt-5">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Play className="size-4" />
          Run tests
        </CardTitle>
        <CardDescription>
          {caseCount === 1
            ? "1 test case"
            : `${caseCount} test cases`}{" "}
          · runs in every browser you pick, all at the same time
        </CardDescription>
      </CardHeader>

      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-2">
          {ALL_BROWSERS.map((browser) => {
            const on = browsers.includes(browser);
            return (
              <button
                key={browser}
                type="button"
                onClick={() => toggle(browser)}
                disabled={active}
                className={`rounded-md border px-3 py-1.5 text-sm transition ${
                  on
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-input text-muted-foreground hover:text-foreground"
                } disabled:opacity-50`}
              >
                {BROWSER_LABEL[browser]}
              </button>
            );
          })}

          <label className="ml-2 flex cursor-pointer items-center gap-1.5 text-sm text-muted-foreground">
            <input
              type="checkbox"
              checked={!headless}
              disabled={active}
              onChange={(e) => setHeadless(!e.target.checked)}
              className="size-3.5 accent-primary"
            />
            Watch it run
          </label>

          <div className="ml-auto flex items-center gap-2">
            {active ? (
              <Button variant="outline" size="sm" onClick={cancel}>
                <Square className="size-3.5" />
                Stop
              </Button>
            ) : null}
            <Button
              size="sm"
              onClick={start}
              disabled={starting || active || browsers.length === 0 || caseCount === 0}
            >
              {active ? (
                <RefreshCw className="size-4 animate-spin" />
              ) : (
                <Play className="size-4" />
              )}
              {active ? "Running…" : starting ? "Starting…" : "Run tests"}
            </Button>
          </div>
        </div>

        {browsers.length === 0 && (
          <p className="text-xs text-muted-foreground">Pick at least one browser.</p>
        )}
        {error && <Alert>{error}</Alert>}

        {run && <RunSummary run={run} />}
        {run && run.results.length > 0 && <ResultMatrix results={run.results} />}

        {run && run.error_message && (
          <Alert>
            {run.error_message}
          </Alert>
        )}

        {history.length > 1 && (
          <details className="text-sm">
            <summary className="cursor-pointer text-muted-foreground">
              Earlier runs ({history.length - 1})
            </summary>
            <ul className="mt-2 flex flex-col gap-1">
              {history.slice(1).map((old) => (
                <li key={old.id}>
                  <button
                    type="button"
                    onClick={async () => setRun(await api.runs.get(old.id))}
                    className="flex w-full items-center gap-3 rounded px-2 py-1 text-left hover:bg-muted"
                  >
                    <span
                      className={`rounded border px-1.5 py-0.5 text-xs ${RUN_TONE[old.status]}`}
                    >
                      {old.status}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {old.passed}/{old.total} passed
                    </span>
                    <span className="ml-auto text-xs text-muted-foreground">
                      {new Date(old.created_at).toLocaleString()}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </details>
        )}
      </CardContent>
    </Card>
  );
}

function RunSummary({ run }: { run: TestRunDetail }) {
  const active = isRunActive(run);
  const done = run.results.length;
  const expected = Math.max(run.total, done);

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-md border bg-muted/40 px-3 py-2">
      <span className={`rounded border px-2 py-0.5 text-xs font-medium ${RUN_TONE[run.status]}`}>
        {active ? "running" : run.status}
      </span>

      {active ? (
        <span className="text-sm text-muted-foreground">
          {done} of {expected} finished…
        </span>
      ) : (
        <span className="text-sm">
          <span className="font-medium text-emerald-700">{run.passed} passed</span>
          {run.failed > 0 && (
            <span className="ml-2 font-medium text-red-700">{run.failed} failed</span>
          )}
          {run.skipped > 0 && (
            <span className="ml-2 text-muted-foreground">{run.skipped} skipped</span>
          )}
        </span>
      )}

      <span className="ml-auto text-xs text-muted-foreground">
        {run.browsers.map((b) => BROWSER_LABEL[b as Browser] ?? b).join(" · ")}
        {run.duration_ms !== null && ` · ${formatDuration(run.duration_ms)}`}
      </span>
    </div>
  );
}
