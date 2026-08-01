"use client";

/** Where a suite's scripts are on disk, and how to open them.
 *
 *  Lifted out of the old suite page when that page was replaced by the
 *  workspace. Unchanged otherwise — it was the one part of that screen
 *  nobody had a complaint about.
 */

import { useState } from "react";
import { Check, Copy, FolderOpen } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Alert,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

/** Where the scripts live, and how to open them. */
export function ScriptLocation({
  outputDir,
  paths,
}: {
  outputDir: string | null;
  paths: string[];
}) {
  const [copied, setCopied] = useState<string | null>(null);

  async function copy(text: string, key: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(key);
      setTimeout(() => setCopied(null), 1500);
    } catch {
      /* clipboard blocked - the text is selectable anyway */
    }
  }

  if (!outputDir) {
    return (
      <Alert>
        The scripts could not be written to disk. They are still stored and will
        run, but there is no folder to open.
      </Alert>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FolderOpen className="size-4" />
          Scripts
        </CardTitle>
        <CardDescription>
          Written to disk. Open the folder in VS Code to review or edit them.
        </CardDescription>
      </CardHeader>

      <CardContent className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <code className="min-w-0 flex-1 truncate rounded bg-muted px-2 py-1.5 font-mono text-xs">
            {outputDir}
          </code>
          <Button
            variant="outline"
            size="sm"
            onClick={() => copy(outputDir, "path")}
            className="shrink-0"
          >
            {copied === "path" ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
            Path
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => copy(`code "${outputDir}"`, "cmd")}
            className="shrink-0"
            title="Copy a terminal command that opens this folder in VS Code"
          >
            {copied === "cmd" ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
            code command
          </Button>
        </div>

        <ul className="flex flex-col gap-0.5">
          {paths.map((path) => (
            <li key={path} className="font-mono text-xs text-muted-foreground">
              {path}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
