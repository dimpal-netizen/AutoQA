# Deploying AutoQA

One virtual machine, Docker Compose, a reverse proxy in front. That shape is
not a starting point to grow out of — it is what the architecture asks for, and
the reason is in [Why one machine](#why-one-machine) below.

---

## Contents

1. [What you need](#1-what-you-need)
2. [The recording problem, and what is done about it](#2-the-recording-problem-and-what-is-done-about-it)
3. [Deploy](#3-deploy)
4. [Reverse proxy and TLS](#4-reverse-proxy-and-tls)
5. [Disk](#5-disk)
6. [Upgrading](#6-upgrading)
7. [Why one machine](#7-why-one-machine)
8. [When something goes wrong](#8-when-something-goes-wrong)

---

## 1. What you need

| | |
|---|---|
| A Linux VM | 4 vCPU, 8 GB RAM, 100 GB disk to start. See [Disk](#5-disk). |
| Docker | With the Compose plugin. |
| A domain | Pointed at the VM, for TLS. |

Three browsers and their libraries make the API image about 3 GB. The build
takes ten to fifteen minutes the first time and is cached afterwards.

---

## 2. The recording problem, and what is done about it

Running a test is headless. **Recording is not.** `launch_recorder` opens a real
browser window that a person clicks around in, and a server has no screen for
that window to open on.

So the image carries a virtual one. Xvfb provides the screen, x11vnc publishes
it, and noVNC serves it to a browser tab: the QA engineer presses Record in the
web app, opens the recording screen, and drives the server's browser from their
own machine.

**The recording screen has no password on it.** Anyone who can reach port 29383
can drive that browser, and that browser is signed in to whatever the engineer
signed in to. Compose binds it to `127.0.0.1`, so it is reachable only through
the reverse proxy — put authentication in front of it, or keep it on a private
network, or turn it off.

To turn it off, set `AUTOQA_VIRTUAL_DISPLAY=0`. Recording then fails on this
deployment, and everything else — execution, reports, history — still works.
That is the right setting when recordings are made on laptops and only run on
the server.

---

## 3. Deploy

```bash
git clone <your-repo> autoqa && cd autoqa
cp .env.production.example .env.production
```

Fill in `.env.production`. Four values have no usable default:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"          # SECRET_KEY
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # ENCRYPTION_KEY
```

and `POSTGRES_PASSWORD`, plus the two addresses:

```
NEXT_PUBLIC_API_URL=https://autoqa.example.com/api/v1
CORS_ORIGINS=https://autoqa.example.com
```

`NEXT_PUBLIC_API_URL` is **compiled into the frontend**, not read at run time.
It has to be the address a visitor's browser can reach — not a container name,
not localhost. Change it later and you must rebuild, not restart.

Then:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

Migrations run on every start, from the entrypoint. There is no separate step
and there should not be one: a dangling Alembic pointer is invisible until a
recording quietly fails to save.

Check it:

```bash
curl -fsS localhost:29381/health
docker compose -f docker-compose.prod.yml logs -f api
```

---

## 4. Reverse proxy and TLS

Nothing is published to the outside world by Compose — the API, the web app and
the recording screen are all bound to `127.0.0.1`. The proxy is what makes any
of them reachable, which makes it the only place access is controlled.

A ready config is at [`docker/nginx/autoqa.conf`](../docker/nginx/autoqa.conf).
Replace `autoqa.example.com` throughout, then:

```bash
sudo apt install nginx certbot python3-certbot-nginx apache2-utils

# The password for the recording screen. It has none of its own — see section 2.
sudo htpasswd -c /etc/nginx/.htpasswd-autoqa qa

sudo cp docker/nginx/autoqa.conf /etc/nginx/sites-available/autoqa
sudo ln -s /etc/nginx/sites-available/autoqa /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default        # it also listens on 80

# Certificates BEFORE the first reload: the config names paths that do not
# exist yet, and nginx refuses to start on a missing certificate.
sudo certbot --nginx -d autoqa.example.com

sudo nginx -t && sudo systemctl reload nginx
```

Certbot installs its own renewal timer; nothing else to do.

What the config handles, and why each part is there:

| Route | Goes to | Why it needs saying |
|---|---|---|
| `/api/` | `:29381` | `proxy_buffering off` — artifacts are streamed by `FileResponse` and a trace runs to tens of megabytes. With buffering on, nginx spools the whole file before sending a byte and a download looks like a hang. 300s timeouts, because generating a suite calls an AI provider. |
| `/health` | `:29381` | Kept off the API prefix so uptime checks do not depend on the version. |
| `/static/` | `:29381` | `recorder.js`, injected into recorded pages. |
| `/record/` | `:29383` | Basic auth, plus `Upgrade`/`Connection` headers — noVNC is a WebSocket, and without them it connects, gets plain HTTP, and shows a blank grey canvas for ever with nothing in any log. 1 hour timeouts, because a recording session lasts as long as the person clicking. |
| `/` | `:29382` | The web app. |

Also set: `client_max_body_size 64m`. nginx defaults to 1 MB, and test-case
spreadsheets are uploaded through the API — over the limit, nginx returns 413
without the request ever reaching the application, so the UI reports a failure
the API logs know nothing about.

If you set `AUTOQA_VIRTUAL_DISPLAY=0`, delete the `/record/` block.

<details>
<summary>Caddy instead</summary>

```caddy
autoqa.example.com {
	handle /api/*    { reverse_proxy 127.0.0.1:29381 }
	handle /health   { reverse_proxy 127.0.0.1:29381 }
	handle /static/* { reverse_proxy 127.0.0.1:29381 }

	handle /record/* {
		basic_auth { qa $2a$14$...  }   # caddy hash-password
		uri strip_prefix /record
		reverse_proxy 127.0.0.1:29383
	}

	handle { reverse_proxy 127.0.0.1:29382 }
}
```

Caddy gets certificates on its own and upgrades WebSockets without being told.
</details>

---

## 5. Disk

Every run keeps a trace, a video, and screenshots. Real numbers from one
failed run: a **36 MB** trace and a **6 MB** video, for one browser. Three
browsers multiplies that.

At thirty runs a day, budget **40–60 GB a month**.

There is no retention policy in the application today. Until there is, a cron
job is the honest answer:

```bash
# Artifacts older than 30 days.
0 3 * * * docker run --rm -v autoqa_storage_data:/data alpine \
    find /data/runs -mindepth 1 -maxdepth 1 -type d -mtime +30 -exec rm -rf {} +
```

Delete the files and the database rows still point at them; the UI will show a
run whose artifacts 404. That is a known rough edge of doing it this way.

---

## 6. Upgrading

```bash
git pull
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

**Runs in progress are lost.** They are threads inside the API process, not
queued work, so a deploy kills them with no retry and no record beyond the run
being left in `running`. Deploy when nothing is executing, or accept the loss.

---

## 7. Why one machine

A run is dispatched with `threading.Thread` inside the API process
(`services/execution_service.py`). It is not queued, and nothing outside that
process knows it exists.

Two consequences, both structural:

- **One uvicorn worker.** A second worker would accept status requests for runs
  it has never heard of and report them missing. The entrypoint pins
  `--workers 1` for this reason.
- **No horizontal scaling.** A second API instance does not share running jobs.

Celery and Redis are dependencies that nothing calls. Scaling past one machine
means moving execution onto a real queue first — at which point Redis earns its
place and this file gets longer.

Until then: one machine, sized for the browsers rather than the traffic. The
web app is idle almost all the time; the CPU goes on Playwright.

---

## 8. When something goes wrong

**The UI loads but every request fails with "Failed to fetch."**
`NEXT_PUBLIC_API_URL` was wrong at build time. It is compiled in — rebuild with
`up -d --build`, do not just restart.

**The API refuses requests from the UI with a CORS error.**
`CORS_ORIGINS` is matched as an exact string: scheme, host, port, and no
trailing slash. In production the permissive localhost pattern is off.

**Runs die partway with "Target closed" or "browser has been closed."**
Usually shared memory. Chromium needs more than Docker's default 64 MB;
compose sets `shm_size: 1gb`. If it persists, check whether the run simply
exceeded `RUN_TIMEOUT_SECONDS` — the process is killed and the symptom is
identical.

**Recording opens nothing.**
Check `AUTOQA_VIRTUAL_DISPLAY=1`, then `docker compose logs api` for the Xvfb
lines. `warning: /tmp/.X11-unix/X99 never appeared` means the virtual screen
failed to start and no window can open.

**The noVNC page connects and stays black.**
Nothing has opened a window yet. The screen exists from container start; it
only shows something once a recording session is launched from the web app.

**The noVNC page loads but the canvas stays grey and never connects.**
The WebSocket upgrade is not getting through. In nginx that is the three
`Upgrade` / `Connection` / `proxy_http_version 1.1` lines on the `/record/`
location. Nothing is logged when they are missing — the connection simply
never becomes a WebSocket.

**Uploading a spreadsheet fails, and the API logs show nothing at all.**
nginx rejected it before the application saw it. Raise
`client_max_body_size`; the default is 1 MB.
