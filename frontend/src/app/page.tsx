"use client";

/** Entry point. Projects come first: you pick the application under test
 *  before there is anything sensible to record, and everything after that
 *  happens inside the project. */

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { FullPageMessage } from "@/components/auth-provider";
import { useAuthStore } from "@/stores/auth-store";

export default function Home() {
  const router = useRouter();
  const hydrated = useAuthStore((s) => s.hydrated);
  const accessToken = useAuthStore((s) => s.accessToken);

  useEffect(() => {
    if (!hydrated) return;
    router.replace(accessToken ? "/dashboard" : "/login");
  }, [hydrated, accessToken, router]);

  return <FullPageMessage>Loading AutoQA…</FullPageMessage>;
}
