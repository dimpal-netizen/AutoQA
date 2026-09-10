# Recording JSON format

**This is the contract between the Chrome extension and the backend.** The extension
(Phase 9) is written to match it. Adding optional fields is safe; renaming or removing
anything means shipping a new extension at the same time.

Defined in [`backend/app/schemas/recording.py`](../backend/app/schemas/recording.py).
Reference payload: [`backend/tests/fixtures/sample_recording.json`](../backend/tests/fixtures/sample_recording.json).

---

## The flow

```
POST /api/v1/projects/{project_id}/recordings   → start, returns {id}
POST /api/v1/recordings/{id}/actions            → upload a batch (repeat while recording)
POST /api/v1/recordings/{id}/stop               → finalise
```

Actions are uploaded **as you record**, not all at once at the end. If the browser
crashes mid-session, whatever was already uploaded survives.

---

## 1. Start a session

```json
{
  "name": "Checkout flow",
  "start_url": "https://shop.example.com/login",
  "extension_version": "0.1.0",
  "browser_info": {
    "user_agent": "Mozilla/5.0 ...",
    "viewport": { "width": 1440, "height": 900 },
    "device_pixel_ratio": 2,
    "platform": "Win32"
  }
}
```

Everything under `browser_info` is optional.

## 2. Upload actions

```json
{ "actions": [ /* up to 500 per batch */ ] }
```

Response:

```json
{ "stored": 8, "skipped_duplicates": 0, "action_count": 8 }
```

**Uploads are idempotent.** An action whose `sequence` already exists is skipped, not
duplicated, so a batch can safely be retried after a dropped connection. That's what
`skipped_duplicates` reports.

## 3. Stop

```json
{ "duration_ms": 30500 }
```

Omit `duration_ms` and the backend uses the last action's `timestamp_ms`.

---

## The action object

```json
{
  "sequence": 2,
  "action_type": "input",
  "timestamp_ms": 2650,
  "url": "https://shop.example.com/login",
  "frame_path": [],
  "selectors": [ /* ranked, best first */ ],
  "element": { /* what it looked like */ },
  "payload": { "value": "buyer@example.com" }
}
```

| Field | Required | Notes |
|---|---|---|
| `sequence` | ✅ | 0-based, unique within the session. This is the idempotency key |
| `action_type` | ✅ | One of the 13 below |
| `timestamp_ms` | ✅ | Milliseconds since the recording started |
| `url` | ✅ | Page URL when the action happened |
| `frame_path` | | The frames between the page and the element, outermost first. `[]` for the main frame, which is almost every element. See below |
| `selectors` | see below | Ranked candidates |
| `element` | | Snapshot of the element for readable descriptions |
| `payload` | see below | Action-specific data |
| `response` | | What the application said back. See below. Optional everywhere |

### Action types and payloads

| `action_type` | Payload | Needs a selector |
|---|---|---|
| `click` | `{}` | ✅ |
| `double_click` | `{}` | ✅ |
| `hover` | `{}` | ✅ |
| `check` / `uncheck` | `{}` | ✅ |
| `input` | `{"value": "text"}` | ✅ |
| `select` | `{"values": ["IN"]}` | ✅ |
| `upload` | `{"files": ["doc.pdf"]}` | ✅ |
| `drag_drop` | `{"target_selectors": [Selector]}` | ✅ |
| `assert` | `{"kind": "to_be_visible", "expected": true}` | ✅ |
| `navigate` | `{"url": "https://..."}` | — |
| `scroll` | `{"x": 0, "y": 640}` | — |
| `key_press` | `{"key": "Tab", "modifiers": []}` | optional |

A payload missing a required key is rejected with **422**. This is deliberate: a
half-recorded action should fail loudly at upload rather than silently produce a
broken test three phases later.

### Selectors — always a ranked list, never one string

This is the single most important design decision in the recording format. Recording
one selector per element is what makes recorded tests disposable; the moment the UI
changes, they all break. Recording several means the fallbacks are already on hand.

```json
"selectors": [
  { "strategy": "test_id", "value": "login-submit", "unique": true, "score": 99 },
  { "strategy": "role_name", "value": "button|Sign in", "unique": true, "score": 95 },
  { "strategy": "text", "value": "Sign in", "unique": true, "score": 80 }
]
```

| Rank | `strategy` | Becomes | Reliability |
|---|---|---|---|
| 1 | `test_id` | `page.get_by_test_id("login-submit")` | Survives redesigns |
| 2 | `role_name` | `page.get_by_role("button", name="Sign in")` | Very good |
| 3 | `label` | `page.get_by_label("Email")` | Very good |
| 4 | `placeholder` | `page.get_by_placeholder("you@company.com")` | Good |
| 5 | `text` | `page.get_by_text("Sign in", exact=True)` | Breaks on copy edits |
| 6 | `css_id` | `page.locator("#email")` | Only if hand-written, not generated |
| 7 | `css` | `page.locator("form.login input")` | Breaks on restructuring |
| 8 | `xpath` | `page.locator("xpath=...")` | Fragile |
| 9 | `nth_child` | positional | Last resort — flagged as fragile |

`role_name` uses the form `"role|accessible name"`.

Notes:

- **The backend re-sorts by strategy on ingest**, so the order you send doesn't matter
  and a buggy extension build can't promote a bad selector by inflating `score`.
- `score` (0–100) only breaks ties between candidates of the same strategy.
- `unique: false` means the selector matched more than one element when recorded. It
  is a hint that the generated test may be flaky — and, when the selector is built out
  of class names rather than positions, it is also how the backend knows the element is
  one of a *set*: a row, a card, a slot. That is what lets a test whose recorded item is
  no longer available try a comparable one. See `backend/app/codegen/dataroles.py`.
