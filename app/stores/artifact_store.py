from __future__ import annotations

from typing import Any, Protocol

from app.core.paths import utc_now

from .run_store import RunStore


class ArtifactStore(Protocol):
    async def list_for_run(self, run_id: str) -> list[dict[str, Any]]: ...
    async def replace_for_run(self, run_id: str, artifacts: list[dict[str, Any]]) -> dict[str, Any] | None: ...
    async def add_or_update(self, run_id: str, artifact: dict[str, Any]) -> dict[str, Any] | None: ...


class FileArtifactStore:
    def __init__(self, run_store: RunStore) -> None:
        self._run_store = run_store

    async def list_for_run(self, run_id: str) -> list[dict[str, Any]]:
        run = await self._run_store.get(run_id)
        return list((run or {}).get("artifacts", []))

    async def replace_for_run(self, run_id: str, artifacts: list[dict[str, Any]]) -> dict[str, Any] | None:
        def apply(run: dict[str, Any]) -> None:
            run["artifacts"] = artifacts
            run.pop("_artifact_refresh_candidates", None)
            run["updated_at"] = utc_now()

        return await self._run_store.mutate_run(run_id, apply)

    async def add_or_update(self, run_id: str, artifact: dict[str, Any]) -> dict[str, Any] | None:
        def apply(run: dict[str, Any]) -> None:
            artifacts = list(run.get("artifacts") or [])
            artifact_id = artifact.get("id") or artifact.get("path") or artifact.get("name")
            updated = False
            for index, existing in enumerate(artifacts):
                existing_id = existing.get("id") or existing.get("path") or existing.get("name")
                if existing_id == artifact_id:
                    artifacts[index] = {**existing, **artifact, "updated_at": artifact.get("updated_at") or utc_now()}
                    updated = True
                    break
            if not updated:
                artifacts.append({**artifact, "updated_at": artifact.get("updated_at") or utc_now()})
            run["artifacts"] = artifacts
            run.pop("_artifact_refresh_candidates", None)
            run["updated_at"] = utc_now()

        return await self._run_store.mutate_run(run_id, apply)
