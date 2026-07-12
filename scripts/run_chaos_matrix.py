#!/usr/bin/env python3
"""Deterministic fault-injection matrix for unattended recovery primitives."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.services.model_circuit_breaker import ModelCircuitBreaker
from app.workflow_runtime.flaky_tests import classify_attempts
from app.workflow_runtime.progress_evaluator import compare_progress
from app.workflow_runtime.run_lease import (
    RunLeaseConflict, acquire_run_lease, attempt_idempotency_key, begin_attempt,
    finish_attempt, release_run_lease,
)


async def execute() -> dict:
    cases: list[dict] = []

    breaker = ModelCircuitBreaker()
    await breaker.record_failure("qwen", "offline", transient=True, now=0)
    await breaker.record_failure("qwen", "offline", transient=True, now=1)
    await breaker.record_failure("qwen", "offline", transient=True, now=2)
    denied = await breaker.allow("qwen", now=2.1)
    recovered = await breaker.record_success("qwen", now=20)
    cases.append({"case": "model-offline-recovery", "pass": not denied["allowed"] and recovered["state"] == "closed"})

    run = {"id": "run-duplicate"}
    acquire_run_lease(run, {"id": "owner-a"}, ttl_sec=60)
    key = attempt_idempotency_key(run, "build")
    begin_attempt(run, step_key="build", idempotency_key=key, owner_id="owner-a")
    blocked = False
    try:
        begin_attempt(run, step_key="build", idempotency_key=key, owner_id="owner-b")
    except RunLeaseConflict:
        blocked = True
    finish_attempt(run, key, status="completed")
    duplicate = begin_attempt(run, step_key="build", idempotency_key=key, owner_id="owner-b")
    cases.append({"case": "duplicate-attempt", "pass": blocked and duplicate.get("duplicate_completed") is True})

    stale = {"id": "run-stale"}
    now = datetime(2026, 7, 11, tzinfo=timezone.utc)
    acquire_run_lease(stale, {"id": "dead-owner"}, ttl_sec=10, now=now)
    takeover = acquire_run_lease(stale, {"id": "new-owner"}, ttl_sec=10, now=now + timedelta(seconds=11))
    cases.append({"case": "stale-lease-takeover", "pass": takeover["owner_id"] == "new-owner"})
    release_run_lease(stale, owner_id="new-owner")

    flaky = classify_attempts([{"status": "failed"}, {"status": "passed"}])
    cases.append({"case": "flaky-test-detection", "pass": flaky["classification"] == "suspected_flaky"})

    progress = compare_progress({"required_failures": 5}, {"required_failures": 1})
    cases.append({"case": "repair-progress", "pass": progress["improved"] is True})

    return {
        "schema": "aiwf.chaos-matrix.v1",
        "status": "PASS" if all(item["pass"] for item in cases) else "FAIL",
        "cases": cases,
        "passed": sum(bool(item["pass"]) for item in cases),
        "total": len(cases),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    args = parser.parse_args()
    result = asyncio.run(execute())
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        from pathlib import Path
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
