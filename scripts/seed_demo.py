#!/usr/bin/env python3
"""Load the demo collection into a running Cabinet instance.

The same thing the "Load the demo collection" button on an empty Cabinet
does: seventeen pieces with values and photos, so there is something to look
at (a populated list, dashboard breakdowns, gain and loss tables) before any
real data is entered. Uses only the standard library, so it needs no
install:

    python scripts/seed_demo.py --token cabinet_...
    python scripts/seed_demo.py --base-url http://cabinet.lan --token cabinet_...

Cabinet refuses unless the collection is empty, so the demo can never mix
with real pieces. The pieces live in the backend
(`backend/app/services/demo_data.py`), with each photo's source, license,
and credit beside it: public domain and CC0 images from Wikimedia Commons,
which Cabinet fetches itself, one at a time (about a minute for all of
them), so the stack needs to reach upload.wikimedia.org. A photo that can't
be fetched is a warning, not a failure, and --no-photos skips them. Remove
the demo again from the notice on the dashboard, or in Settings, General.

Pass a write-scoped API token with --token, or set CABINET_TOKEN. Create one
in Settings -> Account, or use the one scripts/ci/stack-smoke.sh mints.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

POLL_SECONDS = 3
PHOTO_WAIT_SECONDS = 900


def request(base: str, method: str, path: str, token: str | None = None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    req = urllib.request.Request(f"{base}{path}", method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read()
            return resp.status, json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read()).get("detail")
        except ValueError:
            detail = None
        if exc.code == 401:
            raise SystemExit(
                "Cabinet needs a sign-in. Pass a write-scoped API token with --token or "
                "CABINET_TOKEN (Settings -> Account -> API tokens)."
            ) from None
        if exc.code == 404:
            raise SystemExit(
                f"{base} has no demo collection to load: it needs the release after v0.42.0."
            ) from None
        return exc.code, {"detail": detail}
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"Could not reach Cabinet at {base} ({exc.reason}). Is the stack running?"
        ) from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost", help="default: http://localhost")
    parser.add_argument(
        "--token",
        default=os.environ.get("CABINET_TOKEN"),
        help="a write-scoped API token, sent as Bearer (default: the CABINET_TOKEN env var)",
    )
    parser.add_argument(
        "--no-photos",
        action="store_true",
        help="skip the photos (Cabinet fetches them from Wikimedia Commons)",
    )
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    path = "/api/demo?photos=false" if args.no_photos else "/api/demo"
    status, body = request(base, "POST", path, args.token)
    if status == 409:
        print(body["detail"], file=sys.stderr)
        return 1
    if status != 201:
        print(f"POST {path} failed: HTTP {status} {body.get('detail')}", file=sys.stderr)
        return 1
    print(f"Loaded {body['items']} demo pieces into {base}.")

    photos = body["photos"]
    waited = 0
    while photos["state"] == "running" and waited < PHOTO_WAIT_SECONDS:
        time.sleep(POLL_SECONDS)
        waited += POLL_SECONDS
        status, body = request(base, "GET", "/api/demo", args.token)
        if status != 200:
            break
        photos = body["photos"]
    if photos["total"]:
        if photos["state"] == "running":
            print(f"Still fetching photos ({photos['fetched']} of {photos['total']} so far).")
        else:
            print(f"Fetched {photos['fetched']} of {photos['total']} photos.")
        if photos["failed"]:
            print(
                f"{photos['failed']} photo(s) could not be fetched (the pieces are fine).",
                file=sys.stderr,
            )
    print("Open the dashboard to see breakdowns, gains, and value over time.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
