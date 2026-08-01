"use client";

/** FAQ.
 *
 *  Native <details>, not a JavaScript accordion. It is keyboard accessible and
 *  findable with the browser's own Ctrl-F for free, which a div-based accordion
 *  with hidden panels is not.
 */

import { ChevronDown } from "lucide-react";
import {
  CtaBand,
  MarketingShell,
  PageHero,
  Section,
} from "@/components/marketing/shell";

const FAQS: { group: string; items: [string, string][] }[] = [
  {
    group: "Getting started",
    items: [
      [
        "Do I need to know how to code?",
        "No. Recording is using your own application normally, and the tests are written for you. If you do read Python, the output is ordinary Playwright you can edit — but nothing requires you to.",
      ],
      [
        "Do I have to change my application first?",
        "No. There is nothing to install in your app and no data-testid attributes you have to add. AutoQA will use test ids if it finds them, because they make the most durable selectors, but it works fine without any.",
      ],
      [
        "How long does the first test take?",
        "About as long as it takes you to click through the flow once. Generation happens when you press stop.",
      ],
      [
        "Can I test a site behind a login?",
        "Yes — record the login as part of the flow, the way you would perform it. It becomes part of the generated test.",
      ],
    ],
  },
  {
    group: "The tests themselves",
    items: [
      [
        "What exactly gets generated?",
        "A pytest project: a test module per flow, a page object per page, a conftest.py and a pytest.ini. It is written to a folder on your disk in the layout a Playwright engineer would have used.",
      ],
      [
        "Can I edit the generated tests?",
        "Yes, and you are meant to. They are plain files. Open the folder in VS Code, change anything, run it with pytest. AutoQA is not required to run what it produced.",
      ],
      [
        "What happens when the UI changes and a test breaks?",
        "Elements live in page objects, so a changed button is one property in one file rather than an edit in every test. AutoQA also kept the alternative selectors it recorded for that element, so there is somewhere to go.",
      ],
      [
        "Will I get flaky tests?",
        "Generated tests wait for elements rather than sleeping, which removes the most common cause. The honest answer is that no tool eliminates flakiness on a slow or genuinely non-deterministic application — but a failure that only happens sometimes is visible in the run history rather than hidden.",
      ],
    ],
  },
  {
    group: "AI",
    items: [
      [
        "Does AI write the code that runs?",
        "No. The conversion from a recorded action to a Playwright call is done by ordinary deterministic code, so the same recording always produces the same test. AI proposes extra cases, improves naming, and explains failures.",
      ],
      [
        "What happens if I do not add an API key?",
        "Recording, code generation, cross-browser execution, artifacts and reports all work exactly as normal. You lose AI-proposed test cases, failure analysis and bug drafting.",
      ],
      [
        "Which model does it use?",
        "Gemini, with a key you supply. Cost and token count are recorded on every call, so the spend is visible rather than mysterious.",
      ],
      [
        "Could the AI invent a test for a field that does not exist?",
        "It could propose one; it cannot generate one. Every proposed case is validated against the elements actually captured during recording, and anything referring to something that was not there is rejected before code is written.",
      ],
      [
        "Is my application's data sent anywhere?",
        "Only if you enable the AI features, and then only the parts needed for the task — element names, test names, error messages and traces — sent to Google under your own key. With AI off, nothing leaves your machine.",
      ],
    ],
  },
  {
    group: "Running and results",
    items: [
      [
        "Which browsers are supported?",
        "Chromium, Firefox and WebKit — that is Chrome, Firefox and Safari's engines. They run as one process each, started together, so covering all three costs roughly what covering one does.",
      ],
      [
        "Can I watch the tests run?",
        "Yes. Watch mode drives the browser at a deliberately readable speed. It is the fastest way to spot a wrong selector, and worth using the first time you run anything.",
      ],
      [
        "What do I get when a test fails?",
        "A screenshot, a video, the stack trace, and — with AI on — the root cause, a suggested fix, a severity, a confidence score and a verdict on whether your application or your test is at fault.",
      ],
      [
        "Can I stop a run half way?",
        "Yes, and it genuinely stops: the process tree is killed, no browser is left running, and the tests that never got to run are not reported as errors.",
      ],
      [
        "Can I share the results with someone who does not use AutoQA?",
        "Each run produces a single self-contained HTML file with the screenshots embedded. Email it. It opens on any machine with nothing installed.",
      ],
    ],
  },
  {
    group: "Running it yourself",
    items: [
      [
        "Where does it run?",
        "On your own machine. Tests drive a real browser locally, and the data lives in a Postgres database you control.",
      ],
      [
        "What does it cost?",
        "Nothing for AutoQA itself. The only spend is your own AI key, if you use the AI features — typically under three cents to generate a full suite.",
      ],
      [
        "Is it ready for a production regression suite?",
        "It is young, and honest about that. The deterministic half — recorder, generator, runner — is the part to judge first. Record one flow, read what comes out, and decide from that rather than from this page.",
      ],
    ],
  },
];

export default function FaqPage() {
  return (
    <MarketingShell>
      <PageHero
        badge="FAQ"
        title="The questions people"
        accent="actually ask"
        cta={false}
      >
        Including the awkward ones about what AI is and is not doing, and what
        this product is not ready for yet.
      </PageHero>

      {FAQS.map((section, index) => (
        <Section
          key={section.group}
          center
          tinted={index % 2 === 0}
          title={section.group}
        >
          <div className="mx-auto flex max-w-3xl flex-col gap-3 text-left">
            {section.items.map(([question, answer]) => (
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
      ))}

      <CtaBand title="Still deciding?">
        Record one flow on your own application. It answers more of these than
        this page can.
      </CtaBand>
    </MarketingShell>
  );
}
