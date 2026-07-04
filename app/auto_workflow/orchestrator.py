from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

FORBIDDEN_WRITE_PARTS = {".git", ".ai-workflow", ".qwen-workflow"}
ALLOWED_STEP_TYPES = {
    "python_context",
    "agent_plan",
    "agent_build",
    "agent_generate_tests",
    "python_task_verifier",
    "repair_loop",
    "assembly_verifier",
    "external_acceptance_python",
    "evidence_verifier",
    "diff_reviewer_agent",
    "final_gate",
}

DEV_PATTERNS = [
    r"\b(add|build|create|implement|modify|update|fix|repair|generate|write|refactor|optimi[sz]e)\b",
    r"(新增|建立|製作|產生|實作|修改|修正|優化|重構|開發|加入|補上|調整)",
]
NEW_PROJECT_PATTERNS = [r"(新專案|產生專案|建立專案|從零|create\s+(a\s+)?project|new\s+project)"]
ASK_PATTERNS = [r"(為什麼|怎麼|如何|建議|解釋|說明|理解|分析|可以嗎|足夠嗎)", r"\b(why|explain|suggest|analy[sz]e|understand)\b"]


def route_request(raw_requirement: str, *, validation_script: str | None = None, project_has_files: bool = True) -> dict[str, Any]:
    text = raw_requirement or ""
    lowered = text.lower()
    new_project = any(re.search(pattern, lowered, re.I) or re.search(pattern, text, re.I) for pattern in NEW_PROJECT_PATTERNS)
    dev = bool(validation_script) or any(re.search(pattern, lowered, re.I) or re.search(pattern, text, re.I) for pattern in DEV_PATTERNS)
    ask = any(re.search(pattern, lowered, re.I) or re.search(pattern, text, re.I) for pattern in ASK_PATTERNS)
    if new_project:
        intent = "CREATE_NEW_PROJECT"
    elif dev:
        intent = "AUTO_WORKFLOW" if validation_script else "DEVELOP_EXISTING_PROJECT"
    elif ask:
        intent = "ASK"
    else:
        # In the auto workflow path, ambiguous input is treated as a development request
        # only when a project exists; otherwise it becomes a new-project scaffold request.
        intent = "DEVELOP_EXISTING_PROJECT" if project_has_files else "CREATE_NEW_PROJECT"
    return {
        "intent": intent,
        "requires_code_change": intent in {"CREATE_NEW_PROJECT", "DEVELOP_EXISTING_PROJECT", "AUTO_WORKFLOW"},
        "requires_project_index": intent != "ASK",
        "requires_task_manifest": intent in {"CREATE_NEW_PROJECT", "DEVELOP_EXISTING_PROJECT", "AUTO_WORKFLOW"},
        "requires_workflow_instance": intent in {"CREATE_NEW_PROJECT", "DEVELOP_EXISTING_PROJECT", "AUTO_WORKFLOW"},
        "requires_acceptance": bool(validation_script),
        "validation_script": validation_script or "",
    }


def extract_user_instructions(raw_requirement: str, project_dir: Path) -> dict[str, Any]:
    text = raw_requirement or ""
    sequence = []
    for line in text.splitlines():
        match = re.match(r"^\s*(\d+)\s*[\.、\)]\s*(.+?)\s*$", line)
        if match:
            sequence.append({"order": int(match.group(1)), "instruction": match.group(2).strip(), "required": True})
    md_refs = _extract_markdown_refs(text)
    md_constraints = []
    for ref in md_refs:
        path = _resolve_readable_path(project_dir, ref)
        if not path:
            md_constraints.append({"path": ref, "found": False, "summary": "Workflow reference file was mentioned but not found."})
            continue
        content = _safe_read(path)
        md_constraints.append({
            "path": ref,
            "found": True,
            "summary": _summarize_workflow_markdown(content),
        })
    architecture_phrases = []
    if re.search(r"(依照|遵守|沿用).{0,12}(專案架構|目前架構|現有架構)", text):
        architecture_phrases.append("Follow the existing project architecture and do not introduce unrelated top-level structure.")
    if re.search(r"(先|before|first)", text, re.I) and not sequence:
        architecture_phrases.append("Respect explicit ordering words such as first/before when generating tasks.")
    return {
        "user_sequence": sequence,
        "workflow_md_refs": md_constraints,
        "architecture_constraints": architecture_phrases,
        "raw_instruction_excerpt": text[:4000],
    }


