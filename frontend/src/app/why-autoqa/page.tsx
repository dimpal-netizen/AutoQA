"use client";

/** Why AutoQA — the argument, not the feature list.
 *
 *  testRigor's equivalent page leans on customer quotes. AutoQA has no
 *  customers to quote, and inventing them would be the single fastest way to
 *  destroy the credibility of everything else on the site. So this page argues
 *  from the problem instead, which is the honest version of the same page.
 */

import { ArrowRight, Check, X } from "lucide-react";
import {
  CodePanel,
  CtaBand,
  FactList,
  MarketingShell,
  PageHero,
  Section,
  SplitRow,
} from "@/components/marketing/shell";

export default function WhyAutoQAPage() {
  return (
    <MarketingShell>
      <PageHero badge="Why AutoQA" title="Recorded tests have a reputation." accent="This one is built around it.">
        Almost everyone has tried a record-and-playback tool, and almost
        everyone has abandoned one. It is worth being specific about why, and
        about what is different here.
      </PageHero>

      <Section
        tinted
        center
        title="The three ways a recorded suite"
        accent="dies"
        lead="Not one of these is a hypothetical. They are the reason teams say “we tried that and went back to writing tests by hand.”"
      >
        <div className="grid gap-4 md:grid-cols-3">
          {[
            {
              n: "01",
              title: "The selectors were never any good",
              body: "A recorder that grabs the first CSS path it finds produces tests that break on the next redesign — sometimes on the next deploy. The suite goes red, nobody trusts it, and within a month nobody runs it.",
            },
            {
              n: "02",
              title: "You get a script, not a project",
              body: "One enormous linear file with the same selector pasted into forty places. Fixing one changed button means forty edits, so nobody fixes it, so the suite stays red.",
            },
            {
              n: "03",
              title: "Red tells you nothing",
              body: "A timeout and a stack trace. Is the app broken or is the test wrong? Answering that by hand, per failure, costs more than the automation saved.",
            },
          ].map((item) => (
            <div
              key={item.n}
              className="sheen rounded-xl border border-border bg-card p-6 text-left shadow-xs"
            >
              <span className="text-3xl font-extrabold tracking-tight text-destructive/70">
                {item.n}
              </span>
              <h3 className="mt-3 text-base font-bold">{item.title}</h3>
              <p className="mt-2 text-[13px] leading-relaxed text-muted-foreground">
                {item.body}
              </p>
            </div>
          ))}
        </div>
      </Section>

      <Section title="What we did" accent="about each one">
        <div className="divide-y divide-border">
          <SplitRow
            eyebrow="Answer to 01"
            title="Selectors are ranked, and counted"
            aside={
              <CodePanel
                label="Recorded for one button"
                code={`[
  { "strategy": "test_id",  "value": "login-btn",
    "matches": 1, "score": 100 },
  { "strategy": "role_name", "value": "button|Login",
    "matches": 1, "score": 95 },
  { "strategy": "text", "value": "Login",
    "matches": 3, "score": 70 },
  { "strategy": "css", "value": "form > button",
    "matches": 1, "score": 40 }
]

# chosen: test_id — unique, highest rank`}
              />
            }
          >
            <p>
              Every element is captured up to eight ways, and each candidate is
              counted against the live page as it is recorded. A selector that
              matches three elements loses to one that matches exactly one, even
              if the ambiguous one is the prettier strategy.
            </p>
            <p>
              The alternatives are kept, not discarded. When the winner
              eventually breaks, the fallbacks are already on hand — which is
              what makes a recorded test repairable rather than disposable.
            </p>
          </SplitRow>

          <SplitRow
            flip
            eyebrow="Answer to 02"
            title="You get a project you would have written"
            aside={
              <FactList
                label="Generated per recording"
                items={[
                  ["tests/", "one module per flow"],
                  ["pages/", "one page object per page"],
                  ["conftest.py", "fixtures and browser setup"],
                  ["pytest.ini", "markers, artifacts, config"],
                  ["Runs without AutoQA", "yes — plain pytest"],
                ]}
              />
            }
          >
            <p>
              Elements live in page objects, one per page. A changed button is
              one property in one file, and every test that uses it is fixed at
              once.
            </p>
            <p>
              It is written to a folder you own, in the layout a Playwright
              engineer would have chosen. If you stop using AutoQA tomorrow, the
              suite still runs — that is the point.
            </p>
          </SplitRow>

          <SplitRow
            eyebrow="Answer to 03"
            title="Red comes with an explanation"
            aside={
              <FactList
                label="On a failing test"
                items={[
                  ["Root cause", "in plain language"],
                  ["Verdict", "app bug or test bug"],
                  ["Confidence", "stated"],
                  ["Suggested fix", "on the failing line"],
                  ["Bug report", "drafted, with steps"],
                ]}
              />
            }
          >
            <p>
              The trace says the click timed out after thirty seconds. The
              analysis says the account was locked after five failed login
              attempts and will unlock in fifteen minutes. One of those is
              actionable.
            </p>
            <p>
              And it commits to a verdict — your application, or your test.
              When it cannot tell, it says so and blames the test, because
              telling a team their product is broken on a guess is how a tool
              gets switched off.
            </p>
          </SplitRow>
        </div>
      </Section>

      <Section
        tinted
        center
        title="Where AutoQA"
        accent="draws the line"
        lead="Plenty of tools put a language model in the middle of the thing that has to be reliable. This one deliberately does not."
      >
        <div className="mx-auto grid max-w-3xl gap-3">
          {[
            [true, "AI proposes test cases — validated against real recorded elements before anything is written"],
            [true, "AI names tests and explains failures"],
            [false, "AI writes the Python you execute"],
            [false, "AI picks selectors"],
            [false, "AI decides whether a test passed"],
            [false, "AI is required for the product to work"],
          ].map(([ok, text]) => (
            <div
              key={text as string}
              className="sheen flex items-start gap-3 rounded-xl border border-border bg-card px-5 py-3.5 text-left shadow-xs"
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
              <span className="text-[14px] leading-relaxed">{text as string}</span>
            </div>
          ))}
        </div>
        <p className="mx-auto mt-6 max-w-2xl text-center text-[13px] leading-relaxed text-muted-foreground">
          If the AI call fails, is rate-limited, or you never add a key at all,
          you still get working tests. That is the whole reason the code
          generator is ordinary deterministic code.
        </p>
      </Section>

      <Section center title="Honest about what this is not">
        <div className="mx-auto max-w-2xl text-left">
          <p className="text-[15px] leading-relaxed text-muted-foreground">
            AutoQA is young. There are no case studies on this site and no
            customer quotes, because there are no customers to quote yet — and a
            testing tool that fabricates its own evidence has no business asking
            you to trust its test results.
          </p>
          <p className="mt-4 text-[15px] leading-relaxed text-muted-foreground">
            What there is: a recorder that counts its selectors, a generator
            that produces a project you can read, parallel cross-browser
            execution, and failure analysis that commits to an answer. Record
            one flow and judge the output — it is a ten-minute test of every
            claim on this page.
          </p>
          <div className="mt-6 flex items-center gap-2 text-[13px] font-semibold text-primary">
            <a href="/how-it-works" className="inline-flex items-center gap-1.5 hover:underline">
              See exactly what happens at each stage
              <ArrowRight className="size-3.5" />
            </a>
          </div>
        </div>
      </Section>

      <CtaBand title="Ten minutes, one recording">
        The fastest way to settle whether any of this holds up is to point it at
        your own application.
      </CtaBand>
    </MarketingShell>
  );
}
