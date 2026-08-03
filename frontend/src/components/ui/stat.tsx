import { cn } from "@/lib/utils";

/** The numbers that answer "how is this doing" before you read anything else. */
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
  return (
    <div
      className={cn(
        "lit sheen rounded-lg border border-border bg-card px-4 py-3",
        className,
      )}
    >
      <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      {/* Proportional figures, not tabular: tabular gives every digit the width
          of a zero, which makes a number like 121 look gappy at display sizes.
          Tabular is for columns that must align, not for standalone values. */}
      <p className={cn("mt-1 text-xl font-bold leading-none", TONE[tone])}>
        {value}
      </p>
      {hint && (
        <p className="mt-1.5 truncate text-xs text-muted-foreground">{hint}</p>
      )}
    </div>
  );
}

/** The single number a view leads with. Exactly one per screen — a page with
 *  five things this size has no hierarchy, only noise. */
export function Hero({
  label,
  value,
  hint,
  tone = "default",
  children,
}: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  tone?: "default" | "success" | "danger" | "warning" | "muted";
  children?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className={cn("text-4xl font-bold leading-none tracking-tight", TONE[tone])}>
        {value}
      </p>
      {hint && <p className="mt-1 text-[13px] text-muted-foreground">{hint}</p>}
      {children}
    </div>
  );
}

/** A proportion, as a bar. The fill carries severity; the track is a lighter
 *  step of the same hue so the state reads across the whole width rather than
 *  only where the fill happens to end. */
export function Meter({
  value,
  tone = "default",
  className,
}: {
  /** 0–100. */
  value: number;
  tone?: "default" | "success" | "danger" | "warning" | "muted";
  className?: string;
}) {
  const clamped = Math.max(0, Math.min(100, value));

  return (
    <div
      className={cn("h-2 w-full overflow-hidden rounded-full", TRACK[tone], className)}
      role="meter"
      aria-valuenow={Math.round(clamped)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div
        className={cn("h-full rounded-full transition-[width] duration-500", FILL[tone])}
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
}

const TONE = {
  default: "text-foreground",
  success: "text-success",
  danger: "text-destructive",
  warning: "text-warning",
  muted: "text-muted-foreground",
} as const;

const FILL = {
  default: "bg-primary",
  success: "bg-success",
  danger: "bg-destructive",
  warning: "bg-warning",
  muted: "bg-muted-foreground",
} as const;

const TRACK = {
  default: "bg-primary/15",
  success: "bg-success/15",
  danger: "bg-destructive/15",
  warning: "bg-warning/15",
  muted: "bg-muted",
} as const;

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
