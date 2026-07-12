from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from app.core.runtime_context import RuntimeContext
from app.runtime_modules import api as runtime
from app.workflow_runtime.failure_classifier import classify_failure
from app.workflow_runtime.failure_normalizer import normalize_failure
from scripts.build_release import collect_release_files, write_release

ROOT = Path(__file__).resolve().parents[1]


def test_production_requirements_include_yaml_and_are_split() -> None:
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "PyYAML" in requirements
    assert (ROOT / "requirements-dev.txt").exists()
    assert (ROOT / "requirements-browser.txt").exists()
    assert (ROOT / "constraints-tested.txt").exists()


def test_failure_classifier_prefers_structured_code_over_misleading_text() -> None:
    failure = classify_failure(
        {"code": "AGENT_TIMEOUT", "message": "validation passed and no timeout actually appeared here"}
    )
    assert failure["code"] == "TIMEOUT"
    assert failure["classification_source"] == "structured"


def test_failure_normalizer_v3_keeps_diagnostics_but_drives_retry_from_code() -> None:
    failure = normalize_failure(
        {"code": "AGENT_SESSION_RECOVERABLE", "message": "provider wording may change"},
        source="qwen",
        provider="qwen",
        step_key="build",
        evidence_refs=["run-log.md#L20-L25"],
    )
    assert failure["schema"] == "aiwf.failure.v3"
    assert failure["code"] == "AGENT_SESSION_RECOVERABLE"
    assert failure["classification_source"] == "structured"
    assert failure["retryable"] is True
    assert failure["retry_target"] == "same step with fresh session handoff"
    assert failure["evidence_refs"] == ["run-log.md#L20-L25"]


def test_runtime_context_is_explicit_and_uses_existing_singletons() -> None:
    context = runtime.get_runtime_context()
    assert isinstance(context, RuntimeContext)
    assert context.store is runtime.store
    assert context.bus is runtime.bus
    assert context.workflow_executor is runtime.workflow_executor
    assert context.running_tasks is runtime.running_tasks


def test_release_allowlist_excludes_runtime_state_and_caches() -> None:
    paths = {item.archive_path.as_posix() for item in collect_release_files()}
    assert "data/version.json" in paths
    assert "app/main.py" in paths
    assert "requirements-dev.txt" in paths
    assert not any("__pycache__" in path for path in paths)
    assert not any(path.startswith("test-results/") for path in paths)
    assert not any(path.startswith("reports/") for path in paths)
    assert not any(path.startswith("data/project-index/") for path in paths)
    assert not any(path.startswith("data/pytest/") for path in paths)
    assert not any(path.startswith("data/project-validation-profiles/") and not path.endswith(".gitkeep") for path in paths)
    assert not any(path.startswith("data/store") for path in paths)


def test_release_zip_contains_hash_manifest_and_no_runtime_state() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "release.zip"
        _, manifest = write_release(output)
        assert manifest["file_count"] > 100
        with zipfile.ZipFile(output) as archive:
            names = set(archive.namelist())
            assert "RELEASE_MANIFEST.json" in names
            payload = json.loads(archive.read("RELEASE_MANIFEST.json"))
            assert payload["schema"] == "aiwf.release-manifest.v1"
            assert payload["checks"]["runtime_state_excluded"] is True
            assert not any("__pycache__" in name for name in names)
            assert "data/store.sqlite3" not in names


def test_startup_smoke_uses_isolated_state() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/run_startup_smoke.py"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["ready"]["ok"] is True
    assert payload["health_status"] == 200


def test_executor_recovery_is_extracted_from_main_execute_loop() -> None:
    source = (ROOT / "app/workflow_runtime/executor.py").read_text(encoding="utf-8")
    assert "async def _recover_failed_step" in source
    execute_body = source.split("async def execute", 1)[1].split("async def _recover_failed_step", 1)[0]
    assert "Retry stopped:" not in execute_body
