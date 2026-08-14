/** Types mirroring the backend Pydantic schemas.
 *  From Phase 3 these can be generated from the OpenAPI schema instead. */

export type UserRole = "manual_qa" | "qa_engineer" | "test_manager" | "admin";

export type Browser = "chromium" | "firefox" | "webkit";

export interface User {
  id: number;
  email: string;
  full_name: string | null;
  role: UserRole;
  is_active: boolean;
  created_at: string;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: User;
}

export interface Project {
  id: number;
  name: string;
  base_url: string;
  description: string | null;
  default_browsers: Browser[];
  settings: Record<string, unknown>;
  owner_id: number;
  created_at: string;
  updated_at: string;
}

export interface ProjectCreate {
  name: string;
  base_url: string;
  description?: string | null;
  default_browsers?: Browser[];
}

/** One file a test can upload, instead of a generated placeholder.
 *
 *  A browser never says where a chosen file lives, so a recording holds the
 *  name of somebody's photograph and nothing else. A placeholder gets past the
 *  form; a listing that shows its photographs back deserves photographs. */
export interface SampleFile {
  id: number;
  filename: string;
  content_type: string;
  size: number;
}

// --- recordings -----------------------------------------------------------

export type RecordingStatus = "recording" | "completed" | "discarded";

export type ActionType =
  | "click" | "double_click" | "input" | "select" | "check" | "uncheck"
  | "hover" | "drag_drop" | "navigate" | "key_press" | "upload"
  | "scroll" | "assert";

export type SelectorStrategy =
  | "test_id" | "role_name" | "label" | "placeholder"
  | "text" | "css_id" | "css" | "xpath" | "nth_child";

export interface Selector {
  strategy: SelectorStrategy;
  value: string;
  unique: boolean;
  score: number;
}

export interface ElementInfo {
  tag: string;
  input_type: string | null;
  role: string | null;
  accessible_name: string | null;
  text: string | null;
  attributes: Record<string, string>;
}

export interface RecordedAction {
  id: number;
  sequence: number;
  action_type: ActionType;
  timestamp_ms: number;
  url: string;
  frame_path: string[];
  selectors: Selector[];
  element: ElementInfo | null;
  payload: Record<string, unknown>;
  is_ignored: boolean;
  note: string | null;
}

export interface RecordingSession {
  id: number;
  project_id: number;
  created_by_id: number | null;
  name: string;
  start_url: string;
  status: RecordingStatus;
  browser_info: Record<string, unknown>;
  extension_version: string | null;
  action_count: number;
  duration_ms: number | null;
  created_at: string;
  updated_at: string;
  /** True while a launched browser window is still open for this session. */
  browser_open?: boolean;
  /** Set once code has been generated — happens automatically on stop. */
  suite_id?: number | null;
}

export interface RecordingSessionDetail extends RecordingSession {
  actions: RecordedAction[];
}

// --- generated test suites ------------------------------------------------

export type CaseSource = "recording" | "agent" | "manual";
export type CaseStatus = "draft" | "approved" | "deprecated";
export type FileType =
  | "test" | "page_object" | "conftest" | "config"
  | "fixture" | "util" | "helper";

export interface TestStep {
  id: number;
  sequence: number;
  action: ActionType;
  /** Which word from the authoring vocabulary this step was written with.
   *  `action` cannot stand in for it — seven assertions share ActionType
   *  "assert" — so a step without it cannot be loaded into the editor. */
  verb: string | null;
  description: string;
  locator: string | null;
  input_data: string | null;
  expected_result: string | null;
  selector_strategy: SelectorStrategy | null;
}

// ---------------------------------------------------------------------------
// Authoring a case by hand
//
// The editor offers a fixed list of actions and a fixed list of elements,
// both served by the backend. There is no field for code anywhere in here,
// and that is the safeguard: a hand-written case is compiled by the same
// converter as a generated one, so it cannot do anything a generated one
// could not.
// ---------------------------------------------------------------------------
export interface Verb {
  name: string;
  label: string;
  needs_target: boolean;
  needs_value: boolean;
  allows_empty: boolean;
  is_assertion: boolean;
}

