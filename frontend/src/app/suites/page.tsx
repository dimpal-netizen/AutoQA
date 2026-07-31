"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ChevronRight, FlaskConical, Video } from "lucide-react";
import { api } from "@/lib/api";
import type { TestSuite } from "@/lib/types";
import { AppShell } from "@/components/app-shell";
import { RequireAuth } from "@/components/auth-provider";
import { Button } from "@/components/ui/button";
import { Alert, Card, EmptyState, PageHeader } from "@/components/ui/card";
import { SkeletonRows } from "@/components/ui/skeleton";

export default function SuitesPage() {
  return (
    <RequireAuth>
      <AppShell>
        <Suites />
      </AppShell>
    </RequireAuth>
  );
}

function Suites() {
  const [suites, setSuites] = useState<TestSuite[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const data = await api.suites.list();
        if (!cancelled) setSuites(data);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Could not load test suites");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="animate-in">
      <PageHeader
        title="Tests"
        description="Generated from your recordings and saved to disk. A test suite is created automatically every time a recording stops."
      >
        <Link href="/recordings">
          <Button variant="outline">
            <Video />
            Record a session
          </Button>
        </Link>
      </PageHeader>

      {error && <Alert className="mb-4">{error}</Alert>}

      {loading ? (
        <SkeletonRows count={3} />
      ) : suites.length === 0 ? (
        <EmptyState
          icon={<FlaskConical />}
          title="No tests yet"
          description="Record a session and AutoQA turns it into a runnable Playwright test the moment you stop."
          action={
            <Link href="/recordings">
              <Button>
                <Video />
                Record a session
              </Button>
            </Link>
          }
        />
      ) : (
        <div className="flex flex-col gap-2">
          {suites.map((suite) => (
            <Link key={suite.id} href={`/suites/${suite.id}`} className="group">
              <Card className="flex items-center gap-4 px-5 py-4 transition-all hover:border-border-strong hover:shadow-md">
                <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary-subtle text-primary">
                  <FlaskConical className="size-[18px]" />
                </span>

                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">
                    {suite.name}
                  </span>
                  <span className="mt-0.5 block truncate font-mono text-xs text-muted-foreground">
                    {suite.output_dir ?? suite.description}
                  </span>
                </span>

                <ChevronRight className="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
