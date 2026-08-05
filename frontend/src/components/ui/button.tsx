import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

/* Pill-shaped and flat. An earlier version gave the primary button a gradient,
   an inset top highlight and a press-down, which is a good skeuomorphic control
   and the wrong one here — the reference's buttons are solid single-colour pills
   that carry weight through colour and size alone. The only motion left is a
   colour change and a soft glow on hover. */
const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg text-sm font-semibold " +
    "transition-all duration-150 outline-none " +
    "focus-visible:ring-2 focus-visible:ring-ring/60 focus-visible:ring-offset-2 focus-visible:ring-offset-background " +
    "disabled:pointer-events-none disabled:opacity-45 " +
    "[&_svg]:pointer-events-none [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default:
          "bg-primary text-primary-foreground shadow-sm " +
          "hover:bg-primary-hover hover:shadow-[0_6px_18px_var(--primary-glow)]",
        destructive:
          "bg-destructive text-destructive-foreground shadow-sm hover:brightness-95",
        outline:
          "border border-border bg-card text-foreground shadow-xs " +
          "hover:border-primary hover:text-primary",
        secondary:
          "bg-secondary text-secondary-foreground hover:brightness-[0.97]",
        ghost: "text-muted-foreground hover:bg-accent hover:text-foreground",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "h-10 px-5 py-2 [&_svg]:size-4",
        sm: "h-8.5 px-4 text-[13px] [&_svg]:size-3.5",
        lg: "h-12 px-7 text-[15px] [&_svg]:size-4",
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
