from __future__ import annotations

from collections import defaultdict
from typing import Any

BENCHMARK_CASES = [
    {"id": "BENCH-001", "title": "Single-file addition", "profile": "tiny", "expected": ["source file", "tests pass"]},
    {"id": "BENCH-002", "title": "Multi-file feature", "profile": "standard", "expected": ["task checkpoints", "tests pass"]},
    {"id": "BENCH-003", "title": "Repair failing test", "profile": "standard", "expected": ["targeted repair", "no replan"]},
    {"id": "BENCH-004", "title": "Refactor without public API change", "profile": "complex", "expected": ["scope preserved", "regression pass"]},
    {"id": "BENCH-005", "title": "Agent timeout recovery", "profile": "failure", "expected": ["fresh session", "candidate preserved"]},
    {"id": "BENCH-006", "title": "Session lost recovery", "profile": "failure", "expected": ["resume/create fallback"]},
    {"id": "BENCH-007", "title": "Context handoff", "profile": "failure", "expected": ["compact handoff", "continue current task"]},
    {"id": "BENCH-008", "title": "Controller restart", "profile": "recovery", "expected": ["checkpoint resume", "lock released"]},
    {"id": "BENCH-009", "title": "Project lock conflict", "profile": "recovery", "expected": ["single writer"]},
    {"id": "BENCH-010", "title": "Scope expansion cleanup", "profile": "quality", "expected": ["unrequested output reported"]},
    {"id": "BENCH-011", "title": "Validation failure repair", "profile": "failure", "expected": ["owning task repair", "final validation pass"]},
    {"id": "BENCH-012", "title": "Repeated no-file-change recovery", "profile": "failure", "expected": ["fresh session rotation", "bounded recovery"]},
    {"id": "BENCH-013", "title": "Large legacy project local change", "profile": "complex", "expected": ["incremental index", "focused scope", "full gate"]},
    {"id": "BENCH-014", "title": "Multi-language validation plan", "profile": "quality", "expected": ["detected build", "tests", "lint/type check when configured"]},
]


def benchmark_catalog() -> dict[str, Any]:
    return {"schema": "aiwf.benchmark-catalog.v1", "cases": BENCHMARK_CASES, "count": len(BENCHMARK_CASES)}


def benchmark_summary(runs: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
        benchmark_id = run.get("benchmark_id") or metadata.get("benchmark_id")
        if benchmark_id:
            groups[str(benchmark_id)].append(run)
    rows = []
    for case in BENCHMARK_CASES:
        items = groups.get(case["id"], [])
        passed = sum(item.get("status") == "done" for item in items)
        retries = [sum(int(step.get("retry_count") or 0) for step in item.get("steps") or []) for item in items]
        rows.append({
            **case,
            "runs": len(items),
            "passed": passed,
            "success_rate": round(passed * 100 / len(items), 1) if items else None,
            "average_retry": round(sum(retries) / len(retries), 2) if retries else None,
        })
    return {"schema": "aiwf.benchmark-summary.v1", "cases": rows, "total_runs": sum(row["runs"] for row in rows)}


__all__ = ["BENCHMARK_CASES", "benchmark_catalog", "benchmark_summary"]
