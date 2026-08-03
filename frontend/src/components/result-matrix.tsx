"use client";

/** The cross-browser matrix: one row per test, one column per browser.
 *
 *  This layout is the point of storing a result per (case, browser). A flat
 *  list would bury "passes in Chrome, fails in Safari" — the single most
 *  useful thing a cross-browser run can tell you — inside two similar-looking
 *  rows.
 */

import { Fragment, useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Image as ImageIcon, Video } from "lucide-react";
import { fetchArtifact } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { FailureAnalysis } from "@/components/failure-analysis";
import { BugReport } from "@/components/bug-report";
import {
  BROWSER_LABEL,
  RESULT_BADGE,
  formatDuration,
  type Artifact,
  type Browser,
  type ResultStatus,
  type TestResult,
} from "@/lib/types";

const ICON: Record<ResultStatus, string> = {
  passed: "✓",
  failed: "✕",
  error: "!",
  skipped: "–",
  flaky: "~",
};

export function ResultMatrix({ results }: { results: TestResult[] }) {
  // Everything starts closed.
  //
  // This used to open every failure automatically, on the reasoning that
  // someone looking at a red run came to read the error. That holds for one
  // failure and stops holding at five: the run expands into a page of stack
  // traces and analysis prose, and the list of which tests failed — the thing
  // you actually look at first — is pushed off the screen by the detail of the
  // first one. The row says what failed; opening it says why.
  const [openRows, setOpenRows] = useState<Set<number>>(() => new Set());

  // Group by test, keeping the order results arrived in.
  const byCase = new Map<string, TestResult[]>();
  for (const result of results) {
    const key = result.case_name || result.function_name;
    byCase.set(key, [...(byCase.get(key) ?? []), result]);
  }

  const browsers = [...new Set(results.map((r) => r.browser))];

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[32rem] border-separate border-spacing-0 text-sm">
        <thead>
          <tr className="border-b text-left text-xs text-muted-foreground">
            <th className="py-2 pr-3 font-medium">Test</th>
            {browsers.map((browser) => (
              <th key={browser} className="w-24 py-2 pr-3 font-medium">
                {BROWSER_LABEL[browser] ?? browser}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {[...byCase.entries()].map(([name, group]) => {
            const failure = group.find(
              (r) => r.status === "failed" || r.status === "error",
            );
            const expandable = Boolean(failure);
            const isOpen = expandable && openRows.has(group[0].id);

            return (
              <Fragment key={name}>
                <tr
                  className={`border-b ${expandable ? "cursor-pointer hover:bg-muted/50" : ""}`}
                  onClick={() =>
                    expandable &&
                    setOpenRows((current) => {
                      const next = new Set(current);
                      if (!next.delete(group[0].id)) next.add(group[0].id);
                      return next;
                    })
                  }
                >
                  <td className="py-2 pr-3">
                    <span className="flex items-center gap-1">
                      {expandable ? (
                        isOpen ? (
                          <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />
                        ) : (
                          <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" />
                        )
                      ) : (
                        <span className="size-3.5 shrink-0" />
                      )}
                      {name}
                    </span>
                  </td>

                  {browsers.map((browser) => {
                    const result = group.find((r) => r.browser === browser);
                    if (!result) {
                      return (
                        <td key={browser} className="py-2 pr-3 text-muted-foreground">
                          –
                        </td>
                      );
                    }
                    return (
                      <td key={browser} className="py-2 pr-3">
                        <Badge
                          tone={RESULT_BADGE[result.status]}
                          className="tabular"
                          title={result.error_message ?? result.status}
                        >
                          {/* A stopped run leaves results with no duration
                              recorded; "✓ -" is worse than just "✓". */}
                          {ICON[result.status]}
                          {result.duration_ms !== null &&
                            ` ${formatDuration(result.duration_ms)}`}
                        </Badge>
                      </td>
                    );
                  })}
                </tr>

                {isOpen && failure && (
                  <tr className="border-b bg-muted/30">
                    <td colSpan={browsers.length + 1} className="px-3 py-3">
                      <FailureDetail results={group} />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function FailureDetail({ results }: { results: TestResult[] }) {
  const failures = results.filter((r) => r.status === "failed" || r.status === "error");

  return (
    <div className="flex flex-col gap-4">
      {failures.map((result) => (
        <div key={result.id} className="flex flex-col gap-2">
          <p className="text-xs font-medium text-muted-foreground">
            {BROWSER_LABEL[result.browser as Browser] ?? result.browser}
            {result.failed_step !== null && ` · failed at step ${result.failed_step}`}
          </p>

          {result.error_message && (
            <p className="rounded-md border border-destructive/25 bg-destructive-subtle px-2.5 py-2 font-mono text-xs leading-relaxed text-destructive">
              {result.error_message}
            </p>
          )}

          <FailureAnalysis resultId={result.id} />

          <BugReport resultId={result.id} />

          {result.artifacts.length > 0 && <Evidence artifacts={result.artifacts} />}

          {result.stack_trace && (
            <details>
              <summary className="cursor-pointer text-xs text-muted-foreground">
                Full trace
              </summary>
              <pre className="mt-1.5 max-h-64 overflow-auto rounded-md bg-[#0b1220] p-3 font-mono text-xs leading-relaxed text-slate-200">
                {result.stack_trace}
              </pre>
            </details>
          )}
        </div>
      ))}
    </div>
  );
}

/** Screenshot and video for one failure.
 *
 *  Artifacts need the auth header, so they are fetched as blobs rather than
 *  linked directly. Every object URL is revoked on unmount or the browser
 *  leaks the whole video.
 */
function Evidence({ artifacts }: { artifacts: Artifact[] }) {
  const [urls, setUrls] = useState<Record<number, string>>({});

  useEffect(() => {
    let cancelled = false;
    const created: string[] = [];

    void (async () => {
      for (const artifact of artifacts) {
        if (artifact.type !== "screenshot" && artifact.type !== "video") continue;
        try {
          const url = await fetchArtifact(artifact.id);
          created.push(url);
          if (cancelled) return;
          setUrls((current) => ({ ...current, [artifact.id]: url }));
        } catch {
          /* a missing artifact is not worth breaking the panel over */
        }
      }
    })();

    return () => {
      cancelled = true;
      created.forEach((url) => URL.revokeObjectURL(url));
    };
  }, [artifacts]);

  const screenshots = artifacts.filter((a) => a.type === "screenshot");
  const videos = artifacts.filter((a) => a.type === "video");

  return (
    <div className="flex flex-wrap gap-3">
      {screenshots.map((artifact) => (
        <figure key={artifact.id} className="max-w-sm">
          <figcaption className="mb-1 flex items-center gap-1 text-xs text-muted-foreground">
            <ImageIcon className="size-3" />
            What the page looked like
          </figcaption>
          {urls[artifact.id] ? (
            /* eslint-disable-next-line @next/next/no-img-element -- blob URL, not a static asset */
            <img
              src={urls[artifact.id]}
              alt="Screenshot at the moment the test failed"
              className="rounded border"
            />
          ) : (
            <div className="h-32 w-64 animate-pulse rounded border bg-muted" />
          )}
        </figure>
      ))}

      {videos.map((artifact) => (
        <figure key={artifact.id} className="max-w-sm">
          <figcaption className="mb-1 flex items-center gap-1 text-xs text-muted-foreground">
            <Video className="size-3" />
            Recording of the run
          </figcaption>
          {urls[artifact.id] ? (
            <video src={urls[artifact.id]} controls className="w-full rounded border" />
          ) : (
            <div className="h-32 w-64 animate-pulse rounded border bg-muted" />
          )}
        </figure>
      ))}
    </div>
  );
}
