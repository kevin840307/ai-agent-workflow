from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any


@dataclass
class RuntimeMetrics:
    counters: Counter[str] = field(default_factory=Counter)
    durations: dict[str, list[float]] = field(default_factory=dict)

    def increment(self, key: str, amount: int = 1) -> None:
        self.counters[key] += amount

    def observe(self, key: str, seconds: float) -> None:
        self.durations.setdefault(key, []).append(max(0.0, float(seconds)))

    def snapshot(self, *, active_runs: int = 0) -> dict[str, Any]:
        duration_summary = {}
        for key, values in self.durations.items():
            if not values:
                continue
            duration_summary[key] = {
                "count": len(values),
                "avgSec": sum(values) / len(values),
                "maxSec": max(values),
            }
        return {
            "ok": True,
            "counters": dict(self.counters),
            "durations": duration_summary,
            "activeRuns": active_runs,
        }


metrics = RuntimeMetrics()


def now() -> float:
    return perf_counter()
