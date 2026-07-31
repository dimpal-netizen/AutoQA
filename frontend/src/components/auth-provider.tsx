"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/stores/auth-store";

/** Rehydrates the persisted session on mount.
 *
 *  The store uses skipHydration, so reading localStorage happens here — after
 *  the server-rendered HTML is on screen — which avoids a hydration mismatch. */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    useAuthStore.persist.rehydrate();
    useAuthStore.getState().setHydrated(true);
  }, []);

  return <>{children}</>;
}

/** Wraps pages that require a logged-in user. */
export function RequireAuth({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const hydrated = useAuthStore((s) => s.hydrated);
  const accessToken = useAuthStore((s) => s.accessToken);

  useEffect(() => {
    // Wait for rehydration, otherwise every refresh bounces to /login.
    if (hydrated && !accessToken) router.replace("/login");
  }, [hydrated, accessToken, router]);

  if (!hydrated) return <FullPageMessage>Loading…</FullPageMessage>;
  if (!accessToken) return <FullPageMessage>Redirecting…</FullPageMessage>;

  return <>{children}</>;
}

export function FullPageMessage({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-svh items-center justify-center text-sm text-muted-foreground">
      {children}
    </div>
  );
}
