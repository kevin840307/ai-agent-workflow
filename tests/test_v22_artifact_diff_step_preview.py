from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.persistence.sqlite_store import SQLiteStore
from app.runtime_modules.run_state import ARTIFACT_METADATA_SCHEMA, artifact_record
from app.security.isolated_workspace import (
    apply_isolated_changes_atomic,
    changed_project_files,
    create_isolated_project_copy,
)
from app.services import artifact_service
from app.services import workflow_service
from app.workflow_runtime.artifact_policy import artifact_display_metadata, artifact_preview_kind
from app.workflow_runtime.run_artifacts import write_standard_run_artifacts
from app.workflow_runtime.run_diff import build_run_diff, write_baseline_snapshot

ROOT = Path(__file__).resolve().parents[1]


def _run(tmp_path: Path, *, config: dict, key: str = "produce", title: str = "Produce") -> tuple[dict, Path]:
    run_dir = tmp_path / "run"
    (run_dir / "output").mkdir(parents=True)
    run = {
        "id": "run-v22",
        "workspace": str(run_dir),
        "project_path": str(tmp_path / "project"),
        "steps": [{"key": key, "title": title, "config": config}],
    }
    return run, run_dir


def test_declared_outputs_receive_structural_step_metadata(tmp_path: Path) -> None:
    run, run_dir = _run(tmp_path, config={"outputs": "result.md"})
    (run_dir / "output" / "result.md").write_text("# Result\n", encoding="utf-8")

    record = artifact_record(run, run_dir, "output/result.md")

    assert record["category"] == "step"
    assert record["role"] == "step-output"
    assert record["display_name"] == "Produce · result.md"
    assert record["producer_step_key"] == "produce"
    assert record["preview_kind"] == "markdown"
    assert record["metadata_schema"] == ARTIFACT_METADATA_SCHEMA


def test_validation_output_uses_explicit_evidence_contract(tmp_path: Path) -> None:
    run, run_dir = _run(
        tmp_path,
        key="verify",
        title="Verify",
        config={"outputs": ["validation.md"], "evidenceCategory": "validation"},
    )
    (run_dir / "output" / "validation.md").write_text("PASS\n", encoding="utf-8")

    record = artifact_record(run, run_dir, "output/validation.md")

    assert record["category"] == "validation"
    assert record["role"] == "validation-output"
    assert record["visibility"] == "essential"
    assert record["producer_step_key"] == "verify"


def test_explicit_artifact_contract_overrides_generic_output_metadata(tmp_path: Path) -> None:
    run, run_dir = _run(
        tmp_path,
        config={
            "outputs": ["result.json"],
            "artifactContracts": {
                "result.json": {
                    "category": "report",
                    "role": "summary",
                    "displayName": "執行結果摘要",
                    "displayOrder": 17,
                    "visibility": "essential",
                }
            },
        },
    )
    (run_dir / "output" / "result.json").write_text('{"status":"ok"}', encoding="utf-8")

    record = artifact_record(run, run_dir, "output/result.json")

    assert record["category"] == "report"
    assert record["role"] == "summary"
    assert record["display_name"] == "執行結果摘要"
    assert record["display_order"] == 17
    assert record["preview_kind"] == "json"


def test_known_category_with_unknown_role_does_not_fall_back_to_unclassified() -> None:
    metadata = artifact_display_metadata(category="validation", role="custom-validator-output")
    assert metadata["display_name"] == "驗證產物"
    assert metadata["visibility"] == "essential"


@pytest.mark.parametrize("media_type", ["application/yaml", "application/xml", "application/sql", "application/toml", "image/svg+xml"])
def test_structured_text_application_formats_remain_previewable(media_type: str) -> None:
    assert artifact_preview_kind(media_type=media_type, role="step-output") == "text"


def test_sqlite_projection_restores_full_artifact_payload(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "state.sqlite3", default_project_path=lambda: str(tmp_path), default_steps=lambda: [])
    artifact = {
        "id": "run-v22:output|result.md",
        "path": "output/result.md",
        "category": "step",
        "role": "step-output",
        "visibility": "supporting",
        "display_name": "Produce · result.md",
        "display_order": 500,
        "producer_step_key": "produce",
        "media_type": "text/markdown",
        "preview_kind": "markdown",
        "metadata_schema": ARTIFACT_METADATA_SCHEMA,
        "size": 12,
    }
    store.save_sync(
        {
            "sessions": [],
            "messages": [],
            "workflow_configs": [],
            "runs": [{"id": "run-v22", "status": "done", "steps": [], "artifacts": [artifact]}],
        }
    )

    projection = store.query_run_projection("run-v22")
    row = projection["artifacts"][0]

    assert row["display_name"] == artifact["display_name"]
    assert row["producer_step_key"] == "produce"
    assert row["media_type"] == "text/markdown"
    assert row["preview_kind"] == "markdown"
    assert row["metadata_schema"] == ARTIFACT_METADATA_SCHEMA


