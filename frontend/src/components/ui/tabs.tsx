"use client";

/** Tabs for a page whose sections are all "the same thing, differently".
 *
 *  A detail page that keeps growing downwards eventually asks the reader to
 *  scroll past three things to reach the fourth. Tabs make each section cost
 *  nothing until it is wanted, and put their names in one place so you can see
 *  what the page contains without exploring it.
 */

import { cn } from "@/lib/utils";

export interface TabDef {
  id: string;
  label: string;
  count?: number;
  icon?: React.ReactNode;
}

export function Tabs({
  tabs,
  active,
  onChange,
  className,
}: {
  tabs: TabDef[];
  active: string;
  onChange: (id: string) => void;
  className?: string;
}) {
  return (
    <div
      role="tablist"
      className={cn("flex items-center gap-1 border-b border-border", className)}
    >
      {tabs.map((tab) => {
        const selected = tab.id === active;
        return (
          <button
            key={tab.id}
            role="tab"
            aria-selected={selected}
            type="button"
            onClick={() => onChange(tab.id)}
            className={cn(
              "relative flex items-center gap-2 px-3.5 py-2.5 text-sm font-medium transition-colors",
              "[&_svg]:size-4",
              selected
                ? "text-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {tab.icon}
            {tab.label}
            {tab.count !== undefined && (
              <span
                className={cn(
                  "tabular rounded-full px-1.5 py-0.5 text-[11px] font-medium",
                  selected
                    ? "bg-primary-subtle text-primary"
                    : "bg-muted text-muted-foreground",
                )}
              >
                {tab.count}
              </span>
            )}
            {/* Sits on the container's border so the active tab joins the
                panel below it rather than floating above a line. */}
            {selected && (
              <span className="absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-primary" />
            )}
          </button>
        );
      })}
    </div>
  );
}