def build_architecture_contract(project_dir: Path, project_index: str, instructions: dict[str, Any]) -> dict[str, Any]:
    top_level = sorted(
        item.name for item in project_dir.iterdir()
        if item.name not in {".git", "__pycache__"}
    ) if project_dir.exists() else []
    preferred_roots = [name for name in ["app", "src", "tests", "static", "data", "docs"] if name in top_level]
    rules = [
        "Write only inside the selected Project Path.",
        "Do not write .git, .ai-workflow, .qwen-workflow, global settings, or sibling projects.",
        "Follow existing language, naming style, source layout, and dependency style.",
        "Keep production code and tests separate.",
        "Do not introduce a new top-level framework folder unless the task requires a new project scaffold.",
        "Do not create sample-specific deterministic fallbacks or hard-code a user example as product behavior.",
        "Do not run git commit, git push, or commands that change repository history or remote state.",
    ]
    for item in instructions.get("architecture_constraints") or []:
        if item not in rules:
            rules.append(str(item))
    return {
        "status": "READY",
        "project_root": str(project_dir),
        "top_level_entries": top_level[:80],
        "preferred_roots": preferred_roots,
        "rules": rules,
        "project_index_excerpt": project_index[:8000],
    }


def task_manifest_from_todo(todo: str, *, project_dir: Path, instructions: dict[str, Any] | None = None) -> dict[str, Any]:
    tasks = []
    for index, task_id in enumerate(_ordered_task_ids(todo), start=1):
        section = _task_section(todo, task_id)
        title = _task_title(todo, task_id)
        owner = _task_owner(section, title)
        ac = _acceptance_criteria(section)
        depends = _depends_on(section)
        user_step = _infer_user_step(title, section, instructions or {})
        tasks.append({
            "id": task_id,
            "title": title,
            "owner": owner,
            "user_step": user_step,
            "depends_on": depends,
            "allowed_write_paths": _allowed_write_paths_for_owner(owner, project_dir),
            "acceptance": ac or ["Task-specific acceptance criteria are described in todo.md."],
            "source": "todo.md",
        })
    if not tasks:
        tasks.append({
            "id": "TASK-001",
            "title": "Implement the requested change",
            "owner": "build",
            "user_step": None,
            "depends_on": [],
            "allowed_write_paths": _allowed_write_paths_for_owner("build", project_dir),
            "acceptance": ["The requested project change is implemented and verified."],
            "source": "fallback",
        })
    return {
        "status": "READY",
        "schema_version": 1,
        "goal": _extract_requirement(todo),
        "tasks": tasks,
        "final_acceptance": {
            "automated_tests_required": True,
            "external_validation_required_when_configured": True,
            "verifier_report_required": True,
        },
    }


def validate_task_manifest(manifest: dict[str, Any], project_dir: Path) -> list[str]:
    findings: list[str] = []
    tasks = manifest.get("tasks") if isinstance(manifest, dict) else None
    if not isinstance(tasks, list) or not tasks:
        return ["task-manifest.json must contain at least one task."]
    ids: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict):
            findings.append("Every task must be an object.")
            continue
        task_id = str(task.get("id") or "")
        if not re.fullmatch(r"TASK-\d{3}", task_id):
            findings.append(f"Invalid task id: {task_id or '<empty>'}.")
        if task_id in ids:
            findings.append(f"Duplicate task id: {task_id}.")
        ids.add(task_id)
        if not str(task.get("title") or "").strip():
            findings.append(f"{task_id}: title is required.")
        if not task.get("acceptance"):
            findings.append(f"{task_id}: acceptance criteria are required.")
        owner = str(task.get("owner") or "build")
        if owner not in {"planning", "build", "generate_tests", "run_external_validation"}:
            findings.append(f"{task_id}: unsupported owner {owner}.")
        for dep in task.get("depends_on") or []:
            if dep not in ids and not any(t.get("id") == dep for t in tasks if isinstance(t, dict)):
                findings.append(f"{task_id}: depends_on references unknown task {dep}.")
        for rel in task.get("allowed_write_paths") or []:
            findings.extend(_validate_relative_path(str(rel), project_dir, label=f"{task_id} allowed_write_paths"))
    if len(tasks) > 20:
        findings.append(f"Too many tasks for MVP auto workflow: {len(tasks)} > 20.")
    return findings


