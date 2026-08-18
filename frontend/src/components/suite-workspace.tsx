"use client";

/** One suite: how it is doing, then run it, read the tests, find the files.
 *
 *  Rewritten after the two-column version left half the screen blank. Three
 *  things changed and they are all about density:
 *
 *  - The suite picker is a row of pills above the content, not a 17rem column
 *    beside it. A column that holds one truncated name is spending a sixth of
 *    the width to say less than a tab would.
 *  - A stat strip answers "how is this doing" without expanding anything. The
 *    old detail page had this and the workspace lost it.
 *  - Failures are open by default. Someone looking at a red run came to read
 *    the error; making them click for it is the one interaction this screen
 *    should not have.
 */

import { useEffect, useRef, useState } from "react";
import {
  FileSpreadsheet,
  FlaskConical,
  Play,
  Plus,
  Trash2,
} from "lucide-react";
import { api, downloadTestCaseSheet } from "@/lib/api";
import {
  formatRelative,
  hasRole,
  isRecorded,
  type TestCase,
  type TestResult,
  type TestSuite,
  type TestSuiteDetail,
} from "@/lib/types";
import { useAuthStore } from "@/stores/auth-store";
import { CaseEditor } from "@/components/case-editor";
import { GenerateCases } from "@/components/generate-cases";
import { RunPanel } from "@/components/run-panel";
import { TestCaseList } from "@/components/test-case-list";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/card";
import { Tabs } from "@/components/ui/tabs";
import { useConfirm } from "@/components/ui/confirm";
import { cn } from "@/lib/utils";

