from __future__ import annotations

import asyncio
import importlib.util
import json
import subprocess
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.cli import aiwf
from app.services.run_overview_service import _dedupe_changed_files, build_run_overview
from app.workflow_runtime.actions import WorkflowActions

ROOT = Path(__file__).resolve().parents[1]


def _load_installer():
    path = ROOT / "scripts" / "install_agent_commands.py"
    spec = importlib.util.spec_from_file_location("install_agent_commands_v11", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_changed_file_projection_deduplicates_windows_aliases() -> None:
    rows = _dedupe_changed_files(
        [
            {"path": r".\\sorts.py", "status": "modified", "added_lines": 6, "deleted_lines": 0},
            {"path": "sorts.py", "status": "modified", "added": 6, "removed": 0},
        ]
    )
    assert rows == [{"path": "sorts.py", "status": "modified", "added_lines": 6, "deleted_lines": 0, "added": 6, "removed": 0}]


def test_restart_recovery_is_exposed_once_for_current_action(tmp_path: Path) -> None:
    workspace = tmp_path / "run"
    workspace.mkdir()
    (workspace / "requirement.md").write_text("repair sort", encoding="utf-8")
    run = {
        "id": "run-recovery",
        "status": "failed",
        "workspace": str(workspace),
        "project_path": str(tmp_path),
        "restart_recoverable": True,
        "recovery": {"checkpoint_id": "cp-1"},
        "error": "Workflow server restarted before this run completed.",
        "steps": [{"key": "build", "title": "Build", "status": "failed", "retry_count": 0}],
    }
    overview = build_run_overview(run)
    assert overview["restart_recoverable"] is True
    assert overview["recovery"] == {"checkpoint_id": "cp-1"}
    assert overview["recommended_actions"][0]["id"] == "resume"


def test_generate_tests_accepts_preexisting_root_pytest_file(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    root_test = project / "test_sorts.py"
    root_test.write_text("def test_old():\n    assert True\n", encoding="utf-8")
    before = {"test_sorts.py": root_test.read_bytes()}
    root_test.write_text("def test_old():\n    assert True\n\ndef test_new():\n    assert True\n", encoding="utf-8")
    actions = WorkflowActions(agent_runner=None, functions=None, log=AsyncMock(), refresh_artifacts=AsyncMock())
    accepted, restored = actions._enforce_phase_file_ownership(
        project,
        before,
        [("test_sorts.py", root_test.read_text(encoding="utf-8"))],
        phase="generate_tests",
    )
    assert [path for path, _ in accepted] == ["test_sorts.py"]
    assert restored == []
    assert "test_new" in root_test.read_text(encoding="utf-8")


def test_generate_tests_rejects_new_root_pytest_file(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    new_test = project / "test_new.py"
    new_test.write_text("def test_new():\n    assert True\n", encoding="utf-8")
    actions = WorkflowActions(agent_runner=None, functions=None, log=AsyncMock(), refresh_artifacts=AsyncMock())
    accepted, restored = actions._enforce_phase_file_ownership(
        project,
        {},
        [("test_new.py", new_test.read_text(encoding="utf-8"))],
        phase="generate_tests",
    )
    assert accepted == []
    assert restored == ["test_new.py"]
    assert not new_test.exists()


def test_agent_command_installer_routes_wf_and_wstep_from_foreign_project(tmp_path: Path) -> None:
    installer = _load_installer()
    installed = installer.install_commands(target="all", scope="project", project=tmp_path)
    installer.verify_installed_templates(installed)
    result = installer.verify_command_routes(project=tmp_path)
    assert result["ok"] is True
    assert result["routes"]["wf"]["workflow_id"] == "general-auto-development"
    assert result["routes"]["wf"]["project_path"] == str(tmp_path.resolve())
    assert result["routes"]["wstep"]["skill"] == "/build"
    assert result["routes"]["wstep"]["config"] == "build.yaml"
    for path in installed:
        text = path.read_text(encoding="utf-8")
        assert "@@AIWF_" not in text
        assert "aiwf_agent_command.py" in text


def test_aiwf_dry_run_does_not_initialize_runtime(tmp_path: Path, capsys) -> None:
    with patch.object(aiwf, "_init_runtime", new=AsyncMock()) as init_runtime:
        code = asyncio.run(
            aiwf.run_cli([
                "/wf",
                "general-auto-development",
                "add quick sort",
                "--project",
                str(tmp_path),
                "--dry-run",
                "--json",
            ])
        )
    assert code == 0
    init_runtime.assert_not_awaited()
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "aiwf.agent-command-dry-run.v1"
    assert payload["workflow_id"] == "general-auto-development"
    assert payload["requirement"] == "add quick sort"


def test_stable_launcher_imports_controller_outside_repo(tmp_path: Path) -> None:
    launcher = ROOT / "scripts" / "aiwf_agent_command.py"
    proc = subprocess.run(
        [sys.executable, str(launcher), "/wstep", "/build", "build.yaml", "smoke", "--project", str(tmp_path), "--dry-run", "--json"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["skill"] == "/build"
    assert payload["config"] == "build.yaml"


def test_recovery_and_change_preview_ui_are_single_source() -> None:
    script = (ROOT / "static/js/features/runs.js").read_text(encoding="utf-8")
    css = (ROOT / "static/css/workflow-runner.css").read_text(encoding="utf-8")
    assert "target.hidden = true" in script
    assert "服務已重新啟動，進度已保留" in script
    assert script.count("${recoveryHtml}") == 1
    assert "singleFileMode" in script
    assert "change-preview-label" in script
    assert "#changesPanel.active" in css
    assert 'grid-template-areas:' in css
