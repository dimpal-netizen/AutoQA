"use client";

/** The public site: navigation, footer, and the section primitives every info
 *  page is built from.
 *
 *  One shell for all of them, so the pages differ in content and never in
 *  chrome. The primitives below are deliberately few — a hero, a band, a split
 *  row, a card, a CTA — because a marketing site with fifteen bespoke section
 *  layouts is one nobody can add a page to later.
 */

import { useState } from "react";
import Link from "next/link";
import { ArrowRight, ChevronDown, Radar } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** Navigation, grouped the way the site is. Groups with one entry are links. */
const NAV: {
  label: string;
  href?: string;
  items?: { label: string; href: string; hint: string }[];
}[] = [
  { label: "Why AutoQA", href: "/why-autoqa" },
  {
    label: "Product",
    items: [
      {
        label: "How it works",
        href: "/how-it-works",
        hint: "Record, generate, run, understand — in detail",
      },
      {
        label: "Features",
        href: "/features",
        hint: "Everything AutoQA does, grouped by job",
      },
      {
        label: "AI test generation",
        href: "/features#ai",
        hint: "Negative, edge and security cases from one recording",
      },
      {
        label: "Failure analysis",
        href: "/features#analysis",
        hint: "Root cause, suggested fix, and a drafted bug report",
      },
    ],
  },
  {
    label: "Resources",
    items: [
      { label: "FAQ", href: "/faq", hint: "The questions people actually ask" },
      {
        label: "Create an account",
        href: "/register",
        hint: "No card, no trial period, no quota",
      },
      {
        label: "Sign in",
        href: "/login",
        hint: "Back to your projects and runs",
      },
    ],
  },
  { label: "Pricing", href: "/pricing" },
];

export function MarketingShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <Nav />
      <div className="flex-1">{children}</div>
      <Footer />
    </div>
  );
}

