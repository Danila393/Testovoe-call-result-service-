"""Reviewer scenario against a running stack, on any OS.

    docker compose up --build -d --wait
    python scripts/smoke_check.py

Runs ``python producer.py`` exactly as a reviewer would (as a subprocess, with the current
interpreter), then checks the API. Standard library only, apart from what producer.py needs.
Exit code 0 means the scenario passed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

Step = Callable[[], None]

ROOT = Path(__file__).resolve().parent.parent
NOT_FOUND = {"detail": "Кампания не найдена"}
EXPECTED = {"camp_001": ["call_0001", "call_0002"], "camp_002": ["call_0003", "call_0004"]}


class CheckFailedError(Exception):
    pass


def get_json(url: str) -> tuple[int, Any]:
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310 - URL comes from CLI
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8") or "null")


def wait_healthy(base: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last: object = None
    while time.monotonic() < deadline:
        try:
            status, body = get_json(f"{base}/health")
        except (urllib.error.URLError, OSError) as exc:
            last = exc
        else:
            if status == 200:
                return
            last = body
        time.sleep(1)
    raise CheckFailedError(f"service not healthy after {timeout:.0f}s, last: {last}")


def run_producer() -> None:
    result = subprocess.run(  # noqa: S603 - fixed argv, current interpreter
        [sys.executable, str(ROOT / "producer.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise CheckFailedError(f"producer.py exited {result.returncode}: {result.stderr.strip()}")


def wait_calls(base: str, campaign_id: str, expected: list[str], timeout: float) -> None:
    deadline = time.monotonic() + timeout
    body: Any = None
    while time.monotonic() < deadline:
        status, body = get_json(f"{base}/campaigns/{campaign_id}/calls")
        if status == 200 and isinstance(body, dict) and body.get("total") == len(expected):
            ids = [c["call_id"] for c in body["calls"]]
            if ids != expected:
                raise CheckFailedError(f"{campaign_id}: expected {expected}, got {ids}")
            return
        time.sleep(0.5)
    raise CheckFailedError(f"{campaign_id}: expected {len(expected)} calls, last: {body}")


def check(base: str, timeout: float) -> None:
    steps: list[tuple[str, Step]] = [
        ("service is healthy", lambda: wait_healthy(base, timeout)),
        ("python producer.py", run_producer),
        *(
            (f"GET /campaigns/{cid}/calls -> {len(ids)} calls", _waiter(base, cid, ids))
            for cid, ids in EXPECTED.items()
        ),
        ("python producer.py again (idempotent)", run_producer),
        (
            "camp_001 still has exactly 2 calls",
            _after_pause(_waiter(base, "camp_001", EXPECTED["camp_001"])),
        ),
        ("unknown campaign -> 200 'Кампания не найдена'", lambda: _not_found(base)),
    ]
    for title, step in steps:
        step()
        print(f"ok   {title}")


def _waiter(base: str, campaign_id: str, ids: list[str]) -> Step:
    return lambda: wait_calls(base, campaign_id, ids, timeout=30)


def _after_pause(step: Step) -> Step:
    def run() -> None:
        time.sleep(2)  # give redelivered duplicates time to be (not) stored
        step()

    return run


def _not_found(base: str) -> None:
    status, body = get_json(f"{base}/campaigns/camp_smoke_missing/calls")
    if (status, body) != (200, NOT_FOUND):
        raise CheckFailedError(f"expected 200 {NOT_FOUND}, got {status} {body}")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--timeout", type=float, default=120, help="seconds to wait for /health")
    args = parser.parse_args()
    try:
        check(args.base_url.rstrip("/"), args.timeout)
    except CheckFailedError as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1
    print("smoke check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