def compile_workflow_instance(manifest: dict[str, Any], *, run_profile: str = "normal") -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    for task in manifest.get("tasks") or []:
        task_id = task.get("id")
        owner = task.get("owner") or "build"
        if owner == "planning":
            steps.append({"id": f"{task_id}_CONTEXT", "type": "python_context", "task_id": task_id})
            continue
        if owner == "generate_tests":
            steps.append({"id": f"{task_id}_GENERATE_TESTS", "type": "agent_generate_tests", "task_id": task_id})
            steps.append({"id": f"{task_id}_VERIFY", "type": "python_task_verifier", "task_id": task_id})
            steps.append({"id": f"{task_id}_REPAIR", "type": "repair_loop", "task_id": task_id, "on_fail_of": f"{task_id}_VERIFY"})
            continue
        if owner == "run_external_validation":
            steps.append({"id": f"{task_id}_ACCEPTANCE", "type": "external_acceptance_python", "task_id": task_id})
            continue
        steps.extend([
            {"id": f"{task_id}_BUILD", "type": "agent_build", "task_id": task_id},
            {"id": f"{task_id}_GENERATE_TESTS", "type": "agent_generate_tests", "task_id": task_id},
            {"id": f"{task_id}_VERIFY", "type": "python_task_verifier", "task_id": task_id},
            {"id": f"{task_id}_REPAIR", "type": "repair_loop", "task_id": task_id, "on_fail_of": f"{task_id}_VERIFY"},
        ])
    steps.extend([
        {"id": "ASSEMBLY_VERIFY", "type": "assembly_verifier"},
        {"id": "USER_ACCEPTANCE", "type": "external_acceptance_python"},
        {"id": "FINAL_VERIFIER", "type": "evidence_verifier"},
        {"id": "DIFF_REVIEW", "type": "diff_reviewer_agent"},
        {"id": "FINAL_GATE", "type": "final_gate"},
    ])
    return {
        "status": "READY",
        "schema_version": 1,
        "run_profile": run_profile or "normal",
        "execution_mode": "compiled_from_task_manifest",
        "step_type_allowlist": sorted(ALLOWED_STEP_TYPES),
        "steps": steps,
        "policy": {
            "ai_may_generate_tasks": True,
            "ai_may_generate_executable_step_types": False,
            "python_compiles_workflow_instance": True,
            "python_decides_pass_fail": True,
            "git_commit_push_allowed": False,
        },
    }


