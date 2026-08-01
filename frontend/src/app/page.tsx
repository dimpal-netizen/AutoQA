"use client";

/** The public front door.
 *
 *  Signed in or out, this renders the home page. It used to bounce anyone with
 *  a session straight to /dashboard, which meant that once you logged in the
 *  site itself became unreachable — you could never look at the pricing or the
 *  FAQ again without signing out. The header adapts instead: signed in, it
 *  offers the dashboard rather than a login form.
 */

import { Marketing } from "@/components/marketing";

export default function Home() {
  return <Marketing />;
}
