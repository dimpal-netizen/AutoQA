"use client";

/** The public front door.
 *
 *  Signed in, this is not where you want to be — go to the dashboard. Signed
 *  out, it is the only page that has to explain what the product is.
 */

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { Marketing } from "@/components/marketing";
import { FullPageMessage } from "@/components/auth-provider";
import { useAuthStore } from "@/stores/auth-store";

export default function Home() {
  const router = useRouter();
  const hydrated = useAuthStore((s) => s.hydrated);
  const accessToken = useAuthStore((s) => s.accessToken);

  useEffect(() => {
    if (hydrated && accessToken) router.replace("/dashboard");
  }, [hydrated, accessToken, router]);

  // Wait for rehydration before deciding — rendering the landing page and then
  // yanking it away is worse than a moment of nothing. Mirrors RequireAuth.
  if (!hydrated) return <FullPageMessage>Loading AutoQA…</FullPageMessage>;
  if (accessToken) return <FullPageMessage>Redirecting…</FullPageMessage>;

  return <Marketing />;
}
