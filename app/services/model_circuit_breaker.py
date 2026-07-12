from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from dataclasses import dataclass, asdict
from typing import Any


def provider_circuit_key(agent: Any, request: Any | None = None) -> str:
    """Build an endpoint/model-scoped key without inspecting prompt semantics."""
    name = str(getattr(agent, "name", None) or "agent").strip().lower()
    metadata = dict(getattr(request, "metadata", None) or {})
    health_fn = getattr(agent, "health", None)
    try:
        health = health_fn() if callable(health_fn) else {}
    except Exception:
        health = {}
    identity = {
        "provider": name,
        "type": health.get("type"),
        "base_url": metadata.get("provider_base_url") or metadata.get("base_url") or health.get("base_url"),
        "model": metadata.get("model") or health.get("model"),
        "credential_profile": metadata.get("credential_profile") or health.get("credential_profile"),
        "config_dir": health.get("config_dir"),
        "bin": health.get("bin"),
    }
    canonical = json.dumps(identity, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"{name}:{digest}"


@dataclass
class Circuit:
    state: str = "closed"
    failure_count: int = 0
    opened_at: float = 0.0
    next_probe_at: float = 0.0
    last_error: str = ""
    last_success_at: float = 0.0
    half_open_in_flight: bool = False


class ModelCircuitBreaker:
    def __init__(self) -> None:
        self._circuits: dict[str, Circuit] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _threshold() -> int:
        return max(1, int(os.environ.get("AIWF_MODEL_CIRCUIT_FAILURES", "3") or 3))

    @staticmethod
    def _cooldown() -> float:
        return max(1.0, float(os.environ.get("AIWF_MODEL_CIRCUIT_COOLDOWN_SEC", "8") or 8))

    async def allow(self, provider: str, *, now: float | None = None) -> dict[str, Any]:
        key = str(provider or "default").lower()
        current = now if now is not None else time.monotonic()
        async with self._lock:
            circuit = self._circuits.setdefault(key, Circuit())
            if circuit.state == "open" and current >= circuit.next_probe_at:
                circuit.state = "half_open"
                circuit.half_open_in_flight = False
            if circuit.state == "half_open":
                if circuit.half_open_in_flight:
                    return {"allowed": False, **self._snapshot(key, circuit, current)}
                circuit.half_open_in_flight = True
                return {"allowed": True, "probe": True, **self._snapshot(key, circuit, current)}
            return {"allowed": circuit.state == "closed", **self._snapshot(key, circuit, current)}

    async def record_success(self, provider: str, *, now: float | None = None) -> dict[str, Any]:
        key = str(provider or "default").lower()
        current = now if now is not None else time.monotonic()
        async with self._lock:
            circuit = self._circuits.setdefault(key, Circuit())
            circuit.state = "closed"
            circuit.failure_count = 0
            circuit.last_error = ""
            circuit.last_success_at = current
            circuit.half_open_in_flight = False
            circuit.next_probe_at = 0.0
            return self._snapshot(key, circuit, current)

    async def record_failure(self, provider: str, error: Any, *, transient: bool = True, now: float | None = None) -> dict[str, Any]:
        key = str(provider or "default").lower()
        current = now if now is not None else time.monotonic()
        async with self._lock:
            circuit = self._circuits.setdefault(key, Circuit())
            circuit.half_open_in_flight = False
            circuit.last_error = str(error or "")[:500]
            if not transient:
                return self._snapshot(key, circuit, current)
            circuit.failure_count += 1
            if circuit.state == "half_open" or circuit.failure_count >= self._threshold():
                circuit.state = "open"
                circuit.opened_at = current
                multiplier = min(8, max(1, circuit.failure_count - self._threshold() + 1))
                circuit.next_probe_at = current + self._cooldown() * multiplier
            return self._snapshot(key, circuit, current)

    async def snapshots(self, *, now: float | None = None) -> dict[str, dict[str, Any]]:
        current = now if now is not None else time.monotonic()
        async with self._lock:
            return {key: self._snapshot(key, circuit, current) for key, circuit in self._circuits.items()}

    async def reset(self) -> None:
        async with self._lock:
            self._circuits.clear()

    async def snapshot(self, provider: str, *, now: float | None = None) -> dict[str, Any]:
        key = str(provider or "default").lower()
        current = now if now is not None else time.monotonic()
        async with self._lock:
            return self._snapshot(key, self._circuits.setdefault(key, Circuit()), current)

    @staticmethod
    def _snapshot(key: str, circuit: Circuit, current: float) -> dict[str, Any]:
        data = asdict(circuit)
        data.update({
            "schema": "aiwf.model-circuit.v1",
            "provider": key,
            "retry_after_sec": max(0.0, round(circuit.next_probe_at - current, 3)) if circuit.state == "open" else 0.0,
        })
        return data


model_circuit_breaker = ModelCircuitBreaker()

__all__ = ["Circuit", "ModelCircuitBreaker", "model_circuit_breaker", "provider_circuit_key"]
