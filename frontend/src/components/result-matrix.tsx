"use client";

/** The cross-browser matrix: one row per test, one column per browser.
 *
 *  This layout is the point of storing a result per (case, browser). A flat
 *  list would bury "passes in Chrome, fails in Safari" — the single most
 *  useful thing a cross-browser run can tell you — inside two similar-looking
 *  rows.
 */

import { Fragment, useEffect, useState } from "react";
import Link from "next/link";
import {
  ChevronRight,
  Image as ImageIcon,
  Maximize2,
  Video,
  X,
} from "lucide-react";
import { fetchArtifact } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import {
  BROWSER_LABEL,
  RESULT_BADGE,
  RESULT_LABEL,
  formatDuration,
  type Artifact,
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
  // A failure opens its own page rather than an extra row.
  //
  // It expanded inline for a long time, and each thing added to a failure made
  // that worse: the error, the explanation, the bug draft, the screenshot, the
  // recording, the trace, a box for asking questions. Six panels stacked inside
  // a table row, with the rest of the run's tests pushed off the screen below
  // them. Every one is worth having and none belongs in a row.
  //
  // The row says what failed. The page says why.

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

            return (
              <Fragment key={name}>
                <tr className={`border-b ${failure ? "hover:bg-muted/50" : ""}`}>
                  <td className="py-2 pr-3">
                    {failure ? (
                      // A link, not a click handler: a failure is a place, so
                      // it opens in a new tab on a middle click and can be sent
                      // to whoever should look at it.
                      <Link
                        href={`/results/${failure.id}`}
                        className="flex items-center gap-1 transition-colors hover:text-primary"
                      >
                        <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" />
                        {name}
                      </Link>
                    ) : (
                      <span className="flex items-center gap-1">
                        <span className="size-3.5 shrink-0" />
                        {name}
                      </span>
                    )}
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
                          title={`${RESULT_LABEL[result.status] ?? result.status}${
                            result.error_message ? ` - ${result.error_message}` : ""
                          }`}
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
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** Screenshot and video for one failure.
 *
 *  Artifacts need the auth header, so they are fetched as blobs rather than
 *  linked directly. Every object URL is revoked on unmount or the browser
 *  leaks the whole video.
 */
export function Evidence({ artifacts }: { artifacts: Artifact[] }) {
  const [urls, setUrls] = useState<Record<number, string>>({});
  // The screenshot being shown at full size, or null. Held here rather than per
  // figure so only one can be open at a time.
  const [zoomed, setZoomed] = useState<string | null>(null);

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
    <>
      {/* Thumbnails, not the pictures themselves.

          Shown at full size these ran the height of the screen each — a
          full-page screenshot of a sign-up form is two thousand pixels tall,
          and three of them pushed the trace and everything else off the page.
          Scaled down they are unreadable anyway, so the inline copy is a
          contact sheet: enough to tell one from another, one click to read. */}
      <div className="flex flex-wrap gap-3">
        {screenshots.map((artifact) => (
          <figure key={artifact.id} className="w-56">
            <figcaption className="mb-1 flex items-center gap-1 text-xs text-muted-foreground">
              <ImageIcon className="size-3 shrink-0" />
              What the page looked like
            </figcaption>
            {urls[artifact.id] ? (
              <button
                type="button"
                onClick={() => setZoomed(urls[artifact.id])}
                className="group relative block h-36 w-full overflow-hidden rounded border transition-colors hover:border-primary"
              >
                {/* Anchored to the top: the useful part of a full-page capture
                    is the form and the error above the fold, not the footer. */}
                {/* eslint-disable-next-line @next/next/no-img-element -- blob URL, not a static asset */}
                <img
                  src={urls[artifact.id]}
                  alt="Screenshot at the moment the test failed"
                  className="h-full w-full object-cover object-top"
                />
                <span className="absolute inset-0 flex items-center justify-center bg-black/0 text-xs font-medium text-white opacity-0 transition-all group-hover:bg-black/45 group-hover:opacity-100">
                  <Maximize2 className="mr-1 size-3.5" />
                  View full size
                </span>
              </button>
            ) : (
              <div className="h-36 w-full animate-pulse rounded border bg-muted" />
            )}
          </figure>
        ))}

        {videos.map((artifact) => (
          <figure key={artifact.id} className="w-56">
            <figcaption className="mb-1 flex items-center gap-1 text-xs text-muted-foreground">
              <Video className="size-3 shrink-0" />
              Recording of the run
            </figcaption>
            {urls[artifact.id] ? (
              // Kept as a player rather than a still: a recording with no
              // controls is a picture, and the controls are the point.
              <video
                src={urls[artifact.id]}
                controls
                className="h-36 w-full rounded border bg-black object-contain"
              />
            ) : (
              <div className="h-36 w-full animate-pulse rounded border bg-muted" />
            )}
          </figure>
        ))}
      </div>

      {zoomed && <Lightbox src={zoomed} onClose={() => setZoomed(null)} />}
    </>
  );
}

/** The screenshot at the size it was taken.
 *
 *  A full-page screenshot shown at column width is unreadable — the error
 *  message someone opened the failure to read is a few pixels tall. This shows
 *  it whole, scrollable, and gets out of the way on Escape or a click outside.
 */
function Lightbox({ src, onClose }: { src: string; onClose: () => void }) {
  useEffect(() => {
    function escape(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", escape);
    // The page behind must not scroll while this is over it.
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", escape);
      document.body.style.overflow = previous;
    };
  }, [onClose]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Screenshot at the moment the test failed"
      onClick={onClose}
      className="fixed inset-0 z-50 flex items-start justify-center overflow-auto bg-black/80 p-4 sm:p-8"
    >
      <button
        type="button"
        onClick={onClose}
        aria-label="Close"
        className="fixed right-4 top-4 z-10 rounded-full bg-white/10 p-2 text-white transition-colors hover:bg-white/20"
      >
        <X className="size-5" />
      </button>

      {/* eslint-disable-next-line @next/next/no-img-element -- blob URL, not a static asset */}
      <img
        src={src}
        alt="Screenshot at the moment the test failed"
        // Stops a click on the image itself from closing what it just opened.
        onClick={(event) => event.stopPropagation()}
        className="h-auto max-w-full rounded shadow-2xl"
      />
    </div>
  );
}
