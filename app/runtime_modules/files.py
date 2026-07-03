from __future__ import annotations

import json
import re
from pathlib import Path, PureWindowsPath
from urllib.parse import unquote
from typing import Callable, Iterable

from app.runtime_modules.errors import ValidationError, WorkflowError
from app.core.paths import read_text, write_text
from app.security.workspace_guard import (
    LEGACY_WORKFLOW_DIR,
    PROJECT_WORKFLOW_DIR,
    RESERVED_AGENT_WRITE_DIRS,
    resolve_project_relative_write,
    unsafe_relative_path_reason as guarded_unsafe_relative_path_reason,
)

VALIDATION_SCRIPT_NAMES = ("validation.py", "validate.py", "verify.py", "check.py")


def unsafe_relative_path_reason(raw_path: str) -> str | None:
    """Return a reason when an agent-supplied path must not be written/read."""
    normalized = str(raw_path or "").strip().strip("`").replace("\\", "/").lower()
    if normalized in {"relative/path.ext", "relative_path.ext"} or normalized.startswith(("relative/path/", "relative_path/")):
        return "placeholder relative/path output is not a real project file"
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
        "- Build output must use FILE/CONTENT/END_FILE blocks when creating or modifying files.\n"
        "- Prefer simple standard-library code unless the project already uses a framework.\n\n"
        "## Acceptance Criteria\n"
        f"- AC-001: The project implements the requested behavior: {clean_requirement}\n"
        "- AC-002: Automated tests verify the main expected behavior.\n"
        "- AC-003: The test command completes successfully.\n\n"
        "## Unknowns\n"
        "- None blocking. Use reasonable defaults for unspecified implementation details.\n"
    )


def requirement_mentions_language(requirement: str) -> bool:
    lower = requirement.lower()
    keywords = [
        "python",
        ".py",
        "javascript",
        "typescript",
        "node",
        "java",
        "c#",
        "c++",
        "go",
        "rust",
        "php",
        "ruby",
        "批次",
        "腳本",
    ]
    return any(keyword in lower for keyword in keywords)


GENERAL_REQUEST_VERBS = (
    "add", "build", "create", "implement", "write", "make", "fix",
    "update", "optimize", "refactor", "review", "test", "scan", "generate",
    "新增", "加入", "建立", "建置", "製作", "撰寫", "寫", "做",
    "修改", "修正", "優化", "重構", "檢查", "測試", "掃描", "產生",
)


def requirement_has_actionable_signal(requirement: str) -> bool:
    """Return whether the user supplied enough text to attempt a workflow.

    Keep only generic request verbs here. Do not add domain examples such as
    sorting, APIs, UI pages, or security keywords; those make the General Auto
    Development workflow look like it contains hidden hard-coded use cases.
    Stack/language ambiguity is handled separately by should_ask_for_spec_input().
    """
    text = requirement.strip()
    compact = re.sub(r"[\W_]+", "", text, flags=re.UNICODE)
    if len(compact) < 4 or not re.search(r"[a-z0-9\u4e00-\u9fff]", text, re.IGNORECASE):
        return False
    lowered = text.lower()
    return any(verb in lowered for verb in GENERAL_REQUEST_VERBS)


def should_ask_for_spec_input(requirement: str, project_dir: Path, supplemental_input: str = "") -> bool:
    combined_requirement = "\n".join(part.strip() for part in [requirement, supplemental_input] if part and part.strip())
    if not requirement_has_actionable_signal(combined_requirement):
        return True
    return not project_has_user_files(project_dir) and not requirement_mentions_language(combined_requirement)


def spec_input_questions(requirement: str, project_dir: Path, supplemental_input: str = "") -> str:
    combined_requirement = "\n".join(part.strip() for part in [requirement, supplemental_input] if part and part.strip())
    if not requirement_has_actionable_signal(combined_requirement):
        return (
            "## Requirement\n\n"
            "I cannot identify a concrete task from the current message.\n\n"
            "Please describe what you want to build, change, fix, test, or scan. "
            "Include the target language or project area if this is a new or empty project.\n"
        )
    if not project_has_user_files(project_dir) and not requirement_mentions_language(combined_requirement):
        return (
            "## Target Language\n\n"
            "This project appears empty, and the requirement does not say which language or stack to use.\n\n"
            "Please tell me the target language or stack, for example Python, JavaScript, TypeScript, Java, Go, or another option.\n"
        )
    return (
        "## Missing Information\n\n"
        "Please provide the missing blocking detail needed to produce the workflow spec.\n"
    )



