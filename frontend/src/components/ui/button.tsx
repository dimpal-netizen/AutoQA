import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

/* The lift on `default` and `destructive` is what makes a button read as a
   physical control rather than a coloured rectangle: an inset highlight along
   the top edge, a shadow below, and both easing away on press. */
const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium " +
    "transition-all duration-150 outline-none " +
    "focus-visible:ring-2 focus-visible:ring-ring/60 focus-visible:ring-offset-2 focus-visible:ring-offset-background " +
    "disabled:pointer-events-none disabled:opacity-45 " +
    "[&_svg]:pointer-events-none [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default:
          "bg-primary text-primary-foreground shadow-sm hover:bg-primary-hover " +
          "active:translate-y-px",
        destructive:
          "bg-destructive text-destructive-foreground shadow-sm hover:brightness-95 " +
          "active:translate-y-px",
        outline:
          "border border-border bg-card text-foreground shadow-xs " +
          "hover:bg-accent hover:border-border-strong active:translate-y-px",
        secondary:
          "bg-secondary text-secondary-foreground hover:brightness-[0.97] active:translate-y-px",
        ghost: "text-muted-foreground hover:bg-accent hover:text-foreground",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "h-9.5 px-4 py-2 [&_svg]:size-4",
        sm: "h-8.5 rounded-md px-3 text-[13px] [&_svg]:size-3.5",
        lg: "h-11 rounded-lg px-6 [&_svg]:size-4",
        icon: "size-9.5 [&_svg]:size-4",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

export function Button({ className, variant, size, ...props }: ButtonProps) {
  return (
    <button
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  );
}

export { buttonVariants };
