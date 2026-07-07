from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.core.paths import read_text


def _hash_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def _safe_file_hash(path: Path) -> str | None:
    try:
        if path.exists() and path.is_file():
            return _hash_text(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    return None


def build_version_metadata(run: dict[str, Any]) -> dict[str, Any]:
    steps = []
    for step in run.get("steps") or []:
        template_path = step.get("templatePath") or step.get("skillPath") or ""
        contract_path = step.get("contractPath") or step.get("metadataPath") or ""
        steps.append(
            {
                "key": step.get("key"),
                "type": step.get("type"),
                "template_path": template_path,
                "contract_path": contract_path,
                "prompt_hash": step.get("prompt_hash"),
                "contract_hash": step.get("contract_hash"),
            }
        )
    return {
        "schema": "aiwf.run-version-metadata.v1",
        "run_id": run.get("id"),
        "workflow_id": run.get("workflow_id"),
        "workflow_version": run.get("workflow_version") or run.get("workflow_id"),
        "prompt_version": run.get("prompt_version") or "current",
        "contract_version": run.get("contract_version") or "current",
        "agent": run.get("agent"),
        "model_label_removed_from_ui": True,
        "run_profile": run.get("run_profile"),
        "thinking_level": run.get("thinking_level"),
        "validation_script": run.get("validation_script"),
        "context_pack": run.get("context_pack"),
        "patch_mode": run.get("patch_mode") or "auto_apply",
        "steps": steps,
    }


__all__ = ["build_version_metadata"]
