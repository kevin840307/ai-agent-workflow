from __future__ import annotations

import ast
import json
import re
from pathlib import Path, PureWindowsPath
from urllib.parse import unquote
from typing import Any, Callable, Iterable

from app.runtime_modules.errors import ValidationError, WorkflowError
from app.core.paths import read_text, write_text
from app.security.workspace_guard import (
    LEGACY_WORKFLOW_DIR,
    PROJECT_WORKFLOW_DIR,
    RESERVED_AGENT_WRITE_DIRS,
    resolve_project_relative_write,
    unsafe_relative_path_reason as guarded_unsafe_relative_path_reason,
)

def unsafe_relative_path_reason(raw_path: str) -> str | None:
    """Return a reason when an agent-supplied path must not be written/read."""
    normalized = str(raw_path or "").strip().strip("`").replace("\\", "/").lower()
    if normalized in {"relative/path.ext", "relative_path.ext"} or normalized.startswith(("relative/path/", "relative_path/")):
        return "placeholder relative/path output is not a real project file"
    if normalized.startswith("path_to_") or normalized.startswith("example."):
        return "placeholder output path is not a real project file"
    if normalized == "opencode.json":
        return "managed agent guard config: opencode.json"
    return guarded_unsafe_relative_path_reason(raw_path, reserved_dirs=RESERVED_AGENT_WRITE_DIRS)


def require_sections(text: str, sections: Iterable[str], label: str) -> None:
    missing = [section for section in sections if f"## {section}" not in text]
    if missing:
        raise ValidationError(f"{label} missing sections: {', '.join(missing)}")


def ids_with_prefix(text: str, prefix: str) -> set[str]:
    return set(re.findall(rf"\b{prefix}-\d{{3}}\b", text))


def acceptance_criteria_items(spec: str) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for line in spec.splitlines():
        match = re.search(r"\b(AC-\d{3})\b[:.\-\s]*(.*)", line)
        if match:
            items.append((match.group(1), match.group(2).strip() or "Acceptance criterion"))
    seen: set[str] = set()
    unique: list[tuple[str, str]] = []
    for ac_id, text in items:
        if ac_id not in seen:
            seen.add(ac_id)
            unique.append((ac_id, text))
    return unique


def render_generic_todo_from_spec(output_dir: Path) -> str:
    """Render a minimal workflow task plan when the planning artifact is malformed.

    This is intentionally domain-neutral: it does not implement user code or
    infer product behavior. It only preserves the workflow contract so the
    agent can continue with explicit acceptance criteria.
    """
    spec = read_text(output_dir / "spec.md")
    ac_items = acceptance_criteria_items(spec)
    if not ac_items:
        ac_items = [("AC-001", "Complete the requested workflow requirement")]

    todo_lines = ["# Todo", "", "## Todo List"]
    for index, (ac_id, text) in enumerate(ac_items, start=1):
        todo_lines.append(f"- TODO-{index:03d} Implement and verify {ac_id}: {text}")

    todo_lines.extend(["", "## Test Plan"])
    for index, (ac_id, text) in enumerate(ac_items, start=1):
        todo_lines.append(f"- TEST-{index:03d} Test that {ac_id} is satisfied: {text}")

    covered = ", ".join(ac_id for ac_id, _ in ac_items)
    todo_lines.extend(
        [
            "",
            "## Done Criteria",
            f"- All acceptance criteria are implemented and tested: {covered}.",
            "- The workflow can proceed through review, build, test, and final review without validation errors.",
        ]
    )
    return "\n".join(todo_lines) + "\n"


def render_generic_spec_from_requirement(requirement: str) -> str:
    """Render a minimal, domain-neutral spec from the user's requirement."""
    clean_requirement = requirement.strip() or "Complete the requested project task."
    return (
        "# Specification\n\n"
        "## Goal\n"
        f"- {clean_requirement}\n\n"
        "## Scope\n"
        "- Implement the requested behavior in the selected project path.\n"
        "- Keep the solution small, readable, and suitable for automated testing.\n\n"
        "## Out of Scope\n"
        "- Do not add unrelated features or broad refactors.\n"
        "- Do not change files outside the selected project path.\n\n"
        "## Input\n"
        f"- User requirement: {clean_requirement}\n"
        "- Existing project files, if any.\n\n"
        "## Output\n"
        "- Source code implementing the requested behavior.\n"
        "- Separate automated tests for the behavior.\n\n"
        "## Rules\n"
        "- Tests must be stored separately from production code.\n"
        "- Build steps must use Qwen/OpenCode direct file edit/write tools; the platform checks the project diff.\n"
        "- Prefer simple standard-library code unless the project already uses a framework.\n\n"
        "## Acceptance Criteria\n"
        f"- AC-001: The project implements the requested behavior: {clean_requirement}\n"
        "- AC-002: Automated tests verify the main expected behavior.\n"
        "- AC-003: The test command completes successfully.\n\n"
        "## Unknowns\n"
        "- None blocking. Use reasonable defaults for unspecified implementation details.\n"
    )