- **Reject generated ids.** `#\:r1\:`, `#ember1234`, and long hashes change on every
  build. Emit them as `nth_child` at best, never as `css_id`.

### Frames

An element inside an `<iframe>` is meaningless without the frames above it, so
each one is *described* rather than pointed at:

```json
"frame_path": [
  { "name": "checkout", "title": "Checkout", "index": 0 },
  { "src": "https://pay.example.com/widget?session=abc",
    "url": "https://pay.example.com/widget/card", "index": 1 }
]
```

| Field | Notes |
|---|---|
| `name` | The `name` attribute — a developer's own handle on the frame |
| `title` | The `title` attribute |
| `element_id` | The `id`, unless it looks build-generated |
| `src` | What the frame loads. Matched on its path, so a session token in the query does not make it a different frame |
| `url` | Where the frame had got to, which is not always its `src` |
| `index` | Position among its siblings. **A fallback, never a first choice** |

The generator picks the first of `name`, `title`, `element_id`, `src` that is
present, and falls back to the index. The order is about who decided the value:
the first three are choices somebody made about *that* frame, `src` is a fact
about it, and an index is a fact about its **neighbours** — a page that gains a
chat widget renumbers every frame after it.

A list of plain strings is also accepted and treated as literal iframe
selectors. That is what every recording made before frames were captured
carries, and since the only value ever sent was `[]`, it is a promise about
nothing.

**Who fills this in.** In browser-recorder mode, the *backend* does, from
Playwright's own view of which frame a message arrived from. A script inside a
cross-origin frame cannot see the document that holds it — `window.frameElement`
throws, by design, and that design is a browser security boundary. Playwright
sits outside it and can see both sides.

### What the application said back

```json
"response": {
  "kind": "dialog_opened",
  "url": "https://shop.example.com/signup",
  "navigated": false,
  "title_changed": false,
  "dialog_opened": true,
  "dialog_closed": false,
  "mutations": 37,
  "settled_ms": 412,
  "messages": []
}
```

Optional, and optional in every part. Absent on recordings made before it was
captured, and absent on any action whose page navigated before the reply
arrived — so nothing downstream may require it.

Why it exists: a recording of what somebody *did* is only half of what happened.
Without the other half, an address that must be new on every run looks exactly
like one that must already exist, because from a list of clicks and keystrokes
the two are identical. That is what makes a recorded test pass once and fail for
ever after — it replays data the application is right to refuse.

| Field | Notes |
|---|---|
| `kind` | What happened, in one word. See below |
| `url` | Where the page was ~1s after the action |
| `navigated` | Whether that differs from the action's own `url` |
| `title_changed` | Whether `document.title` changed |
| `dialog_opened` / `dialog_closed` | Change in visible `dialog[open]`, `[role=dialog]`, `[role=alertdialog]` |
| `mutations` | DOM mutations the action set off. `0` means nothing moved |
| `settled_ms` | How long after the action the observation was taken |
| `messages` | Text that *appeared* because of this action, up to 32 entries |

`kind` is the decisive observation, and the generator turns it directly into
what the test waits for:

| `kind` | The test waits for |
|---|---|
| `navigated` | the recorded address, or any address but the one it was on |
| `dialog_opened` | a dialog to become visible |
| `dialog_closed` | the dialog to go |
| `messages` | the sentence the application put on screen |
| `dom_changed` | the DOM to stop changing |
| `quiet` | **nothing** — the action changed nothing a browser could see |

The order matters: a click that navigates also mutates the DOM, so the most
decisive answer wins and the rest are kept as detail. `quiet` is a real answer
rather than a failure to find one — a test that insists on waiting for something
after an action that did nothing waits for ever.

**A click that navigates never gets to run the observation timer.** The page is
torn down first. The recorder handles this on `pagehide`: any action still
waiting to hear back when the page goes away *navigated*, which is what a
navigation looks like from inside the page it leaves. That same handler flushes
the upload queue — without it, actions recorded in the two seconds before a
navigation were lost with the page, and the action most likely to be lost was
the click that caused it.

`messages` is collected by shape, never by meaning: elements with an alert role,
a live region, or a class containing `error`/`message`/`alert`. Only text that
was not on screen before the action is included — a form already showing
"Required" on three fields must not report them as the answer to every keystroke
after it. Reading which of them is a *refusal* happens in the backend.

Emitting `response` for an action means the extension must hold that action back
briefly rather than uploading it immediately. One batch tick of latency on the
most recent action; nothing else changes.

### Element snapshot

```json
"element": {
  "tag": "button",
  "input_type": "submit",
  "role": "button",
  "accessible_name": "Sign in",
  "text": "Sign in",
  "attributes": { "data-testid": "login-submit" },
  "bounding_box": { "x": 520, "y": 280, "width": 400, "height": 44 }
}
```

All fields optional. Used for human-readable step descriptions in the UI, and in
Phase 7 to re-find an element whose selector has drifted.

`attributes` should carry, where the element has them: `id`, `name`, `class`,
`type`, `href`, `data-testid`, `placeholder`, `autocomplete`, `pattern`,
`required`, `maxlength`, `minlength`.

The last five are the field describing *itself*, in a vocabulary the HTML spec
fixed and every site shares — which is what lets the backend tell a value that
has to be new on every run from one that has to already exist, without knowing
anything about the application. Omitting them is safe; it only means the backend
has less to go on and falls back to replaying the recorded value.

---

## Testing without the extension

The extension doesn't exist until Phase 9, so use the seed script — it drives the
same endpoints, in the same order, with the same payloads:

```bash
cd backend
python scripts/seed_recording.py
```

It registers a user, creates a project, uploads the fixture in batches of 8, retries a
batch to demonstrate idempotency, and stops the recording.
