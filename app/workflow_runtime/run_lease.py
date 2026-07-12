from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.paths import utc_now

LEASE_SCHEMA = "aiwf.run-lease.v2"


class RunLeaseConflict(RuntimeError):
    """Another live controller/attempt already owns the Run."""


def _now(now: datetime | None = None) -> datetime:
    value = now or datetime.now(timezone.utc)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def lease_ttl_seconds() -> int:
    try:
        return max(10, int(os.environ.get("AIWF_RUN_LEASE_TTL_SEC", "90") or 90))
    except (TypeError, ValueError):
        return 90


def lease_heartbeat_seconds(ttl_sec: int | None = None) -> int:
    ttl = int(ttl_sec or lease_ttl_seconds())
    try:
        configured = int(os.environ.get("AIWF_RUN_LEASE_HEARTBEAT_SEC", "0") or 0)
    except (TypeError, ValueError):
        configured = 0
    # Always refresh well before expiry. Explicit values are bounded so a typo
    # cannot silently make the heartbeat slower than the lease itself.
    default = max(2, ttl // 3)
    return max(1, min(configured or default, max(1, ttl - 2)))


def lease_is_expired(lease: dict[str, Any] | None, *, now: datetime | None = None) -> bool:
    if not lease:
        return True
    expires = _parse(lease.get("expires_at"))
    return not expires or expires <= _now(now)


def _next_fencing_token(run: dict[str, Any], current: dict[str, Any] | None) -> int:
    values = [
        int((current or {}).get("fencing_token") or 0),
        int((run.get("last_run_lease") or {}).get("fencing_token") or 0) if isinstance(run.get("last_run_lease"), dict) else 0,
        int(run.get("run_lease_epoch") or 0),
    ]
    return max(values) + 1


def acquire_run_lease(
    run: dict[str, Any],
    owner: dict[str, Any],
    *,
    ttl_sec: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = run.get("run_lease") if isinstance(run.get("run_lease"), dict) else None
    owner_id = str(owner.get("instance_id") or owner.get("id") or owner.get("pid") or "controller")
    live_other_owner = current and not lease_is_expired(current, now=now) and str(current.get("owner_id")) != owner_id
    if live_other_owner:
        raise RunLeaseConflict(f"Run lease is held by {current.get('owner_id')}")
    timestamp = _now(now)
    ttl = int(ttl_sec or lease_ttl_seconds())
    same_live_owner = bool(current and not lease_is_expired(current, now=now) and str(current.get("owner_id")) == owner_id)
    fencing_token = int(current.get("fencing_token") or 0) if same_live_owner else _next_fencing_token(run, current)
    lease = {
        "schema": LEASE_SCHEMA,
        "owner_id": owner_id,
        "owner": dict(owner),
        "acquired_at": current.get("acquired_at") if same_live_owner else timestamp.isoformat(),
        "heartbeat_at": timestamp.isoformat(),
        "expires_at": (timestamp + timedelta(seconds=ttl)).isoformat(),
        "ttl_sec": ttl,
        "fencing_token": fencing_token,
    }
    run["run_lease"] = lease
    run["run_lease_epoch"] = fencing_token
    return lease


def assert_run_lease(
    run: dict[str, Any],
    *,
    owner_id: str,
    fencing_token: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    lease = run.get("run_lease") if isinstance(run.get("run_lease"), dict) else None
    if not lease:
        raise RunLeaseConflict("Run lease is missing")
    if lease_is_expired(lease, now=now):
        raise RunLeaseConflict("Run lease expired")
    if str(lease.get("owner_id")) != str(owner_id):
        raise RunLeaseConflict(f"Run lease owner changed to {lease.get('owner_id')}")
    if int(lease.get("fencing_token") or 0) != int(fencing_token):
        raise RunLeaseConflict(
            f"Run lease fencing token changed from {fencing_token} to {lease.get('fencing_token')}"
        )
    return lease


def renew_run_lease(
    run: dict[str, Any],
    owner: dict[str, Any],
    *,
    ttl_sec: int | None = None,
    now: datetime | None = None,
    fencing_token: int | None = None,
) -> dict[str, Any]:
    owner_id = str(owner.get("instance_id") or owner.get("id") or owner.get("pid") or "controller")
    current = run.get("run_lease") if isinstance(run.get("run_lease"), dict) else None
    if fencing_token is not None:
        assert_run_lease(run, owner_id=owner_id, fencing_token=int(fencing_token), now=now)
    elif current and not lease_is_expired(current, now=now) and str(current.get("owner_id")) != owner_id:
        raise RunLeaseConflict(f"Run lease is held by {current.get('owner_id')}")
    return acquire_run_lease(run, owner, ttl_sec=ttl_sec, now=now)


def release_run_lease(
    run: dict[str, Any],
    *,
    owner_id: str | None = None,
    fencing_token: int | None = None,
) -> bool:
    lease = run.get("run_lease") if isinstance(run.get("run_lease"), dict) else None
    if not lease:
        return False
    if owner_id and str(lease.get("owner_id")) != str(owner_id):
        return False
    if fencing_token is not None and int(lease.get("fencing_token") or 0) != int(fencing_token):
        return False
    run["last_run_lease"] = {**lease, "released_at": utc_now()}
    run["run_lease"] = None
    return True


def attempt_idempotency_key(run: dict[str, Any], step_key: str, *, retry_count: int = 0) -> str:
    raw = "|".join([
        str(run.get("id") or ""),
        str(step_key or ""),
        str(retry_count),
        str(run.get("last_task_checkpoint_id") or run.get("last_checkpoint_id") or "baseline"),
    ])
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:24]


def begin_attempt(run: dict[str, Any], *, step_key: str, idempotency_key: str, owner_id: str) -> dict[str, Any]:
    attempts = run.setdefault("attempts", [])
    existing = next((item for item in reversed(attempts) if item.get("idempotency_key") == idempotency_key), None)
    if existing and existing.get("status") == "running" and existing.get("owner_id") != owner_id:
        raise RunLeaseConflict(f"Duplicate active attempt for {step_key}")
    if existing and existing.get("status") == "completed":
        return {**existing, "duplicate_completed": True}
    if existing:
        existing.update({"status": "running", "owner_id": owner_id, "resumed_at": utc_now()})
        return existing
    attempt = {
        "id": f"attempt-{len(attempts) + 1}",
        "step_key": step_key,
        "idempotency_key": idempotency_key,
        "owner_id": owner_id,
        "status": "running",
        "started_at": utc_now(),
    }
    attempts.append(attempt)
    del attempts[:-200]
    run["active_attempt"] = attempt["id"]
    return attempt


def finish_attempt(run: dict[str, Any], idempotency_key: str, *, status: str, error: str | None = None) -> dict[str, Any] | None:
    for item in reversed(run.get("attempts") or []):
        if item.get("idempotency_key") == idempotency_key:
            item["status"] = status
            item["ended_at"] = utc_now()
            item["error"] = error
            if run.get("active_attempt") == item.get("id"):
                run["active_attempt"] = None
            return item
    return None


__all__ = [
    "LEASE_SCHEMA",
    "RunLeaseConflict",
    "acquire_run_lease",
    "assert_run_lease",
    "attempt_idempotency_key",
    "begin_attempt",
    "finish_attempt",
    "lease_heartbeat_seconds",
    "lease_is_expired",
    "lease_ttl_seconds",
    "release_run_lease",
    "renew_run_lease",
]
