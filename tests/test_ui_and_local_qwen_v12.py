from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_changes_panel_is_stacked_and_preview_owns_scroll() -> None:
    css = (ROOT / "static/css/workflow-runner.css").read_text(encoding="utf-8")
    assert "V12 focused review UX" in css
    block = css.split("/* V12 focused review UX", 1)[1]
    assert '#changesPanel.active' in block
    assert 'grid-template-areas: "summary" "files" "preview"' in block
    assert 'grid-template-columns: minmax(0, 1fr)' in block
    assert '#changesList' in block and 'scrollbar-gutter: stable' in block
    assert '#changePreview .diff-code' in block
    assert 'scrollbar-gutter: stable both-edges' in block


def test_patch_unified_and_split_views_have_independent_scrollbars() -> None:
    css = (ROOT / "static/css/workflow-runner.css").read_text(encoding="utf-8")
    diagnostics = (ROOT / "static/js/features/diagnostics.js").read_text(encoding="utf-8")
    block = css.split("/* V12 focused review UX", 1)[1]
    assert '.diagnostics-drawer.patch-review-mode' in block
    assert '.patch-preview-pane' in block and 'overflow: auto !important' in block
    assert '.patch-preview-pane > pre' in block and 'width: max-content' in block
    assert '.patch-preview-pane > .patch-split' in block
    assert 'patch-view-unified' in diagnostics and 'patch-view-split' in diagnostics
    assert 'patch-review-mode' in diagnostics


def test_result_is_center_modal_and_can_be_closed_three_ways() -> None:
    html = (ROOT / "static/index.html").read_text(encoding="utf-8")
    runs = (ROOT / "static/js/features/runs.js").read_text(encoding="utf-8")
    events = (ROOT / "static/js/features/events.js").read_text(encoding="utf-8")
    assert 'run-result-modal-backdrop' in html
    assert 'run-result-panel result-dock' not in html
    assert 'run-result-modal-close' in runs
    assert 'event.target === ui.byKey("runResultPanel")' in events
    assert 'ctx.features.runs.closeResultModal({ remember: true })' in events
    assert 'event.key === "Escape"' in events


def test_real_qwen_case_library_has_single_line_prompts_and_validation() -> None:
    root = ROOT / "examples/real_qwen_cases"
    case_dirs = [path for path in sorted(root.iterdir()) if path.is_dir()]
    assert len(case_dirs) >= 6
    for case_dir in case_dirs:
        meta = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
        prompt = (case_dir / "prompt.txt").read_text(encoding="utf-8").strip()
        assert prompt and "\n" not in prompt
        assert meta["prompt_is_single_line"] is True
        assert (case_dir / "validation.py").is_file()
        assert (case_dir / "project_seed").is_dir()


def test_local_qwen_case_runner_lists_and_dry_runs(tmp_path: Path) -> None:
    runner = ROOT / "scripts/run_local_qwen_cases.py"
    listed = subprocess.run(
        [sys.executable, str(runner), "--list"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert listed.returncode == 0, listed.stderr
    payload = json.loads(listed.stdout)
    assert any(item["id"] == "root_pytest_update" for item in payload["cases"])

    output = tmp_path / "dry-run"
    dry = subprocess.run(
        [
            sys.executable,
            str(runner),
            "--case",
            "bubble_sort_new",
            "--dry-run",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert dry.returncode == 0, dry.stderr
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "PASS"
    assert summary["results"][0]["status"] == "DRY_RUN"
    plan = json.loads((output / "bubble_sort_new" / "plan.json").read_text(encoding="utf-8"))
    assert "bubble_sort.py" in plan["prompt"]


def test_windows_qwen_wrapper_and_user_guide_are_shipped() -> None:
    assert (ROOT / "scripts/run_local_qwen_cases.ps1").is_file()
    guide = (ROOT / "doc/zh-TW/LOCAL_REAL_QWEN_CASES.md").read_text(encoding="utf-8")
    assert "run_local_qwen_cases.ps1" in guide
    assert "validation.py" in guide
    assert "Repeat 5" in guide
