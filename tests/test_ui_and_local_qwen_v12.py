from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_run_center_and_diagnostics_use_one_vertical_scroll_owner() -> None:
    css = (ROOT / "static/css/workflow-runner.css").read_text(encoding="utf-8")
    diagnostics = (ROOT / "static/js/features/diagnostics.js").read_text(encoding="utf-8")
    patch_review = (ROOT / "static/js/features/patch-review.js").read_text(encoding="utf-8")
    block = css.split("/* V17 single-scroll workspace contract", 1)[1]
    assert ".run-center > .panel.active" in block
    assert ".diagnostic-section.active" in block
    assert "overflow-y: auto" in block
    assert ".patch-review-workbench" in css
    assert ".artifact-viewer-layout" in css
    assert "diagnosticPatch" not in diagnostics
    assert "data-patch-view" in patch_review and '"split"' in patch_review and '"unified"' in patch_review


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
    guide = (ROOT / "doc/zh-TW/TESTING.md").read_text(encoding="utf-8")
    assert "run_local_qwen_cases.ps1" in guide
    assert "validation.py" in guide
    assert "Repeat 5" in guide
