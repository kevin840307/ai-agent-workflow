from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Iterable

from app.core.provider_slots import provider_execution_slot
from app.core.command_runner import CommandPolicy, CommandRequest, run_command_async
from app.workflow_runtime.flaky_tests import merge_flaky_result
from app.workflow_runtime.impacted_tests import identify_impacted_tests

from .registry import detect_validator_plans, primary_validator


def _available(command: list[str]) -> bool:
    return bool(command and (Path(command[0]).exists() or shutil.which(command[0])))


def _phase(
    id: str,
    title: str,
    category: str,
    command: list[str],
    *,
    required: bool,
    detected_by: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": id,
        "title": title,
        "category": category,
        "command": [str(item) for item in command],
        "command_text": " ".join(str(item) for item in command),
        "required": bool(required),
        "detected_by": list(detected_by or []),
        "available": _available(command),
    }


def _package_scripts(project: Path) -> dict[str, str]:
    path = project / "package.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    scripts = data.get("scripts") if isinstance(data, dict) else None
    return {str(key): str(value) for key, value in scripts.items()} if isinstance(scripts, dict) else {}


def build_validation_plan(
    project_path: str | Path,
    *,
    changed_files: Iterable[dict[str, Any] | str] | None = None,
) -> dict[str, Any]:
    """Create a deterministic Build -> Test -> Lint -> Type Check plan.

    The controller only selects and runs project-native commands. It never
    generates source files or substitutes for Qwen/OpenCode implementation work.
    """
    project = Path(project_path).expanduser().resolve()
    detected = detect_validator_plans(project)
    primary = primary_validator(project)
    phases: list[dict[str, Any]] = []
    impacted = identify_impacted_tests(project, changed_files) if changed_files else {
        "schema": "aiwf.impacted-tests.v1", "changed_files": [], "tests": [], "confidence": "none", "full_suite_required": True
    }
    primary_id = str((primary or {}).get("id") or "")

    if primary_id == "python":
        phases.append(_phase("python-compile", "Python compile", "build", [sys.executable, "-m", "compileall", "-q", "."], required=True, detected_by=["*.py"]))
        impacted_paths = [str(item.get("path")) for item in impacted.get("tests") or [] if item.get("path")]
        if impacted_paths:
            phases.append(_phase(
                "python-focused-test",
                "Python impacted tests",
                "focused_test",
                [sys.executable, "-m", "pytest", *impacted_paths],
                required=True,
                detected_by=["changed-files impact map"],
            ))
        phases.append(_phase("python-test", "Python tests", "test", list(primary["command"]), required=True, detected_by=list(primary.get("detected_by") or [])))
        pyproject = (project / "pyproject.toml").read_text(encoding="utf-8", errors="replace") if (project / "pyproject.toml").is_file() else ""
        if (project / ".ruff.toml").is_file() or (project / "ruff.toml").is_file() or "[tool.ruff" in pyproject:
            phases.append(_phase("python-lint", "Ruff lint", "lint", ["ruff", "check", "."], required=False, detected_by=["ruff config"]))
        if (project / "mypy.ini").is_file() or (project / ".mypy.ini").is_file() or "[tool.mypy" in pyproject:
            phases.append(_phase("python-typecheck", "Mypy type check", "typecheck", ["mypy", "."], required=False, detected_by=["mypy config"]))
    elif primary_id == "maven":
        phases.extend([
            _phase("maven-build", "Maven build", "build", ["mvn", "-q", "-DskipTests", "package"], required=True, detected_by=["pom.xml"]),
            _phase("maven-test", "Maven tests", "test", ["mvn", "-q", "test"], required=True, detected_by=["pom.xml"]),
        ])
    elif primary_id == "gradle":
        executable = "gradlew.bat" if (project / "gradlew.bat").is_file() else "./gradlew" if (project / "gradlew").is_file() else "gradle"
        phases.extend([
            _phase("gradle-build", "Gradle build", "build", [executable, "classes"], required=True, detected_by=list(primary.get("detected_by") or [])),
            _phase("gradle-test", "Gradle tests", "test", [executable, "test"], required=True, detected_by=list(primary.get("detected_by") or [])),
        ])
    elif primary_id == "dotnet":
        target = next(iter(project.glob("*.sln")), None)
        target_args = [target.name] if target else []
        phases.extend([
            _phase("dotnet-build", ".NET build", "build", ["dotnet", "build", *target_args, "--nologo"], required=True, detected_by=list(primary.get("detected_by") or [])),
            _phase("dotnet-test", ".NET tests", "test", ["dotnet", "test", *target_args, "--no-build", "--nologo"], required=True, detected_by=list(primary.get("detected_by") or [])),
        ])
    elif primary_id == "node":
        scripts = _package_scripts(project)
        if "build" in scripts:
            phases.append(_phase("node-build", "Node build", "build", ["npm", "run", "build"], required=True, detected_by=["package.json#scripts.build"]))
        if "test" in scripts:
            phases.append(_phase("node-test", "Node tests", "test", ["npm", "test"], required=True, detected_by=["package.json#scripts.test"]))
        if "lint" in scripts:
            phases.append(_phase("node-lint", "Node lint", "lint", ["npm", "run", "lint"], required=False, detected_by=["package.json#scripts.lint"]))
        type_script = "typecheck" if "typecheck" in scripts else "type-check" if "type-check" in scripts else ""
        if type_script:
            phases.append(_phase("node-typecheck", "Node type check", "typecheck", ["npm", "run", type_script], required=False, detected_by=[f"package.json#scripts.{type_script}"]))
        if not phases:
            phases.append(_phase("node-test", "Node tests", "test", list(primary["command"]), required=True, detected_by=list(primary.get("detected_by") or [])))
    elif primary:
        phases.append(_phase(str(primary["id"]), str(primary["title"]), str(primary.get("category") or "custom"), list(primary["command"]), required=bool(primary.get("required", True)), detected_by=list(primary.get("detected_by") or [])))

    # Add non-primary syntax/configuration checks without duplicating the main command.
    seen_commands = {tuple(item["command"]) for item in phases}
    for item in detected:
        command_key = tuple(item.get("command") or [])
        if item.get("id") == primary_id or command_key in seen_commands:
            continue
        if item.get("category") not in {"syntax", "configuration", "custom"}:
            continue
        phases.append(_phase(str(item["id"]), str(item["title"]), str(item.get("category") or "validation"), list(item.get("command") or []), required=bool(item.get("required", False)), detected_by=list(item.get("detected_by") or [])))
        seen_commands.add(command_key)

    return {
        "schema": "aiwf.validation-plan.v1",
        "project_path": str(project),
        "primary_validator": primary_id or None,
        "impacted_tests": impacted,
        "phases": phases,
    }