def requirement_has_actionable_signal(requirement: str) -> bool:
    """Return whether the user supplied enough readable text to start.

    This intentionally avoids language, framework, domain, or action keyword
    lists. A workflow may ask follow-up questions later through its configured
    interaction policy, but the runtime should not hard-code what counts as a
    valid software request.
    """
    text = requirement.strip()
    compact = re.sub(r"[\W_]+", "", text, flags=re.UNICODE)
    return len(compact) >= 4 and bool(re.search(r"[a-z0-9\u4e00-\u9fff]", text, re.IGNORECASE))


def should_ask_for_spec_input(requirement: str, project_dir: Path, supplemental_input: str = "") -> bool:
    combined_requirement = "\n".join(part.strip() for part in [requirement, supplemental_input] if part and part.strip())
    return not requirement_has_actionable_signal(combined_requirement)


def spec_input_questions(requirement: str, project_dir: Path, supplemental_input: str = "") -> str:
    return (
        "## Requirement\n\n"
        "I cannot identify a concrete task from the current message.\n\n"
        "Please describe what you want to build, change, fix, test, scan, or generate. "
        "Include any required language, files, inputs, outputs, or constraints when they matter.\n"
    )


def classify_test_retry_target(project_dir: Path, test_result: str) -> str:
    text = test_result or ""
    lower = text.lower()
    if _mentions_project_production_python_file(project_dir, text):
        return "build"
    test_collection_or_import_problem = any(
        marker in lower
        for marker in [
            "error collecting",
            "importerror while importing test module",
            "import file mismatch",
            "is not the same as the test file",
            "syntaxerror",
        ]
    )
    if test_collection_or_import_problem:
        return "generate_tests"
    generated_test_runtime_problem = (
        ("nameerror:" in lower or "attributeerror:" in lower)
        and ("test_" in lower or "tests/" in lower or "tests\\" in lower)
    )
    if generated_test_runtime_problem:
        return "generate_tests"
    return "build"


def _mentions_project_production_python_file(project_dir: Path, text: str) -> bool:
    project_root = project_dir.expanduser().resolve()
    for raw_path in re.findall(r'File "([^"]+?\.py)"', text or ""):
        try:
            path = Path(raw_path).expanduser().resolve()
        except OSError:
            continue
        try:
            rel = path.relative_to(project_root).as_posix().lower()
        except ValueError:
            continue
        if rel and not rel.startswith("tests/"):
            return True
    return False