def test_legacy_run_artifacts_are_repaired_once_on_first_listing(monkeypatch: pytest.MonkeyPatch) -> None:
    run = {"id": "run-v22", "artifact_metadata_schema": None}
    records = [{"id": "run-v22:output|result.md", "path": "output/result.md", "category": "unclassified", "role": "unclassified"}]
    refresh_calls: list[str] = []

    async def fake_get_run(_run_id: str) -> dict:
        return run

    async def fake_refresh(run_id: str) -> None:
        refresh_calls.append(run_id)
        run["artifact_metadata_schema"] = ARTIFACT_METADATA_SCHEMA
        records[:] = [{
            "id": "run-v22:output|result.md",
            "path": "output/result.md",
            "category": "step",
            "role": "step-output",
            "display_name": "Produce · result.md",
            "media_type": "text/markdown",
            "preview_kind": "markdown",
        }]

    class FakeArtifactStore:
        async def list_for_run(self, _run_id: str) -> list[dict]:
            return list(records)

    monkeypatch.setattr(workflow_service, "get_run", fake_get_run)
    monkeypatch.setattr(workflow_service.runtime, "refresh_artifacts", fake_refresh)
    monkeypatch.setattr(workflow_service, "_ARTIFACT_STORE", FakeArtifactStore())

    first = asyncio.run(workflow_service.get_artifacts("run-v22", view="all"))
    second = asyncio.run(workflow_service.get_artifacts("run-v22", view="all"))

    assert refresh_calls == ["run-v22"]
    assert first[0]["category"] == "step"
    assert first[0]["display_name"] == "Produce · result.md"
    assert second == first


def test_artifact_preview_reads_standard_index_record_storage_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_dir = tmp_path / "run"
    (run_dir / ".workflow").mkdir(parents=True)
    run = {
        "id": "run-v22",
        "workspace": str(run_dir),
        "project_path": str(tmp_path),
        "status": "done",
        "steps": [],
    }
    index = write_standard_run_artifacts(run, run_dir)
    record = next(item for item in index["records"] if item["role"] == "final-report")
    assert record["storage_path"].startswith(".workflow/artifacts/")

    async def fake_get_run(_run_id: str) -> dict:
        return {**run, "artifacts": index["records"]}

    monkeypatch.setattr(artifact_service.workflow_service, "get_run", fake_get_run)
    payload = asyncio.run(artifact_service.get_artifact(record["id"]))

    assert payload["preview_kind"] == "markdown"
    assert "Workflow Final Report" in payload["content"]
    assert payload["display_name"] == "最終報告"


def test_binary_artifact_returns_safe_preview_contract_and_download_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_dir = tmp_path / "run"
    binary = run_dir / "output" / "image.png"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"\x89PNG\r\n\x1a\n\x00\xff")
    artifact_id = "run-v22:output|image.png"
    run = {
        "id": "run-v22",
        "workspace": str(run_dir),
        "artifacts": [{
            "id": artifact_id,
            "path": "output/image.png",
            "category": "step",
            "role": "step-output",
            "display_name": "Image",
            "media_type": "image/png",
            "preview_kind": "binary",
        }],
    }

    async def fake_get_run(_run_id: str) -> dict:
        return run

    monkeypatch.setattr(artifact_service.workflow_service, "get_run", fake_get_run)
    payload = asyncio.run(artifact_service.get_artifact(artifact_id))
    download_path, media_type, filename = asyncio.run(artifact_service.get_artifact_download(artifact_id))

    assert payload["preview_available"] is False
    assert payload["content"] == ""
    assert download_path == binary.resolve()
    assert media_type == "image/png"
    assert filename == "image.png"


