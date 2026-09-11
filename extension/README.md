# AutoQA Recorder — Chrome extension

The recorder, running in the tester's own browser. Nothing is installed on the
server side and nothing runs there but the API: the tester adds this to Chrome
once, and every recording after that is a click on the toolbar icon.

Testers do not read this file. They download the extension from the AutoQA web
app (**Recordings → Download extension**), which serves a zip built from this
folder plus the backend's `recorder.js` and a `config.js` naming that server.
The install steps are on the app's `/extension` page.

## How it fits together

```
page (any site)               extension                          server
──────────────────────        ─────────────────────────────      ─────────────
recorder.js  ── bridge ──▶  content-main.js   (page world)
                             ⇅ postMessage
                            content-relay.js  (isolated world)
                             ⇅ runtime.sendMessage
                            background.js     (service worker)  ── HTTPS ──▶  /api/v1
popup.html / popup.js  ──────┘
```

- `recorder.js` is **unchanged** from `backend/app/static/recorder.js`. It runs
  in the same "bridge" mode it runs in when Playwright injects it on the server;
  `content-main.js` simply provides `window.__autoqaBridge`.
- `background.js` answers the recorder's three messages — `hello`, `actions`,
  `stop` — by calling the API with the tester's sign-in, which is what
  `backend/app/services/browser_recorder.py` does against the database.
- The AutoQA web app can also start a recording through the extension
  (**Start recording** on a project page): it hands over its own sign-in and
  the extension opens the URL in a new tab.

## Working on it

```
cd backend && poetry run python ../extension/build.py   # writes recorder.js + config.js
```

then `chrome://extensions` → Developer mode → Load unpacked → this folder.
After editing, press ↻ on the extension's card. `build.py` again after changing
`recorder.js` in the backend.

Bump `version` in `manifest.json` for every change testers should pick up; the
web app compares it with what is installed and offers the download.