def failure_feedback_for_step(all_feedback: str, step_key: str, *, latest_only: bool = False) -> str:
    if not all_feedback.strip():
        return ""
    pattern = re.compile(
        rf"^## Retry Feedback for {re.escape(step_key)}\s*$.*?(?=^## Retry Feedback for |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    blocks = [match.group(0).strip() for match in pattern.finditer(all_feedback)]
    if latest_only:
        return blocks[-1] if blocks else ""
    return "\n\n".join(blocks)


def project_file_snapshot(project_dir: Path) -> dict[str, tuple[int, int]]:
    snapshot: dict[str, tuple[int, int]] = {}
    if not project_dir.exists():
        return snapshot
    ignored_dirs = {".git", ".vs", ".qwen", LEGACY_WORKFLOW_DIR, PROJECT_WORKFLOW_DIR, "__pycache__", ".pytest_cache", ".mypy_cache", "node_modules", ".venv", "venv", "workspaces", "dist", "build", ".next", "coverage"}
    ignored_files = {"opencode.json"}
    for path in project_dir.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(project_dir).parts
        if any(part in ignored_dirs for part in rel_parts):
            continue
        if path.name in ignored_files:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        snapshot[str(path.relative_to(project_dir))] = (stat.st_size, stat.st_mtime_ns)
    return snapshot


def project_content_snapshot(project_dir: Path) -> dict[str, bytes]:
    """Capture project file bytes for restoring a failed agent attempt.

    This uses the same visible-file boundary as project_file_snapshot so agent
    guard files, workflow run artifacts, virtual environments, and dependency
    folders are not copied or restored.
    """
    snapshot: dict[str, bytes] = {}
    for rel_path in project_file_snapshot(project_dir):
        target = project_dir / rel_path
        try:
            snapshot[rel_path] = target.read_bytes()
        except OSError:
            continue
    return snapshot


def restore_selected_project_paths(
    project_dir: Path,
    snapshot: dict[str, bytes],
    rel_paths: Iterable[str],
) -> list[str]:
    """Restore or remove selected project paths using a pre-step snapshot.

    This is intentionally narrower than ``restore_project_content_snapshot``. It
    lets the controller reject files that belong to the wrong workflow phase
    (for example Build-created tests) while preserving valid source edits from
    the same agent attempt. Paths absent from the snapshot are deleted; paths
    present in the snapshot are restored byte-for-byte.
    """
    project_root = project_dir.expanduser().resolve()
    restored: list[str] = []
    normalized_paths = sorted({normalized_rel_path(value) for value in rel_paths if str(value).strip()})
    for rel_path in normalized_paths:
        target = (project_root / rel_path).resolve()
        try:
            target.relative_to(project_root)
        except ValueError:
            continue
        if rel_path in snapshot:
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                target.write_bytes(snapshot[rel_path])
                restored.append(rel_path)
            except OSError:
                continue
        else:
            try:
                if target.is_file():
                    target.unlink()
                    restored.append(rel_path)
            except OSError:
                continue

    # Remove empty directories left by newly-created rejected files, but never
    # walk above the selected Project Path.
    candidate_dirs = sorted(
        {(project_root / rel).parent for rel in normalized_paths},
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for directory in candidate_dirs:
        current = directory
        while current != project_root:
            try:
                current.relative_to(project_root)
            except ValueError:
                break
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent
    return restored


def restore_project_content_snapshot(project_dir: Path, snapshot: dict[str, bytes]) -> None:
    """Restore project files to a previous content snapshot.

    Files created after the snapshot are removed; files present in the snapshot
    are rewritten with their original bytes. Empty directories left behind by
    removed files are pruned inside the project root.
    """
    project_root = project_dir.expanduser().resolve()
    current_paths = set(project_file_snapshot(project_dir))
    snapshot_paths = set(snapshot)

    for rel_path in sorted(current_paths - snapshot_paths, key=lambda value: value.count("/"), reverse=True):
        target = (project_root / rel_path).resolve()
        try:
            target.relative_to(project_root)
        except ValueError:
            continue
        try:
            if target.is_file():
                target.unlink()
        except OSError:
            continue

    for rel_path, content in snapshot.items():
        target = (project_root / rel_path).resolve()
        try:
            target.relative_to(project_root)
        except ValueError:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.write_bytes(content)
        except OSError:
            continue

    _prune_empty_project_dirs(project_root)


def _prune_empty_project_dirs(project_root: Path) -> None:
    ignored = {".git", ".vs", ".qwen", LEGACY_WORKFLOW_DIR, PROJECT_WORKFLOW_DIR, "node_modules", ".venv", "venv"}
    if not project_root.is_dir():
        return
    dirs = [path for path in project_root.rglob("*") if path.is_dir()]
    for path in sorted(dirs, key=lambda item: len(item.parts), reverse=True):
        try:
            rel_parts = path.relative_to(project_root).parts
        except ValueError:
            continue
        if any(part in ignored for part in rel_parts):
            continue
        try:
            path.rmdir()
        except OSError:
            continue


def project_has_user_files(project_dir: Path) -> bool:
    return bool(project_file_snapshot(project_dir))


def project_overview(project_dir: Path, limit: int = 180) -> str:
    snapshot = project_file_snapshot(project_dir)
    if not snapshot:
        return "Project appears empty."
    paths = sorted(snapshot)
    shown = paths[:limit]
    lines = [f"- {path}" for path in shown]
    if len(paths) > limit:
        lines.append(f"- ... {len(paths) - limit} more files")
    return "\n".join(lines)


def project_profile(project_dir: Path) -> str:
    snapshot = project_file_snapshot(project_dir)
    if not snapshot:
        return (
            "Project appears empty.\n"
            "- Dominant source extensions: none.\n"
            "- Architecture guidance: create a minimal structure for the requested language."
        )

    paths = sorted(snapshot)
    normalized_paths = [path.replace("\\", "/") for path in paths]
    lower_paths = [path.lower() for path in normalized_paths]
    suffix_counts: dict[str, int] = {}
    for path in normalized_paths:
        suffix = Path(path).suffix.lower()
        if suffix:
            suffix_counts[suffix] = suffix_counts.get(suffix, 0) + 1

    test_frameworks = _detect_test_frameworks(project_dir, lower_paths)
    source_files = _sample_paths(normalized_paths, _is_source_path, 12)
    test_files = _sample_paths(normalized_paths, _is_test_path, 12)
    marker_files = _sample_paths(normalized_paths, _is_marker_file, 12)
    source_roots = _source_roots(source_files)
    dominant_extensions = ", ".join(f"{suffix} ({count})" for suffix, count in sorted(suffix_counts.items(), key=lambda item: (-item[1], item[0]))[:8])

    return "\n".join(
        [
            "Detected project profile:",
            f"- Dominant source extensions: {dominant_extensions or 'none detected'}",
            f"- Test framework: {', '.join(test_frameworks) if test_frameworks else 'unknown'}",
            f"- Marker/config files: {', '.join(marker_files) if marker_files else 'none detected'}",
            f"- Source roots by usage: {', '.join(source_roots) if source_roots else 'none detected'}",
            f"- Existing source files: {', '.join(source_files) if source_files else 'none detected'}",
            f"- Existing test files: {', '.join(test_files) if test_files else 'none detected'}",
            "- Architecture guidance: extend the dominant existing language, module layout, naming, and test style. Do not introduce a new src/tests layout unless it is the dominant source root or architecture.md says to use it.",
        ]
    )



def render_project_index_markdown(project_dir: Path) -> str:
    """Render a deterministic project index for coding-agent prompts.

    The index is intentionally generated by Python instead of an agent so later
    steps receive stable evidence about the selected project. It is read-only
    context; it never infers domain behavior or creates production files.
    """
    snapshot = project_file_snapshot(project_dir)
    profile = project_profile(project_dir)
    overview = project_overview(project_dir, limit=240)
    test_commands = infer_test_commands(project_dir, snapshot)
    protected = [".git", PROJECT_WORKFLOW_DIR, LEGACY_WORKFLOW_DIR]
    lines = [
        "# Project Index",
        "",
        "Status: READY",
        "",
        "## Project Path",
        f"- {project_dir.expanduser().resolve()}",
        "",
        "## Deterministic Profile",
        profile,
        "",
        "## Suggested Test Commands",
    ]
    if test_commands:
        lines.extend(f"- `{command}`" for command in test_commands)
    else:
        lines.append("- Unknown; use the configured workflow test command or project convention.")
    lines.extend(
        [
            "",
            "## Workspace Isolation",
            "- Agent writes must stay inside Project Path.",
            "- External paths may be read as context but are not write targets.",
            "- Protected write directories: " + ", ".join(f"`{name}`" for name in protected),
            "",
            "## Visible Files",
            overview,
            "",
        ]
    )
    return "\n".join(lines)


def infer_test_commands(project_dir: Path, snapshot: dict[str, tuple[int, int]] | None = None) -> list[str]:
    """Infer likely test commands from stable project markers."""
    snapshot = snapshot if snapshot is not None else project_file_snapshot(project_dir)
    lower_paths = {path.replace("\\", "/").lower() for path in snapshot}
    commands: list[str] = []
    if "pytest.ini" in lower_paths or any(path.startswith("tests/test_") for path in lower_paths) or "pyproject.toml" in lower_paths:
        commands.append("python -m pytest")
    if "package.json" in lower_paths:
        package_text = read_text(project_dir / "package.json")
        try:
            package = json.loads(package_text)
        except json.JSONDecodeError:
            package = {}
        scripts = package.get("scripts") if isinstance(package, dict) else {}
        if isinstance(scripts, dict) and "test" in scripts:
            commands.append("npm test")
        elif "vitest" in package_text.lower():
            commands.append("npx vitest run")
    if "pom.xml" in lower_paths:
        commands.append("mvn test")
    if "build.gradle" in lower_paths or "build.gradle.kts" in lower_paths:
        commands.append("./gradlew test")
    if "go.mod" in lower_paths:
        commands.append("go test ./...")
    if "cargo.toml" in lower_paths:
        commands.append("cargo test")
    return _unique(commands)

def _detect_test_frameworks(project_dir: Path, lower_paths: list[str]) -> list[str]:
    frameworks: list[str] = []
    if any(path == "pytest.ini" or path.startswith("tests/test_") for path in lower_paths):
        frameworks.append("pytest")
    if any(path.endswith(".py") and "unittest" in _safe_read_lower(project_dir / path) for path in lower_paths[:80]):
        frameworks.append("unittest")
    if "package.json" in lower_paths:
        package_text = read_text(project_dir / "package.json")
        try:
            package = json.loads(package_text)
        except json.JSONDecodeError:
            package = {}
        package_blob = json.dumps(package).lower() if package else package_text.lower()
        for name in ["vitest", "jest", "mocha", "playwright"]:
            if name in package_blob:
                frameworks.append(name)
    if any(path == "pom.xml" for path in lower_paths):
        frameworks.append("maven test")
    if any(path == "build.gradle" or path == "build.gradle.kts" for path in lower_paths):
        frameworks.append("gradle test")
    return _unique(frameworks)


def _sample_paths(paths: list[str], predicate: Callable[[str], bool], limit: int) -> list[str]:
    return [path for path in paths if predicate(path.replace("\\", "/"))][:limit]


def _source_roots(source_files: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    for source_file in source_files:
        parts = Path(source_file).parts
        root = parts[0] if len(parts) > 1 else "."
        counts[root] = counts.get(root, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], 0 if item[0] == "." else 1, item[0]))
    return [f"{root} ({count})" for root, count in ranked]


def _is_source_path(path: str) -> bool:
    lower = path.lower()
    if _is_test_path(lower):
        return False
    return Path(lower).suffix in {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".cs", ".go", ".rs", ".php", ".rb"}


def _is_test_path(path: str) -> bool:
    lower = path.lower()
    name = Path(lower).name
    return (
        lower.startswith("tests/")
        or "/tests/" in lower
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name.endswith(".test.js")
        or name.endswith(".spec.js")
        or name.endswith(".test.ts")
        or name.endswith(".spec.ts")
        or name.endswith("test.java")
    )


def _is_marker_file(path: str) -> bool:
    name = Path(path.lower()).name
    return name in {
        "architecture.md",
        "pyproject.toml",
        "requirements.txt",
        "pytest.ini",
        "setup.py",
        "tox.ini",
        "package.json",
        "tsconfig.json",
        "vite.config.js",
        "vite.config.ts",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "go.mod",
        "cargo.toml",
        "composer.json",
        "gemfile",
    } or name.endswith(".csproj") or name.endswith(".sln")


def _safe_read_lower(path: Path, max_chars: int = 8000) -> str:
    try:
        return read_text(path)[:max_chars].lower()
    except OSError:
        return ""


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            unique_values.append(value)
    return unique_values


def snapshot_changed(before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]) -> bool:
    return before != after