def test_change_detection_excludes_tool_metadata_but_keeps_project_dotfiles(tmp_path: Path) -> None:
    original = tmp_path / "project"
    workspace = tmp_path / "workspace"
    original.mkdir()
    (original / "src.py").write_text("before\n", encoding="utf-8")
    (original / ".gitignore").write_text("*.tmp\n", encoding="utf-8")
    for name in (".git", ".vs", ".qwen", ".opencode", ".idea", ".vscode", ".claude", ".cursor"):
        (original / name).mkdir()
        (original / name / "config.txt").write_text("before\n", encoding="utf-8")

    isolated = create_isolated_project_copy(original, workspace, strategy="copy")
    (isolated / "src.py").write_text("after\n", encoding="utf-8")
    (isolated / ".gitignore").write_text("*.tmp\n.cache\n", encoding="utf-8")
    for name in (".git", ".vs", ".qwen", ".opencode", ".idea", ".vscode", ".claude", ".cursor"):
        target = isolated / name / "config.txt"
        if target.exists():
            target.write_text("after\n", encoding="utf-8")

    changed = changed_project_files(original, isolated)

    assert changed == [".gitignore", "src.py"]
    assert (isolated / ".qwen" / "config.txt").is_file(), "Agent config must still be copied into its CWD"
    assert (isolated / ".opencode" / "config.txt").is_file(), "OpenCode config must still be copied into its CWD"
    assert not (isolated / ".vs").exists(), "Editor caches should not consume isolated workspace resources"
    assert not (isolated / ".idea").exists()
    assert not (isolated / ".vscode").exists()


def test_run_diff_excludes_tool_metadata_from_existing_baseline_and_current_tree(tmp_path: Path) -> None:
    original = tmp_path / "original"
    isolated = tmp_path / "isolated"
    run_dir = tmp_path / "run"
    original.mkdir()
    isolated.mkdir()
    run_dir.mkdir()
    for root in (original, isolated):
        (root / "app.py").write_text("before\n", encoding="utf-8")
        (root / ".qwen").mkdir()
        (root / ".qwen" / "settings.json").write_text("{}\n", encoding="utf-8")
    run = {
        "id": "run-v22",
        "workspace": str(run_dir),
        "project_path": str(isolated),
        "original_project_path": str(original),
    }
    write_baseline_snapshot(run, run_dir)
    (isolated / "app.py").write_text("after\n", encoding="utf-8")
    (isolated / ".qwen" / "settings.json").write_text('{"changed":true}\n', encoding="utf-8")

    diff = build_run_diff(run, run_dir)

    assert [row["path"] for row in diff["files"]] == ["app.py"]
    assert ".qwen" in diff["ignored_dirs"]


def test_atomic_apply_rejects_explicit_tool_metadata_path(tmp_path: Path) -> None:
    original = tmp_path / "project"
    isolated = tmp_path / "isolated"
    (original / ".qwen").mkdir(parents=True)
    (isolated / ".qwen").mkdir(parents=True)
    (original / ".qwen" / "settings.json").write_text("{}", encoding="utf-8")
    (isolated / ".qwen" / "settings.json").write_text('{"changed":true}', encoding="utf-8")

    with pytest.raises(RuntimeError, match="ATOMIC_APPLY_IGNORED_PATH"):
        apply_isolated_changes_atomic(original, isolated, [".qwen/settings.json"])


def test_step_preview_and_split_diff_static_contracts() -> None:
    artifacts = (ROOT / "static/js/features/artifacts.js").read_text(encoding="utf-8")
    runs = (ROOT / "static/js/features/runs.js").read_text(encoding="utf-8")
    patch = (ROOT / "static/js/features/patch-review.js").read_text(encoding="utf-8")
    css = (ROOT / "static/css/workflow-runner.css").read_text(encoding="utf-8")

    assert "stepFilesModalBackdrop" in artifacts
    assert "僅顯示此 Step" in artifacts
    assert "config.outputs" in artifacts
    assert 'ctx.features.diagnostics.open("diagnosticArtifacts")' not in artifacts[artifacts.index("async function openStepFilesModal"):]
    assert "預覽對應文件" in runs
    assert "split-diff-grid" in patch
    assert "--split-side-min" in patch
    assert "flex: 0 0 50%" in css
    assert "width: 50%" in css


def test_frontend_cache_version_is_v22_everywhere() -> None:
    static_text = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "static").rglob("*") if path.is_file())
    assert "20260712-ui-v21" not in static_text
    assert "20260712-ui-v22" in static_text
