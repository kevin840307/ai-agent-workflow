#!/usr/bin/env python3
"""Bounded reliability soak for leases, attempts, circuits, and progress state.

This is intentionally model-free so it can run in CI or before a real-agent
certification. Use --iterations for an overnight/high-volume run.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.agents.process_registry import ProcessRegistry
from app.services.model_circuit_breaker import ModelCircuitBreaker
from app.workflow_runtime.failure_normalizer import normalize_failure
from app.workflow_runtime.run_lease import (
    acquire_run_lease, attempt_idempotency_key, begin_attempt, finish_attempt, release_run_lease,
)


async def run(iterations: int) -> dict:
    breaker = ModelCircuitBreaker()
    with tempfile.TemporaryDirectory(prefix="aiwf-soak-") as raw:
        registry = ProcessRegistry(Path(raw) / "processes.json")
        completed = 0
        for index in range(iterations):
            run_state = {"id": f"run-{index}", "created_at": datetime.now(timezone.utc).isoformat()}
            owner = {"id": "soak-controller", "pid": 1}
            acquire_run_lease(run_state, owner, ttl_sec=30)
            key = attempt_idempotency_key(run_state, "execute", retry_count=index)
            begin_attempt(run_state, step_key="execute", idempotency_key=key, owner_id="soak-controller")
            failure = normalize_failure("temporary endpoint offline", source="soak", step_key="execute")
            assert failure["summary"]
            await breaker.record_failure("qwen", failure["summary"], transient=True, now=float(index * 10))
            await breaker.record_success("qwen", now=float(index * 10 + 1))
            finish_attempt(run_state, key, status="completed")
            assert release_run_lease(run_state, owner_id="soak-controller")
            assert run_state.get("active_attempt") is None
            completed += 1
        assert len(registry) == 0 and not registry.records()
    return {
        "schema": "aiwf.reliability-soak.v1",
        "status": "PASS",
        "iterations": iterations,
        "completed": completed,
        "open_processes": 0,
        "active_leases": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=200)
    parser.add_argument("--output")
    args = parser.parse_args()
    result = asyncio.run(run(max(1, args.iterations)))
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
