"use client";

/** How it works — the real pipeline, stage by stage.
 *
 *  The home page gives four sentences. This page is for the person deciding
 *  whether to trust it with their regression suite, so it says what is actually
 *  generated, what the AI does and does not touch, and where the files land.
 */

import {
  Bug,
  FileText,
  MonitorPlay,
  Video,
} from "lucide-react";
import {
  CodePanel,
  CtaBand,
  FactList,
  MarketingShell,
  PageHero,
  Section,
  SplitRow,
} from "@/components/marketing/shell";

export default function HowItWorksPage() {
  return (
    <MarketingShell>
      <PageHero badge="How does it all work?" title="From a click-through" accent="to a running suite">
        Four stages. Only one of them involves AI, and it is not the one that
        writes the code you run.
      </PageHero>

      <Section tinted>
        <div className="divide-y divide-border">
          <SplitRow
            eyebrow="Stage 1 — Record"
            title="You use the site. Nothing else."
            aside={
              <FactList
                label="Captured per action"
                items={[
                  ["Actions understood", "click, type, select, check, navigate"],
                  ["Selectors kept per element", "up to 8, ranked"],
                  ["Frames", "followed, including iframes"],
                  ["Setup required on your app", "none"],
                ]}
              />
            }
          >
            <p>
              Enter a URL and a browser opens with the recorder already running.
              Log in, fill the form, click through the flow — whatever the test
              should cover. There is nothing to install in your application and
              no attribute you have to add first.
            </p>
            <p>
              Each element you touch is recorded several ways at once — test id,
              role and accessible name, label, placeholder, id, text, CSS —
              along with how many elements on the page each of those actually
              matches. That count is what stops the generated test from picking
              a selector that looks elegant and matches three things.
            </p>
          </SplitRow>

          <SplitRow
            flip
            eyebrow="Stage 2 — Generate"
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
              free, and identically every time — so that is what does it. No
              model is involved in producing the code that runs.
            </p>
            <p>
              You get a real project: a test module, a page object per page,
              a <code className="rounded bg-muted px-1 py-0.5 font-mono text-[12px]">conftest.py</code>{" "}
              and a{" "}
              <code className="rounded bg-muted px-1 py-0.5 font-mono text-[12px]">pytest.ini</code>.
              It is written to a folder you own and it runs with plain{" "}
              <code className="rounded bg-muted px-1 py-0.5 font-mono text-[12px]">pytest</code>,
              with or without AutoQA.
            </p>
          </SplitRow>

          <SplitRow
            eyebrow="Stage 3 — Run"
            title="Three browsers, one wait"
            aside={
              <FactList
                label="Execution"
                items={[
                  ["Browsers", "Chromium, Firefox, WebKit"],
                  ["Parallelism", "one process each, started together"],
                  ["On failure", "screenshot, video, stack trace"],
                  ["Watch mode", "slowed down so you can follow it"],
                  ["Stop", "cancels the process tree, immediately"],
                ]}
              />
            }
          >
            <p>
              Runs are launched one process per browser, all at the same time,
              so covering three browsers costs about what covering one does.
              That matters more than it sounds — cross-browser testing that
              triples the wait is cross-browser testing that quietly stops
              happening.
            </p>
            <p>
              You can watch it drive the browser at a readable speed, or let it
              run headless. Progress is streamed as it goes, including which
              test is running right now, and Stop actually stops — it kills the
              process tree rather than asking politely and marking the rest as
              errors.
            </p>
          </SplitRow>

          <SplitRow
            flip
            eyebrow="Stage 4 — Understand"
            title="A failure, explained"
            aside={
              <FactList
                label="Per failure"
                items={[
                  ["Root cause", "in plain language"],
                  ["Suggested fix", "concrete, on the failing line"],
                  ["Category", "application bug or test bug"],
                  ["Severity & priority", "assigned"],
                  ["Confidence", "stated, not implied"],
                  ["Bug report", "drafted, with repro steps"],
                ]}
              />
            }
          >
            <p>
              This is the stage that uses AI. It reads the error, the stack
              trace, the page state and how the same test behaved in the other
              browsers, then tells you what went wrong and what to do about it.
            </p>
            <p>
              Most usefully, it separates the two failures that look identical
              in a test report: your application is broken, or your test is. When
              it is not sure, it says so and defaults to blaming the test —
              telling a team their product is broken on a guess is a good way to
              get the tool switched off.
            </p>
          </SplitRow>
        </div>
      </Section>

      <Section
        center
        title="What AI does"
        accent="and does not do"
        lead="The distinction is the most important design decision in the product, so it is worth being blunt about."
      >
        <div className="grid gap-4 md:grid-cols-2">
          <div className="sheen rounded-xl border border-success/30 bg-card p-6 shadow-xs">
            <h3 className="text-base font-bold text-success">AI does</h3>
            <ul className="mt-3 flex flex-col gap-2.5 text-[13px] leading-relaxed text-muted-foreground">
              <li>Name tests and steps in language a human would use</li>
              <li>Propose extra cases around the flow you recorded</li>
              <li>Explain failures and draft bug reports</li>
              <li>Judge whether the app or the test is at fault</li>
            </ul>
          </div>
          <div className="sheen rounded-xl border border-border bg-card p-6 shadow-xs">
            <h3 className="text-base font-bold">AI does not</h3>
            <ul className="mt-3 flex flex-col gap-2.5 text-[13px] leading-relaxed text-muted-foreground">
              <li>Write the Python that gets executed</li>
              <li>Choose selectors</li>
              <li>Decide whether a test passed or failed</li>
              <li>Run at all, unless you add a key</li>
            </ul>
          </div>
        </div>
        <p className="mx-auto mt-6 max-w-2xl text-center text-[13px] leading-relaxed text-muted-foreground">
          Proposed cases are checked against the elements that were actually
          recorded before anything is written. A case referring to a field that
          does not exist is rejected rather than generated and left to fail
          later, and a case with no assertion is rejected too — a test that
          cannot fail is worse than no test.
        </p>
      </Section>

      <Section tinted center title="Where things end up">
        <div className="mx-auto grid max-w-4xl gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[
            { icon: <Video />, label: "Recordings", body: "Stored per project, replayable and editable before you generate." },
            { icon: <FileText />, label: "Generated project", body: "A folder on disk: tests, page objects, conftest, pytest.ini." },
            { icon: <MonitorPlay />, label: "Run artifacts", body: "Screenshots, video and traces, attributed to the test that produced them." },
            { icon: <Bug />, label: "Analyses & bugs", body: "Saved against the failure, so the history survives the next run." },
          ].map((item) => (
            <div key={item.label} className="sheen rounded-xl border border-border bg-card p-5 text-left shadow-xs">
              <span className="flex size-10 items-center justify-center rounded-xl bg-primary-subtle text-primary [&_svg]:size-5">
                {item.icon}
              </span>
              <h3 className="mt-4 text-[15px] font-bold">{item.label}</h3>
              <p className="mt-1.5 text-[13px] leading-relaxed text-muted-foreground">
                {item.body}
              </p>
            </div>
          ))}
        </div>
      </Section>

      <CtaBand title="See it on your own application">
        The fastest way to judge any of this is to record one flow and look at
        what comes out.
      </CtaBand>
    </MarketingShell>
  );
}
