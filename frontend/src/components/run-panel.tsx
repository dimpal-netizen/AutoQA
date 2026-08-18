"use client";

/** Run a suite and watch the results arrive.
 *
 *  Polls while a run is active rather than holding a socket open. Phase 6
 *  replaces the polling with a WebSocket; keeping the fetch behind one
 *  `refresh()` here means that swap touches this file only.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Download,
  Eye,
  Play,
  RefreshCw,
  Sparkles,
  Square,
  Trash2,
} from "lucide-react";
import { api, downloadReport } from "@/lib/api";
import {
  BROWSER_LABEL,
  RUN_BADGE,
  formatDuration,
  isRunActive,
  type Browser,
  type RunTriage,
  type TestRun,
  type TestRunDetail,
} from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Badge, LiveDot } from "@/components/ui/badge";
import {
  Alert,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ResultMatrix } from "@/components/result-matrix";
import { useConfirm } from "@/components/ui/confirm";

const ALL_BROWSERS: Browser[] = ["chromium", "firefox", "webkit"];
const POLL_MS = 2000;

export function RunPanel({
  suiteId,
  caseCount,
  recordedCaseIds = [],
  request,
  reloadToken = 0,
  onDeleted,
  onRunningChange,
}: {
  suiteId: number;
  caseCount: number;
  /** The cases that came from the recording: the walkthrough a tester
   *  performed, with the checks they made while performing it.
   *
   *  Held as ids rather than a count because the two buttons below differ only
   *  in what they send: the whole suite, or these. */
  recordedCaseIds?: number[];
  /** A row below asked for one case to be run. The token changes per press. */
  request?: { caseIds: number[]; token: number } | null;
  /** Bumped when the suite's cases are replaced, so the panel drops the run it
   *  is showing — that verdict was about code that no longer exists. */
  reloadToken?: number;
  /** A run was deleted, so anything showing it needs to refresh. */
  onDeleted?: () => void;
  /** What is running: null when idle, the case ids when a run is going, and
   *  an empty array when that run is the whole suite. */
  onRunningChange?: (caseIds: number[] | null) => void;
}) {
  const [browsers, setBrowsers] = useState<Browser[]>(["chromium"]);
  // Every run is watched, stepping through one action at a time. Not a choice.
  //
  // How slowly is the server's decision, not this one. Sending a number from
  // here meant two places held it, they drifted - 700 there, 2500 here - and
  // every run took three and a half times as long as the setting claimed.
  const headless = false;
  const [run, setRun] = useState<TestRunDetail | null>(null);
  const [starting, setStarting] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [building, setBuilding] = useState(false);
  const [removing, setRemoving] = useState(false);
  const { confirm, dialog } = useConfirm();
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<TestRun[]>([]);

  // Held in a ref so the polling effect doesn't restart on every tick.
  const runId = run?.id ?? null;
  const active = run ? isRunActive(run) : false;
  const mounted = useRef(true);

  // In a ref so the polling effect does not restart every time the parent
  // re-renders and hands over a fresh function. Written in an effect, not
  // during render — a ref updated mid-render is read by whatever rendered
  // first, which is the order React makes no promises about.
  const notifyRunning = useRef(onRunningChange);
  useEffect(() => {
    notifyRunning.current = onRunningChange;
  }, [onRunningChange]);

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
      // Explicitly null when there is nothing left: after a regeneration the
      // runs are gone, and keeping the last one on screen would show a verdict
      // for a test that has been rewritten.
      setRun(runs[0] ? await api.runs.get(runs[0].id).catch(() => null) : null);
    })();
  }, [suiteId, reloadToken]);

  useEffect(() => {
    if (!runId || !active) return;

    const timer = setInterval(async () => {
      try {
        const detail = await api.runs.get(runId);
        if (!mounted.current) return;
        setRun(detail);
        if (!isRunActive(detail)) {
          notifyRunning.current?.(null);
          void loadHistory();
        }
      } catch {
        /* a dropped poll is not worth an error banner - the next one retries */
      }
    }, POLL_MS);

    return () => clearInterval(timer);
  }, [runId, active, loadHistory]);

  const start = useCallback(
    async (caseIds?: number[]) => {
      setStarting(true);
      setError(null);
      try {
        const started = await api.runs.start(suiteId, {
          browsers,
          headless,
          // Omitted entirely when running everything — the API reads an absent
          // case_ids as "the whole suite", and [] would mean "no tests".
          ...(caseIds && caseIds.length > 0 ? { case_ids: caseIds } : {}),
        });
        setStopping(false);
        setRun({ ...started, results: [] });
        notifyRunning.current?.(caseIds ?? []);
        void loadHistory();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not start the run");
        notifyRunning.current?.(null);
      } finally {
        setStarting(false);
      }
    },
    [suiteId, browsers, headless, loadHistory],
  );

  // A row below pressed its play button.
  //
  // The token is what identifies a press, not the ids: pressing the same row
  // twice must start two runs, and comparing ids would make the second press
  // look identical to the first. It also means `start` can be an honest
  // dependency — it changes whenever the browser choice does, and the guard
  // makes that re-run harmless.
  const lastToken = useRef(0);
  useEffect(() => {
    if (!request || request.token === lastToken.current) return;
    lastToken.current = request.token;
    void (async () => {
      await start(request.caseIds);
    })();
  }, [request, start]);

  async function removeRun() {
    if (!runId) return;

    const confirmed = await confirm({
      title: `Delete run #${runId}?`,
      body:
        `Its results and any screenshots, video and traces it produced are ` +
        `removed from disk. This cannot be undone.\n\n` +
        `The tests themselves are not touched.`,
      confirmLabel: "Delete run",
    });
    if (!confirmed) return;

    setRemoving(true);
    setError(null);
    try {
      await api.runs.remove(runId);
      setRun(null);
      await loadHistory();
      onDeleted?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete this run");
    } finally {
      setRemoving(false);
    }
  }

  async function cancel() {
    if (!runId) return;
    setStopping(true);
    try {
      await api.runs.cancel(runId);
      setRun(await api.runs.get(runId));
      notifyRunning.current?.(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not stop the run");
    } finally {
      setStopping(false);
    }
  }

  async function report() {
    if (!runId) return;
    setBuilding(true);
    setError(null);
    try {
      const artifact = await api.reports.build(runId);
      await downloadReport(artifact.id, `autoqa-run-${runId}.html`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not build the report");
    } finally {
      setBuilding(false);
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
    <Card>
      {dialog}
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Play className="size-4" />
          Run tests
        </CardTitle>
        <CardDescription>
          {caseCount === 1 ? "1 test case" : `${caseCount} test cases`}
          {" "}· runs in every browser you pick, all at the same time. Use the
          play button on a row to run just that one.
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
                className={`flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm font-medium transition-all ${
                  on
                    ? "border-primary/30 bg-primary-subtle text-primary shadow-xs"
                    : "border-border bg-card text-muted-foreground hover:border-border-strong hover:text-foreground"
                } disabled:opacity-50`}
              >
                <span
                  className={`size-1.5 rounded-full ${on ? "bg-primary" : "bg-border-strong"}`}
                />
                {BROWSER_LABEL[browser]}
              </button>
            );
          })}

          <span
            className="ml-1 flex items-center gap-2 rounded-md border border-border bg-card px-3 py-1.5 text-sm text-muted-foreground"
            title="A real browser opens and steps through one action at a time"
          >
            <Eye className="size-4" />
            Watch it run
          </span>

          <div className="ml-auto flex items-center gap-2">
            {run && !active && (
              <Button
                variant="outline"
                size="sm"
                onClick={report}
                disabled={building}
                title="One self-contained HTML file you can email to anyone"
              >
                <Download className={building ? "animate-pulse" : ""} />
                {building ? "Building…" : "Report"}
              </Button>
            )}
            {active ? (
              <Button variant="destructive" size="sm" onClick={cancel} disabled={stopping}>
                <Square className="size-3.5 fill-current" />
                {stopping ? "Stopping…" : "Stop"}
              </Button>
            ) : null}
            {/* Two ways to run, and the difference is only what gets sent.
                The first is the recording: the journey a tester walked through
                and the checks they made along the way. Fewer tests, every one
                of them a flow that really happens - which is the regression
                run. The second is unchanged: no case ids at all, which the API
                already reads as the whole suite. */}
            {recordedCaseIds.length > 0 && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => void start(recordedCaseIds)}
                disabled={starting || active || browsers.length === 0}
                title={
                  `Runs the ${recordedCaseIds.length} recorded case` +
                  `${recordedCaseIds.length === 1 ? "" : "s"}: the walkthrough a tester ` +
                  "performed and the checks they made during it. Nothing written by " +
                  "hand afterwards, nothing a model invented."
                }
              >
                <Play className="size-4" />
                Run Recorded Test Cases
              </Button>
            )}
            <Button
              size="sm"
              onClick={() => void start()}
              disabled={starting || active || browsers.length === 0 || caseCount === 0}
              title={
                `Runs all ${caseCount} case${caseCount === 1 ? "" : "s"} — the ` +
                "recording, anything written by hand, and every case the model " +
                "generated around them."
              }
            >
              {active ? (
                <RefreshCw className="size-4 animate-spin" />
              ) : (
                <Play className="size-4" />
              )}
              {active
                ? "Running…"
                : starting
                  ? "Starting…"
                  : "Run All AI Test Cases"}
            </Button>
          </div>
        </div>

        {browsers.length === 0 && (
          <p className="text-xs text-muted-foreground">Pick at least one browser.</p>
        )}
        {!active && (
          <p className="text-xs leading-relaxed text-muted-foreground">
            A browser window opens and pauses between each action, so
            you can follow every step. Runs take noticeably longer this way.
          </p>
        )}
        {error && <Alert>{error}</Alert>}

        {run && (
          <div className="flex flex-wrap items-center gap-2">
            <div className="min-w-0 flex-1">
              <RunSummary run={run} />
            </div>
            {/* Deleting is only offered once the run has stopped. Removing one
                mid-flight would leave the worker writing screenshots into a
                directory with nothing pointing at it, which is why the API
                refuses it too. */}
            {!active && (
              <Button
                variant="ghost"
                size="sm"
                disabled={removing}
                onClick={removeRun}
                className="shrink-0 text-muted-foreground hover:bg-destructive-subtle hover:text-destructive"
              >
                <Trash2 className="size-3.5" />
                {removing ? "Deleting…" : "Delete run"}
              </Button>
            )}
          </div>
        )}
        {/* One call for the whole run, offered where the failures are. Doing
            them one at a time costs a request each — sixteen red tests is a
            free-tier key's whole day — and no single-failure analysis can say
            that six of them are one problem. */}
        {run && !active && run.failed > 0 && (
          <TriageRun runId={run.id} onDone={() => void loadHistory()} />
        )}

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
                    <Badge tone={RUN_BADGE[old.status]}>{old.status}</Badge>
                    <span className="tabular text-xs text-muted-foreground">
                      {old.passed}/{old.total} passed
                    </span>
                    <span className="tabular ml-auto text-xs text-muted-foreground">
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

