"use client";

/** Dark or light, remembered.
 *
 *  The theme is written to <html data-theme> by a script in the document head
 *  (see layout.tsx), not from React. Waiting for hydration would paint the
 *  default theme first and then swap — a white flash on every load for anyone
 *  using dark, which is exactly the audience that notices.
 */

import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";

export type Theme = "dark" | "light";

export const THEME_KEY = "autoqa-theme";

export function ThemeToggle({ className }: { className?: string }) {
  const [theme, setTheme] = useState<Theme>("light");

  // Read what the head script already applied, rather than deciding again.
  // This has to be an effect: the value lives on the DOM, put there before
  // React existed, and reading it during render would break hydration.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => setTheme(
    document.documentElement.dataset.theme === "dark" ? "dark" : "light",
  ), []);

  function toggle() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch {
      /* private mode - the theme just will not persist */
    }
  }

  return (
    <button
      type="button"
      onClick={toggle}
      title={theme === "dark" ? "Switch to light" : "Switch to dark"}
      aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
      className={`rounded-full p-1.5 text-sidebar-muted transition-colors hover:bg-accent hover:text-foreground ${className ?? ""}`}
    >
      {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
    </button>
  );
}
