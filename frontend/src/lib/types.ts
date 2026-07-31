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
  description: string;
  locator: string | null;
  input_data: string | null;
  expected_result: string | null;
  selector_strategy: SelectorStrategy | null;
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
  error_message: string | null;
  stack_trace: string | null;
  failed_step: number | null;
  retries: number;
  artifacts: Artifact[];
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
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

/** How slowly to drive the browser when watching, in milliseconds per action.
 *  Offered as a choice because the right speed depends on why you are
 *  watching: proving it works, or reading every field as it is filled. */
export const WATCH_SPEEDS: { label: string; ms: number }[] = [
  { label: "Normal", ms: 300 },
  { label: "Slow", ms: 1000 },
  { label: "Step by step", ms: 2500 },
];

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

export const RUN_BADGE: Record<RunStatus, Tone> = {
  queued: "neutral",
  running: "primary",
  passed: "success",
  failed: "danger",
  cancelled: "neutral",
  error: "warning",
};

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
