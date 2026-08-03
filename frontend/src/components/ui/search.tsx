"use client";

/** A filter box for a list on this page.
 *
 *  Filters what has already been fetched rather than querying the server. Both
 *  lists it is used on are a page of records someone can see in one scroll —
 *  a round trip per keystroke would be slower and would make the results lag
 *  the box you are typing in.
 */

import { Search, X } from "lucide-react";
import { cn } from "@/lib/utils";

export function SearchBox({
  value,
  onChange,
  placeholder = "Search…",
  count,
  total,
  className,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  /** How many are showing, and out of how many. Only rendered while filtering,
   *  so an unfiltered list is not narrated back at you. */
  count?: number;
  total?: number;
  className?: string;
}) {
  const filtering = value.trim().length > 0;

  return (
    <div className={cn("flex flex-wrap items-center gap-3", className)}>
      <div className="relative min-w-0 flex-1 sm:max-w-sm">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <input
          type="search"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          aria-label={placeholder}
          className={cn(
            "h-9.5 w-full rounded-full border border-input bg-card pl-9 pr-9 text-sm",
            "placeholder:text-muted-foreground",
            "outline-none transition-colors focus-visible:border-primary",
            "focus-visible:ring-2 focus-visible:ring-ring/40",
            // Safari draws its own clear button on type=search, which would
            // sit under ours.
            "[&::-webkit-search-cancel-button]:appearance-none",
          )}
        />
        {filtering && (
          <button
            type="button"
            onClick={() => onChange("")}
            aria-label="Clear search"
            className="absolute right-2.5 top-1/2 flex size-5 -translate-y-1/2 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <X className="size-3.5" />
          </button>
        )}
      </div>

      {filtering && count !== undefined && total !== undefined && (
        <span className="tabular text-[13px] text-muted-foreground">
          {count} of {total}
        </span>
      )}
    </div>
  );
}

/** Case-insensitive substring match across the fields worth searching.
 *
 *  Every word in the query must appear somewhere, in any field and any order,
 *  so "login chrome" finds a thing whose name says login and whose URL says
 *  chrome. Matching the query as one string would fail that, and it is how
 *  people actually type.
 */
export function matches(query: string, ...fields: (string | null | undefined)[]) {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return true;

  const haystack = fields.filter(Boolean).join(" ").toLowerCase();
  return words.every((word) => haystack.includes(word));
}
