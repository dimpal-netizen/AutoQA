"use client";

/** Files a test uploads, instead of a generated placeholder.
 *
 *  A browser never says where a chosen file lives, so a recording of somebody
 *  adding a property holds the name of their photograph and nothing else.
 *  AutoQA builds a plain 800x600 image in its place, which uploads correctly
 *  and gets past the form.
 *
 *  It is still a grey rectangle. A site that resizes the photograph, checks it,
 *  or shows it back on the listing afterwards deserves a photograph — and a
 *  test that asserts the gallery has images cannot be written against a
 *  rectangle. Upload a handful here and every upload step everywhere uses them,
 *  in turn, with no step pointed at a file by hand.
 *
 *  Shared by every project. A photograph is a photograph, and a copy per
 *  project would mean uploading the same six pictures again for each one.
 */

import { useEffect, useRef, useState } from "react";
import { ImagePlus, Loader2, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import type { SampleFile } from "@/lib/types";
import { Alert } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

/** "812 KB" — the size matters here because every one is copied into every run. */
function readableSize(bytes: number): string {
  return bytes >= 1024 * 1024
    ? `${(bytes / (1024 * 1024)).toFixed(1)} MB`
    : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

export function SampleFiles({ canEdit }: { canEdit: boolean }) {
  const picker = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<SampleFile[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api.sampleFiles
      .list()
      .then((found) => live && setFiles(found))
      .catch(() => live && setFiles([]));
    return () => {
      live = false;
    };
  }, []);

  async function add(chosen: FileList) {
    setBusy(true);
    setError(null);
    // One at a time so a rejected file names itself. Uploaded as a batch, "one
    // of these is too big" is a message nobody can act on.
    for (const file of Array.from(chosen)) {
      try {
        const saved = await api.sampleFiles.add(file);
        setFiles((current) => [...current, saved]);
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : String(cause));
      }
    }
    setBusy(false);
    if (picker.current) picker.current.value = "";
  }

  async function remove(file: SampleFile) {
    setError(null);
    try {
      await api.sampleFiles.remove(file.id);
      setFiles((current) => current.filter((f) => f.id !== file.id));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-muted-foreground">
          {files.length === 0
            ? "None yet — uploads use a generated placeholder image"
            : `${files.length} file${files.length === 1 ? "" : "s"}, used in turn`}
        </span>

        {canEdit && (
          <>
            <input
              ref={picker}
              type="file"
              multiple
              accept=".jpg,.jpeg,.png,.gif,.webp,.pdf,.txt,.csv"
              className="hidden"
              onChange={(event) => {
                if (event.target.files?.length) void add(event.target.files);
              }}
            />
            <Button
              variant="outline"
              size="sm"
              className="ml-auto"
              disabled={busy}
              title="Real photographs or documents for tests to upload"
              onClick={() => picker.current?.click()}
            >
              {busy ? <Loader2 className="animate-spin" /> : <ImagePlus />}
              {busy ? "Uploading…" : "Add files"}
            </Button>
          </>
        )}
      </div>

      {error && <Alert>{error}</Alert>}

      {files.length > 0 && (
        <ul className="flex flex-col divide-y rounded-lg border">
          {files.map((file) => (
            <li key={file.id} className="flex items-center gap-3 px-3 py-2 text-sm">
              <span className="flex-1 truncate">{file.filename}</span>
              <span className="tabular text-xs text-muted-foreground">
                {readableSize(file.size)}
              </span>
              {canEdit && (
                <button
                  type="button"
                  aria-label={`Remove ${file.filename}`}
                  className="text-muted-foreground transition-colors hover:text-destructive"
                  onClick={() => void remove(file)}
                >
                  <Trash2 className="size-4" />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