export function SuiteWorkspace({
  suite,
  suites,
  onSelect,
  onChange,
  onDeleted,
}: {
  suite: TestSuiteDetail;
  suites: TestSuite[];
  onSelect: (id: number) => void;
  onChange: (suite: TestSuiteDetail) => void;
  /** The suite is gone — the parent owns the list, so it reloads and picks
   *  whatever is left. */
  onDeleted: () => void;
}) {
  const [tab, setTab] = useState("cases");
  const [deleting, setDeleting] = useState(false);
  // A row asked to run one case. The token makes each request distinct, so
  // pressing the same row twice starts two runs rather than looking unchanged
  // to the panel below.
  const [runRequest, setRunRequest] = useState<{
    caseIds: number[];
    token: number;
  } | null>(null);
  const requestCount = useRef(0);
  // What the run panel says is running, so the row that was pressed can show
  // it. Null means nothing is.
  const [runningCaseIds, setRunningCaseIds] = useState<number[] | null>(null);

  // Where each case currently stands, newest result first. Fetched separately
  // from the last run because they answer different questions: the run says
  // what happened at 14:02, this says whether the suite is green now.
  const [caseResults, setCaseResults] = useState<TestResult[]>([]);
  const [statusToken, setStatusToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const results = await api.runs
        .caseStatus(suite.id)
        .catch(() => [] as TestResult[]);
      if (!cancelled) setCaseResults(results);
    })();
    return () => {
      cancelled = true;
    };
    // statusToken re-fetches after a run finishes.
  }, [suite.id, statusToken]);

  const statusByCase = new Map<number, TestResult[]>();
  for (const result of caseResults) {
    if (result.test_case_id === null) continue;
    const list = statusByCase.get(result.test_case_id) ?? [];
    list.push(result);
    statusByCase.set(result.test_case_id, list);
  }

  const [error, setError] = useState<string | null>(null);
  const { confirm, dialog } = useConfirm();

  // Why the last generation failed, when it did. Held here rather than inside
  // the button, because anything that button renders beneath itself grows the
  // toolbar row it sits in and knocks the buttons beside it out of line.
  const [generateOutcome, setGenerateOutcome] = useState<string | null>(null);

  // The case editor, or null when it is closed. `testCase: null` inside it
  // means "write a new one" — the same panel does both, because creating and
  // editing a case are the same form with a different starting point.
  const [editing, setEditing] = useState<{ testCase: TestCase | null } | null>(
    null,
  );

  const user = useAuthStore((s) => s.user);
  // Writing a case and deleting a suite are the same permission: both change
  // what this suite will run the next time somebody presses go.
  const canEdit = hasRole(user, "qa_engineer");

  async function reload() {
    try {
      onChange(await api.suites.get(suite.id));
      // Saving a case can discard the runs that tested the old version of it.
      setStatusToken((n) => n + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reload the suite");
    }
  }

  async function removeCase(testCase: TestCase) {
    const confirmed = await confirm({
      title: `Delete "${testCase.name}"?`,
      body:
        `Its ${testCase.steps.length} step(s) and its script go with it. ` +
        `This cannot be undone.`,
      confirmLabel: "Delete test case",
    });
    if (!confirmed) return;

    setError(null);
    try {
      await api.cases.remove(testCase.id);
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete this case");
    }
  }

  // Names collide when the same site is recorded twice; the pills then need a
  // date to tell them apart.
  const duplicateNames = new Set(
    suites
      .map((s) => s.name)
      .filter((name, i, all) => all.indexOf(name) !== i),
  );

  async function remove() {
    // Deleting a suite takes its test cases and run history with it, and there
    // is no undo — so the prompt names the suite and its age, which is the only
    // thing distinguishing two recordings of the same site.
    const confirmed = await confirm({
      title: `Delete "${suite.name}"?`,
      body:
        `Created ${formatRelative(suite.created_at)}. Its ` +
        `${suite.cases.length} test case(s) and run history go with it. ` +
        `This cannot be undone.\n\n` +
        `The recording itself is kept — you can generate from it again.`,
      confirmLabel: "Delete suite",
    });
    if (!confirmed) return;

    setDeleting(true);
    setError(null);
    try {
      await api.suites.remove(suite.id);
      onDeleted();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete this suite");
    } finally {
      setDeleting(false);
    }
  }

  const generated = suite.cases.filter((c) => c.category !== "recorded").length;

  return (
    <section className="flex min-w-0 flex-col gap-5">
      {dialog}
      {/* Only worth showing when there is a choice to make. */}
      {suites.length > 1 && (
        <div className="flex flex-wrap items-center gap-1.5">
          {suites.map((option) => {
            const active = option.id === suite.id;
            return (
              <button
                key={option.id}
                type="button"
                onClick={() => onSelect(option.id)}
                className={cn(
                  "max-w-xs truncate rounded-md border px-3 py-1.5 text-[13px] font-medium transition-all",
                  active
                    ? "lit border-primary/35 bg-card text-primary"
                    : "border-border bg-card/60 text-muted-foreground hover:border-border-strong hover:text-foreground",
                )}
              >
                <span className="block truncate">{option.name}</span>
                {/* Recording a site twice gives two suites with the same name,
                    and then the only way to tell them apart is when they were
                    made. Shown only when the names actually collide, so it is
                    absent in the ordinary case. */}
                {duplicateNames.has(option.name) && (
                  <span className="block text-[11px] font-normal opacity-70">
                    {formatRelative(option.created_at)}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      )}

      {/* One line, not a banded row of four figures.

          "Test cases 15" went first: the tab beside it already says 14, because
          the tab counts the generated cases and the figure counted the
          recording too. Two numbers under the same word on one screen is worse
          than saying it once.

          What is left is the part that is genuinely nowhere else. Passed and
          failed here are across the whole suite, not the last run — running one
          case makes a run of one, and reading these off it once said "0 passed"
          while a dozen cases sat there green from earlier. And the count is
          meaningless without the date: "14 passed" from three weeks ago and
          from two minutes ago are very different facts.

          A quarter of the height, and every number on it is one you cannot get
          by looking at the table. */}

      {error && <Alert>{error}</Alert>}

      <div>
        {/* The suite's heading row used to sit above the figures: its title
            restated the project's own URL, its subtitle was the recording id
            and an action count, and the only part anyone used was these three
            buttons. They sit opposite the tabs now, and the row is gone. */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Tabs
            active={tab}
            onChange={setTab}
            tabs={[
              {
                id: "cases",
                label: "Test cases",
                // Every case, matching the rows in the table exactly. It used
                // to count only the generated ones while the table hid the
                // recorded one, which agreed; now the table shows it, so a
                // badge saying 14 above a table of 15 would be a small lie.
                count: suite.cases.length,
                icon: <FlaskConical />,
              },
              // Its own section. Running used to sit above the table, and the
              // result matrix lists every test case again as it executes — so
              // thirteen rows became twenty-six, the same names twice on one
              // screen. What tests exist and what happened when they ran are
              // different questions, asked at different moments.
              {
                id: "runs",
                label: "Runs",
                icon: <Play />,
              },
            ]}
          />

          {/* One row. The three you press constantly are here, labelled; the
              three you rarely press — one of which deletes the suite — are a
              click away in the menu. They belong to the Test cases tab, so
              they are absent on the other two rather than sitting there
              inert. */}
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            {tab === "cases" && (
              <>
                <GenerateCases
                  suiteId={suite.id}
                  hasGenerated={generated > 0}
                  onOutcome={setGenerateOutcome}
                  onGenerated={(updated) => {
                    onChange(updated);
                    // The old runs tested the cases this just replaced.
                    setStatusToken((n) => n + 1);
                  }}
                />

                {canEdit && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setEditing({ testCase: null })}
                    title="Write a case the model did not think of, using the same actions and elements the generated tests are built from."
                  >
                    <Plus />
                    Add test case
                  </Button>
                )}

                <ExportSheet suite={suite} />
              </>
            )}

            {/* Delete, directly. This was behind a `⋯` menu, which earns its
                place when it holds three or four things and is a click for
                nothing when it holds one. Icon-only because the row above is
                already three labelled buttons wide, and a fourth spelling out
                "Delete suite" would push them onto two lines — the confirm
                dialog names the suite before anything happens, so the label is
                not what is keeping this safe.

                Red standing still — the tint as well as the icon, and not only
                on hover. It is the one control here that destroys something,
                and a button that looks ordinary until the pointer is already
                on it announces itself too late to be a warning.

                Both hover colours are restated because the ghost variant sets
                `hover:bg-accent hover:text-foreground`, which would turn it
                grey at exactly the moment somebody is about to press it.
                Squared off with `w-8.5 px-0` so it reads as an icon rather
                than a button missing its label, while keeping the `h-8.5` of
                the labelled buttons beside it. */}
            {canEdit && (
              <Button
                variant="ghost"
                size="sm"
                onClick={remove}
                disabled={deleting}
                aria-label={`Delete ${suite.name}`}
                title={`Delete "${suite.name}", its test cases and its run history`}
                className="w-8.5 bg-destructive-subtle px-0 text-destructive hover:bg-destructive-subtle hover:text-destructive hover:brightness-95"
              >
                <Trash2 />
              </Button>
            )}
          </div>
        </div>

        <div className="mt-4">
          {tab === "cases" && (
            <div className="flex flex-col gap-4">
              {/* Nothing between the tabs and the table any more. This held
                  three stacked rows in three different containers — a dashed
                  box, a bordered card and a bare line — each with a sentence
                  you read once and scrolled past forever after, plus a
                  full-width amber banner repeating a warning every affected
                  row already carries beside its own name.

                  The buttons moved up beside the tabs; the sentences moved
                  onto the buttons. */}

              {/* Only when it went wrong. The success banner said "Added 12
                  test cases · 11,482 tokens · $0.0235" above a table that had
                  just filled with twelve new rows and a tab badge that had
                  just changed to match — the same news three times, and the
                  only copy of it you had to dismiss. A failure still has to be
                  said, because nothing else on the page would show it.

                  "Built from the recording because no provider is configured"
                  went the same way, and for the same reason. It is true, and it
                  is three sentences of blue prose above a table that has just
                  answered the question you pressed the button to ask. */}
              {generateOutcome && <Alert>{generateOutcome}</Alert>}

              {/* The pass/fail summary was here. Every row already carries its
                  own verdict in the Status column, and the Runs tab carries
                  the run itself. */}
              <TestCaseList
                cases={suite.cases}
                runningCaseIds={runningCaseIds}
                statusByCase={statusByCase}
                onRunCase={(caseId) => {
                  requestCount.current += 1;
                  setRunRequest({ caseIds: [caseId], token: requestCount.current });
                  // Optimistic: the panel confirms a moment later, but the
                  // spinner has to appear on the press, not after a round trip.
                  setRunningCaseIds([caseId]);
                  // You pressed run, so show the run. Without this the press
                  // looks like it did nothing, because what it started is on
                  // the tab you are not looking at.
                  setTab("runs");
                }}
                onEditCase={
                  canEdit ? (testCase) => setEditing({ testCase }) : undefined
                }
                onDeleteCase={canEdit ? removeCase : undefined}
              />
            </div>
          )}

          {/* Hidden rather than unmounted, and that is load-bearing: this panel
              owns the polling, the live progress and the "a run finished"
              callback that refreshes every row's status. Unmounting it to
              switch tabs would abandon a run still in flight and leave the
              rows spinning for good. */}
          <div className={tab === "runs" ? "" : "hidden"}>
            <RunPanel
              suiteId={suite.id}
              caseCount={suite.cases.length}
              // The recording and nothing else: the walkthrough a tester
              // performed, with the checks they made while performing it. Not
              // hand-written cases, and not invented ones.
              recordedCaseIds={suite.cases
                .filter(isRecorded)
                .map((testCase) => testCase.id)}
              request={runRequest}
              reloadToken={statusToken}
              onDeleted={() => void onChange(suite)}
              onRunningChange={(ids) => {
                setRunningCaseIds(ids);
                // A finished run changes where cases stand.
                if (ids === null) setStatusToken((n) => n + 1);
              }}
            />
          </div>

        </div>
      </div>

      {editing && (
        <CaseEditor
          suiteId={suite.id}
          testCase={editing.testCase}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void reload();
          }}
        />
      )}
    </section>
  );
}

/** Hand the suite to whoever keeps the test-case sheet.
 *
 *  QA teams track cases in Excel and are asked for that sheet by people who
 *  will never open this app. AutoQA already holds every column it wants, so
 *  making them retype it would be absurd. */
function ExportSheet({ suite }: { suite: TestSuiteDetail }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleExport() {
    setBusy(true);
    setError(null);
    try {
      const stem =
        suite.name.replace(/[^a-z0-9]+/gi, "_").replace(/^_+|_+$/g, "") ||
        `suite_${suite.id}`;
      await downloadTestCaseSheet(suite.id, `test_cases_${stem}.xlsx`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not export the sheet");
    } finally {
      setBusy(false);
    }
  }

  // A button, not a card. What it produces fits in a tooltip, and a paragraph
  // describing a spreadsheet was taking a full row above the table.
  return (
    <Button
      variant="outline"
      size="sm"
      onClick={handleExport}
      disabled={busy || suite.cases.length === 0}
      title={
        error ??
        `All ${suite.cases.length} cases as an Excel workbook — ID, priority, ` +
          "positive/negative, steps, expected result. The execution columns are " +
          "filled in from the latest run."
      }
      className={error ? "border-destructive/40 text-destructive" : undefined}
    >
      <FileSpreadsheet />
      {busy ? "Exporting…" : error ? "Export failed" : "Export test log"}
    </Button>
  );
}