export interface ElementChoice {
  /** How a step names it: `login_page.email_input`. */
  target: string;
  label: string;
  page: string;
  page_url: string;
  strategy: SelectorStrategy;
  fragile: boolean;
  ambiguous: boolean;
}

export interface CaseVocabulary {
  verbs: Verb[];
  elements: ElementChoice[];
  placeholders: { token: string; label: string }[];
  max_steps: number;
}

export interface CaseStepWrite {
  action: string;
  target?: string | null;
  value?: string | null;
  description?: string | null;
}

export interface CaseWrite {
  name: string;
  description?: string | null;
  category: CaseCategory;
  priority: CasePriority;
  steps: CaseStepWrite[];
}

/** A row of an uploaded sheet that could not become an automated test. */
export interface SkippedRow {
  row: number;
  scenario: string;
  reason: string;
}

/** A team's own manual test-case sheet, read and drafted - saved by nobody yet.
 *
 *  `reading` is how the sheet was understood, naming the columns used. It comes
 *  back because a sheet misread by one column produces confident nonsense, and
 *  saying which column was taken for what is the only way to catch that before
 *  anything is saved. */
export interface ImportPreview {
  reading: string;
  rows: number;
  cases: CaseWrite[];
  skipped: SkippedRow[];
  model: string;
  tokens: number;
  cost_usd: number;
}

export interface TestCase {
  id: number;
  category: CaseCategory;
  priority: CasePriority;
  generated_by: string;
  suite_id: number;
  project_id: number;
  name: string;
  description: string | null;
  function_name: string;
  file_path: string;
  source: CaseSource;
  status: CaseStatus;
  tags: string[];
  is_enabled: boolean;
  version: number;
  created_at: string;
  code: string;
  steps: TestStep[];
}

export interface GeneratedFile {
  id: number;
  file_type: FileType;
  path: string;
  language: string;
  version: number;
  content: string;
}

export interface TestSuite {
  id: number;
  project_id: number;
  recording_id: number | null;
  name: string;
  description: string | null;
  source: CaseSource;
  generator: string;
  /** Folder the scripts were written to, for opening in VS Code. */
  output_dir: string | null;
  created_at: string;
  updated_at: string;
}

export interface TestSuiteDetail extends TestSuite {
  cases: TestCase[];
  files: GeneratedFile[];
}

/** Mirrors SELECTOR_RANK in backend/app/models/enums.py. Lower is better. */
export const SELECTOR_RANK: Record<SelectorStrategy, number> = {
  test_id: 1, role_name: 2, label: 3, placeholder: 4,
  text: 5, css_id: 6, css: 7, xpath: 8, nth_child: 9,
};

/** Ranks above this are too brittle to trust — the UI flags them. */
export const RELIABLE_RANK = SELECTOR_RANK.css_id;

/** How the Phase 3 generator will express each strategy in Playwright. */
export function playwrightFor(selector: Selector): string {
  const v = selector.value;
  switch (selector.strategy) {
    case "test_id":
      return `page.get_by_test_id("${v}")`;
    case "role_name": {
      const [role, ...rest] = v.split("|");
      return `page.get_by_role("${role}", name="${rest.join("|")}")`;
    }
    case "label":
      return `page.get_by_label("${v}")`;
    case "placeholder":
      return `page.get_by_placeholder("${v}")`;
    case "text":
      return `page.get_by_text("${v}", exact=True)`;
    case "xpath":
      return `page.locator("xpath=${v}")`;
    default:
      return `page.locator("${v}")`;
  }
}

/** Roles are hierarchical — test_manager can do anything qa_engineer can.
 *  Mirrors ROLE_LEVEL in backend/app/models/enums.py. */
export const ROLE_LEVEL: Record<UserRole, number> = {
  manual_qa: 1,
  qa_engineer: 2,
  test_manager: 3,
  admin: 4,
};