async def _execute_phase(project: Path, phase: dict[str, Any], timeout_sec: int) -> dict[str, Any]:
    if not phase.get("available"):
        return {
            **phase,
            "status": "unavailable" if phase.get("required") else "skipped",
            "exit_code": None,
            "duration_sec": 0.0,
            "reason": f"Command is not installed: {(phase.get('command') or ['unknown'])[0]}",
        }
    async with provider_execution_slot("validator"):
        result = await run_command_async(
            CommandRequest(
                command=list(phase.get("command") or []),
                cwd=project,
                project_root=project,
                policy=CommandPolicy.PROJECT,
                shell=False,
                timeout_seconds=max(1, int(timeout_sec)),
                env={"PYTHONUTF8": "1"},
                max_output_chars=20000,
            )
        )
    if result.timed_out:
        return {
            **phase,
            "status": "failed",
            "exit_code": None,
            "error_code": "VALIDATION_TIMEOUT",
            "duration_sec": result.duration_seconds,
            "timeout_sec": timeout_sec,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    return {
        **phase,
        "status": "passed" if result.returncode == 0 else "failed",
        "exit_code": result.returncode,
        "duration_sec": result.duration_seconds,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _failure_identifiers(result: dict[str, Any]) -> set[str]:
    """Extract stable failure identifiers across common build/test tools."""
    import re

    text = "\n".join(str(result.get(key) or "") for key in ("stdout", "stderr", "reason"))
    identifiers: set[str] = set()
    patterns = [
        r"(?im)^FAILED\s+([^\s]+)",
        r"(?im)^ERROR\s+([^\s]+)",
        r"(?im)^\s*Failed\s+([^\r\n]+)",
        r"(?im)^\[ERROR\]\s+([^\r\n]+)",
        r"(?im)^\s*✕\s+([^\r\n]+)",
        r"(?im)^\s*×\s+([^\r\n]+)",
    ]
    for pattern in patterns:
        for match in re.findall(pattern, text):
            normalized = re.sub(r"\s+", " ", str(match).strip().lower())[:300]
            if normalized:
                identifiers.add(normalized)
    if not identifiers and result.get("status") in {"failed", "unavailable"}:
        normalized = re.sub(r"\s+", " ", text.strip().lower())
        normalized = re.sub(r"\b\d+(?:\.\d+)?s\b", "<time>", normalized)
        normalized = re.sub(r"0x[0-9a-f]+", "0xaddr", normalized)
        identifiers.add(normalized[-800:] if normalized else str(result.get("status")))
    return identifiers


def compare_validation_to_baseline(current: dict[str, Any], baseline: dict[str, Any] | None) -> dict[str, Any]:
    baseline_results = {str(item.get("id")): item for item in (baseline or {}).get("results") or []}
    regressions: list[dict[str, Any]] = []
    tolerated: list[dict[str, Any]] = []
    for item in current.get("results") or []:
        if not item.get("required") or item.get("status") == "passed":
            continue
        previous = baseline_results.get(str(item.get("id")))
        current_ids = _failure_identifiers(item)
        previous_ids = _failure_identifiers(previous or {}) if previous and previous.get("status") != "passed" else set()
        if previous and previous.get("status") != "passed" and current_ids and current_ids.issubset(previous_ids):
            tolerated.append({"phase": item.get("id"), "failure_identifiers": sorted(current_ids)})
        else:
            regressions.append({"phase": item.get("id"), "current": sorted(current_ids), "baseline": sorted(previous_ids)})
    return {
        "schema": "aiwf.validation-baseline-comparison.v1",
        "regression_count": len(regressions),
        "tolerated_count": len(tolerated),
        "regressions": regressions,
        "tolerated": tolerated,
    }


async def execute_validation_plan(
    project_path: str | Path,
    *,
    timeout_sec: int = 900,
    categories: Iterable[str] | None = None,
    exclude_categories: Iterable[str] | None = None,
    fail_fast: bool = True,
    changed_files: Iterable[dict[str, Any] | str] | None = None,
    profile: dict[str, Any] | None = None,
    baseline_result: dict[str, Any] | None = None,
    flaky_retries: int | None = None,
) -> dict[str, Any]:
    project = Path(project_path).expanduser().resolve()
    if profile and profile.get("phases"):
        from app.workflow_runtime.project_validation_profile import validation_plan_from_profile
        plan = validation_plan_from_profile(project, profile)
        for phase in plan.get("phases") or []:
            phase["available"] = _available(list(phase.get("command") or []))
    else:
        plan = build_validation_plan(project, changed_files=changed_files)
    include = {str(item) for item in categories or []}
    exclude = {str(item) for item in exclude_categories or []}
    phases = [
        phase for phase in plan["phases"]
        if (not include or phase.get("category") in include) and phase.get("category") not in exclude
    ]
    results: list[dict[str, Any]] = []
    rerun_limit = flaky_retries
    if rerun_limit is None:
        try:
            rerun_limit = max(0, min(3, int(os.environ.get("AIWF_FLAKY_TEST_RERUNS", "2") or 2)))
        except (TypeError, ValueError):
            rerun_limit = 2
    for phase in phases:
        result = await _execute_phase(project, phase, timeout_sec)
        if (
            result.get("status") == "failed"
            and phase.get("required")
            and phase.get("category") in {"test", "focused_test"}
            and rerun_limit > 0
        ):
            reruns: list[dict[str, Any]] = []
            for _ in range(rerun_limit):
                rerun = await _execute_phase(project, phase, timeout_sec)
                reruns.append(rerun)
                if rerun.get("status") == "passed":
                    break
            result = merge_flaky_result(result, reruns)
        results.append(result)
        if fail_fast and phase.get("required") and result.get("status") != "passed":
            break
    required_failures = [item for item in results if item.get("required") and item.get("status") != "passed"]
    flaky_results = [item for item in results if item.get("classification") == "suspected_flaky"]
    baseline_comparison = compare_validation_to_baseline({"results": results}, baseline_result) if baseline_result else None
    if required_failures and baseline_comparison and baseline_comparison.get("regression_count") == 0:
        status = "passed_with_baseline"
    else:
        status = "failed" if required_failures else "passed" if any(item.get("status") == "passed" for item in results) else "skipped"
    return {
        **plan,
        "schema": "aiwf.validation-result.v3",
        "status": status,
        "results": results,
        "executed": len(results),
        "required_failures": len(required_failures),
        "flaky_count": len(flaky_results),
        "flaky_results": flaky_results,
        "baseline_comparison": baseline_comparison,
    }


__all__ = ["build_validation_plan", "compare_validation_to_baseline", "execute_validation_plan"]
