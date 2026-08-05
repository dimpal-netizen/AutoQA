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
  /* A segmented control rather than an underline. The underline version drew a
     full-width rule across the page, which read as a section divider and cut
     the tabs off from the panel they belong to. A pill group is self-contained
     and matches the shape language everything else now uses. */
  return (
    <div
      role="tablist"
      className={cn(
        "flex flex-wrap items-center gap-5",
        className,
      )}
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
              "flex items-center gap-2 border-b-2 pb-2.5 text-sm transition-colors",
              "[&_svg]:size-4",
              selected
                ? "border-primary font-semibold text-primary"
                : "border-transparent font-medium text-muted-foreground hover:text-foreground",
            )}
          >
            {tab.icon}
            {tab.label}
            {tab.count !== undefined && (
              <span
                className={cn(
                  "tabular text-xs font-normal",
                  selected
                    ? "text-primary/60"
                    : "text-muted-foreground/60",
                )}
              >
                {tab.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