export const ROLE_LABEL: Record<UserRole, string> = {
  manual_qa: "Manual QA Engineer",
  qa_engineer: "QA Engineer",
  test_manager: "Test Manager",
  admin: "Admin",
};

export function hasRole(user: User | null, minimum: UserRole): boolean {
  if (!user) return false;
  return ROLE_LEVEL[user.role] >= ROLE_LEVEL[minimum];
}

/** Did this case come from the recording itself?
 *
 *  Not the category, and not `source`. Every case in a recorded suite carries
 *  `source: "recording"`, invented ones included — it says where the suite came
 *  from, not where the test came from. `generated_by` is the field that
 *  answers this:
 *
 *    `deterministic_v1`  the recording. The tester's own walkthrough and every
 *                        check they made in assert mode along the way,
 *                        compiled by the converter rather than invented.
 *    `manual`            one a tester wrote by hand in the editor afterwards.
 *    anything else       the name of the model that wrote it.
 *
 *  Only the first counts. A hand-written case is somebody's own work too, but
 *  it is not what was recorded, and the run mode is named after the recording.
 */
export function isRecorded(testCase: TestCase): boolean {
  return (testCase.generated_by || "").startsWith("deterministic");
}

// ---------------------------------------------------------------------------
// Test execution
// ---------------------------------------------------------------------------
export type RunStatus =
  | "queued"
  | "running"
  | "passed"
  | "failed"
  | "cancelled"
  | "error";

export type ResultStatus = "passed" | "failed" | "skipped" | "error" | "flaky";

export type ArtifactType =
  | "screenshot"
  | "video"
  | "log"
  | "trace"
  | "html_report"
  | "allure_report";

export interface Artifact {
  id: number;
  type: ArtifactType;
  file_path: string;
  file_size: number | null;
}

export interface TestResult {
  id: number;
  test_case_id: number | null;
  case_name: string;
  function_name: string;
  browser: Browser;
  status: ResultStatus;
  duration_ms: number | null;
  /** The test pytest is inside right now, while the run is active. */
  current_test: string | null;
  error_message: string | null;
  stack_trace: string | null;
  failed_step: number | null;
  retries: number;
  artifacts: Artifact[];
}

/** One failure, with enough around it to be a page of its own.
 *
 *  Everything about a failure used to have to fit inside an expanded row of the
 *  run's table — error, analysis, bug draft, screenshot, recording, trace. It
 *  stopped fitting, so a failure gets a page, and a page needs its own heading
 *  and its own way back. */
export interface TestResultDetail extends TestResult {
  run_id: number;
  run_status: RunStatus;
  project_id: number;
  project_name: string;
  suite_id: number | null;
  suite_name: string;
  started_at: string | null;
  /** The same test in the other browsers. "Passes in Chrome, fails in WebKit"
   *  is the most useful thing to know about a failure, and it is invisible to
   *  anyone looking at one result on its own. */
  siblings: TestResult[];
}

export interface TestRun {
  id: number;
  project_id: number;
  suite_id: number | null;
  status: RunStatus;
  browsers: string[];
  case_ids: number[];
  headless: boolean;
  slow_mo_ms: number;
  total: number;
  passed: number;
  failed: number;
  skipped: number;
  duration_ms: number | null;
  /** The test pytest is inside right now, while the run is active. */
  current_test: string | null;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  /** Named on the list endpoint, so a page of runs from every project can group
   *  itself without a request per row. */
  project_name: string;
  /** Empty once the suite is deleted — a run outlives what it ran, which is the
   *  point of keeping it. */
  suite_name: string;
}

export interface TestRunDetail extends TestRun {
  results: TestResult[];
}

/** A run that is still going. Drives polling and the spinner. */
export function isRunActive(run: Pick<TestRun, "status">): boolean {
  return run.status === "queued" || run.status === "running";
}

export const BROWSER_LABEL: Record<Browser, string> = {
  chromium: "Chrome",
  firefox: "Firefox",
  webkit: "Safari",
};

/** Badge tones, so status colour is decided once and stays consistent.
 *  Hard-coded Tailwind palette classes were used here before, which ignored
 *  the theme and looked wrong in dark mode. */
