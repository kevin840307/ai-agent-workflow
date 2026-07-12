from __future__ import annotations

import json
from pathlib import Path


def test_real_qwen_unattended_case_library_is_behavior_based() -> None:
    root = Path(__file__).resolve().parents[1]
    payload = json.loads((root / "tests/fixtures/real_qwen_unattended/cases.json").read_text(encoding="utf-8"))
    assert payload["schema"] == "aiwf.real-qwen-e2e-cases.v1"
    ids = {case["id"] for case in payload["cases"]}
    assert {"bugfix-existing-python", "multi-file-feature", "project-local-agent-context", "validation-repair-loop"} <= ids
    assert all(case.get("test_command") for case in payload["cases"])
    assert all(case.get("expected_files") for case in payload["cases"])


def test_real_qwen_runner_preserves_agent_ownership_and_project_cwd() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "scripts/run_real_qwen_unattended_e2e.py").read_text(encoding="utf-8")
    assert '"agent": "qwen"' in source
    assert '"patchMode": "atomic_apply"' in source
    assert '"autopilotMode": "safe_apply"' in source
    assert 'expected_files' in source
    assert 'effective_cwd' in source
    assert "write_text" in source  # fixture setup and report only
    assert "Agent-generated file" in source
    assert "ThreadPoolExecutor" in source