/** Explain every failure in this run, in one call.
 *
 *  The per-failure "Explain this failure" is still there and still better — it
 *  gets the screenshot, which this cannot afford sixteen of. What this has
 *  instead is the whole run at once, and therefore the one thing no
 *  single-failure analysis can work out: which failures are the same problem.
 *  "16 failed" and "16 failed, 3 causes" are a week and an afternoon.
 */
function TriageRun({ runId, onDone }: { runId: number; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [triage, setTriage] = useState<RunTriage | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Every failure here already carries an explanation, so there is nothing for
  // this to do and nothing worth saying about that.
  const [nothingToDo, setNothingToDo] = useState(false);

  // A new run is a new question. Without this the previous run's summary sits
  // under the new one's failures, describing tests that are no longer on screen.
  useEffect(() => {
    setTriage(null);
    setError(null);
    setNothingToDo(false);
  }, [runId]);

  async function explain() {
    setBusy(true);
    setError(null);
    try {
      const found = await api.analysis.forRun(runId);
      setTriage(found);
      // The rows carry their own verdicts now, so the panel below reloads.
      onDone();
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Could not explain this run";

      // Not a failure — the work was already done, probably on an earlier
      // visit. Reporting "already explained" in red says something has gone
      // wrong when nothing has, so the control simply goes away.
      if (message.includes("already been explained")) {
        setNothingToDo(true);
      } else {
        setError(message);
      }
    } finally {
      setBusy(false);
    }
  }

  if (nothingToDo) return null;

  if (triage) {
    return (
      <div className="rounded-md border border-border bg-card p-3.5">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="outline">
            {triage.distinct_causes === 1
              ? "1 underlying cause"
              : `${triage.distinct_causes} underlying causes`}
          </Badge>
          <Badge tone="neutral">
            {triage.analyses.length} failure(s) explained
          </Badge>
          <span className="ml-auto text-[11px] text-muted-foreground">
            {triage.model} · {triage.tokens.toLocaleString()} tokens · $
            {triage.cost_usd.toFixed(4)}
          </span>
        </div>
        <p className="mt-2.5 text-[13px] leading-relaxed">{triage.summary}</p>
        <p className="mt-2 text-[11px] text-muted-foreground">
          Each failure now carries its own explanation below. Open one and
          choose “Explain this failure” for a closer look with the screenshot —
          this pass read the errors only.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <div>
        <Button variant="outline" size="sm" onClick={() => void explain()} disabled={busy}>
          <Sparkles className={busy ? "animate-pulse" : ""} />
          {busy ? "Reading the failures…" : "Explain all failures"}
        </Button>
      </div>
      {error && <Alert>{error}</Alert>}
    </div>
  );
}

function RunSummary({ run }: { run: TestRunDetail }) {
  const active = isRunActive(run);
  const done = run.results.length;
  const expected = Math.max(run.total, done);

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-md border border-border bg-muted/50 px-3.5 py-2.5">
      <Badge tone={active ? "primary" : RUN_BADGE[run.status]}>
        {active && <LiveDot />}
        {active ? "running" : run.status}
      </Badge>

      {active ? (
        <span className="flex min-w-0 items-baseline gap-2 text-sm">
          <span className="tabular shrink-0 text-muted-foreground">
            {done} of {expected}
          </span>
          {run.current_test && (
            <span className="min-w-0 truncate text-foreground" title={run.current_test}>
              {run.current_test}
            </span>
          )}
        </span>
      ) : (
        <span className="tabular flex items-center gap-3 text-sm">
          <span className="font-medium text-success">{run.passed} passed</span>
          {run.failed > 0 && (
            <span className="font-medium text-destructive">{run.failed} failed</span>
          )}
          {run.skipped > 0 && (
            <span className="text-muted-foreground">{run.skipped} skipped</span>
          )}
        </span>
      )}

      <span className="tabular ml-auto text-xs text-muted-foreground">
        {run.browsers.map((b) => BROWSER_LABEL[b as Browser] ?? b).join(" · ")}
        {run.duration_ms !== null && ` · ${formatDuration(run.duration_ms)}`}
      </span>

      {active && (
        <div className="h-1 w-full overflow-hidden rounded-full bg-border">
          {/* Real progress, not a spinner: each test writes its row the moment
              pytest reports it, so this tracks actual work rather than time. */}
          <div
            className="h-full rounded-full bg-primary transition-[width] duration-500"
            style={{ width: `${expected ? (done / expected) * 100 : 4}%` }}
          />
        </div>
      )}
    </div>
  );
}
