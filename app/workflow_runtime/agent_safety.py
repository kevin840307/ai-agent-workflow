from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.paths import read_text, utc_now, write_text
from app.workflow_runtime.run_diff import build_run_diff

SAFETY_SCHEMA = "aiwf.agent-safety-report.v1"
DANGEROUS_TERMS = [
    " rm -rf ",
    "Remove-Item",
    "del /f",
    "format ",
    "shutdown",
    "curl ",
    "wget ",
    "Invoke-WebRequest",
]
SECRET_TERMS = [".env", "password", "passwd", "secret", "credential", "token", "apikey", "api_key"]


def _safe_rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except Exception:
        return str(path)


def _changed_files_from_diff(run: dict[str, Any]) -> list[str]:
    diff = build_run_diff(run, Path(run.get("workspace") or ""))
    files = []
    for item in diff.get("files", []) if isinstance(diff, dict) else []:
        rel = str(item.get("path") or "")
        if rel:
            files.append(rel)
    return sorted(dict.fromkeys(files))


def _scan_text_for_terms(text: str, terms: list[str]) -> list[str]:
    lower = text.lower()
    found = []
    for term in terms:
        marker = term.lower()
        if marker.strip() and marker in lower:
            found.append(term.strip())
    return sorted(dict.fromkeys(found))


def build_agent_safety_report(run: dict[str, Any]) -> dict[str, Any]:
    workspace = Path(run.get("workspace") or "")
    project = Path(run.get("project_path") or workspace)
    original_project = Path(run.get("original_project_path") or project)
    changed_files = _changed_files_from_diff(run)
    log_text = read_text(workspace / ".workflow" / "run-log.md")
    prompt_meta_text = ""
    prompt_dir = workspace / "prompts"
    if prompt_dir.exists():
        for path in prompt_dir.glob("*.prompt-meta.json"):
            prompt_meta_text += "\n" + read_text(path)
    suspicious_changed = [path for path in changed_files if any(term.lower().strip() in path.lower() for term in SECRET_TERMS)]
    large_files: list[dict[str, Any]] = []
    for rel in changed_files:
        target = project / rel
        try:
            if target.exists() and target.is_file() and target.stat().st_size > 1_000_000:
                large_files.append({"path": rel, "size": target.stat().st_size})
        except OSError:
            continue
    isolated = bool(run.get("original_project_path")) and str(original_project.resolve()) != str(project.resolve())
    dangerous_terms = _scan_text_for_terms(log_text + "\n" + prompt_meta_text, DANGEROUS_TERMS)
    secret_terms = _scan_text_for_terms("\n".join(changed_files) + "\n" + prompt_meta_text, SECRET_TERMS)
    warnings = []
    if not project.exists():
        warnings.append("project_path does not exist at report time")
    if not workspace.exists():
        warnings.append("workspace does not exist at report time")
    if suspicious_changed:
        warnings.append("changed files include secret/credential-like names")
    if dangerous_terms:
        warnings.append("agent logs/prompts include potentially dangerous command terms")
    if large_files:
        warnings.append("large output files detected")
    return {
        "schema": SAFETY_SCHEMA,
        "generated_at": utc_now(),
        "run_id": run.get("id"),
        "agent": run.get("agent"),
        "workflow_id": run.get("workflow_id"),
        "status": run.get("status"),
        "cwd": str(project),
        "cwd_exists": project.exists(),
        "workspace": str(workspace),
        "original_project_path": str(original_project),
        "isolated_workspace": isolated,
        "patch_mode": run.get("patch_mode") or "auto_apply",
        "changed_file_count": len(changed_files),
        "changed_files": changed_files,
        "suspicious_changed_files": suspicious_changed,
        "dangerous_terms": dangerous_terms,
        "secret_terms": secret_terms,
        "large_files": large_files,
        "warnings": warnings,
        "risk": "high" if dangerous_terms or suspicious_changed else ("medium" if large_files or warnings else "low"),
    }


def render_agent_safety_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Agent Safety Report",
        "",
        f"Schema: `{report.get('schema')}`",
        f"Run ID: `{report.get('run_id')}`",
        f"Workflow: `{report.get('workflow_id')}`",
        f"Agent: `{report.get('agent')}`",
        f"Status: `{report.get('status')}`",
        f"Risk: **{str(report.get('risk') or '').upper()}**",
        "",
        "## Execution Scope",
        f"- cwd: `{report.get('cwd')}`",
        f"- workspace: `{report.get('workspace')}`",
        f"- original project: `{report.get('original_project_path')}`",
        f"- isolated workspace: `{report.get('isolated_workspace')}`",
        f"- patch mode: `{report.get('patch_mode')}`",
        "",
        "## Changed Files",
        f"Total: {report.get('changed_file_count', 0)}",
    ]
    changed = report.get("changed_files") or []
    lines.extend([f"- `{item}`" for item in changed[:80]] or ["- none detected"])
    if len(changed) > 80:
        lines.append(f"- ... {len(changed) - 80} more")
    lines.extend(["", "## Warnings"])
    lines.extend([f"- {item}" for item in report.get("warnings") or []] or ["- none"])
    return "\n".join(lines) + "\n"


def write_agent_safety_report(run: dict[str, Any]) -> dict[str, Any]:
    workspace = Path(run.get("workspace") or "")
    out_dir = workspace / ".workflow" / "artifacts" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    report = build_agent_safety_report(run)
    write_text(out_dir / "agent-safety-report.json", json.dumps(report, indent=2, ensure_ascii=False))
    write_text(out_dir / "agent-safety-report.md", render_agent_safety_markdown(report))
    return report
