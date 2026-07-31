"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { FileCode2 } from "lucide-react";
import { api } from "@/lib/api";
import type { TestSuite } from "@/lib/types";
import { AppHeader } from "@/components/app-header";
import { RequireAuth } from "@/components/auth-provider";
import { Alert, Card, CardContent } from "@/components/ui/card";

export default function SuitesPage() {
  return (
    <RequireAuth>
      <AppHeader />
      <Suites />
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
    <main className="mx-auto max-w-5xl p-6">
      <h1 className="text-2xl font-semibold">Tests</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        Playwright scripts generated from your recordings, written to disk for
        review in VS Code. A suite is created automatically each time a
        recording stops.
      </p>

      {error && <Alert className="mt-4">{error}</Alert>}

      <div className="mt-6 flex flex-col gap-3">
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : suites.length === 0 ? (
          <Card>
            <CardContent className="py-10 text-center text-sm text-muted-foreground">
              No tests yet.{" "}
              <Link
                href="/recordings"
                className="text-foreground underline underline-offset-4"
              >
                Record a session
              </Link>{" "}
              and one is generated for you.
            </CardContent>
          </Card>
        ) : (
          suites.map((suite) => (
            <Link key={suite.id} href={`/suites/${suite.id}`}>
              <Card className="transition-colors hover:border-foreground/20">
                <CardContent className="flex items-center gap-4 py-4">
                  <FileCode2 className="size-5 shrink-0 text-muted-foreground" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium">{suite.name}</p>
                    <p className="truncate text-xs text-muted-foreground">
                      {suite.output_dir ?? suite.description}
                    </p>
                  </div>
                </CardContent>
              </Card>
            </Link>
          ))
        )}
      </div>
    </main>
  );
}
