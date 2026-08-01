"use client";

/** The home page — the whole site on one page.
 *
 *  Everything a visitor needs is here and reachable by scrolling: what it is,
 *  what it looks like, the problem it solves, how it works, what it does, what
 *  it costs, and the common questions. The nav scrolls rather than navigates.
 *
 *  The illustrations are drawn in markup rather than loaded as images. Three
 *  reasons, in order of how much they matter: they depict the real interface
 *  instead of a stock photograph of somebody pointing at a laptop; they follow
 *  the theme, so they are correct in dark mode without a second asset; and
 *  they cost no network request and never arrive after the text.
 */

import Link from "next/link";
import {
  ArrowRight,
  Ban,
  Bug,
  Camera,
  Check,
  ChevronDown,
  Code2,
  Crosshair,
  FileText,
  Gauge,
  Layers,
  MonitorPlay,
  MousePointer2,
  Radar,
  ShieldCheck,
  Sparkles,
  Timer,
  Users,
  Video,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/stores/auth-store";

/** Whether to offer the app or offer a way in.
 *
 *  Before rehydration finishes we do not know yet, and we answer "signed out" —
 *  most people reading this page are, and a wrong guess costs one repaint of
 *  two buttons rather than a wrong page. */
function useSignedIn() {
  const hydrated = useAuthStore((s) => s.hydrated);
  const accessToken = useAuthStore((s) => s.accessToken);
  return hydrated && Boolean(accessToken);
}

/** The pair of buttons in the header, the hero and the closing band. They agree
 *  with each other because they are the same component. */
function AuthCta({ size = "default" }: { size?: "default" | "sm" | "lg" }) {
  const signedIn = useSignedIn();

  if (signedIn) {
    return (
      <>
        <Link href="/projects">
          <Button variant={size === "sm" ? "ghost" : "outline"} size={size}>
            Projects
          </Button>
        </Link>
        <Link href="/dashboard">
          <Button size={size}>
            Go to dashboard
            {size !== "sm" && <ArrowRight />}
          </Button>
        </Link>
      </>
    );
  }

  return (
    <>
      <Link href="/login">
        <Button variant={size === "sm" ? "ghost" : "outline"} size={size}>
          Login
        </Button>
      </Link>
      <Link href="/register">
        <Button size={size}>
          Get started
          {size !== "sm" && <ArrowRight />}
        </Button>
      </Link>
    </>
  );
}

export function Marketing() {
  return (
    <div className="min-h-screen">
      <Nav />
      <Hero />
      <TechStrip />
      <Stats />
      <Problem />
      <HowItWorks />
      <Features />
      <TheLine />
      <Pricing />
      <Faq />
      <Closing />
      <Footer />
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * Navigation — anchors, because everything is on this page
 * ------------------------------------------------------------------ */

const SECTIONS = [
  ["Why AutoQA", "#why"],
  ["How it works", "#how"],
  ["Features", "#features"],
  ["Pricing", "#pricing"],
  ["FAQ", "#faq"],
];

function Nav() {
  return (
    <header className="sticky top-0 z-40 border-b border-border bg-card/85 backdrop-blur-xl">
      <div className="mx-auto flex max-w-6xl items-center gap-6 px-5 py-3.5 sm:px-8">
        <a href="#top" className="flex shrink-0 items-center gap-2.5">
          <span className="brand-gradient flex size-8 items-center justify-center rounded-xl text-white">
            <Radar className="size-[17px]" />
          </span>
          <span className="text-[15px] font-bold tracking-tight">AutoQA</span>
        </a>

        <nav className="ml-2 hidden items-center gap-1 lg:flex">
          {SECTIONS.map(([label, href]) => (
            <a
              key={href}
              href={href}
              className="rounded-full px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              {label}
            </a>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-2">
          <AuthCta size="sm" />
        </div>
      </div>
    </header>
  );
}

/* ------------------------------------------------------------------ *
 * Hero
 * ------------------------------------------------------------------ */

function Hero() {
  const signedIn = useSignedIn();

  return (
    <section id="top" className="relative overflow-hidden">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-10"
        style={{
          background:
            "linear-gradient(180deg, var(--primary-subtle) 0%, transparent 100%)",
        }}
      />

      <div className="mx-auto max-w-4xl px-5 pt-16 text-center sm:px-8 sm:pt-24">
        <Badge>
          <Sparkles className="size-3.5" />
          Record once. AutoQA writes the rest.
        </Badge>

        <h1 className="mt-6 text-4xl font-extrabold leading-[1.08] tracking-tight sm:text-5xl md:text-6xl">
          Test automation
          <br />
          <span className="text-primary">without writing code</span>
        </h1>

        <p className="mx-auto mt-6 max-w-2xl text-base leading-relaxed text-muted-foreground sm:text-lg">
          Click through your app the way a tester would. AutoQA turns that into
          real Playwright tests, runs them across Chrome, Firefox and Safari,
          and explains anything that breaks — root cause, suggested fix, and a
          bug report a developer can act on.
        </p>

        <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
          <AuthCta size="lg" />
        </div>

        {/* Sign-up reassurance, so it goes once you have signed up. */}
        {!signedIn && (
          <ul className="mt-6 flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-[13px] text-muted-foreground">
            {["No credit card", "Runs on your machine", "AI features optional"].map(
              (item) => (
                <li key={item} className="flex items-center gap-1.5">
                  <Check className="size-3.5 text-success" />
                  {item}
                </li>
              ),
            )}
          </ul>
        )}
      </div>

      <div className="mx-auto mt-14 max-w-5xl px-5 pb-16 sm:px-8">
        <DashboardShot />
      </div>
    </section>
  );
}

/** The product, as a browser window. It is the same layout the app really has:
 *  rail, hero pass-rate, run trend, failure list. */
function DashboardShot() {
  const bars = [
    [9, 4],
    [11, 2],
    [8, 5],
    [12, 1],
    [13, 0],
    [10, 3],
    [13, 0],
  ];
  const max = 13;

  return (
    <BrowserFrame url="autoqa.local/dashboard">
      <div className="flex min-h-[22rem] text-left">
        {/* Rail */}
        <div className="hidden w-[9.5rem] shrink-0 flex-col gap-1 border-r border-border p-3 sm:flex">
          <div className="mb-2 flex items-center gap-2 px-1">
            <span className="brand-gradient flex size-6 items-center justify-center rounded-lg text-white">
              <Radar className="size-3" />
            </span>
            <span className="text-[11px] font-bold">AutoQA</span>
          </div>
          {[
            ["Dashboard", true],
            ["Projects", false],
            ["Recordings", false],
          ].map(([label, active]) => (
            <div
              key={label as string}
              className={
                active
                  ? "rounded-full bg-primary-subtle px-3 py-1.5 text-[11px] font-semibold text-primary"
                  : "rounded-full px-3 py-1.5 text-[11px] text-muted-foreground"
              }
            >
              {label as string}
            </div>
          ))}
        </div>

        {/* Content */}
        <div className="min-w-0 flex-1 p-4">
          <div className="flex items-center justify-between gap-3">
            <p className="text-base font-extrabold tracking-tight">Dashboard</p>
            <span className="rounded-full bg-primary px-3 py-1.5 text-[10px] font-semibold text-primary-foreground">
              Record a session
            </span>
          </div>

          <div className="mt-3 grid gap-3 lg:grid-cols-[minmax(0,13rem)_minmax(0,1fr)]">
            <div className="sheen rounded-xl border border-border bg-card p-3.5">
              <p className="text-[9px] font-semibold uppercase tracking-wide text-muted-foreground">
                Pass rate
              </p>
              <p className="mt-1 text-3xl font-extrabold leading-none text-success">
                92%
              </p>
              <p className="mt-1 text-[10px] text-muted-foreground">
                76 of 83 tests across 7 runs
              </p>
              <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-success/15">
                <div className="h-full w-[92%] rounded-full bg-success" />
              </div>
            </div>

            <div className="sheen rounded-xl border border-border bg-card p-3.5">
              <p className="text-[11px] font-bold">Runs over time</p>
              <div className="mt-3 flex h-24 items-end gap-2">
                {bars.map(([pass, fail], i) => (
                  <div key={i} className="flex flex-1 flex-col justify-end gap-0.5">
                    {fail > 0 && (
                      <div
                        className="w-full rounded-md bg-destructive"
                        style={{ height: `${(fail / max) * 100}%` }}
                      />
                    )}
                    <div
                      className="w-full rounded-md bg-success"
                      style={{ height: `${(pass / max) * 100}%` }}
                    />
                  </div>
                ))}
              </div>
              <div className="mt-2 flex items-center gap-3 text-[9px] text-muted-foreground">
                <span className="flex items-center gap-1">
                  <span className="size-1.5 rounded-sm bg-success" /> Passed
                </span>
                <span className="flex items-center gap-1">
                  <span className="size-1.5 rounded-sm bg-destructive" /> Failed
                </span>
                <span className="ml-auto">last 7 runs</span>
              </div>
            </div>
          </div>

          <p className="mt-4 text-[11px] font-bold">Needs attention</p>
          <div className="mt-2 flex flex-col gap-1.5">
            {[
              ["Verify login is rejected without a password", "Chrome"],
              ["Verify the cart total updates on quantity change", "Firefox"],
            ].map(([name, browser]) => (
              <div
                key={name}
                className="sheen flex items-center gap-2.5 rounded-lg border border-border bg-card px-3 py-2"
              >
                <span className="rounded-full bg-destructive-subtle px-2 py-0.5 text-[9px] font-semibold text-destructive">
                  failed
                </span>
                <span className="min-w-0 flex-1 truncate text-[11px] font-medium">
                  {name}
                </span>
                <span className="shrink-0 text-[10px] text-muted-foreground">
                  {browser}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </BrowserFrame>
  );
}

/* ------------------------------------------------------------------ *
 * Trust strip
 * ------------------------------------------------------------------ */

function TechStrip() {
  return (
    <div className="border-y border-border bg-card">
      <div className="mx-auto max-w-6xl px-5 py-10 text-center sm:px-8">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Built on tools your team already trusts
        </p>
        <div className="mt-5 flex flex-wrap items-center justify-center gap-x-10 gap-y-4 text-[15px] font-bold text-muted-foreground">
          {[
            "Playwright",
            "pytest",
            "Python",
            "Chromium",
            "Firefox",
            "WebKit",
            "Gemini",
          ].map((name) => (
            <span key={name}>{name}</span>
          ))}
        </div>
        <p className="mx-auto mt-5 max-w-xl text-[13px] leading-relaxed text-muted-foreground">
          Nothing proprietary underneath. What AutoQA produces is a normal
          Playwright project that runs with plain <code className="font-mono">pytest</code>,
          with or without us.
        </p>
      </div>
    </div>
  );
}

function Stats() {
  const items = [
    ["3", "Browsers, in parallel"],
    ["13", "Tests from one recording"],
    ["< $0.03", "To generate a full suite"],
    ["0", "Lines of code to write"],
  ];

  return (
    <Section>
      <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
        {items.map(([value, label]) => (
          <div key={label} className="text-center">
            <p className="text-4xl font-extrabold tracking-tight text-primary">
              {value}
            </p>
            <p className="mt-1 text-[13px] text-muted-foreground">{label}</p>
          </div>
        ))}
      </div>
    </Section>
  );
}

/* ------------------------------------------------------------------ *
 * Why
 * ------------------------------------------------------------------ */

function Problem() {
  const problems = [
    [
      "01",
      "The selectors were never any good",
      "A recorder that grabs the first CSS path it finds produces tests that break on the next redesign — sometimes on the next deploy. The suite goes red, nobody trusts it, and within a month nobody runs it.",
    ],
    [
      "02",
      "You get a script, not a project",
      "One enormous linear file with the same selector pasted into forty places. Fixing one changed button means forty edits, so nobody fixes it, so the suite stays red.",
    ],
    [
      "03",
      "Red tells you nothing",
      "A timeout and a stack trace. Is the app broken or is the test wrong? Answering that by hand, per failure, costs more than the automation saved.",
    ],
  ];

  return (
    <Section id="why" tinted>
      <Heading
        center
        title="Recorded tests have a reputation."
        accent="This one is built around it."
        lead="Almost everyone has tried a record-and-playback tool, and almost everyone has abandoned one. These are the three reasons why."
      />
      <div className="mt-10 grid gap-4 md:grid-cols-3">
        {problems.map(([n, title, body]) => (
          <div
            key={n}
            className="sheen rounded-xl border border-border bg-card p-6 shadow-xs"
          >
            <span className="text-3xl font-extrabold tracking-tight text-destructive/70">
              {n}
            </span>
            <h3 className="mt-3 text-base font-bold">{title}</h3>
            <p className="mt-2 text-[13px] leading-relaxed text-muted-foreground">
              {body}
            </p>
          </div>
        ))}
      </div>
    </Section>
  );
}

/* ------------------------------------------------------------------ *
 * How it works
 * ------------------------------------------------------------------ */

function HowItWorks() {
  return (
    <Section id="how">
      <Heading
        center
        title="Four steps, and you write"
        accent="none of them"
        lead="The part that runs is ordinary Python, generated by ordinary code — so the same recording gives the same test every time. AI improves the naming and explains failures; it never sits in the path of your tests working."
      />

      <ol className="mt-10 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {[
          [<Video key="v" />, "Record", "Enter a URL. A browser opens with the recorder running — use the site normally and every click, keystroke and selection is captured."],
          [<FileText key="f" />, "Generate", "Stop recording and the test is already written: page objects, fallback selectors, readable steps. Saved to disk for VS Code."],
          [<MonitorPlay key="m" />, "Run", "Chrome, Firefox and Safari at the same time. Watch it drive the browser, or let it run headless."],
          [<Bug key="b" />, "Understand", "AI reads the error and the trace, tells you whether your app or your test is broken, and drafts the bug report."],
        ].map(([icon, title, body], index) => (
          <li key={title as string}>
            <div className="sheen h-full rounded-xl border border-border bg-card p-5 shadow-xs">
              <span className="flex size-10 items-center justify-center rounded-xl bg-primary-subtle text-primary [&_svg]:size-5">
                {icon as React.ReactNode}
              </span>
              <p className="mt-4 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                Step {index + 1}
              </p>
              <h3 className="mt-1 text-lg font-bold">{title as string}</h3>
              <p className="mt-2 text-[13px] leading-relaxed text-muted-foreground">
                {body as string}
              </p>
            </div>
          </li>
        ))}
      </ol>

      <div className="mt-6 divide-y divide-border">
        <Split
          eyebrow="Step 1 — Record"
          title="You use the site. Nothing else."
          aside={<RecorderShot />}
        >
          <p>
            There is nothing to install in your application and no attribute you
            have to add first. Log in, fill the form, click through the flow —
            whatever the test should cover.
          </p>
          <p>
            Each element you touch is captured up to eight ways at once, along
            with how many elements on the page each of those actually matches.
            That count is what stops the generated test from choosing a selector
            that looks elegant and matches three things.
          </p>
        </Split>

        <Split
          flip
          eyebrow="Step 2 — Generate"
          title="Ordinary code writes the code"
          aside={
            <CodePanel
              label="pages/login_page.py"
              code={`class LoginPage:
    def __init__(self, page: Page) -> None:
        self.page = page

    @property
    def email_input(self) -> Locator:
        return self.page.get_by_label(
            'Email', exact=True)

    @property
    def login_button(self) -> Locator:
        return self.page.get_by_role(
            'button', name='Login', exact=True)`}
            />
          }
        >
          <p>
            The mapping from a recorded action to a Playwright call is a fixed
            set of cases. A plain function does that perfectly, instantly, for
            free, and identically every time — so that is what does it. No model
            is involved in producing the code that runs.
          </p>
          <p>
            You get a real project: a test module, a page object per page, a
            conftest and a pytest.ini, written to a folder you own.
          </p>
        </Split>

        <Split
          eyebrow="Step 3 — Run"
          title="Three browsers, one wait"
          aside={<RunShot />}
        >
          <p>
            Runs are launched one process per browser, all at the same time, so
            covering three browsers costs about what covering one does. That
            matters more than it sounds — cross-browser testing that triples the
            wait is cross-browser testing that quietly stops happening.
          </p>
          <p>
            You see which test is running right now, not a spinner and a total
            at the end. And Stop actually stops: it kills the process tree
            rather than asking politely and marking the rest as errors.
          </p>
        </Split>

        <Split
          flip
          eyebrow="Step 4 — Understand"
          title="A failure, explained"
          aside={<AnalysisShot />}
        >
          <p>
            The trace says the click timed out after thirty seconds. The
            analysis says the account was locked after five failed login
            attempts and will unlock in fifteen minutes. One of those is
            actionable.
          </p>
          <p>
            It also commits to a verdict — your application, or your test. When
            it cannot tell, it says so and blames the test, because telling a
            team their product is broken on a guess is how a tool gets switched
            off.
          </p>
        </Split>
      </div>
    </Section>
  );
}

/* ------------------------------------------------------------------ *
 * Illustrations
 * ------------------------------------------------------------------ */

function BrowserFrame({
  url,
  children,
}: {
  url: string;
  children: React.ReactNode;
}) {
  return (
    <div className="overflow-hidden rounded-2xl border border-border bg-card shadow-lg">
      <div className="flex items-center gap-2 border-b border-border bg-muted/60 px-3 py-2.5">
        <span className="flex gap-1.5">
          <span className="size-2.5 rounded-full bg-destructive/50" />
          <span className="size-2.5 rounded-full bg-warning/50" />
          <span className="size-2.5 rounded-full bg-success/50" />
        </span>
        <span className="mx-auto max-w-[18rem] flex-1 truncate rounded-full bg-card px-3 py-1 text-center font-mono text-[10px] text-muted-foreground">
          {url}
        </span>
      </div>
      {children}
    </div>
  );
}

/** What the recorder sees: a form, a cursor, and the ranked candidates it
 *  captured for the element under it. */
function RecorderShot() {
  return (
    <div className="sheen rounded-xl border border-border bg-card p-5 shadow-xs">
      <div className="flex items-center gap-2">
        <span className="flex size-2 animate-pulse rounded-full bg-destructive" />
        <span className="text-[11px] font-semibold uppercase tracking-wide text-destructive">
          Recording
        </span>
        <span className="ml-auto text-[11px] text-muted-foreground">
          4 actions
        </span>
      </div>

      <div className="mt-4 rounded-lg border border-border bg-background p-4">
        <p className="text-[10px] font-medium text-muted-foreground">Email</p>
        <div className="mt-1 h-7 rounded-md border border-border bg-card" />
        <p className="mt-3 text-[10px] font-medium text-muted-foreground">
          Password
        </p>
        <div className="mt-1 h-7 rounded-md border border-border bg-card" />
        <div className="relative mt-3">
          <div className="h-8 w-24 rounded-full bg-primary ring-2 ring-primary/30 ring-offset-2 ring-offset-background" />
          <span className="absolute left-9 top-1.5 text-[10px] font-semibold text-primary-foreground">
            Login
          </span>
          <MousePointer2 className="absolute left-[4.6rem] top-5 size-4 fill-foreground text-foreground" />
        </div>
      </div>

      <p className="mt-4 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
        Captured for that button
      </p>
      <ul className="mt-2 flex flex-col gap-1.5 font-mono text-[11px]">
        {[
          ["test_id", "login-btn", 1, true],
          ["role + name", "button | Login", 1, false],
          ["text", "Login", 3, false],
          ["css", "form > button", 1, false],
        ].map(([strategy, value, matches, chosen]) => (
          <li
            key={strategy as string}
            className={
              chosen
                ? "flex items-center gap-2 rounded-md border border-primary/40 bg-primary-subtle px-2.5 py-1.5"
                : "flex items-center gap-2 rounded-md border border-border px-2.5 py-1.5"
            }
          >
            <span className="w-[5.5rem] shrink-0 text-muted-foreground">
              {strategy as string}
            </span>
            <span className="min-w-0 flex-1 truncate">{value as string}</span>
            <span
              className={
                matches === 1
                  ? "shrink-0 text-success"
                  : "shrink-0 text-destructive"
              }
            >
              {matches as number} match{matches === 1 ? "" : "es"}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[11px] text-muted-foreground">
        Chosen: <span className="font-mono">test_id</span> — unique, and the
        highest-ranked strategy that is.
      </p>
    </div>
  );
}

/** Three browsers running at once, mid-run. */
function RunShot() {
  const panes = [
    ["Chromium", 13, 13, 0, "done"],
    ["Firefox", 13, 9, 1, "running"],
    ["WebKit", 13, 11, 0, "running"],
  ] as const;

  return (
    <div className="sheen rounded-xl border border-border bg-card p-5 shadow-xs">
      <div className="flex items-center gap-2">
        <span className="flex size-2 animate-pulse rounded-full bg-primary" />
        <span className="text-[11px] font-semibold">Run #48</span>
        <span className="ml-auto rounded-full border border-border px-2.5 py-0.5 text-[10px] font-semibold text-muted-foreground">
          Stop
        </span>
      </div>

      <div className="mt-4 flex flex-col gap-3">
        {panes.map(([name, total, passed, failed, state]) => {
          const pct = Math.round(((passed + failed) / total) * 100);
          return (
            <div key={name}>
              <div className="flex items-baseline gap-2">
                <span className="text-[11px] font-semibold">{name}</span>
                <span className="text-[10px] text-muted-foreground">
                  {passed + failed}/{total}
                </span>
                <span className="ml-auto text-[10px] text-muted-foreground">
                  {state === "done" ? "finished" : "running"}
                </span>
              </div>
              <div className="mt-1 flex h-1.5 w-full overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full bg-success"
                  style={{ width: `${(passed / total) * 100}%` }}
                />
                <div
                  className="h-full bg-destructive"
                  style={{ width: `${(failed / total) * 100}%` }}
                />
                <div className="h-full flex-1" />
              </div>
              <p className="mt-1 truncate font-mono text-[10px] text-muted-foreground">
                {state === "done"
                  ? `${pct}% · all tests finished`
                  : "▸ test_rejects_login_without_password"}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** What an analysed failure looks like. */
function AnalysisShot() {
  return (
    <div className="sheen rounded-xl border border-border bg-card p-5 shadow-xs">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full bg-destructive-subtle px-2.5 py-0.5 text-[10px] font-semibold text-destructive">
          failed
        </span>
        <span className="text-[12px] font-semibold">test_signs_in</span>
        <span className="ml-auto rounded-full bg-warning-subtle px-2.5 py-0.5 text-[10px] font-semibold text-warning">
          Application bug
        </span>
      </div>

      <p className="mt-3 rounded-md bg-muted px-3 py-2 font-mono text-[10px] leading-relaxed text-muted-foreground">
        TimeoutError: Locator.click: Timeout 30000ms exceeded.
      </p>

      <dl className="mt-4 flex flex-col gap-3 text-[12px] leading-relaxed">
        <div>
          <dt className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
            Root cause
          </dt>
          <dd className="mt-0.5">
            The account is locked. After five failed attempts the app shows
            “Too many failed login attempts. Please try again after 15 minutes.”
            and the submit button never re-enables.
          </dd>
        </div>
        <div>
          <dt className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
            Suggested fix
          </dt>
          <dd className="mt-0.5">
            Use a dedicated test account per run, or reset the lockout counter
            in setup.
          </dd>
        </div>
      </dl>

      <div className="mt-4 flex items-center gap-3 border-t border-border pt-3">
        <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
          Confidence
        </span>
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-primary/15">
          <div className="h-full w-[86%] rounded-full bg-primary" />
        </div>
        <span className="text-[11px] font-bold">86%</span>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * Features
 * ------------------------------------------------------------------ */

function Features() {
  const features = [
    [<Crosshair key="a" />, "Ranked, counted selectors", "Up to eight ways to find each element, best first — and each one counted against the live page, so an ambiguous selector never beats a unique one."],
    [<Layers key="b" />, "Page objects, not one long script", "Elements are grouped per page. A changed button is one property in one file, and every test that uses it is fixed at once."],
    [<Code2 key="c" />, "Real Playwright, on your disk", "A proper pytest project you can open in VS Code, edit and run yourself. AutoQA is not required to run what it produced."],
    [<Sparkles key="d" />, "The cases you would have written next", "From one happy path: the wrong password, the empty field, the 320-character email, the SQL payload and the XSS payload."],
    [<ShieldCheck key="e" />, "Security cases that belong to QA", "Injection and script payloads in the fields you already recorded, asserting the app rejects them. Not a penetration test — the checks a tester is expected to run."],
    [<Ban key="f" />, "No assertion, no test", "A generated case that asserts nothing is refused rather than written. A green tick that cannot fail is worse than no test at all."],
    [<Gauge key="g" />, "Genuinely parallel browsers", "One process each, started together. Three browsers cost about what one costs, which is the only way it keeps happening."],
    [<Timer key="h" />, "Watch mode", "Slowed down deliberately so you can follow what the test is doing. The fastest way to spot a wrong selector."],
    [<Camera key="i" />, "Evidence on every failure", "Screenshot, video and stack trace, attached to the test that produced them rather than dumped in a folder to match up later."],
    [<Bug key="j" />, "App bug or test bug", "Stated plainly on every failure, with a confidence score — and when it is unsure, it blames the test."],
    [<FileText key="k" />, "Reports you can email", "One self-contained HTML file per run with the screenshots embedded. It opens on any machine, years later, with nothing installed."],
    [<Users key="l" />, "Roles that match a QA team", "Manual QA, QA engineer, test manager and admin, so approving a suite and running one are different permissions."],
  ];

  return (
    <Section id="features" tinted>
      <Heading
        center
        title="Built for the way QA"
        accent="actually works"
        lead="Everything AutoQA does, and a couple of things it deliberately refuses to do."
      />
      <div className="mt-10 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {features.map(([icon, title, body]) => (
          <div
            key={title as string}
            className="sheen rounded-xl border border-border bg-card p-5 shadow-xs transition-all hover:border-primary/40 hover:shadow-md"
          >
            <span className="flex size-10 items-center justify-center rounded-xl bg-primary-subtle text-primary [&_svg]:size-5">
              {icon as React.ReactNode}
            </span>
            <h3 className="mt-4 text-base font-bold">{title as string}</h3>
            <p className="mt-2 text-[13px] leading-relaxed text-muted-foreground">
              {body as string}
            </p>
          </div>
        ))}
      </div>
    </Section>
  );
}

/* ------------------------------------------------------------------ *
 * Where the line is
 * ------------------------------------------------------------------ */

function TheLine() {
  const rows: [boolean, string][] = [
    [true, "AI proposes test cases — validated against real recorded elements before anything is written"],
    [true, "AI names tests and steps in language a human would use"],
    [true, "AI explains failures and drafts bug reports"],
    [false, "AI writes the Python you execute"],
    [false, "AI picks selectors"],
    [false, "AI decides whether a test passed"],
    [false, "AI is required for the product to work"],
  ];

  return (
    <Section>
      <Heading
        center
        title="Where AutoQA"
        accent="draws the line"
        lead="Plenty of tools put a language model in the middle of the thing that has to be reliable. This one deliberately does not."
      />
      <div className="mx-auto mt-10 grid max-w-3xl gap-2.5">
        {rows.map(([ok, text]) => (
          <div
            key={text}
            className="sheen flex items-start gap-3 rounded-xl border border-border bg-card px-5 py-3.5 shadow-xs"
          >
            <span
              className={
                ok
                  ? "mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-success-subtle text-success"
                  : "mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-destructive-subtle text-destructive"
              }
            >
              {ok ? <Check className="size-3" /> : <X className="size-3" />}
            </span>
            <span className="text-[14px] leading-relaxed">{text}</span>
          </div>
        ))}
      </div>
      <p className="mx-auto mt-6 max-w-2xl text-center text-[13px] leading-relaxed text-muted-foreground">
        If the AI call fails, is rate-limited, or you never add a key at all,
        you still get working tests. That is the whole reason the code generator
        is ordinary deterministic code.
      </p>
    </Section>
  );
}

/* ------------------------------------------------------------------ *
 * Pricing
 * ------------------------------------------------------------------ */

function Pricing() {
  return (
    <Section id="pricing" tinted>
      <Heading
        center
        title="There is no licence fee."
        accent="There is no billing at all."
        lead="AutoQA runs on your own machine. The only money involved is what you spend on your own AI key, and only if you switch the AI features on."
      />

      <div className="mx-auto mt-10 grid max-w-4xl gap-5 md:grid-cols-2">
        <div className="sheen flex flex-col rounded-xl border-2 border-primary bg-card p-7 shadow-md">
          <h3 className="text-xl font-extrabold">AutoQA itself</h3>
          <p className="mt-1 text-[13px] text-muted-foreground">
            Everything except the AI features.
          </p>
          <p className="mt-5 text-5xl font-extrabold tracking-tight">Free</p>
          <p className="mt-1.5 text-[13px] text-muted-foreground">
            No account limits, no seat count, no expiry.
          </p>
          <ul className="mt-6 flex flex-col gap-2.5 text-[14px]">
            {[
              "Unlimited recordings and projects",
              "Playwright test generation",
              "Chromium, Firefox and WebKit runs",
              "Screenshots, video and traces",
              "HTML reports",
              "Team roles and permissions",
            ].map((item) => (
              <li key={item} className="flex items-start gap-2.5">
                <Check className="mt-0.5 size-4 shrink-0 text-success" />
                {item}
              </li>
            ))}
          </ul>
        </div>

        <div className="sheen flex flex-col rounded-xl border border-border bg-card p-7 shadow-xs">
          <h3 className="text-xl font-extrabold">AI features</h3>
          <p className="mt-1 text-[13px] text-muted-foreground">
            Test generation, failure analysis, bug drafting.
          </p>
          <p className="mt-5 text-5xl font-extrabold tracking-tight">Your key</p>
          <p className="mt-1.5 text-[13px] text-muted-foreground">
            Billed to you by Google, at their rates. AutoQA takes no cut and
            adds no markup.
          </p>
          <ul className="mt-6 flex flex-col gap-2.5 text-[14px]">
            {[
              "Paste a Gemini key in settings",
              "Cost and tokens recorded per call",
              "Under $0.03 to generate a full suite",
              "Works on Google's free tier",
              "Turn it off and everything else still works",
            ].map((item) => (
              <li key={item} className="flex items-start gap-2.5">
                <Check className="mt-0.5 size-4 shrink-0 text-success" />
                {item}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </Section>
  );
}

/* ------------------------------------------------------------------ *
 * FAQ
 * ------------------------------------------------------------------ */

function Faq() {
  const faqs: [string, string][] = [
    [
      "Do I need to know how to code?",
      "No. Recording is using your own application normally, and the tests are written for you. If you do read Python, the output is ordinary Playwright you can edit — but nothing requires you to.",
    ],
    [
      "Do I have to change my application first?",
      "No. There is nothing to install in your app and no data-testid attributes you have to add. AutoQA will use test ids if it finds them, because they make the most durable selectors, but it works fine without any.",
    ],
    [
      "Does AI write the code that runs?",
      "No. The conversion from a recorded action to a Playwright call is done by ordinary deterministic code, so the same recording always produces the same test. AI proposes extra cases, improves naming, and explains failures.",
    ],
    [
      "What happens if I do not add an API key?",
      "Recording, code generation, cross-browser execution, artifacts and reports all work exactly as normal. You lose AI-proposed test cases, failure analysis and bug drafting.",
    ],
    [
      "What happens when the UI changes and a test breaks?",
      "Elements live in page objects, so a changed button is one property in one file rather than an edit in every test. AutoQA also kept the alternative selectors it recorded for that element, so there is somewhere to go.",
    ],
    [
      "Can I share results with someone who does not use AutoQA?",
      "Each run produces a single self-contained HTML file with the screenshots embedded. Email it — it opens on any machine with nothing installed.",
    ],
    [
      "Is my application's data sent anywhere?",
      "Only if you enable the AI features, and then only what the task needs — element names, test names, error messages and traces — sent to Google under your own key. With AI off, nothing leaves your machine.",
    ],
    [
      "Is it ready for a production regression suite?",
      "It is young, and honest about that. The deterministic half — recorder, generator, runner — is the part to judge first. Record one flow, read what comes out, and decide from that rather than from this page.",
    ],
  ];

  return (
    <Section id="faq">
      <Heading center title="Questions people" accent="actually ask" />
      <div className="mx-auto mt-10 flex max-w-3xl flex-col gap-3">
        {faqs.map(([question, answer]) => (
          <details
            key={question}
            className="sheen group rounded-xl border border-border bg-card px-5 shadow-xs transition-colors open:border-primary/40"
          >
            <summary className="flex cursor-pointer list-none items-center gap-4 py-4 text-[15px] font-semibold [&::-webkit-details-marker]:hidden">
              {question}
              <ChevronDown className="ml-auto size-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" />
            </summary>
            <p className="pb-4 text-[14px] leading-relaxed text-muted-foreground">
              {answer}
            </p>
          </details>
        ))}
      </div>
    </Section>
  );
}

/* ------------------------------------------------------------------ *
 * Closing
 * ------------------------------------------------------------------ */

function Closing() {
  return (
    <section className="border-y border-border bg-card">
      <div className="mx-auto max-w-4xl px-5 py-20 text-center sm:px-8">
        <h2 className="text-3xl font-extrabold tracking-tight sm:text-4xl">
          Record your first test in a minute
        </h2>
        <p className="mx-auto mt-4 max-w-xl text-base leading-relaxed text-muted-foreground">
          Add the application you want to test, press record, and use it. The
          test is written by the time you stop.
        </p>
        <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
          <AuthCta size="lg" />
        </div>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer>
      <div className="mx-auto max-w-6xl px-5 py-12 sm:px-8">
        <div className="flex flex-wrap items-center gap-4">
          <a href="#top" className="flex items-center gap-2.5">
            <span className="brand-gradient flex size-8 items-center justify-center rounded-xl text-white">
              <Radar className="size-[17px]" />
            </span>
            <span className="text-[15px] font-bold tracking-tight">AutoQA</span>
          </a>

          <nav className="flex flex-wrap items-center gap-x-5 gap-y-2 text-[13px] text-muted-foreground">
            {SECTIONS.map(([label, href]) => (
              <a key={href} href={href} className="hover:text-foreground">
                {label}
              </a>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-2">
            <AuthCta size="sm" />
          </div>
        </div>

        <p className="mt-8 border-t border-border pt-6 text-[13px] text-muted-foreground">
          AutoQA — AI-powered test automation. Runs on your own machine.
        </p>
      </div>
    </footer>
  );
}

/* ------------------------------------------------------------------ *
 * Small shared pieces
 * ------------------------------------------------------------------ */

function Badge({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-primary/20 bg-card px-3.5 py-1.5 text-[13px] font-medium text-primary shadow-xs">
      {children}
    </span>
  );
}

function Section({
  id,
  tinted = false,
  children,
}: {
  id?: string;
  tinted?: boolean;
  children: React.ReactNode;
}) {
  return (
    <section
      id={id}
      className={
        tinted
          ? "scroll-mt-16 border-y border-border bg-card"
          : "scroll-mt-16"
      }
    >
      <div className="mx-auto max-w-6xl px-5 py-16 sm:px-8 sm:py-20">
        {children}
      </div>
    </section>
  );
}

function Heading({
  title,
  accent,
  lead,
  center = false,
}: {
  title: string;
  accent?: string;
  lead?: string;
  center?: boolean;
}) {
  return (
    <div className={center ? "mx-auto max-w-2xl text-center" : "max-w-2xl"}>
      <h2 className="text-3xl font-extrabold tracking-tight sm:text-4xl">
        {title} {accent && <span className="text-primary">{accent}</span>}
      </h2>
      {lead && (
        <p className="mt-4 text-base leading-relaxed text-muted-foreground">
          {lead}
        </p>
      )}
    </div>
  );
}

function Split({
  eyebrow,
  title,
  children,
  aside,
  flip = false,
}: {
  eyebrow: string;
  title: string;
  children: React.ReactNode;
  aside: React.ReactNode;
  flip?: boolean;
}) {
  return (
    <div className="grid items-center gap-8 py-10 md:grid-cols-2 md:gap-14">
      <div className={flip ? "md:order-2" : undefined}>
        <p className="text-[11px] font-semibold uppercase tracking-wide text-primary">
          {eyebrow}
        </p>
        <h3 className="mt-2 text-2xl font-extrabold tracking-tight">{title}</h3>
        <div className="mt-3 flex flex-col gap-3 text-[15px] leading-relaxed text-muted-foreground">
          {children}
        </div>
      </div>
      <div className={flip ? "md:order-1" : undefined}>{aside}</div>
    </div>
  );
}

function CodePanel({ label, code }: { label: string; code: string }) {
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-[#0d1b2f] p-5 shadow-sm">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
        {label}
      </p>
      <pre className="mt-3 overflow-x-auto font-mono text-[12px] leading-relaxed text-slate-200">
        <code>{code}</code>
      </pre>
    </div>
  );
}
