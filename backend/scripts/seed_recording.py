"""Load the sample recording through the real API.

The Chrome extension does not exist until Phase 9, so this stands in for it:
it drives exactly the same endpoints, in the same order, with the same payloads.

    python scripts/seed_recording.py

Optional:
    --api      http://localhost:5022/api/v1
    --email / --password    reuse an existing account instead of creating one
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "sample_recording.json"
BATCH_SIZE = 8  # deliberately small, so the upload takes several batches


def call(url: str, payload: dict | None = None, token: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = Request(
        url,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers=headers,
        method="POST" if payload is not None else "GET",
    )
    try:
        with urlopen(request) as response:
            body = response.read()
            return json.loads(body) if body else {}
    except HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise SystemExit(f"\n{exc.code} from {url}\n{detail}\n") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:5022/api/v1")
    parser.add_argument("--email")
    parser.add_argument("--password", default="supersecret123")
    args = parser.parse_args()

    api = args.api.rstrip("/")
    sample = json.loads(FIXTURE.read_text(encoding="utf-8"))

    # 1. Account
    if args.email:
        print(f"Signing in as {args.email}")
        tokens = call(f"{api}/auth/login", {"email": args.email, "password": args.password})
    else:
        email = f"seed-{uuid.uuid4().hex[:8]}@example.com"
        print(f"Registering {email}")
        tokens = call(
            f"{api}/auth/register",
            {
                "email": email,
                "password": args.password,
                "full_name": "Seed User",
                "role": "qa_engineer",
            },
        )
    token = tokens["access_token"]
    print(f"  role: {tokens['user']['role']}")

    # 2. Project
    project = call(
        f"{api}/projects",
        {
            "name": f"Demo Shop {uuid.uuid4().hex[:6]}",
            "base_url": "https://shop.example.com",
            "description": "Seeded from sample_recording.json",
            "default_browsers": ["chromium", "firefox"],
        },
        token,
    )
    print(f"Created project {project['id']}: {project['name']}")

    # 3. Recording — exactly what the extension will do
    session = call(f"{api}/projects/{project['id']}/recordings", sample["session"], token)
    print(f"Started recording {session['id']}: {session['name']}")

    actions = sample["actions"]
    for start in range(0, len(actions), BATCH_SIZE):
        chunk = actions[start : start + BATCH_SIZE]
        result = call(
            f"{api}/recordings/{session['id']}/actions", {"actions": chunk}, token
        )
        print(
            f"  batch {start:>3}-{start + len(chunk) - 1:<3} "
            f"stored={result['stored']} skipped={result['skipped_duplicates']} "
            f"total={result['action_count']}"
        )

    # Prove idempotency the way a flaky network would
    repeat = call(f"{api}/recordings/{session['id']}/actions", {"actions": actions[:BATCH_SIZE]}, token)
    print(f"  retried first batch -> stored={repeat['stored']} (expected 0)")

    stopped = call(f"{api}/recordings/{session['id']}/stop", {}, token)
    print(
        f"Stopped: status={stopped['status']} "
        f"actions={stopped['action_count']} duration={stopped['duration_ms']}ms"
    )

    print(f"\nDone. View it at {api}/recordings/{session['id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
