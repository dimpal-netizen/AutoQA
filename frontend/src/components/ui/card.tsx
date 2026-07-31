import * as React from "react";
import { cn } from "@/lib/utils";

export function Card({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-lg border border-border bg-card text-card-foreground shadow-sm",
        className,
      )}
      {...props}
    />
  );
}

export function CardHeader({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("flex flex-col gap-1 px-5 pt-5 pb-4", className)} {...props} />
  );
}

export function CardTitle({
  className,
  ...props
}: React.HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h3
      className={cn("text-[15px] font-semibold leading-none", className)}
      {...props}
    />
  );
}

export function CardDescription({
  className,
  ...props
}: React.HTMLAttributes<HTMLParagraphElement>) {
  return (
    <p
      className={cn("text-[13px] leading-relaxed text-muted-foreground", className)}
      {...props}
    />
  );
}

export function CardContent({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("px-5 pb-5", className)} {...props} />;
}

export function CardFooter({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "flex items-center gap-2 border-t border-border bg-muted/40 px-5 py-3",
        className,
      )}
      {...props}
    />
  );
}

/** Inline banner for a message that belongs to the thing next to it. */
export function Alert({
  variant = "error",
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & {
  variant?: "error" | "info" | "warning";
}) {
  const tone = {
    error: "border-destructive/25 bg-destructive-subtle text-destructive",
    info: "border-primary/20 bg-primary-subtle text-primary",
    warning: "border-warning/25 bg-warning-subtle text-warning",
  }[variant];

  return (
    <div
      role="alert"
      className={cn(
        "rounded-md border px-3.5 py-2.5 text-[13px] leading-relaxed",
        tone,
        className,
      )}
      {...props}
    />
  );
}

/**
 * What to show where content would be. An empty state that explains the next
 * action is the difference between "nothing here" and "you have not started
 * yet, here is how" — and it is the first thing a new user sees.
 */
export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <Card className={cn("border-dashed shadow-none", className)}>
      <div className="flex flex-col items-center gap-3 px-6 py-12 text-center">
        {icon && (
          <div className="flex size-11 items-center justify-center rounded-full bg-muted text-muted-foreground [&_svg]:size-5">
            {icon}
          </div>
        )}
        <div className="flex flex-col gap-1">
          <p className="text-sm font-medium">{title}</p>
          {description && (
            <p className="max-w-sm text-[13px] leading-relaxed text-muted-foreground">
              {description}
            </p>
          )}
        </div>
        {action}
      </div>
    </Card>
  );
}

/** Page title, subtitle, and the actions belonging to the page. */
export function PageHeader({
  title,
  description,
  children,
  className,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-start justify-between gap-4 pb-6",
        className,
      )}
    >
      <div className="min-w-0">
        <h1 className="text-[26px] font-semibold leading-tight">{title}</h1>
        {description && (
          <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
            {description}
          </p>
        )}
      </div>
      {children && <div className="flex shrink-0 items-center gap-2">{children}</div>}
    </div>
  );
}
