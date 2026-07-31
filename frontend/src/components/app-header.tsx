"use client";

import { useRouter } from "next/navigation";
import { LogOut } from "lucide-react";
import { useAuthStore } from "@/stores/auth-store";
import { ROLE_LABEL } from "@/lib/types";
import { Button } from "@/components/ui/button";

export function AppHeader() {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);

  function handleLogout() {
    logout();
    router.replace("/login");
  }

  return (
    <header className="border-b border-border">
      <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-4 py-3">
        <div>
          <p className="font-semibold">AutoQA</p>
          <p className="text-xs text-muted-foreground">
            Autonomous test automation
          </p>
        </div>

        <div className="flex items-center gap-3">
          {user && (
            <div className="text-right">
              <p className="text-sm font-medium">
                {user.full_name || user.email}
              </p>
              <p className="text-xs text-muted-foreground">
                {ROLE_LABEL[user.role]}
              </p>
            </div>
          )}
          <Button variant="outline" size="sm" onClick={handleLogout}>
            <LogOut className="size-4" />
            Sign out
          </Button>
        </div>
      </div>
    </header>
  );
}
