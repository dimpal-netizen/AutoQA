"use client";

/** Pricing.
 *
 *  AutoQA has no billing. Inventing three tiers with ticks and crosses would
 *  look like every other pricing page and would be a lie on a page whose entire
 *  job is to be believed, so this one says what it actually costs to run —
 *  which is nothing, plus whatever you spend on your own AI key.
 */

import { Check, Cpu, Server, Sparkles } from "lucide-react";
import {
  CtaBand,
  FactList,
  MarketingShell,
  PageHero,
  Section,
} from "@/components/marketing/shell";

export default function PricingPage() {
  return (
    <MarketingShell>
      <PageHero badge="Pricing" title="There is no licence fee." accent="There is no billing at all.">
        AutoQA runs on your own machine. The only money involved is what you
        spend on your own AI key, and only if you switch the AI features on.
      </PageHero>

      <Section tinted>
        <div className="mx-auto grid max-w-4xl gap-5 md:grid-cols-2">
          <div className="sheen flex flex-col rounded-xl border-2 border-primary bg-card p-7 shadow-md">
            <span className="flex size-11 items-center justify-center rounded-xl bg-primary-subtle text-primary">
              <Server className="size-5" />
            </span>
            <h3 className="mt-5 text-xl font-bold">AutoQA itself</h3>
            <p className="mt-1 text-[13px] text-muted-foreground">
              Everything except the AI features.
            </p>
            <p className="mt-5 text-4xl font-bold tracking-tight">Free</p>
            <p className="mt-1.5 text-[13px] text-muted-foreground">
              No account limits, no seat count, no expiry.
            </p>

            <ul className="mt-6 flex flex-col gap-2.5 text-[14px]">
              {[
                "Unlimited recordings and projects",
                "Playwright test generation",
                "Page objects, conftest, pytest.ini",
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
            <span className="flex size-11 items-center justify-center rounded-xl bg-primary-subtle text-primary">
              <Sparkles className="size-5" />
            </span>
            <h3 className="mt-5 text-xl font-bold">AI features</h3>
            <p className="mt-1 text-[13px] text-muted-foreground">
              Test generation, failure analysis, bug drafting.
            </p>
            <p className="mt-5 text-4xl font-bold tracking-tight">
              Your key
            </p>
            <p className="mt-1.5 text-[13px] text-muted-foreground">
              Billed to you by Google, at their rates. AutoQA takes no cut and
              adds no markup.
            </p>

            <ul className="mt-6 flex flex-col gap-2.5 text-[14px]">
              {[
                "Paste a Gemini key in settings",
                "Cost and tokens recorded per call",
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

      <Section
        center
        title="What the AI features"
        accent="actually cost"
        lead="Small enough that the interesting number is not the money. These are typical figures from real runs; your own totals are recorded per call so you never have to guess."
      >
        <div className="mx-auto max-w-2xl">
          <FactList
            label="Typical cost"
            items={[
              ["Generating a suite from one recording", "under $0.03"],
              ["Analysing one failure", "well under a cent"],
              ["Drafting one bug report", "well under a cent"],
              ["Recording, generating code, running tests", "$0.00 — no AI involved"],
            ]}
          />
          <p className="mt-6 text-center text-[13px] leading-relaxed text-muted-foreground">
            The deterministic half of the product — the recorder, the code
            generator and the test runner — never calls a model, so it costs
            nothing to run regardless of how large your suite gets.
          </p>
        </div>
      </Section>

      <Section tinted center title="What you need to run it">
        <div className="mx-auto grid max-w-4xl gap-4 sm:grid-cols-3">
          {[
            {
              icon: <Cpu />,
              title: "A machine",
              body: "Your laptop is fine. Tests run locally, which is also why there is nothing to pay for.",
            },
            {
              icon: <Server />,
              title: "Postgres",
              body: "One database for projects, recordings, runs and results.",
            },
            {
              icon: <Sparkles />,
              title: "A Gemini key, optionally",
              body: "Only for the AI features. Everything else works without one.",
            },
          ].map((item) => (
            <div
              key={item.title}
              className="sheen rounded-xl border border-border bg-card p-5 text-left shadow-xs"
            >
              <span className="flex size-10 items-center justify-center rounded-xl bg-primary-subtle text-primary [&_svg]:size-5">
                {item.icon}
              </span>
              <h3 className="mt-4 text-[15px] font-bold">{item.title}</h3>
              <p className="mt-1.5 text-[13px] leading-relaxed text-muted-foreground">
                {item.body}
              </p>
            </div>
          ))}
        </div>
      </Section>

      <CtaBand title="Nothing to sign up for but an account">
        No card, no trial period, no quota. Create an account and record
        something.
      </CtaBand>
    </MarketingShell>
  );
}
