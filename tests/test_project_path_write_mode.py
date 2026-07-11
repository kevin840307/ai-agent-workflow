from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.services.workflow_service import default_patch_mode_for_agent


def test_local_agents_write_to_selected_project_by_default() -> None:
    with patch.dict(os.environ, {}, clear=True):
        assert default_patch_mode_for_agent("qwen") == "auto_apply"
        assert default_patch_mode_for_agent("opencode") == "auto_apply"
        assert default_patch_mode_for_agent(None) == "auto_apply"


def test_isolated_patch_workspace_is_explicit_opt_in() -> None:
    with patch.dict(os.environ, {"AIWF_DEFAULT_PATCH_MODE": "review"}, clear=True):
        assert default_patch_mode_for_agent("qwen") == "review"
    with patch.dict(os.environ, {"AIWF_DEFAULT_PATCH_MODE": "dry-run"}, clear=True):
        assert default_patch_mode_for_agent("qwen") == "dry_run"


def test_ui_uses_original_project_path_and_can_apply_legacy_isolated_patch() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "static/js/features/runs.js").read_text(encoding="utf-8")
    index = (root / "static/index.html").read_text(encoding="utf-8")
    assert "run.original_project_path || run.project_path" in source
    assert "/patch/apply" in source
    assert "applyRunPatch" in source
    assert "Apply to Project" in index
    assert "套用到專案" in index


def test_created_run_uses_selected_project_as_effective_cwd_by_default() -> None:
    with TemporaryDirectory() as tmp, patch.dict(os.environ, {"QWEN_MOCK": "1"}, clear=False), TestClient(app) as client:
        project = Path(tmp) / "project"
        project.mkdir()
        session = client.post("/api/sessions", json={"title": "direct-write", "project_path": str(project)})
        assert session.status_code == 200, session.text
        run = client.post(
            f"/api/sessions/{session.json()['id']}/workflow-runs",
            json={
                "workflow_id": "adaptive-auto-workflow",
                "requirement": "Create hello.txt containing hello.",
                "runProfile": "small",
            },
        )
        assert run.status_code == 200, run.text
        payload = run.json()
        assert payload["patch_mode"] == "auto_apply"
        assert Path(payload["project_path"]).resolve() == project.resolve()
        assert payload["isolated_project_path"] is None
