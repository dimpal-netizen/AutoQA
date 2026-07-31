import { cn } from "@/lib/utils";

/** The numbers that answer "how is this doing" before you read anything else.
 *
 *  A row of these at the top of a detail page is the difference between
 *  scrolling to find out whether the last run passed and simply knowing.
 */
export function Stat({
  label,
  value,
  hint,
  tone = "default",
  className,
}: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  tone?: "default" | "success" | "danger" | "warning" | "muted";
  className?: string;
}) {
  const colour = {
    default: "text-foreground",
    success: "text-success",
    danger: "text-destructive",
    warning: "text-warning",
    muted: "text-muted-foreground",
  }[tone];

  return (
    <div
      className={cn(
        "rounded-lg border border-border bg-card px-4 py-3 shadow-xs",
        className,
      )}
    >
      <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className={cn("tabular mt-1 text-2xl font-semibold leading-none", colour)}>
        {value}
      </p>
      {hint && (
        <p className="mt-1.5 truncate text-xs text-muted-foreground">{hint}</p>
      )}
    </div>
  );
}

export function StatRow({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4",
        className,
      )}
    >
      {children}
    </div>
  );
}
