"use client";

/** Features, grouped by the job they do rather than by the part of the codebase
 *  they live in. Anchors match the nav dropdown (#ai, #analysis). */

import {
  Ban,
  Bug,
  Camera,
  Code2,
  Crosshair,
  FileText,
  FlaskConical,
  Gauge,
  Github,
  KeyRound,
  Layers,
  ListChecks,
  Radar,
  ShieldCheck,
  Sparkles,
  SquareStack,
  Timer,
  Users,
  Video,
} from "lucide-react";
import {
  CtaBand,
  FeatureCard,
  MarketingShell,
  PageHero,
  Section,
} from "@/components/marketing/shell";

const GROUPS: {
  id?: string;
  title: string;
  accent: string;
  lead: string;
  tinted?: boolean;
  features: { icon: React.ReactNode; title: string; body: string }[];
}[] = [
  {
    id: "recording",
    title: "Recording and",
    accent: "code generation",
    lead: "The half of the product with no AI in it at all. It is deterministic on purpose: the same recording produces the same test, every time, forever.",
    tinted: true,
    features: [
      {
        icon: <Video />,
        title: "Zero-setup recorder",
        body: "A browser opens with the recorder already injected. Nothing to install in your application, no attributes to add first, no extension to approve.",
      },
      {
        icon: <Crosshair />,
        title: "Ranked, counted selectors",
        body: "Up to eight ways to find each element, best first — and each one is counted against the live page, so a selector that matches three elements never wins over one that matches exactly one.",
      },
      {
        icon: <Layers />,
        title: "Page objects, not one long script",
        body: "Elements are grouped into a page object per page. When the login form changes, you edit one property in one file rather than every test that logs in.",
      },
      {
        icon: <Code2 />,
        title: "Real Playwright, on your disk",
        body: "A proper pytest project: tests, page objects, conftest and pytest.ini. Open it in VS Code, edit it, run it with pytest. AutoQA is not required to use what it produced.",
      },
      {
        icon: <ListChecks />,
        title: "Readable steps beside the code",
        body: "Every test carries its human-readable steps, so a manual tester can review what it does without reading Python.",
      },
      {
        icon: <Ban />,
        title: "No assertion, no test",
        body: "A generated case that asserts nothing is refused rather than written. A test that cannot fail is worse than no test — it is a green tick that means nothing.",
      },
    ],
  },
  {
    id: "ai",
    title: "AI test",
    accent: "generation",
    lead: "You record the happy path. AutoQA proposes the cases a thorough tester would write next — and validates every one of them against the elements that were actually recorded before writing a line.",
    features: [
      {
        icon: <Sparkles />,
        title: "Five kinds of case",
        body: "Positive, negative, edge, regression and security. From one login recording that is the wrong password, the empty field, the 320-character email, the SQL payload and the XSS payload.",
      },
      {
        icon: <ShieldCheck />,
        title: "Security cases that belong to QA",
        body: "Injection and script payloads in the fields you already recorded, asserting the application rejects them. Not a penetration test — the checks a tester is expected to run.",
      },
      {
        icon: <FlaskConical />,
        title: "Validated, then generated",
        body: "A proposed case referring to a field that does not exist is rejected outright. Nothing reaches your suite that was invented rather than observed.",
      },
      {
        icon: <SquareStack />,
        title: "Priority and category on every case",
        body: "Each case arrives tagged, so you can run the critical ones on every commit and the long tail nightly.",
      },
      {
        icon: <KeyRound />,
        title: "Your key, your bill",
        body: "AI features use a Gemini key you supply. Cost and token count are recorded per call, so you can see exactly what a suite cost to generate.",
      },
      {
        icon: <Ban />,
        title: "Entirely optional",
        body: "No key, no AI — and everything else still works. Recording, generation and execution never depend on a model being reachable.",
      },
    ],
  },
  {
    id: "execution",
    title: "Running",
    accent: "your tests",
    lead: "Execution is where trust is won or lost. These are the things that decide whether a suite still gets run three months in.",
    tinted: true,
    features: [
      {
        icon: <Gauge />,
        title: "Genuinely parallel browsers",
        body: "Chromium, Firefox and WebKit in one process each, started together. Three browsers cost about what one costs.",
      },
      {
        icon: <Radar />,
        title: "Live progress, by name",
        body: "You see which test is running right now, not a spinner and a total at the end.",
      },
      {
        icon: <Timer />,
        title: "Watch mode",
        body: "Slowed down deliberately so you can follow what the test is doing. Useful the first time you run something, and the fastest way to spot a wrong selector.",
      },
      {
        icon: <Ban />,
        title: "Stop means stop",
        body: "Cancelling kills the process tree. It does not leave a browser running, and it does not fabricate errors for the tests that never got to run.",
      },
      {
        icon: <Camera />,
        title: "Evidence on every failure",
        body: "Screenshot, video and stack trace, attached to the test that produced them rather than dumped in a folder for you to match up.",
      },
      {
        icon: <Users />,
        title: "Roles that match a QA team",
        body: "Manual QA, QA engineer, test manager and admin — so approving a suite and running one are different permissions.",
      },
    ],
  },
  {
    id: "analysis",
    title: "Failure analysis",
    accent: "and reporting",
    lead: "A red test tells you something is wrong. These features tell you what, and hand you something you can send to a developer.",
    features: [
      {
        icon: <Bug />,
        title: "Root cause, not just the error",
        body: "The stack trace says the click timed out. The analysis says the account was locked after five failed attempts — which is what you actually needed to know.",
      },
      {
        icon: <ShieldCheck />,
        title: "App bug or test bug",
        body: "Stated plainly on every failure, with a confidence score. When it is uncertain it blames the test, because accusing a team's product on a guess is how a tool loses its audience.",
      },
      {
        icon: <FileText />,
        title: "Drafted bug reports",
        body: "Title, description, reproduction steps, severity and priority, generated from the failure and the analysis. Edit and send.",
      },
      {
        icon: <Github />,
        title: "Self-contained HTML reports",
        body: "One file per run with the screenshots embedded. It opens on any machine, years later, with nothing installed and no server running.",
      },
    ],
  },
];

export default function FeaturesPage() {
  return (
    <MarketingShell>
      <PageHero badge="Top features" title="Everything AutoQA does," accent="and what it refuses to do">
        Grouped by the job it does for you. The refusals are listed alongside
        the features on purpose — what a testing tool declines to guess at is
        as important as what it automates.
      </PageHero>

      {GROUPS.map((group) => (
        <Section
          key={group.title}
          id={group.id}
          tinted={group.tinted}
          title={group.title}
          accent={group.accent}
          lead={group.lead}
        >
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {group.features.map((feature) => (
              <FeatureCard
                key={feature.title}
                icon={feature.icon}
                title={feature.title}
              >
                {feature.body}
              </FeatureCard>
            ))}
          </div>
        </Section>
      ))}

      <CtaBand title="Try it against something real">
        Record one flow on your own application. Everything above either shows
        up in the output or it does not.
      </CtaBand>
    </MarketingShell>
  );
}
