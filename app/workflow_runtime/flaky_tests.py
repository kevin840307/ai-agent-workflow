from __future__ import annotations

from typing import Any, Iterable


def classify_attempts(attempts: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = [dict(item) for item in attempts]
    statuses = [str(item.get("status") or "failed") for item in rows]
    passed = sum(status == "passed" for status in statuses)
    failed = sum(status == "failed" for status in statuses)
    flaky = passed > 0 and failed > 0
    stable_pass = passed == len(rows) and bool(rows)
    stable_fail = failed == len(rows) and bool(rows)
    return {
        "schema": "aiwf.flaky-test-evidence.v1",
        "classification": "suspected_flaky" if flaky else "stable_pass" if stable_pass else "stable_failure" if stable_fail else "inconclusive",
        "flaky": flaky,
        "passed_attempts": passed,
        "failed_attempts": failed,
        "attempt_count": len(rows),
        "attempts": rows,
    }


def merge_flaky_result(initial: dict[str, Any], reruns: list[dict[str, Any]]) -> dict[str, Any]:
    evidence = classify_attempts([initial, *reruns])
    result = dict(reruns[-1] if reruns else initial)
    result["attempts"] = [initial, *reruns]
    result["flaky_evidence"] = evidence
    if evidence["flaky"]:
        result["status"] = "passed"
        result["classification"] = "suspected_flaky"
        result["warning"] = "Validation passed inconsistently across reruns; evidence was preserved."
    return result


__all__ = ["classify_attempts", "merge_flaky_result"]
