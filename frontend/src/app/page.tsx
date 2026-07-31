"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { FullPageMessage } from "@/components/auth-provider";
import { useAuthStore } from "@/stores/auth-store";

/** Entry point: send people to their projects, or to login. */
export default function Home() {
  const router = useRouter();
  const hydrated = useAuthStore((s) => s.hydrated);
  const accessToken = useAuthStore((s) => s.accessToken);

  useEffect(() => {
    if (!hydrated) return;
    router.replace(accessToken ? "/projects" : "/login");
  }, [hydrated, accessToken, router]);

  return <FullPageMessage>Loading AutoQA…</FullPageMessage>;
}
