"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input, Label, Textarea } from "@/components/ui/input";
import { Alert, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/** A practice page for the recorder.
 *
 *  Deliberately mixed markup: some controls have data-testid, some only a
 *  label, some only generated class names. That variety is the point — it
 *  shows which selector strategy the engine falls back to for each one. */
export default function DemoPage() {
  const [items, setItems] = useState(["Mechanical keyboard", "USB-C hub", "Monitor stand"]);
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [submitted, setSubmitted] = useState<string | null>(null);
  const [showMenu, setShowMenu] = useState(false);

  function handleDrop(target: number) {
    if (dragIndex === null || dragIndex === target) return;
    const next = [...items];
    const [moved] = next.splice(dragIndex, 1);
    next.splice(target, 0, moved);
    setItems(next);
    setDragIndex(null);
  }

  return (
    <main className="mx-auto max-w-3xl p-6">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold">Recorder practice page</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Every control below maps to one of the 13 action types. Start the recorder,
          interact with them, then stop and inspect what was captured.
        </p>
      </header>

      <Alert variant="info" className="mb-6">
        Paste into the DevTools console:{" "}
        <code className="font-mono text-xs">
          await import(&quot;http://localhost:3000/recorder.js&quot;)
        </code>
      </Alert>

      {/* click, input, check, key_press ---------------------------------- */}
      <Card className="mb-6">
        <CardHeader>
          <CardTitle>Sign in — click, input, check, key_press</CardTitle>
        </CardHeader>
        <CardContent>
          <form
            className="flex flex-col gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              setSubmitted("Signed in");
            }}
          >
            {/* has data-testid -> rank 1 */}
            <div className="flex flex-col gap-2">
              <Label htmlFor="demo-email">Email address</Label>
              <Input
                id="demo-email"
                data-testid="email-input"
                type="email"
                placeholder="you@company.com"
              />
            </div>

            {/* no testid, but a real label -> rank 3 */}
            <div className="flex flex-col gap-2">
              <Label htmlFor="demo-password">Password</Label>
              <Input id="demo-password" type="password" placeholder="••••••••" />
            </div>

            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" data-testid="remember-me" className="size-4" />
              Remember me
            </label>

            <div className="flex gap-2">
              <Button type="submit" data-testid="login-submit">
                Sign in
              </Button>
              {/* no testid, no label — falls back to role+name */}
              <Button type="button" variant="outline">
                Forgot password
              </Button>
            </div>
          </form>
          {submitted && <p className="mt-3 text-sm text-success">{submitted}</p>}
        </CardContent>
      </Card>

      {/* hover ------------------------------------------------------------ */}
      <Card className="mb-6">
        <CardHeader>
          <CardTitle>Menu — hover</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="mb-2 text-sm text-muted-foreground">
            Rest the pointer here for about a second. Hover needs a dwell, or every
            mouse movement would become an action.
          </p>
          <div
            className="relative inline-block"
            onMouseEnter={() => setShowMenu(true)}
            onMouseLeave={() => setShowMenu(false)}
          >
            <button
              type="button"
              aria-haspopup="true"
              data-testid="shop-menu"
              className="rounded-md border border-border px-4 py-2 text-sm"
            >
              Shop ▾
            </button>
            {showMenu && (
              <div className="absolute left-0 top-full z-10 mt-1 w-48 rounded-md border border-border bg-card p-1 shadow-lg">
                <a href="#shipping" className="block rounded px-3 py-2 text-sm hover:bg-accent">
                  Shipping details
                </a>
                <a href="#billing" className="block rounded px-3 py-2 text-sm hover:bg-accent">
                  Billing
                </a>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* select, upload, uncheck ------------------------------------------ */}
      <Card className="mb-6">
        <CardHeader>
          <CardTitle>Shipping — select, upload, uncheck</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="demo-country">Country</Label>
            <select
              id="demo-country"
              data-testid="country-select"
              defaultValue="IN"
              className="h-10 rounded-md border border-input bg-background px-3 text-sm"
            >
              <option value="IN">India</option>
              <option value="US">United States</option>
              <option value="GB">United Kingdom</option>
            </select>
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="demo-address">Address line 1</Label>
            <Textarea id="demo-address" placeholder="42 Example Street" />
          </div>

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              data-testid="billing-same"
              defaultChecked
              className="size-4"
            />
            Billing address is the same
          </label>

          <div className="flex flex-col gap-2">
            <Label htmlFor="demo-file">GST certificate</Label>
            <input
              id="demo-file"
              data-testid="gst-certificate"
              type="file"
              className="text-sm file:mr-3 file:rounded-md file:border-0 file:bg-secondary file:px-3 file:py-2 file:text-sm"
            />
          </div>
        </CardContent>
      </Card>

      {/* drag_drop, double_click ------------------------------------------ */}
      <Card className="mb-6">
        <CardHeader>
          <CardTitle>Cart — drag_drop, double_click</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="mb-3 text-sm text-muted-foreground">
            Drag a row to reorder it. Double-click a quantity box.
          </p>
          <ul id="cart" className="flex flex-col gap-2">
            {items.map((item, index) => (
              <li
                key={item}
                data-testid={`cart-item-${index + 1}`}
                draggable
                onDragStart={() => setDragIndex(index)}
                onDragOver={(e) => e.preventDefault()}
                onDrop={() => handleDrop(index)}
                className="flex cursor-grab items-center justify-between rounded-md border border-border px-3 py-2 text-sm"
              >
                <span>{item}</span>
                <input
                  type="number"
                  data-testid={`quantity-${index + 1}`}
                  defaultValue={1}
                  min={1}
                  aria-label={`Quantity for ${item}`}
                  className="w-16 rounded border border-input bg-background px-2 py-1 text-sm"
                />
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>

      {/* assert + scroll --------------------------------------------------- */}
      <Card className="mb-6">
        <CardHeader>
          <CardTitle>Confirmation — assert</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="mb-3 text-sm text-muted-foreground">
            Press <kbd className="rounded border border-border px-1">Alt</kbd>+
            <kbd className="rounded border border-border px-1">A</kbd>, then click the
            banner below to record an assertion instead of a click.
          </p>
          <div
            data-testid="order-confirmation"
            role="status"
            className="rounded-md border border-success/40 bg-success/10 px-4 py-3 text-sm text-success"
          >
            Thank you! Your order is confirmed.
          </div>
        </CardContent>
      </Card>

      {/* Tall spacer so there is something to scroll. */}
      <div className="h-[80vh]" aria-hidden />
      <p id="shipping" className="pb-10 text-sm text-muted-foreground">
        Scroll down to here — the recorder captures one scroll action per gesture,
        not one per pixel.
      </p>
    </main>
  );
}
