import * as React from "react";
import { cn } from "@/lib/utils";

/* One shared style so an <input>, a <select> and a <textarea> sitting in the
   same row line up and share a focus treatment. Mismatched heights between
   native controls are the most common reason a form looks unfinished. */
const field =
  "w-full rounded-md border border-input bg-card px-3 text-sm text-foreground shadow-xs " +
  "transition-[border-color,box-shadow] duration-150 " +
  "placeholder:text-muted-foreground/70 " +
  "hover:border-border-strong " +
  "focus-visible:border-primary focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-primary/12 " +
  "disabled:cursor-not-allowed disabled:opacity-55 disabled:hover:border-input";

export function Input({
  className,
  type,
  ...props
}: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input type={type} className={cn(field, "h-9.5 py-2", className)} {...props} />
  );
}

export function Select({
  className,
  ...props
}: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(field, "h-9.5 cursor-pointer appearance-none py-2 pr-9", className)}
      style={{
        // Inlined so the chevron follows the theme without a second asset.
        backgroundImage:
          "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' fill='none' stroke='%235c6a80' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m4 6 4 4 4-4'/%3E%3C/svg%3E\")",
        backgroundRepeat: "no-repeat",
        backgroundPosition: "right 0.65rem center",
      }}
      {...props}
    />
  );
}

export function Textarea({
  className,
  ...props
}: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn(field, "min-h-20 py-2", className)} {...props} />;
}

export function Label({
  className,
  ...props
}: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return (
    <label
      className={cn(
        "text-[13px] font-medium leading-none text-foreground",
        className,
      )}
      {...props}
    />
  );
}
