from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _child() -> int:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        ready = client.get("/ready")
        health = client.get("/api/health")
        payload = {
            "schema": "aiwf.startup-smoke.v1",
            "ready_status": ready.status_code,
            "health_status": health.status_code,
            "ready": ready.json(),
            "health": health.json(),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if ready.status_code == 200 and ready.json().get("ok") and health.status_code == 200 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Boot the API against isolated runtime state and verify readiness.")
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        return _child()

    with tempfile.TemporaryDirectory(prefix="aiwf-startup-smoke-") as tmp:
        env = os.environ.copy()
        env.update(
            {
                "AIWF_STORE_BACKEND": "sqlite",
                "AIWF_STORE_FILE": str(Path(tmp) / "store.sqlite3"),
                "AIWF_INVARIANT_MONITOR": "0",
                "QWEN_MOCK": "1",
                "QWEN_USE_SERVE": "0",
                "PYTHONPATH": str(ROOT),
            }
        )
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--child"],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=90,
        )
        if completed.stdout:
            print(completed.stdout, end="")
        if completed.stderr:
            print(completed.stderr, file=sys.stderr, end="")
        return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
