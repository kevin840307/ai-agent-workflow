from __future__ import annotations

from pathlib import Path
from typing import Any

from app.runtime_modules.files import (
    only_test_files,
    validate_build_files_do_not_overwrite_validation_scripts,
    validate_generated_code_files_are_clean,
    validate_generated_test_files,
    validate_test_code_is_separate,
)
from app.workflow_runtime.run_diff import build_run_diff


def run_owned_text_files(run: dict[str, Any], project_dir: Path, run_workspace: Path) -> list[tuple[str, str]]:
    """Return current text files changed by this run, relative to the run baseline.

    This intentionally reads the filesystem produced by Qwen/OpenCode. It does
    not generate, repair, or rewrite project files.
    """
    diff = build_run_diff({**run, "project_path": str(project_dir)}, run_workspace)
    files: list[tuple[str, str]] = []
    for item in diff.get("files") or []:
        if str(item.get("status") or "") == "deleted":
            continue
        rel = str(item.get("path") or "").replace("\\", "/").strip("/")
        if not rel:
            continue
        path = (project_dir / rel).resolve()
        try:
            path.relative_to(project_dir.resolve())
        except ValueError:
            continue
        if not path.is_file():
            continue
        try:
            files.append((rel, path.read_text(encoding="utf-8")))
        except UnicodeDecodeError:
            continue
    return files


def validate_agent_candidate(
    *,
    run: dict[str, Any],
    project_dir: Path,
    run_workspace: Path,
    direct_files: list[tuple[str, str]],
    validation_script: str | None,
    fallback_scripts: list[str],
) -> list[tuple[str, str]]:
    """Validate both this attempt and the cumulative run-owned candidate.

    A retry may only touch a test file while an invalid production file from a
    previous attempt remains. Validating only the latest diff would incorrectly
    accept that state. The cumulative validation closes that gap without the
    controller editing any source file.
    """
    validate_build_files_do_not_overwrite_validation_scripts(
        project_dir,
        direct_files,
        validation_script=validation_script,
        fallback_scripts=fallback_scripts,
    )
    cumulative = run_owned_text_files(run, project_dir, run_workspace)
    candidate = cumulative or direct_files
    validate_test_code_is_separate(candidate)
    validate_generated_code_files_are_clean(candidate)
    tests = only_test_files(candidate)
    if tests:
        validate_generated_test_files(tests, project_dir=project_dir)
    return candidate


__all__ = ["run_owned_text_files", "validate_agent_candidate"]
