"use client";

/** The Chrome extension: download, install steps, and whether this browser
 *  has it. Linked from wherever recording is offered and the extension is
 *  missing, and from the Recordings page for anyone setting up a new machine.
 */

import Link from "next/link";
import { Video } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { RequireAuth } from "@/components/auth-provider";
import { ExtensionSetup, useExtension } from "@/components/extension-setup";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, PageHeader } from "@/components/ui/card";

export default function ExtensionPage() {
  return (
    <RequireAuth>
      <AppShell>
        <Extension />
      </AppShell>
    </RequireAuth>
  );
}

function Extension() {
  const { installed, recheck } = useExtension();

  return (
    <div className="animate-in">
      <PageHeader
        title="AutoQA Recorder for Chrome"
        description="Recordings are made in your own browser. Install the extension once on each computer you record from; there is nothing to install on the server and nothing to configure."
      >
        {installed && (
          <Link href="/projects">
            <Button>
              <Video />
              Start recording
            </Button>
          </Link>
        )}
      </PageHeader>

      <ExtensionSetup installed={installed} onRecheck={recheck} />

      <Card>
        <CardHeader>
          <CardTitle>How recording works</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 text-[13px] leading-relaxed text-muted-foreground sm:grid-cols-3">
          <div>
            <p className="font-medium text-foreground">From a project</p>
            Open a project, press <b>Record a session</b> and enter the URL. A new
            Chrome tab opens with the recorder running. You do not need to sign in
            to the extension — it uses your AutoQA session.
          </div>
          <div>
            <p className="font-medium text-foreground">From any site</p>
            On the site you want to test, click the AutoQA icon in the toolbar,
            pick the project and press <b>Start recording</b>. The first time, it
            asks for your AutoQA email and password.
          </div>
          <div>
            <p className="font-medium text-foreground">Stopping</p>
            Press <b>Stop</b> in the small panel on the page, in the toolbar popup,
            or here in AutoQA — or just close the tab. The test suite is generated
            on the server and appears in the project.
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