export type Tone = "neutral" | "primary" | "success" | "danger" | "warning";

export const RESULT_BADGE: Record<ResultStatus, Tone> = {
  passed: "success",
  failed: "danger",
  error: "warning",
  skipped: "neutral",
  flaky: "warning",
};

/** What each status means to the person reading it, rather than to pytest.
 *
 *  "Blocked" is the one that earns its place. A test whose click never reached
 *  its element asked the application nothing, so it has no verdict to give —
 *  about the application or about anything else. Shown as "Error" it reads as
 *  a defect and sends someone to look at a page that works; shown as "Failed"
 *  it is worse. Red has to keep meaning "your application is wrong", or the
 *  next red one gets dismissed too. */
export const RESULT_LABEL: Record<ResultStatus, string> = {
  passed: "Passed",
  failed: "Failed",
  error: "Blocked",
  skipped: "Skipped",
  flaky: "Flaky",
};

export const BLOCKED_MEANS =
  "AutoQA could not reach the element this step needed, so the test never got " +
  "as far as checking anything. That is a problem with the test, not evidence " +
  "of a bug in your application.";

export const RUN_BADGE: Record<RunStatus, Tone> = {
  queued: "neutral",
  running: "primary",
  passed: "success",
  failed: "danger",
  cancelled: "neutral",
  error: "warning",
};

/** "4m ago" / "yesterday" / "12 Jul" — when something happened, at the
 *  precision that is actually useful. Nothing older than a week gets a fuzzy
 *  label, because "3 weeks ago" is harder to reason about than a date. */