def changed_snapshot_paths(before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]) -> list[str]:
    """Return added, modified, or deleted project-relative paths."""
    keys = sorted(set(before) | set(after))
    return [key for key in keys if before.get(key) != after.get(key)]


def files_from_changed_snapshot(project_dir: Path, changed_paths: list[str]) -> list[tuple[str, str]]:
    """Read changed project files into project-relative text tuples."""
    files: list[tuple[str, str]] = []
    project_root = project_dir.expanduser().resolve()
    for rel_path in changed_paths:
        normalized = str(rel_path).replace("\\", "/")
        reason = unsafe_relative_path_reason(normalized)
        if reason:
            raise WorkflowError(f"Agent changed unsafe project path ({reason}): {normalized}")
        target = (project_root / normalized).resolve()
        if not target.is_file():
            continue
        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = target.read_bytes().decode("utf-8", errors="replace")
        files.append((normalized, content.rstrip("\n") + "\n"))
    return files



def normalized_rel_path(rel_path: str) -> str:
    return rel_path.strip().strip("`").replace("\\", "/")


def is_test_file_path(rel_path: str) -> bool:
    normalized = normalized_rel_path(rel_path)
    path = Path(normalized)
    parts = path.parts
    if not parts:
        return False
    if "tests" not in parts:
        return False
    name = path.name
    return name == "conftest.py" or (name.startswith("test_") and name.endswith(".py"))