function Nav() {
  const [open, setOpen] = useState<string | null>(null);

  return (
    <header className="sticky top-0 z-40 border-b border-border bg-card/85 backdrop-blur-xl">
      <div className="mx-auto flex max-w-6xl items-center gap-6 px-5 py-3.5 sm:px-8">
        <Link href="/" className="flex shrink-0 items-center gap-2.5">
          <span className="brand-gradient flex size-8 items-center justify-center rounded-xl text-white">
            <Radar className="size-[17px]" />
          </span>
          <span className="text-[15px] font-bold tracking-tight">AutoQA</span>
        </Link>

        <nav
          className="ml-2 hidden items-center gap-1 lg:flex"
          onMouseLeave={() => setOpen(null)}
        >
          {NAV.map((group) =>
            group.href ? (
              <Link
                key={group.label}
                href={group.href}
                className="rounded-full px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
              >
                {group.label}
              </Link>
            ) : (
              <div
                key={group.label}
                className="relative"
                onMouseEnter={() => setOpen(group.label)}
              >
                <button
                  type="button"
                  onClick={() =>
                    setOpen(open === group.label ? null : group.label)
                  }
                  className="flex items-center gap-1 rounded-full px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                  aria-expanded={open === group.label}
                >
                  {group.label}
                  <ChevronDown
                    className={cn(
                      "size-3.5 transition-transform",
                      open === group.label && "rotate-180",
                    )}
                  />
                </button>

                {open === group.label && (
                  <div className="absolute left-0 top-full w-[22rem] pt-2">
                    <div className="sheen animate-in rounded-xl border border-border bg-card p-2 shadow-lg">
                      {group.items?.map((item) => (
                        <Link
                          key={item.href}
                          href={item.href}
                          onClick={() => setOpen(null)}
                          className="block rounded-lg px-3 py-2.5 transition-colors hover:bg-accent"
                        >
                          <span className="block text-[13px] font-semibold">
                            {item.label}
                          </span>
                          <span className="mt-0.5 block text-xs leading-relaxed text-muted-foreground">
                            {item.hint}
                          </span>
                        </Link>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ),
          )}
        </nav>

        <div className="ml-auto flex items-center gap-2">
          <Link href="/login">
            <Button variant="ghost" size="sm">
              Sign in
            </Button>
          </Link>
          <Link href="/register">
            <Button size="sm">Get started</Button>
          </Link>
        </div>
      </div>
    </header>
  );
}

const FOOTER: { title: string; links: { label: string; href: string }[] }[] = [
  {
    title: "Product",
    links: [
      { label: "How it works", href: "/how-it-works" },
      { label: "Features", href: "/features" },
      { label: "Why AutoQA", href: "/why-autoqa" },
      { label: "Pricing", href: "/pricing" },
    ],
  },
  {
    title: "Capabilities",
    links: [
      { label: "Recording", href: "/how-it-works#record" },
      { label: "Test generation", href: "/how-it-works#generate" },
      { label: "Cross-browser runs", href: "/how-it-works#run" },
      { label: "Failure analysis", href: "/how-it-works#understand" },
    ],
  },
  {
    title: "Resources",
    links: [
      { label: "FAQ", href: "/faq" },
      { label: "Sign in", href: "/login" },
      { label: "Create an account", href: "/register" },
    ],
  },
];

function Footer() {
  return (
    <footer className="border-t border-border bg-card">
      <div className="mx-auto max-w-6xl px-5 py-14 sm:px-8">
        <div className="grid gap-10 md:grid-cols-[minmax(0,1.4fr)_repeat(3,minmax(0,1fr))]">
          <div>
            <Link href="/" className="flex items-center gap-2.5">
              <span className="brand-gradient flex size-8 items-center justify-center rounded-xl text-white">
                <Radar className="size-[17px]" />
              </span>
              <span className="text-[15px] font-bold tracking-tight">AutoQA</span>
            </Link>
            <p className="mt-3 max-w-xs text-[13px] leading-relaxed text-muted-foreground">
              Record a session, get real Playwright tests, run them everywhere,
              and find out why anything broke.
            </p>
          </div>

          {FOOTER.map((column) => (
            <div key={column.title}>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                {column.title}
              </p>
              <ul className="mt-3 flex flex-col gap-2">
                {column.links.map((link) => (
                  <li key={link.href + link.label}>
                    <Link
                      href={link.href}
                      className="text-[13px] text-muted-foreground transition-colors hover:text-foreground"
                    >
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="mt-12 border-t border-border pt-6 text-[13px] text-muted-foreground">
          AutoQA — AI-powered test automation. Runs on your own machine.
        </div>
      </div>
    </footer>
  );
}

/* ------------------------------------------------------------------ *
 * Section primitives
 * ------------------------------------------------------------------ */

/** The top of an info page: badge, two-line headline, subhead, optional CTA. */
export function PageHero({
  badge,
  title,
  accent,
  children,
  cta = true,
}: {
  badge: string;
  title: string;
  /** The second line, in the brand colour. */
  accent: string;
  children: React.ReactNode;
  cta?: boolean;
}) {
  return (
    <section className="relative overflow-hidden">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-10"
        style={{
          background:
            "linear-gradient(180deg, var(--primary-subtle) 0%, transparent 100%)",
        }}
      />
      <div className="mx-auto max-w-3xl px-5 py-16 text-center sm:px-8 sm:py-20">
        <Badge>{badge}</Badge>
        <h1 className="mt-6 text-3xl font-bold leading-[1.1] tracking-tight sm:text-4xl">
          {title}
          <br />
          <span className="text-primary">{accent}</span>
        </h1>
        <div className="mx-auto mt-5 max-w-2xl text-base leading-relaxed text-muted-foreground">
          {children}
        </div>
        {cta && (
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
        )}
      </div>
    </section>
  );
}

export function Badge({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-primary/20 bg-card px-3.5 py-1.5 text-[13px] font-medium text-primary shadow-xs">
      {children}
    </span>
  );
}

/** A page section. `tinted` alternates the background so sections separate
 *  without needing a rule between them. */
export function Section({
  id,
  title,
  accent,
  lead,
  tinted = false,
  center = false,
  children,
}: {
  id?: string;
  title?: string;
  /** A trailing phrase of the title, in the brand colour. */
  accent?: string;
  lead?: React.ReactNode;
  tinted?: boolean;
  center?: boolean;
  children?: React.ReactNode;
}) {
  return (
    <section
      id={id}
      className={cn("border-y border-border", tinted ? "bg-card" : "border-transparent")}
    >
      <div className="mx-auto max-w-6xl px-5 py-16 sm:px-8 sm:py-20">
        {title && (
          <div className={cn("max-w-2xl", center && "mx-auto text-center")}>
            <h2 className="text-2xl font-bold tracking-tight sm:text-3xl">
              {title} {accent && <span className="text-primary">{accent}</span>}
            </h2>
            {lead && (
              <div className="mt-4 text-base leading-relaxed text-muted-foreground">
                {lead}
              </div>
            )}
          </div>
        )}
        {children && <div className={cn(title && "mt-10")}>{children}</div>}
      </div>
    </section>
  );
}

/** Text on one side, a supporting panel on the other. Flipped on alternate
 *  rows so a run of them does not read as a list. */
export function SplitRow({
  eyebrow,
  title,
  children,
  aside,
  flip = false,
}: {
  eyebrow?: string;
  title: string;
  children: React.ReactNode;
  aside: React.ReactNode;
  flip?: boolean;
}) {
  return (
    <div className="grid items-center gap-8 py-10 md:grid-cols-2 md:gap-14">
      <div className={cn(flip && "md:order-2")}>
        {eyebrow && (
          <p className="text-[11px] font-semibold uppercase tracking-wide text-primary">
            {eyebrow}
          </p>
        )}
        <h3 className="mt-2 text-2xl font-bold tracking-tight">{title}</h3>
        <div className="mt-3 flex flex-col gap-3 text-[15px] leading-relaxed text-muted-foreground">
          {children}
        </div>
      </div>
      <div className={cn(flip && "md:order-1")}>{aside}</div>
    </div>
  );
}

export function FeatureCard({
  icon,
  title,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="sheen rounded-xl border border-border bg-card p-5 shadow-xs transition-all hover:border-primary/40 hover:shadow-md">
      <span className="flex size-10 items-center justify-center rounded-xl bg-primary-subtle text-primary [&_svg]:size-5">
        {icon}
      </span>
      <h3 className="mt-4 text-base font-bold">{title}</h3>
      <p className="mt-2 text-[13px] leading-relaxed text-muted-foreground">
        {children}
      </p>
    </div>
  );
}

/** A dark panel holding generated code. Used as the aside on split rows. */
export function CodePanel({
  label,
  code,
}: {
  label: string;
  code: string;
}) {
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

/** A list of short facts in a bordered panel — the other common aside. */
export function FactList({
  label,
  items,
}: {
  label: string;
  items: [string, string][];
}) {
  return (
    <div className="sheen rounded-xl border border-border bg-card p-5 shadow-xs">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <dl className="mt-3 flex flex-col divide-y divide-border">
        {items.map(([term, value]) => (
          <div key={term} className="flex items-baseline gap-4 py-2.5">
            <dt className="text-[13px] font-medium">{term}</dt>
            <dd className="ml-auto text-right text-[13px] text-muted-foreground">
              {value}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export function CtaBand({
  title,
  children,
}: {
  title: string;
  children?: React.ReactNode;
}) {
  return (
    <section className="mx-auto max-w-4xl px-5 py-20 text-center sm:px-8">
      <h2 className="text-2xl font-bold tracking-tight sm:text-3xl">
        {title}
      </h2>
      {children && (
        <p className="mx-auto mt-4 max-w-xl text-base leading-relaxed text-muted-foreground">
          {children}
        </p>
      )}
      <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
        <Link href="/register">
          <Button size="lg">
            Get started
            <ArrowRight />
          </Button>
        </Link>
        <Link href="/login">
          <Button size="lg" variant="outline">
            Sign in
          </Button>
        </Link>
      </div>
    </section>
  );
}