export function formatRelative(iso: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "—";

  const seconds = Math.round((Date.now() - then.getTime()) / 1000);
  if (seconds < 45) return "just now";
  if (seconds < 90) return "a minute ago";

  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;

  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  if (hours < 48) return "yesterday";

  const days = Math.round(hours / 24);
  if (days < 7) return `${days}d ago`;

  return then.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** "1.8s" / "2m 04s" — durations in a table need to be scannable. */
export function formatDuration(ms: number | null): string {
  if (ms === null || ms < 0) return "-";
  if (ms < 1000) return `${ms}ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${String(Math.round(seconds % 60)).padStart(2, "0")}s`;
}

// ---------------------------------------------------------------------------
// Test case categories
// ---------------------------------------------------------------------------
export type CaseCategory =
  | "recorded"
  | "positive"
  | "negative"
  | "edge"
  | "security";

export type CasePriority = "critical" | "high" | "medium" | "low";

export const CATEGORY_LABEL: Record<CaseCategory, string> = {
  recorded: "Recorded",
  positive: "Positive",
  negative: "Negative",
  edge: "Edge case",
  security: "Security",
};

/** One line each, shown under the group heading. A category name alone does
 *  not tell a manual QA engineer what the group is for. */
export const CATEGORY_BLURB: Record<CaseCategory, string> = {
  recorded: "The flow you actually walked. This is your regression test.",
  positive: "Other paths that should succeed.",
  negative: "Input the app should reject, cleanly.",
  edge: "Boundaries: empty, very long, whitespace, unicode.",
  security: "Input validation and auth handling.",
};

export const CATEGORY_TONE: Record<CaseCategory, Tone> = {
  recorded: "primary",
  positive: "success",
  negative: "danger",
  edge: "warning",
  security: "neutral",
};

/** Display order. Recorded first because it is the one that was real. */
export const CATEGORY_ORDER: CaseCategory[] = [
  "recorded",
  "positive",
  "negative",
  "edge",
  "security",
];

export const PRIORITY_TONE: Record<CasePriority, Tone> = {
  critical: "danger",
  high: "warning",
  medium: "neutral",
  low: "neutral",
};

export interface GenerateCasesResult {
  suite: TestSuiteDetail;
  generated: number;
  rejected: string[];
  model: string;
  tokens: number;
  cost_usd: number;
}

// ---------------------------------------------------------------------------
// AI failure analysis
// ---------------------------------------------------------------------------
export type FailureCategory =
  | "application_bug"
  | "test_bug"
  | "selector_broken"
  | "timing"
  | "environment"
  | "test_data"
  | "flaky";

export type Severity = "critical" | "high" | "medium" | "low";

export const CATEGORY_TEXT: Record<FailureCategory, string> = {
  application_bug: "Application bug",
  test_bug: "Test bug",
  selector_broken: "Selector broken",
  timing: "Timing",
  environment: "Environment",
  test_data: "Test data",
  flaky: "Flaky",
};

export const SEVERITY_TONE: Record<Severity, Tone> = {
  critical: "danger",
  high: "warning",
  medium: "neutral",
  low: "neutral",
};

export interface Analysis {
  id: number;
  result_id: number;
  run_id: number;
  provider: string;
  model: string;
  // The two sides of the mismatch, in a person's words. Null on analyses
  // written before the model was asked for them.
  expected: string | null;
  actual: string | null;
  root_cause: string;
  suggested_fix: string;
  category: FailureCategory;
  severity: Severity;
  priority: Severity;
  is_product_bug: boolean;
  confidence: number;
  tokens: number;
  cost_usd: number;
  created_at: string;
}

/** A whole run explained in one pass.
 *
 *  `distinct_causes` is the number that changes someone's day: "16 failed" and
 *  "16 failed, 3 causes" are a week and an afternoon. Nothing that looks at a
 *  single failure can tell them apart, which is why this exists alongside the
 *  per-failure analysis rather than replacing it. */
export interface RunTriage {
  analyses: Analysis[];
  summary: string;
  distinct_causes: number;
  model: string;
  tokens: number;
  cost_usd: number;
}

/** One exchange, sent back with the next question so a follow-up works. */
export interface AskTurn {
  question: string;
  answer: string;
}

/** An answer about a project's results, grounded in its stored history. */
export interface AskAnswer {
  answer: string;
  cites: string[];
  /** False when the stored results did not really support an answer. Shown
   *  rather than hidden: acting on a confident wrong answer costs an
   *  afternoon. */
  confident: boolean;
  model: string;
  tokens: number;
  cost_usd: number;
}

/** One element only the recorded happy path drives. */
/** One check proposed for a recorded test that asserts nothing.
 *
 *  A recording captures what somebody did, not what should have been true
 *  afterwards — so the test it produces passes as long as every click found
 *  something to click. */

export interface Untouched {
  page: string;
  page_url: string;
  element: string;
  label: string;
  /** A test written against this is brittle the day it is written. */
  fragile: boolean;
}

/** How much of the recorded flow has a test other than the recording.
 *
 *  Not "how much of your code is tested" — this tool cannot see the code. The
 *  recording walks one route and everything on it works; the value is in the
 *  cases written around it, so this counts the parts of the flow that have no
 *  test except the one that was always going to pass. */
export interface Coverage {
  touched: number;
  total: number;
  percent: number;
  untouched: Untouched[];
}

/** One test and browser whose verdict changes without the test changing. */
export interface FlakyTest {
  test_case_id: number;
  browser: string;
  case_name: string;
  runs: number;
  passed: number;
  failed: number;
  /** How many times the verdict changed between consecutive runs. */
  flips: number;
  summary: string;
}

// ---------------------------------------------------------------------------
// Bug reports
// ---------------------------------------------------------------------------
export type BugStatus = "draft" | "open" | "resolved" | "wont_fix";

export const BUG_STATUS_TONE: Record<BugStatus, Tone> = {
  draft: "neutral",
  open: "warning",
  resolved: "success",
  wont_fix: "neutral",
};

/** `wont_fix` is not a word. */
export const BUG_STATUS_LABEL: Record<BugStatus, string> = {
  draft: "Draft",
  open: "Open",
  resolved: "Resolved",
  wont_fix: "Won't fix",
};

export interface BugReport {
  id: number;
  project_id: number;
  result_id: number | null;
  analysis_id: number | null;
  title: string;
  description: string;
  steps_to_reproduce: string[];
  expected: string;
  actual: string;
  environment: Record<string, unknown>;
  severity: Severity;
  priority: Severity;
  status: BugStatus;
  created_at: string;
  /** Named on the list endpoints, so a page spanning every project can group
   *  itself without a request per row. Empty on the per-failure lookups, which
   *  already know where they are. */
  project_name: string;
  /** The test that found it. Empty once the run has been deleted — the bug
   *  outlives it, which is why its steps were copied in when it was drafted. */
  case_name: string;
}

/** The whole report as plain text, for pasting into a tracker. */
export function bugAsText(bug: BugReport): string {
  const steps = bug.steps_to_reproduce
    .map((step, i) => `${i + 1}. ${step}`)
    .join("\n");
  const env = Object.entries(bug.environment)
    .filter(([, value]) => value !== null && value !== undefined)
    .map(([key, value]) => `- ${key}: ${value}`)
    .join("\n");

  return [
    bug.title,
    "",
    bug.description,
    "",
    "Steps to reproduce:",
    steps,
    "",
    `Expected: ${bug.expected}`,
    `Actual: ${bug.actual}`,
    "",
    "Environment:",
    env,
    "",
    `Severity: ${bug.severity} · Priority: ${bug.priority}`,
  ].join("\n");
}

/** One plain sentence for a Playwright error, or null when we have no better
 *  words than the ones already there.
 *
 *  The raw message is written for whoever wrote the test:
 *
 *      playwright._impl._errors.TimeoutError: Locator.click: Timeout 30000ms
 *      exceeded. Call log: waiting for get_by_role("link", name="Home").first
 *
 *  A Manual QA Engineer reads that and learns nothing they can act on, which is
 *  the whole audience this tool exists for. The technical text is kept below —
 *  it is what you paste to a developer — but it should not be the first thing
 *  on screen.
 */
export function plainError(message: string): string | null {
  const thing = elementIn(message);

  if (/strict mode violation/i.test(message)) {
    const count = /resolved to (\d+) elements/i.exec(message);
    return sentence(
      `${thing} matches ${count ? count[1] : "more than one"} things on the page, so the test could not tell which one to use.`,
    );
  }
  if (/Timeout .*exceeded/i.test(message) && /waiting for/i.test(message)) {
    return sentence(`${thing} never appeared. The test waited and then gave up.`);
  }
  if (/expected not to be|not_to_have_url/i.test(message)) {
    return "The page address was the one the test said it should not be.";
  }
  if (/to_have_url|Page URL expected/i.test(message)) {
    return "The page address was not the one the test expected.";
  }
  if (/expected to be visible/i.test(message)) {
    return sentence(`${thing} was not visible on the page.`);
  }
  if (/expected to be hidden/i.test(message)) {
    return sentence(
      `${thing} was still on the page when the test expected it to be gone.`,
    );
  }
  if (/to_contain_text|expected to contain text/i.test(message)) {
    return "The text on the page was not the text the test expected.";
  }
  if (/ERR_NAME_NOT_RESOLVED|ERR_CONNECTION|net::ERR/i.test(message)) {
    return "The page could not be reached at all — the address did not respond.";
  }
  if (/ModuleNotFoundError|ImportError/i.test(message)) {
    return "The test file could not be loaded. Regenerate the suite.";
  }
  return null;
}

/** What the test was looking for, named the way it appears on screen.
 *
 *  `name=` first, and that ordering is the whole point:
 *  `get_by_role("link", name="See All Properties")` describes a link called
 *  "See All Properties", and taking the first quoted string instead reports
 *  that `"link"` never appeared — true of nothing anyone can look for. */
function elementIn(message: string): string {
  const byName = /(?:name|text)=["']([^"']+)["']/.exec(message);
  if (byName) return `"${byName[1]}"`;

  const byLookup =
    /get_by_(?:label|placeholder|text|test_id)\(\s*["']([^"']+)["']/.exec(message);
  if (byLookup) return `"${byLookup[1]}"`;

  return "the element it needed";
}

/** Capitalise, since these read as prose and can begin with a quoted label. */
function sentence(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}