def is_pytest_file_name(rel_path: str) -> bool:
    """Return whether *rel_path* has a pytest-discoverable Python filename.

    Pytest's default discovery accepts ``test_*.py`` and ``*_test.py``.  The
    controller still prefers ``tests/`` for newly created files, but existing
    projects are allowed to keep an established root-level test layout.
    """
    name = Path(normalized_rel_path(rel_path)).name.lower()
    return name == "conftest.py" or (
        name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py"))
    )


def is_owned_test_file_path(rel_path: str, *, existing_paths: Iterable[str] | None = None) -> bool:
    """Return whether Generate Tests may own the path.

    New tests must use the canonical ``tests/`` layout.  A pre-existing
    root-level pytest file is also accepted so the workflow can extend legacy
    projects without restoring a valid edit and entering a pointless retry
    loop.  This intentionally does *not* permit creating a new root test when a
    canonical test layout is available.
    """
    normalized = normalized_rel_path(rel_path)
    if is_test_file_path(normalized):
        return True
    existing = {normalized_rel_path(item) for item in (existing_paths or [])}
    return normalized in existing and is_pytest_file_name(normalized)


def validate_generated_test_files(
    files: list[tuple[str, str]],
    *,
    project_dir: Path | None = None,
    existing_paths: Iterable[str] | None = None,
) -> None:
    if not files:
        raise WorkflowError("generate_tests did not directly create any test files under tests/. Use Qwen/OpenCode edit/write tools; the platform checks the project diff.")
    invalid = [
        rel_path
        for rel_path, _ in files
        if not is_owned_test_file_path(rel_path, existing_paths=existing_paths)
    ]
    if invalid:
        raise WorkflowError(
            "generate_tests can only write new pytest files under tests/, or modify an existing "
            "pytest-discoverable file already present in the project. "
            f"Invalid file(s): {', '.join(invalid)}"
        )
    syntax_errors: list[str] = []
    for rel_path, content in files:
        if Path(rel_path).suffix.lower() != ".py":
            continue
        try:
            compile(content, rel_path, "exec")
        except SyntaxError as exc:
            syntax_errors.append(f"{rel_path}: {exc.msg} at line {exc.lineno}")
    if syntax_errors:
        raise WorkflowError("generate_tests produced invalid Python syntax. " + "; ".join(syntax_errors))
    placeholder_tests = [
        rel_path
        for rel_path, content in files
        if Path(rel_path).name == "test_example.py"
        or re.search(r"^\s*(from\s+example\s+import|import\s+example\b)", content, re.MULTILINE)
        or re.search(r"^\s*(from\s+your_module\s+import|import\s+your_module\b)", content, re.MULTILINE)
        or re.search(r"Replace ['\"]?your_module['\"]? with the actual module", content, re.IGNORECASE)
        or re.search(r"(?m)^\s*assert\s+False\b", content)
        or re.search(r"implementation\s+is\s+incomplete|TODO-only|placeholder", content, re.IGNORECASE)
    ]
    if placeholder_tests:
        raise WorkflowError("generate_tests produced placeholder example tests instead of project-specific tests: " + ", ".join(placeholder_tests))
    concrete_test_files = [rel_path for rel_path, _ in files if Path(rel_path).name != "conftest.py"]
    if not concrete_test_files:
        raise WorkflowError("generate_tests must produce at least one concrete pytest test file under tests/test_*.py, not only conftest.py.")
    files_without_tests = [
        rel_path
        for rel_path, content in files
        if Path(rel_path).name != "conftest.py"
        and not re.search(r"(?m)^\s*(def|async\s+def)\s+test_[A-Za-z0-9_]*\s*\(", content)
        and not re.search(r"(?m)^\s*class\s+Test[A-Za-z0-9_]*\s*[:(]", content)
    ]
    if files_without_tests and len(files_without_tests) == len(concrete_test_files):
        raise WorkflowError("generate_tests produced pytest files without test functions or Test* classes: " + ", ".join(files_without_tests))
    fixture_errors = _test_functions_with_unresolved_required_args(files, project_dir=project_dir)
    if fixture_errors:
        raise WorkflowError(
            "generate_tests produced pytest functions with unresolved required fixture arguments: "
            + ", ".join(fixture_errors)
        )


