import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

/* Status badges. Tinted background plus matching text and a faint border, so
   they read at a glance in a dense table without shouting. Colour alone is not
   the signal - the text always says what it means, which is also why these
   still work for anyone who cannot separate red from green. */
const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium " +
    "[&_svg]:size-3 [&_svg]:shrink-0",
  {
    variants: {
      tone: {
        neutral: "border-border bg-muted text-muted-foreground",
        primary: "border-primary/20 bg-primary-subtle text-primary",
        success: "border-success/25 bg-success-subtle text-success",
        danger: "border-destructive/25 bg-destructive-subtle text-destructive",
        warning: "border-warning/25 bg-warning-subtle text-warning",
        outline: "border-border-strong bg-transparent text-muted-foreground",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}

/** A small dot that pulses while something is in progress. */
export function LiveDot({ className }: { className?: string }) {
  return (
    <span className={cn("relative flex size-2", className)}>
      <span className="absolute inline-flex size-full animate-ping rounded-full bg-current opacity-60" />
      <span className="relative inline-flex size-2 rounded-full bg-current" />
    </span>
  );
}

export { badgeVariants };
