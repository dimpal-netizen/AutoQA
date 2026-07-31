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
| `frame_path` | | iframe chain, outermost first. `[]` for the main frame |
| `selectors` | see below | Ranked candidates |
| `element` | | Snapshot of the element for readable descriptions |
| `payload` | see below | Action-specific data |

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
- `unique: false` means the selector matched more than one element when recorded — a
  strong hint the generated test will be flaky.
- **Reject generated ids.** `#\:r1\:`, `#ember1234`, and long hashes change on every
  build. Emit them as `nth_child` at best, never as `css_id`.

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