PYTEST_BUILTIN_FIXTURES = {
    "cache", "capfd", "capfdbinary", "caplog", "capsys", "capsysbinary",
    "doctest_namespace", "monkeypatch", "pytestconfig", "record_property",
    "record_testsuite_property", "record_xml_attribute", "recwarn", "request",
    "tmp_path", "tmp_path_factory", "tmpdir", "tmpdir_factory",
}


def _test_functions_with_unresolved_required_args(
    files: list[tuple[str, str]], *, project_dir: Path | None = None
) -> list[str]:
    fixture_names: set[str] = set(PYTEST_BUILTIN_FIXTURES)
    parsed_files: list[tuple[str, ast.AST]] = []

    sources: list[tuple[str, str]] = list(files)
    if project_dir is not None:
        root = Path(project_dir).expanduser().resolve()
        for conftest in root.rglob("conftest.py"):
            if ".ai-workflow" in conftest.parts or "__pycache__" in conftest.parts:
                continue
            try:
                rel = conftest.relative_to(root).as_posix()
                if not any(Path(path).as_posix() == rel for path, _content in sources):
                    sources.append((rel, conftest.read_text(encoding="utf-8-sig")))
            except (OSError, UnicodeError, ValueError):
                continue

    for rel_path, content in sources:
        if Path(rel_path).suffix.lower() != ".py":
            continue
        try:
            tree = ast.parse(content, filename=rel_path)
        except SyntaxError:
            continue
        if any(Path(path).as_posix() == Path(rel_path).as_posix() for path, _content in files):
            parsed_files.append((rel_path, tree))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_pytest_fixture(node):
                fixture_names.add(node.name)

    errors: list[str] = []
    for rel_path, tree in parsed_files:
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.name.startswith("test_"):
                continue
            parametrized = _pytest_parametrize_names(node)
            for arg in _required_test_args(node):
                if arg not in fixture_names and arg not in parametrized:
                    errors.append(f"{rel_path}:{node.name}({arg})")
    return errors


def _pytest_parametrize_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    names: set[str] = set()
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        target = decorator.func
        is_parametrize = (
            isinstance(target, ast.Attribute) and target.attr == "parametrize"
        ) or (isinstance(target, ast.Name) and target.id == "parametrize")
        if not is_parametrize or not decorator.args:
            continue
        raw = decorator.args[0]
        if isinstance(raw, ast.Constant) and isinstance(raw.value, str):
            names.update(item.strip() for item in raw.value.split(",") if item.strip())
        elif isinstance(raw, (ast.List, ast.Tuple)):
            for item in raw.elts:
                if isinstance(item, ast.Constant) and isinstance(item.value, str):
                    names.add(item.value.strip())
    return names


def _is_pytest_fixture(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Attribute) and target.attr == "fixture":
            return True
        if isinstance(target, ast.Name) and target.id == "fixture":
            return True
    return False


