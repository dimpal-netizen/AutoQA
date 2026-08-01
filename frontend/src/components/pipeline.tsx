"use client";

/** The four steps of using AutoQA, with where you actually are on them.
 *
 *  The app is one pipeline — record, generate, run, read the results — but it
 *  was presented as four unrelated pages you had to already know the order of.
 *  This says the order out loud and points at the next thing, so nobody has to
 *  hold the workflow in their head.
 */

import Link from "next/link";
import { ArrowRight, Check, FlaskConical, Play, Video } from "lucide-react";
import { cn } from "@/lib/utils";

export interface Step {
  id: string;
  label: string;
  detail: string;
  icon: React.ReactNode;
  href: string;
  /** Done means you have one; current is the next thing worth doing. */
  done: boolean;
}

export function Pipeline({ steps }: { steps: Step[] }) {
  const currentIndex = steps.findIndex((step) => !step.done);

  return (
    <ol className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {steps.map((step, index) => {
        const current = index === currentIndex;
        // Everything after the next step is unreachable in practice — you
        // cannot run tests you have not generated — so it is shown but muted
        // rather than presented as an equal choice.
        const ahead = currentIndex !== -1 && index > currentIndex;

        return (
          <li key={step.id}>
            <Link
              href={step.href}
              className={cn(
                "lit sheen group flex h-full flex-col gap-2 rounded-lg border p-4 transition-all",
                current
                  ? "border-primary/40 bg-card ring-2 ring-primary/15"
                  : "border-border bg-card hover:border-border-strong hover:shadow-md",
                ahead && "opacity-60",
              )}
            >
              <span className="flex items-center gap-2">
                <span
                  className={cn(
                    "flex size-7 shrink-0 items-center justify-center rounded-md [&_svg]:size-4",
                    step.done
                      ? "bg-success-subtle text-success"
                      : current
                        ? "brand-gradient text-white"
                        : "bg-muted text-muted-foreground",
                  )}
                >
                  {step.done ? <Check /> : step.icon}
                </span>
                <span className="text-sm font-medium">{step.label}</span>
                {current && (
                  <ArrowRight className="ml-auto size-4 text-primary transition-transform group-hover:translate-x-0.5" />
                )}
              </span>

              <span className="text-[13px] leading-relaxed text-muted-foreground">
                {step.detail}
              </span>
            </Link>
          </li>
        );
      })}
    </ol>
  );
}

export const STEP_ICONS = {
  record: <Video />,
  generate: <FlaskConical />,
  run: <Play />,
};