def classify_test_retry_target(project_dir: Path, test_result: str) -> str:
    text = test_result or ""
    lower = text.lower()
    test_collection_or_import_problem = any(
        marker in lower
        for marker in [
            "error collecting",
            "importerror while importing test module",
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


def failure_feedback_for_step(all_feedback: str, step_key: str) -> str:
    if not all_feedback.strip():
        return ""
    pattern = re.compile(
        rf"^## Retry Feedback for {re.escape(step_key)}\s*$.*?(?=^## Retry Feedback for |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    blocks = [match.group(0).strip() for match in pattern.finditer(all_feedback)]
    return "\n\n".join(blocks)


def project_file_snapshot(project_dir: Path) -> dict[str, tuple[int, int]]:
    snapshot: dict[str, tuple[int, int]] = {}
    if not project_dir.exists():
        return snapshot
    ignored_dirs = {".git", ".vs", ".qwen", LEGACY_WORKFLOW_DIR, PROJECT_WORKFLOW_DIR, "__pycache__", ".pytest_cache", ".mypy_cache", "node_modules", ".venv", "venv", "workspaces", "dist", "build", ".next", "coverage"}
    for path in project_dir.rglob("*"):
        if not path.is_file():
            continue
        if any(part in ignored_dirs for part in path.relative_to(project_dir).parts):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        snapshot[str(path.relative_to(project_dir))] = (stat.st_size, stat.st_mtime_ns)
    return snapshot


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
            "- Primary language: unknown until requirement specifies it.\n"
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

    languages = _detect_project_languages(lower_paths, suffix_counts)
    test_frameworks = _detect_test_frameworks(project_dir, lower_paths)
    source_files = _sample_paths(normalized_paths, _is_source_path, 12)
    test_files = _sample_paths(normalized_paths, _is_test_path, 12)
    marker_files = _sample_paths(normalized_paths, _is_marker_file, 12)
    source_roots = _source_roots(source_files)

    primary_language = languages[0] if languages else "unknown"
    return "\n".join(
        [
            "Detected project profile:",
            f"- Primary language: {primary_language}",
            f"- Languages detected: {', '.join(languages) if languages else 'unknown'}",
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

def _detect_project_languages(lower_paths: list[str], suffix_counts: dict[str, int]) -> list[str]:
    scores = {
        "Python": suffix_counts.get(".py", 0) * 3,
        "TypeScript": (suffix_counts.get(".ts", 0) + suffix_counts.get(".tsx", 0)) * 3,
        "JavaScript": (suffix_counts.get(".js", 0) + suffix_counts.get(".jsx", 0) + suffix_counts.get(".mjs", 0)) * 3,
        "Java": suffix_counts.get(".java", 0) * 3,
        "C#": suffix_counts.get(".cs", 0) * 3,
        "Go": suffix_counts.get(".go", 0) * 3,
        "Rust": suffix_counts.get(".rs", 0) * 3,
        "PHP": suffix_counts.get(".php", 0) * 3,
        "Ruby": suffix_counts.get(".rb", 0) * 3,
    }
    marker_boosts = {
        "Python": ["pyproject.toml", "requirements.txt", "pytest.ini", "setup.py", "tox.ini"],
        "TypeScript": ["tsconfig.json"],
        "JavaScript": ["package.json", "vite.config.js", "webpack.config.js"],
        "Java": ["pom.xml", "build.gradle", "src/main/java"],
        "C#": [".csproj", ".sln"],
        "Go": ["go.mod"],
        "Rust": ["cargo.toml"],
        "PHP": ["composer.json"],
        "Ruby": ["gemfile"],
    }
    for language, markers in marker_boosts.items():
        for marker in markers:
            if any(marker in path for path in lower_paths):
                scores[language] += 5
    ranked = sorted(((score, language) for language, score in scores.items() if score > 0), reverse=True)
    return [language for _, language in ranked]


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


def extract_build_files(build_result: str) -> list[tuple[str, str]]:
    files: list[tuple[str, str]] = []
    pattern = re.compile(
        r"^FILE:\s*(?P<path>.+?)\s*\r?\nCONTENT:\r?\n(?P<content>.*?)(?=^FILE:\s*|^END_FILE\s*$|\Z)",
        re.DOTALL | re.MULTILINE,
    )
    for match in pattern.finditer(build_result):
        rel_path = match.group("path").strip().strip("`").replace("\\", "/")
        content = match.group("content")
        content = re.sub(r"\r?\nEND_FILE\s*$", "", content)
        content = re.sub(r"\r?\n$", "", content)
        content = strip_wrapping_code_fence(rel_path, content)
        files.append((rel_path, content + "\n"))
    return files


def strip_wrapping_code_fence(rel_path: str, content: str) -> str:
    suffix = Path(rel_path).suffix.lower()
    if suffix in {".md", ".markdown", ".txt", ".rst"}:
        return content
    stripped = content.strip()
    match = re.fullmatch(r"```[\w.+-]*\s*\r?\n(?P<body>.*)\r?\n```", stripped, re.DOTALL)
    if not match:
        return content
    return match.group("body")


def apply_extracted_files(project_dir: Path, files: list[tuple[str, str]], *, output_label: str = "build output") -> list[Path]:
    written: list[Path] = []
    project_root = project_dir.expanduser().resolve()
    for rel_path, content in files:
        target = resolve_project_relative_write(project_root, rel_path, label=output_label)
        write_text(target, content)
        written.append(target)
    return written


def apply_build_files(project_dir: Path, build_result: str) -> list[Path]:
    return apply_extracted_files(project_dir, extract_build_files(build_result))



def normalized_rel_path(rel_path: str) -> str:
    return rel_path.strip().strip("`").replace("\\", "/")


def is_test_file_path(rel_path: str) -> bool:
    normalized = normalized_rel_path(rel_path)
    path = Path(normalized)
    parts = path.parts
    if not parts:
        return False
    if parts[0] != "tests":
        return False
    name = path.name
    return name == "conftest.py" or (name.startswith("test_") and name.endswith(".py"))


def validate_generated_test_files(files: list[tuple[str, str]]) -> None:
    if not files:
        raise WorkflowError("generate_tests did not create any test files. Agent test output must include FILE/CONTENT/END_FILE blocks.")
    invalid = [rel_path for rel_path, _ in files if not is_test_file_path(rel_path)]
    if invalid:
        raise WorkflowError(
            "generate_tests can only write pytest files under tests/ "
            f"(tests/test_*.py or tests/conftest.py). Invalid file(s): {', '.join(invalid)}"
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
    ]
    if placeholder_tests:
        raise WorkflowError("generate_tests produced placeholder example tests instead of project-specific tests: " + ", ".join(placeholder_tests))


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


def existing_validation_scripts(project_dir: Path, validation_script: str | None = None) -> set[Path]:
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
    for name in VALIDATION_SCRIPT_NAMES:
        path = project_root / name
        if path.is_file():
            scripts.add(path.resolve())
    return scripts


def validate_build_files_do_not_overwrite_validation_scripts(
    project_dir: Path,
    files: list[tuple[str, str]],
    *,
    validation_script: str | None = None,
) -> None:
    protected_scripts = existing_validation_scripts(project_dir, validation_script)
    if not protected_scripts:
        return
    project_root = project_dir.expanduser().resolve()
    invalid: list[str] = []
    for rel_path, _content in files:
        target = resolve_project_relative_write(project_root, rel_path, label="build output")
        if target.resolve() in protected_scripts:
            invalid.append(rel_path)
    if invalid:
        raise WorkflowError(
            "build must not create or modify existing validation scripts. "
            "Validation scripts are user-provided acceptance tools, not Build-owned artifacts. "
            f"Invalid build file(s): {', '.join(invalid)}"
        )


def only_test_files(files: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [file_block for file_block in files if is_test_file_path(file_block[0])]


def non_test_files(files: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [file_block for file_block in files if not is_test_file_path(file_block[0])]


def build_generic_python_import_smoke_test(project_dir: Path, requirement: str = "") -> list[tuple[str, str]]:
    """Create a generic import-only smoke test for Python modules.

    This does not assert domain behavior; it is only a safety net when an
    existing Python project has code but the agent failed to emit valid test
    blocks. Requirement behavior must still be covered by generated tests or
    external validation.
    """
    snapshot = project_file_snapshot(project_dir)
    python_files = [
        path
        for path in sorted(snapshot)
        if path.endswith(".py")
        and not is_build_test_file_path(path)
        and not Path(path).name.startswith("__")
        and Path(path).name != "conftest.py"
        and Path(path).name not in set(VALIDATION_SCRIPT_NAMES)
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


def build_validation_script_pytest_wrapper(project_dir: Path, validation_script: str | None = None) -> list[tuple[str, str]]:
    """Wrap the user-provided validation script as a pytest test."""
    script = _find_validation_script_for_tests(project_dir, validation_script)
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
        "    proc = subprocess.run(\n"
        "        [sys.executable, str(VALIDATION_SCRIPT)],\n"
        "        cwd=PROJECT_ROOT,\n"
        "        text=True,\n"
        "        capture_output=True,\n"
        "        timeout=120,\n"
        "    )\n"
        "    assert proc.returncode == 0, proc.stdout + proc.stderr\n"
    )
    return [("tests/test_ai_workflow_validation.py", content)]


def _find_validation_script_for_tests(project_dir: Path, validation_script: str | None = None) -> Path | None:
    if validation_script:
        candidate = Path(validation_script).expanduser()
        path = candidate if candidate.is_absolute() else project_dir / candidate
        path = path.resolve()
        try:
            path.relative_to(project_dir.resolve())
        except ValueError:
            return None
        return path if path.is_file() and path.suffix.lower() == ".py" else None
    for name in VALIDATION_SCRIPT_NAMES:
        candidate = project_dir / name
        if candidate.is_file():
            return candidate.resolve()
    return None
