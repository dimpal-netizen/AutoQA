"use client";

/** The home page.
 *
 *  Every claim on it is something the product actually does — the numbers come
 *  from the real pipeline, and the sample code is what the generator really
 *  emits. A landing page that overstates gets found out on day one, and this
 *  one is read by the people who will use it that day.
 */

import Link from "next/link";
import {
  ArrowRight,
  Bug,
  Check,
  FileText,
  Gauge,
  MonitorPlay,
  ShieldCheck,
  Sparkles,
  Video,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Badge,
  CodePanel,
  CtaBand,
  FeatureCard,
  MarketingShell,
  Section,
} from "@/components/marketing/shell";

export function Marketing() {
  return (
    <MarketingShell>
      <Hero />
      <Proof />
      <HowItWorks />
      <Features />
      <CtaBand title="Record your first test in a minute">
        Add the application you want to test, press record, and use it. The test
        is written by the time you stop.
      </CtaBand>
      <Assurances />
    </MarketingShell>
  );
}

function Hero() {
  return (
    <section className="relative overflow-hidden">
      {/* The soft blue wash behind the fold, and only there. It has to reach
          transparent before the section ends — a gradient that is still tinted
          where the next section starts reads as a seam, not as light. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-10"
        style={{
          background:
            "linear-gradient(180deg, var(--primary-subtle) 0%, transparent 100%)",
        }}
      />

      <div className="mx-auto max-w-4xl px-5 pb-16 pt-16 text-center sm:px-8 sm:pt-24">
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
          <Link href="/register">
            <Button size="lg">
              Get started
              <ArrowRight />
            </Button>
          </Link>
          <Link href="/how-it-works">
            <Button size="lg" variant="outline">
              See how it works
            </Button>
          </Link>
        </div>

        <p className="mt-4 text-[13px] text-muted-foreground">
          Runs on your machine. No API key needed to record, generate or run.
        </p>
      </div>

      <CodeSample />
    </section>
  );
}

/** The generated output, shown rather than described. It is the claim that
 *  needs evidence most — "no code" reads as "no real code" until you see it. */
function CodeSample() {
  return (
    <div className="mx-auto max-w-4xl px-5 pb-16 sm:px-8">
      <div className="grid gap-4 md:grid-cols-2">
        <div className="sheen rounded-xl border border-border bg-card p-5 shadow-xs">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            What you did
          </p>
          <ol className="mt-3 flex flex-col gap-2 text-[13px]">
            {[
              "Opened the login page",
              'Typed into "Email"',
              'Typed into "Password"',
              'Clicked "Login"',
            ].map((step, i) => (
              <li key={step} className="flex items-start gap-2.5">
                <span className="mt-px flex size-5 shrink-0 items-center justify-center rounded-full bg-primary-subtle text-[10px] font-bold text-primary">
                  {i + 1}
                </span>
                {step}
              </li>
            ))}
          </ol>
        </div>

        <CodePanel
          label="What AutoQA wrote"
          code={`def test_signs_in(page: Page) -> None:
    login = LoginPage(page)

    page.goto(BASE_URL + '/login')
    login.email_input.fill('sharon@acme.io')
    login.password_input.fill('••••••••')
    login.login_button.click()

    expect(page).to_have_url(DASHBOARD)`}
        />
      </div>
    </div>
  );
}

function Proof() {
  const items = [
    { value: "3", label: "Browsers, in parallel" },
    { value: "13", label: "Tests from one recording" },
    { value: "< $0.03", label: "To generate a full suite" },
    { value: "0", label: "Lines of code to write" },
  ];

  return (
    <div className="border-y border-border bg-card">
      <div className="mx-auto grid max-w-6xl gap-6 px-5 py-12 sm:grid-cols-2 sm:px-8 lg:grid-cols-4">
        {items.map((item) => (
          <div key={item.label} className="text-center">
            <p className="text-4xl font-extrabold tracking-tight text-primary">
              {item.value}
            </p>
            <p className="mt-1 text-[13px] text-muted-foreground">{item.label}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function HowItWorks() {
  const steps = [
    {
      icon: <Video />,
      title: "Record",
      body: "Enter a URL. A browser opens with the recorder running — use the site normally and every click, keystroke and selection is captured.",
    },
    {
      icon: <FileText />,
      title: "Generate",
      body: "Stop recording and the Playwright test is already written: page objects, fallback selectors, readable steps. Saved to disk for VS Code.",
    },
    {
      icon: <MonitorPlay />,
      title: "Run",
      body: "Chrome, Firefox and Safari at the same time. Watch it drive the browser, or let it run headless. Screenshots and video on every failure.",
    },
    {
      icon: <Bug />,
      title: "Understand",
      body: "AI reads the error, the trace and the other browsers, then tells you whether your app is broken or your test is — and drafts the bug report.",
    },
  ];

  return (
    <Section
      title="Four steps, and you write"
      accent="none of them"
      lead="The part that runs is ordinary Python, generated by ordinary code — so the same recording gives the same test every time. AI improves the naming and explains failures; it never sits in the path of your tests working."
    >
      <ol className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {steps.map((step, index) => (
          <li key={step.title}>
            <div className="sheen h-full rounded-xl border border-border bg-card p-5 shadow-xs transition-all hover:border-primary/40 hover:shadow-md">
              <span className="flex size-10 items-center justify-center rounded-xl bg-primary-subtle text-primary [&_svg]:size-5">
                {step.icon}
              </span>
              <p className="mt-4 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                Step {index + 1}
              </p>
              <h3 className="mt-1 text-lg font-bold">{step.title}</h3>
              <p className="mt-2 text-[13px] leading-relaxed text-muted-foreground">
                {step.body}
              </p>
            </div>
          </li>
        ))}
      </ol>

      <div className="mt-8">
        <Link href="/how-it-works">
          <Button variant="outline">
            The whole pipeline, in detail
            <ArrowRight />
          </Button>
        </Link>
      </div>
    </Section>
  );
}

function Features() {
  const features = [
    {
      icon: <ShieldCheck />,
      title: "Tests that survive a redesign",
      body: "Every element is recorded several ways, best first, and the alternatives are kept. When a selector breaks, the fix is one line in one file — not a hunt through every test.",
    },
    {
      icon: <Sparkles />,
      title: "The cases you would have written next",
      body: "From one happy path, AutoQA adds the negative, edge and security cases around it — wrong password, empty field, 320-character email, SQL and XSS payloads.",
    },
    {
      icon: <Gauge />,
      title: "Cross-browser, genuinely parallel",
      body: "One process per browser, all started together. Testing on three browsers takes about as long as testing on one, which is the only way it keeps happening.",
    },
    {
      icon: <Bug />,
      title: "Failures explained, not just reported",
      body: "Root cause, suggested fix, severity and a confidence score — and it says plainly whether the application is at fault or the test is.",
    },
    {
      icon: <FileText />,
      title: "Reports you can email",
      body: "One self-contained HTML file per run, screenshots embedded. It opens on any machine, years later, with nothing installed.",
    },
    {
      icon: <MonitorPlay />,
      title: "Yours to edit",
      body: "The generated Playwright project is written to a folder you own. Open it in VS Code, change anything, run it with pytest. No lock-in and no black box.",
    },
  ];

  return (
    <Section
      tinted
      title="Built for the way QA"
      accent="actually works"
      lead="Recorded tests have a reputation for breaking the first time anyone touches the UI. Most of this product is the answer to that."
    >
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {features.map((feature) => (
          <FeatureCard key={feature.title} icon={feature.icon} title={feature.title}>
            {feature.body}
          </FeatureCard>
        ))}
      </div>

      <div className="mt-8">
        <Link href="/features">
          <Button variant="outline">
            All features
            <ArrowRight />
          </Button>
        </Link>
      </div>
    </Section>
  );
}

function Assurances() {
  return (
    <ul className="mx-auto -mt-12 mb-16 flex max-w-lg flex-wrap items-center justify-center gap-x-6 gap-y-2 px-5 text-[13px] text-muted-foreground">
      {["No credit card", "Runs on your machine", "AI features optional"].map(
        (item) => (
          <li key={item} className="flex items-center gap-1.5">
            <Check className="size-3.5 text-success" />
            {item}
          </li>
        ),
      )}
    </ul>
  );
}
