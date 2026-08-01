"use client";

/** The signed-in layout: a fixed sidebar and a scrolling content column.
 *
 *  A sidebar rather than a top nav because this app grows sideways — runs,
 *  reports, bug reports and integrations are all still to come, and a row of
 *  pills stops working around the fifth one. It also frees the top of every
 *  page for the page's own title and actions instead of spending it on chrome.
 */

import { useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  FolderKanban,
  LayoutDashboard,
  LogOut,
  Menu,
  Radar,
  Video,
  X,
} from "lucide-react";
import { useAuthStore } from "@/stores/auth-store";
import { ROLE_LABEL } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ThemeToggle } from "@/components/theme-toggle";

// Three entries, in the order you use them. "Tests" is the workspace and the
// place work actually happens; the other two are things you set up once.
// In the order the work happens: pick a project, then everything else lives
// inside it. Recordings is a flat history across all projects.
const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/projects", label: "Projects", icon: FolderKanban },
  { href: "/recordings", label: "Recordings", icon: Video },
];

export function AppShell({
  children,
  wide = false,
}: {
  children: React.ReactNode;
  /** The workspace needs the room; a form page does not. */
  wide?: boolean;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="min-h-screen">
      <Sidebar open={open} onClose={() => setOpen(false)} />

      {/* Narrow screens get a top bar instead; the sidebar slides over. */}
      <div className="flex items-center gap-3 border-b border-border bg-surface/80 px-4 py-3 backdrop-blur-xl lg:hidden">
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
          aria-label="Open navigation"
        >
          <Menu className="size-5" />
        </button>
        <Wordmark />
      </div>

      <div className="lg:pl-[248px]">
        <main
          className={cn(
            "mx-auto w-full px-5 py-8 sm:px-8 lg:py-10",
            wide ? "max-w-[100rem]" : "max-w-6xl",
          )}
        >
          {children}
        </main>
      </div>
    </div>
  );
}

function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const pathname = usePathname();

  return (
    <>
      {open && (
        <div
          className="fixed inset-0 z-40 bg-foreground/20 backdrop-blur-sm lg:hidden"
          onClick={onClose}
        />
      )}

      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-50 flex w-[248px] flex-col",
          "border-r border-sidebar-border bg-sidebar text-sidebar-foreground",
          "transition-transform duration-200 lg:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex items-center justify-between px-5 py-5">
          <Wordmark />
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-sidebar-muted hover:bg-white/10 lg:hidden"
            aria-label="Close navigation"
          >
            <X className="size-4" />
          </button>
        </div>

        <nav className="flex flex-1 flex-col gap-0.5 px-3">
          {NAV.map((item) => {
            const active =
              item.href === "/"
                ? pathname === "/"
                : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={onClose}
                className={cn(
                  "group relative flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                  active
                    ? "bg-sidebar-active text-white"
                    : "text-sidebar-muted hover:bg-white/5 hover:text-sidebar-foreground",
                )}
              >
                {/* A rail on the active item, so the current page is legible
                    from the corner of the eye rather than needing a colour
                    comparison between two similar tints. */}
                {active && (
                  <span className="absolute inset-y-1.5 -left-3 w-1 rounded-r-full bg-primary" />
                )}
                <item.icon className="size-[18px] shrink-0" />
                {item.label}
              </Link>
            );
          })}
        </nav>

        <UserCard />
      </aside>
    </>
  );
}

function Wordmark() {
  return (
    <Link href="/dashboard" className="flex items-center gap-2.5">
      <span className="brand-gradient lit flex size-8 items-center justify-center rounded-lg text-white">
        <Radar className="size-[17px]" />
      </span>
      <span className="flex flex-col leading-none">
        <span className="text-[15px] font-semibold tracking-tight text-white">AutoQA</span>
        <span className="mt-1 text-[11px] text-sidebar-muted">
          Test automation
        </span>
      </span>
    </Link>
  );
}

function UserCard() {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);

  if (!user) return null;

  const name = user.full_name || user.email;
  const initials = name
    .split(/[\s@.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");

  return (
    <div className="border-t border-sidebar-border p-3">
      <div className="flex items-center gap-3 rounded-md px-2 py-2">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-white/10 text-[11px] font-semibold text-sidebar-foreground">
          {initials}
        </span>
        <span className="min-w-0 flex-1 leading-tight">
          <span className="block truncate text-[13px] font-medium">{name}</span>
          <span className="block text-[11px] text-sidebar-muted">
            {ROLE_LABEL[user.role]}
          </span>
        </span>
        <ThemeToggle />
        <button
          type="button"
          onClick={() => {
            logout();
            router.replace("/login");
          }}
          className="rounded-md p-1.5 text-sidebar-muted transition-colors hover:bg-white/10 hover:text-sidebar-foreground"
          title="Sign out"
          aria-label="Sign out"
        >
          <LogOut className="size-4" />
        </button>
      </div>
    </div>
  );
}