def validate_workflow_instance(instance: dict[str, Any], manifest: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    task_ids = {str(task.get("id")) for task in manifest.get("tasks") or [] if isinstance(task, dict)}
    steps = instance.get("steps") if isinstance(instance, dict) else None
    if not isinstance(steps, list) or not steps:
        return ["generated-workflow-instance.json must contain steps."]
    for step in steps:
        if not isinstance(step, dict):
            findings.append("Every workflow instance step must be an object.")
            continue
        step_id = str(step.get("id") or "")
        step_type = str(step.get("type") or "")
        task_id = str(step.get("task_id") or "")
        if not re.fullmatch(r"[A-Z0-9_\-]+", step_id):
            findings.append(f"Invalid workflow step id: {step_id or '<empty>'}.")
        if step_type not in ALLOWED_STEP_TYPES:
            findings.append(f"Step {step_id}: unsupported type {step_type}.")
        if task_id and task_id not in task_ids:
            findings.append(f"Step {step_id}: references unknown task {task_id}.")
    required = {"ASSEMBLY_VERIFY", "USER_ACCEPTANCE", "FINAL_VERIFIER", "DIFF_REVIEW", "FINAL_GATE"}
    found = {str(step.get("id")) for step in steps if isinstance(step, dict)}
    missing = sorted(required - found)
    if missing:
        findings.append("Workflow instance missing required final step(s): " + ", ".join(missing))
    return findings


def render_validation_markdown(task_findings: list[str], workflow_findings: list[str]) -> str:
    status = "PASS" if not task_findings and not workflow_findings else "FAIL"
    lines = [
        "# Workflow Instance Validation",
        "",
        f"Status: {status}",
        "",
        "## Task Manifest Checks",
    ]
    lines.extend([f"- FAIL: {item}" for item in task_findings] or ["- PASS: task-manifest.json is valid."])
    lines.extend(["", "## Workflow Instance Checks"])
    lines.extend([f"- FAIL: {item}" for item in workflow_findings] or ["- PASS: generated-workflow-instance.json uses only allowed step types and required final steps."])
    lines.extend(["", "## Policy", "- AI produces the task manifest; Python compiles and validates the executable workflow instance.", "- The generated instance is declarative evidence for this run; only built-in runner methods may execute work.", ""])
    return "\n".join(lines)


def render_run_trace(instance: dict[str, Any]) -> str:
    lines = ["# Workflow Run Trace", "", "Status: PLANNED", "", "## Compiled Step Order"]
    for index, step in enumerate(instance.get("steps") or [], start=1):
        task = f" task={step.get('task_id')}" if step.get("task_id") else ""
        lines.append(f"{index}. {step.get('id')} [{step.get('type')}]{task}")
    lines.extend(["", "## Runtime Note", "- The visible UI workflow remains simple; this compiled instance documents the internal task workflow executed by the Python-controlled runner.", ""])
    return "\n".join(lines)


def _ordered_task_ids(todo: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for match in re.finditer(r"\bTASK-\d{3}\b", todo or ""):
        task_id = match.group(0)
        if task_id not in seen:
            seen.add(task_id)
            ordered.append(task_id)
    return ordered


def _task_title(todo: str, task_id: str) -> str:
    heading = re.search(rf"^###\s+{re.escape(task_id)}\s*:?\s*(.+?)\s*$", todo or "", flags=re.MULTILINE)
    if heading:
        return heading.group(1).strip() or task_id
    table_row = re.search(rf"^\|\s*{re.escape(task_id)}\s*\|\s*([^|]+?)\s*\|", todo or "", flags=re.MULTILINE)
    if table_row:
        return table_row.group(1).strip() or task_id
    return task_id


def _task_section(todo: str, task_id: str) -> str:
    match = re.search(rf"^###\s+{re.escape(task_id)}\b.*?(?=^###\s+TASK-\d{{3}}\b|^##\s+|\Z)", todo or "", flags=re.MULTILINE | re.DOTALL)
    return match.group(0).strip() if match else ""


def _task_owner(section: str, title: str) -> str:
    header = title.lower()
    goal_match = re.search(r"(?im)^\s*-\s*goal:\s*(.+)$", section or "")
    goal = goal_match.group(1).lower() if goal_match else ""
    primary = f"{header}\n{goal}"
    text = f"{primary}\n{section}".lower()
    # Owner is derived from the task's own title/goal first.  Later validation or
    # assembly text may mention Generate Tests / External Validation as downstream
    # gates and must not steal Build ownership from an implementation task.
    if re.search(r"\b(implement|create|modify|update|write|add|generate|produce|build)\b", primary) or re.search(r"(實作|新增|建立|修改|產生|製作)", primary):
        if not re.search(r"\btests?\b", primary) and "測試" not in primary:
            return "build"
    if re.search(r"\b(generate|create|write|add)\s+(focused\s+)?(automated\s+)?tests?\b", primary) or "test files only" in text:
        return "generate_tests"
    if "external validation" in primary and not re.search(r"\b(implement|create|modify|update|write|add|build)\b", primary):
        return "run_external_validation"
    if re.search(r"\b(review|analyze|analyse|inspect|scan|understand|plan)\b", primary) and not re.search(r"\b(implement|create|modify|update|write|add|generate|produce|build)\b", primary):
        return "planning"
    return "build"


def _acceptance_criteria(section: str) -> list[str]:
    criteria = []
    in_ac = False
    for line in section.splitlines():
        if re.search(r"acceptance criteria", line, re.I):
            in_ac = True
            continue
        if in_ac and re.match(r"^\s*-\s+(depends on|assembly|validation|files|goal)\s*:", line, re.I):
            break
        if in_ac and re.match(r"^\s*-\s+", line):
            criteria.append(re.sub(r"^\s*-\s+", "", line).strip())
        elif in_ac and re.match(r"^\s*\w", line) and not line.startswith(" "):
            break
    return criteria[:12]


def _depends_on(section: str) -> list[str]:
    deps = sorted(set(re.findall(r"\bTASK-\d{3}\b", section or "")))
    self_id = re.search(r"\bTASK-\d{3}\b", section or "")
    if self_id:
        deps = [dep for dep in deps if dep != self_id.group(0)]
    return deps


def _allowed_write_paths_for_owner(owner: str, project_dir: Path) -> list[str]:
    if owner == "generate_tests":
        return ["tests/"]
    if owner in {"planning", "run_external_validation"}:
        return []
    roots = []
    for name in ["app", "src", "lib", "static", "data", "docs"]:
        if (project_dir / name).exists():
            roots.append(f"{name}/")
    return roots or ["./"]


def _extract_requirement(todo: str) -> str:
    match = re.search(r"^## Requirement\s*(.*?)(?=^##\s+|\Z)", todo or "", flags=re.MULTILINE | re.DOTALL)
    if not match:
        return "Complete the requested change."
    lines = [line.strip(" -") for line in match.group(1).splitlines() if line.strip()]
    return " ".join(lines)[:1000] or "Complete the requested change."


def _infer_user_step(title: str, section: str, instructions: dict[str, Any]) -> int | None:
    sequence = instructions.get("user_sequence") or []
    text = f"{title}\n{section}".lower()
    for item in sequence:
        instruction = str(item.get("instruction") or "").lower()
        if instruction and any(token for token in instruction.split() if token in text):
            try:
                return int(item.get("order"))
            except Exception:
                return None
    return None


def _validate_relative_path(value: str, project_dir: Path, *, label: str) -> list[str]:
    findings = []
    if not value:
        return findings
    normalized = value.replace("\\", "/")
    if Path(value).is_absolute():
        findings.append(f"{label}: absolute path is not allowed: {value}")
    if ".." in Path(normalized).parts:
        findings.append(f"{label}: parent-directory path is not allowed: {value}")
    if any(part in FORBIDDEN_WRITE_PARTS for part in Path(normalized).parts):
        findings.append(f"{label}: forbidden workflow/git path: {value}")
    return findings


def _extract_markdown_refs(text: str) -> list[str]:
    refs = re.findall(r"(?<![\w.-])([\w./\\-]+\.md)(?![\w.-])", text or "", flags=re.I)
    seen = []
    for ref in refs:
        if ref not in seen:
            seen.append(ref)
    return seen[:10]


def _resolve_readable_path(project_dir: Path, ref: str) -> Path | None:
    raw = Path(ref).expanduser()
    candidates = [raw] if raw.is_absolute() else [project_dir / raw, Path.cwd() / raw]
    for path in candidates:
        try:
            resolved = path.resolve()
        except Exception:
            continue
        if resolved.is_file() and resolved.suffix.lower() == ".md":
            return resolved
    return None


def _safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _summarize_workflow_markdown(content: str) -> dict[str, Any]:
    lines = [line.strip() for line in (content or "").splitlines() if line.strip()]
    phases = []
    must = []
    for line in lines[:200]:
        if re.match(r"^(#+|\d+[\.、\)]|[-*])", line):
            if re.search(r"(step|phase|流程|步驟|先|再|最後|驗證|test|build|review)", line, re.I):
                phases.append(line[:240])
        if re.search(r"(must|必須|一定|禁止|不可|不能|不要|do not|驗證)", line, re.I):
            must.append(line[:240])
    return {"required_phases": phases[:20], "must_follow_rules": must[:20], "excerpt": "\n".join(lines[:40])[:4000]}


def dumps(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)
