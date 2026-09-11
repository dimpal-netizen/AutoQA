"use client";

import { useCallback, useEffect, useState } from "react";
import { Check, Download, Puzzle, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import { extension, extensionDownloadUrl, type ExtensionPing } from "@/lib/extension";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

/** What this browser has installed, checked by asking the extension itself.
 *
 *  `undefined` while asking, `null` when nothing answered. Re-asks when the
 *  tab regains focus, which is the moment after somebody has been over in
 *  chrome://extensions loading it. */
export function useExtension() {
  const [installed, setInstalled] = useState<ExtensionPing | null | undefined>(undefined);

  const check = useCallback(() => {
    void extension
      .detect()
      .then((found) => setInstalled(found))
      .catch(() => setInstalled(null));
  }, []);

  useEffect(() => {
    // The answer arrives by postMessage, so this is a subscription to the
    // extension rather than a synchronous state change.
    let cancelled = false;
    void extension
      .detect()
      .then((found) => !cancelled && setInstalled(found))
      .catch(() => !cancelled && setInstalled(null));
    window.addEventListener("focus", check);
    return () => {
      cancelled = true;
      window.removeEventListener("focus", check);
    };
  }, [check]);

  return { installed, recheck: check };
}

/** Compare "1.2.3" strings. */
function olderThan(installed: string, available: string): boolean {
  const a = installed.split(".").map(Number);
  const b = available.split(".").map(Number);
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const x = a[i] ?? 0;
    const y = b[i] ?? 0;
    if (x !== y) return x < y;
  }
  return false;
}

/** Download button plus the install steps. Shown wherever recording needs
 *  the extension and this browser does not have it - and on /extension, where
 *  the steps are the whole page. */
export function ExtensionSetup({
  installed,
  onRecheck,
  compact = false,
}: {
  installed: ExtensionPing | null | undefined;
  onRecheck?: () => void;
  compact?: boolean;
}) {
  const [available, setAvailable] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void api.extension
      .info()
      .then((info) => !cancelled && setAvailable(info.version))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const needsUpdate =
    installed && available ? olderThan(installed.version, available) : false;

  return (
    <Card className="mb-6 shadow-md">
      <CardHeader className="flex-row flex-wrap items-start gap-3">
        <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary-subtle text-primary">
          <Puzzle className="size-4.5" />
        </div>
        <div className="min-w-0 flex-1">
          <CardTitle className="flex flex-wrap items-center gap-2">
            Record from your own browser
            {installed === undefined ? null : installed ? (
              <Badge tone={needsUpdate ? "warning" : "success"}>
                <Check />
                Installed v{installed.version}
                {needsUpdate && ` · v${available} available`}
              </Badge>
            ) : (
              <Badge tone="neutral">Not detected</Badge>
            )}
          </CardTitle>
          {installed === null && (
            <p className="mt-1.5 text-xs text-muted-foreground">
              Just loaded it? Chrome only adds an extension to pages opened
              after it was installed —{" "}
              <button
                type="button"
                className="text-primary underline-offset-4 hover:underline"
                onClick={() => window.location.reload()}
              >
                reload this page
              </button>
              .
            </p>
          )}
          <CardDescription className="mt-1.5">
            The AutoQA Recorder is a small Chrome extension. Add it once, then
            every recording opens in a normal Chrome tab on this computer — use
            the site as you always do and the test is written when you stop.
          </CardDescription>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <a href={extensionDownloadUrl()} download>
            <Button variant={installed && !needsUpdate ? "outline" : "default"} size="sm">
              <Download />
              {needsUpdate ? `Download v${available}` : "Download extension"}
            </Button>
          </a>
          {onRecheck && (
            <Button variant="ghost" size="sm" onClick={onRecheck} aria-label="Check again">
              <RefreshCw />
            </Button>
          )}
        </div>
      </CardHeader>

      {(!compact || !installed || needsUpdate) && (
        <CardContent className="pt-0">
          <ol className="grid gap-2 text-[13px] leading-relaxed text-muted-foreground sm:grid-cols-2">
            <Step n={1}>
              <b className="text-foreground">Download</b> the extension and unzip it
              into a folder you will keep — Chrome loads it from there. Replacing the
              files in that folder is how you update later.
            </Step>
            <Step n={2}>
              In Chrome, open <Code>chrome://extensions</Code> (Edge:{" "}
              <Code>edge://extensions</Code>) and turn on{" "}
              <b className="text-foreground">Developer mode</b>, top right.
            </Step>
            <Step n={3}>
              Click <b className="text-foreground">Load unpacked</b> and choose the
              unzipped <Code>autoqa-recorder</Code> folder.
              {needsUpdate && (
                <>
                  {" "}
                  Already loaded? Press <b className="text-foreground">↻ Reload</b> on its card instead.
                </>
              )}
            </Step>
            <Step n={4}>
              Click the puzzle icon in Chrome&apos;s toolbar and pin{" "}
              <b className="text-foreground">AutoQA Recorder</b>. Come back here — the
              badge above turns green.
            </Step>
          </ol>
          <p className="mt-3 text-xs text-muted-foreground">
            Chrome may ask about developer-mode extensions when it starts; that is
            expected for an extension installed this way — close the message.
            Works in Chrome, Edge and Brave.
          </p>
        </CardContent>
      )}
    </Card>
  );
}

function Step({ n, children }: { n: number; children: React.ReactNode }) {
  return (
    <li className="flex gap-2.5 rounded-md border border-border bg-muted/30 px-3 py-2.5">
      <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-primary text-[11px] font-semibold text-primary-foreground">
        {n}
      </span>
      <span>{children}</span>
    </li>
  );
}

function Code({ children }: { children: React.ReactNode }) {
  return (
    <code className="rounded bg-muted px-1 py-0.5 font-mono text-[12px] text-foreground">
      {children}
    </code>
  );
}
