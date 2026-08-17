"use client";

/** Files tests upload when a form asks for one.
 *
 *  A browser never says where a chosen file lives, so a recording of somebody
 *  adding a property holds the name of their photograph and nothing else.
 *  AutoQA builds a plain 800x600 image in its place, which uploads correctly
 *  and gets past the form — but it is a grey rectangle, so a listing that shows
 *  its photographs back has nothing to show, and a test checking the gallery
 *  cannot be written against it.
 *
 *  Here rather than buried in one project's page because this is set up once
 *  and then forgotten — and because it is shared, so it belongs to no single
 *  project. A photograph is a photograph.
 */

import { hasRole } from "@/lib/types";
import { useAuthStore } from "@/stores/auth-store";
import { AppShell } from "@/components/app-shell";
import { RequireAuth } from "@/components/auth-provider";
import { SampleFiles } from "@/components/sample-files";


export default function SampleFilesPage() {
  return (
    <RequireAuth>
      <AppShell wide>
        <Library />
      </AppShell>
    </RequireAuth>
  );
}

function Library() {
  const user = useAuthStore((s) => s.user);

  return (
    <div className="animate-in flex flex-col gap-6">
      <header>
        <h1 className="text-2xl font-bold leading-tight tracking-tight">
          Sample files
        </h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          What a test uploads when a form asks for a file. Shared by every
          project, and used in turn — so a listing form asking for six
          photographs gets six different ones. Without any, uploads use a
          generated placeholder image.
        </p>
      </header>

      <SampleFiles canEdit={hasRole(user, "qa_engineer")} />
    </div>
  );
}