def _required_test_args(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    args = list(node.args.posonlyargs) + list(node.args.args)
    if args and args[0].arg in {"self", "cls"}:
        args = args[1:]
    default_count = len(node.args.defaults)
    required_count = max(0, len(args) - default_count)
    return [arg.arg for arg in args[:required_count]]


def is_build_test_file_path(rel_path: str) -> bool:
    normalized = normalized_rel_path(rel_path)
    return is_test_file_path(normalized) or Path(normalized).name.startswith("test_")


def split_build_files(files: list[tuple[str, str]]) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    production_files: list[tuple[str, str]] = []
    test_files: list[tuple[str, str]] = []
    for file_block in files:
        rel_path, _ = file_block
        if is_build_test_file_path(rel_path):
            test_files.append(file_block)
        else:
            production_files.append(file_block)
    return production_files, test_files


def validate_build_files_are_not_tests(files: list[tuple[str, str]]) -> None:
    invalid = [rel_path for rel_path, _ in files if is_build_test_file_path(rel_path)]
    if invalid:
        raise WorkflowError(
            "build must not create or modify test files. Generate Tests owns tests/. "
            f"Invalid build file(s): {', '.join(invalid)}"
        )


def existing_validation_scripts(
    project_dir: Path,
    validation_script: str | None = None,
    fallback_scripts: Iterable[str] | None = None,
) -> set[Path]:
    """Return validation scripts that already exist before Build starts.

    Existing validation scripts are user-provided acceptance tools. Build may
    read them, but must not rewrite them to make validation pass.
    """
    project_root = project_dir.expanduser().resolve()
    scripts: set[Path] = set()
    if validation_script:
        candidate = Path(validation_script).expanduser()
        path = candidate if candidate.is_absolute() else project_root / candidate
        if path.is_file():
            scripts.add(path.resolve())
    for name in fallback_scripts or []:
        path = project_root / name
        if path.is_file():
            scripts.add(path.resolve())
    return scripts


def validation_script_protected_names(
    validation_script: str | None = None,
    fallback_scripts: Iterable[str] | None = None,
) -> set[str]:
    names: set[str] = set()
    if validation_script:
        candidate_name = Path(validation_script).name.strip().lower()
        if candidate_name:
            names.add(candidate_name)
    for name in fallback_scripts or []:
        candidate_name = Path(str(name)).name.strip().lower()
        if candidate_name:
            names.add(candidate_name)
    return names


def validate_build_files_do_not_overwrite_validation_scripts(
    project_dir: Path,
    files: list[tuple[str, str]],
    *,
    validation_script: str | None = None,
    fallback_scripts: Iterable[str] | None = None,
) -> None:
    protected_scripts = existing_validation_scripts(project_dir, validation_script, fallback_scripts)
    protected_names = validation_script_protected_names(validation_script, fallback_scripts)
    if not protected_scripts and not protected_names:
        return
    project_root = project_dir.expanduser().resolve()
    invalid: list[str] = []
    for rel_path, _content in files:
        target = resolve_project_relative_write(project_root, rel_path, label="build output")
        if target.resolve() in protected_scripts or _matches_protected_validation_name(target.name, protected_names):
            invalid.append(rel_path)
    if invalid:
        raise WorkflowError(
            "build must not create, copy, or modify validation scripts. "
            "Validation scripts are user-provided acceptance tools, not Build-owned artifacts. "
            f"Invalid build file(s): {', '.join(invalid)}"
        )


def _matches_protected_validation_name(file_name: str, protected_names: set[str]) -> bool:
    normalized = file_name.strip().lower()
    return any(name and (normalized == name or name in normalized) for name in protected_names)


def validate_generated_code_files_are_clean(files: list[tuple[str, str]]) -> None:
    invalid_markers: list[str] = []
    syntax_errors: list[str] = []
    marker_pattern = re.compile(
        r"(?m)^(?:## Retry Feedback for |FILE:\s|CONTENT:\s*$|END_FILE\s*$|```)"
    )
    for rel_path, content in files:
        suffix = Path(rel_path).suffix.lower()
        if suffix not in {".py"}:
            continue
        if marker_pattern.search(content or ""):
            invalid_markers.append(rel_path)
            continue
        try:
            compile(content or "", rel_path, "exec")
        except SyntaxError as exc:
            syntax_errors.append(f"{rel_path}: {exc.msg} at line {exc.lineno}")
    if invalid_markers:
        raise WorkflowError(
            "generated Python files must contain source code only, not workflow feedback, markdown fences, "
            "or FILE/CONTENT/END_FILE markers. Invalid file(s): " + ", ".join(invalid_markers)
        )
    if syntax_errors:
        raise WorkflowError("generated Python files contain invalid syntax. " + "; ".join(syntax_errors))


def validate_test_code_is_separate(files: list[tuple[str, str]]) -> None:
    invalid: list[str] = []
    for rel_path, content in files:
        if is_test_file_path(rel_path):
            continue
        suffix = Path(rel_path).suffix.lower()
        if suffix == ".py" and re.search(r"(?m)^\s*(?:async\s+)?def\s+test_[A-Za-z0-9_]*\s*\(", content or ""):
            invalid.append(rel_path)
            continue
        if suffix == ".py" and re.search(r"(?m)^\s*class\s+Test[A-Za-z0-9_]*\b", content or ""):
            invalid.append(rel_path)
            continue
        if re.search(r"(?m)^\s*(?:def\s+test_|class\s+Test[A-Za-z0-9_]*\b)", content or ""):
            invalid.append(rel_path)
    if invalid:
        raise WorkflowError(
            "test code must be separated from production files. "
            "Put pytest tests under tests/ instead of embedding them in production artifacts or project-root files. "
            f"Invalid file(s): {', '.join(invalid)}"
        )


def only_test_files(files: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [file_block for file_block in files if is_test_file_path(file_block[0])]


def non_test_files(files: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [file_block for file_block in files if not is_test_file_path(file_block[0])]


def build_generic_python_import_smoke_test(
    project_dir: Path,
    requirement: str = "",
    *,
    excluded_paths: Iterable[Path] | None = None,
) -> list[tuple[str, str]]:
    """Create a generic import-only smoke test for Python modules.

    This does not assert domain behavior; it is only a safety net when an
    existing Python project has code but the agent failed to emit valid test
    blocks. Requirement behavior must still be covered by generated tests or
    external validation.
    """
    snapshot = project_file_snapshot(project_dir)
    project_root = project_dir.expanduser().resolve()
    excluded: set[str] = set()
    for path in excluded_paths or []:
        try:
            excluded.add(path.expanduser().resolve().relative_to(project_root).as_posix())
        except ValueError:
            continue
    python_files = [
        path
        for path in sorted(snapshot)
        if path.endswith(".py")
        and not is_build_test_file_path(path)
        and not Path(path).name.startswith("__")
        and Path(path).name != "conftest.py"
        and path.replace("\\", "/") not in excluded
    ]
    if not python_files:
        return []
    shown = [path.replace("\\", "/") for path in python_files[:20]]
    list_literal = "[\n" + "".join(f"    {path!r},\n" for path in shown) + "]"
    content = (
        "from __future__ import annotations\n\n"
        "import importlib.util\n"
        "from pathlib import Path\n\n"
        "PROJECT_ROOT = Path(__file__).resolve().parents[1]\n"
        f"PYTHON_FILES = {list_literal}\n\n\n"
        "def _load_module(relative_path: str):\n"
        "    path = PROJECT_ROOT / relative_path\n"
        "    module_name = 'ai_workflow_smoke_' + relative_path.replace('/', '_').replace('\\\\', '_').replace('.', '_')\n"
        "    spec = importlib.util.spec_from_file_location(module_name, path)\n"
        "    assert spec is not None and spec.loader is not None, f'Cannot load {relative_path}'\n"
        "    module = importlib.util.module_from_spec(spec)\n"
        "    spec.loader.exec_module(module)\n"
        "    return module\n\n\n"
        "def test_generated_python_modules_import_cleanly():\n"
        "    assert PYTHON_FILES, 'Expected at least one production Python file'\n"
        "    for relative_path in PYTHON_FILES:\n"
        "        _load_module(relative_path)\n"
        "\n"
    )
    return [("tests/test_ai_workflow_generated_smoke.py", content)]


def build_validation_script_pytest_wrapper(
    project_dir: Path,
    validation_script: str | None = None,
    fallback_scripts: Iterable[str] | None = None,
) -> list[tuple[str, str]]:
    """Wrap the user-provided validation script as a pytest test."""
    script = _find_validation_script_for_tests(project_dir, validation_script, fallback_scripts)
    if script is None:
        return []
    rel_script = script.relative_to(project_dir).as_posix()
    content = (
        "from __future__ import annotations\n\n"
        "import subprocess\n"
        "import sys\n"
        "from pathlib import Path\n\n"
        "PROJECT_ROOT = Path(__file__).resolve().parents[1]\n"
        f"VALIDATION_SCRIPT = PROJECT_ROOT / {rel_script!r}\n\n\n"
        "def test_validation_script_passes():\n"
        "    command = [\n"
        "        sys.executable,\n"
        "        str(VALIDATION_SCRIPT),\n"
        "        '--project',\n"
        "        str(PROJECT_ROOT),\n"
        "        '--workspace',\n"
        "        str(PROJECT_ROOT),\n"
        "        '--output',\n"
        "        str(PROJECT_ROOT),\n"
        "    ]\n"
        "    proc = subprocess.run(\n"
        "        command,\n"
        "        cwd=PROJECT_ROOT,\n"
        "        text=True,\n"
        "        capture_output=True,\n"
        "        timeout=120,\n"
        "    )\n"
        "    if proc.returncode != 0 and _looks_like_argument_error(proc.stderr):\n"
        "        proc = subprocess.run(\n"
        "            [sys.executable, str(VALIDATION_SCRIPT)],\n"
        "            cwd=PROJECT_ROOT,\n"
        "            text=True,\n"
        "            capture_output=True,\n"
        "            timeout=120,\n"
        "        )\n"
        "    assert proc.returncode == 0, proc.stdout + proc.stderr\n\n\n"
        "def _looks_like_argument_error(stderr: str) -> bool:\n"
        "    lowered = (stderr or '').lower()\n"
        "    return any(marker in lowered for marker in ['unrecognized arguments', 'unknown option', 'no such option', 'usage:'])\n"
    )
    return [("tests/test_ai_workflow_validation.py", content)]


def _find_validation_script_for_tests(
    project_dir: Path,
    validation_script: str | None = None,
    fallback_scripts: Iterable[str] | None = None,
) -> Path | None:
    if validation_script:
        candidate = Path(validation_script).expanduser()
        path = candidate if candidate.is_absolute() else project_dir / candidate
        path = path.resolve()
        try:
            path.relative_to(project_dir.resolve())
        except ValueError:
            return None
        return path if path.is_file() and path.suffix.lower() == ".py" else None
    for name in fallback_scripts or []:
        candidate = project_dir / name
        if candidate.is_file():
            return candidate.resolve()
    return None
