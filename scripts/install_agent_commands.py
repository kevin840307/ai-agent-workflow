from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
COMMAND_TEMPLATE_ROOT = ROOT / "data" / "agent-commands"
LAUNCHER = ROOT / "scripts" / "aiwf_agent_command.py"

SUPPORTED_TARGETS = ("qwen", "opencode")
SUPPORTED_SCOPES = ("project", "user")


def _default_destination(target: str, scope: str, project: Path) -> Path:
    if target == "qwen":
        return (project / ".qwen" / "commands") if scope == "project" else (Path.home() / ".qwen" / "commands")
    if target == "opencode":
        return (project / ".opencode" / "commands") if scope == "project" else (Path.home() / ".config" / "opencode" / "commands")
    raise ValueError(f"Unsupported target: {target}")


def _targets(value: str) -> Iterable[str]:
    if value == "all":
        return SUPPORTED_TARGETS
    return (value,)


def _shell_quote(value: Path | str) -> str:
    """Return a cmd.exe/PowerShell/bash-compatible quoted argument.

    Qwen Code executes shell injection with ``cmd.exe /c`` on Windows.  Double
    quoted forward-slash paths work there and also remain valid on POSIX shells.
    """
    text = str(value).replace("\\", "/").replace('"', '\\"')
    return f'"{text}"'


def render_template(text: str, *, python_executable: Path | str | None = None, launcher: Path | None = None) -> str:
    python_value = _shell_quote(python_executable or sys.executable)
    launcher_value = _shell_quote((launcher or LAUNCHER).resolve())
    rendered = text.replace("@@AIWF_PYTHON@@", python_value).replace("@@AIWF_LAUNCHER@@", launcher_value)
    if "@@AIWF_" in rendered:
        raise ValueError("Unresolved AIWF command template token")
    return rendered


def install_commands(*, target: str, scope: str, project: Path, destination: Path | None = None) -> list[Path]:
    installed: list[Path] = []
    project = project.expanduser().resolve()
    if not LAUNCHER.is_file():
        raise FileNotFoundError(f"AI Workflow slash-command launcher not found: {LAUNCHER}")
    for target_name in _targets(target):
        source = COMMAND_TEMPLATE_ROOT / target_name / "commands"
        if not source.exists():
            raise FileNotFoundError(f"Command template directory not found: {source}")
        dest = destination.expanduser().resolve() if destination else _default_destination(target_name, scope, project)
        dest.mkdir(parents=True, exist_ok=True)
        for template in sorted(source.glob("*.md")):
            output = dest / template.name
            output.write_text(render_template(template.read_text(encoding="utf-8")), encoding="utf-8")
            installed.append(output)
    return installed


def verify_command_routes(*, project: Path, python_executable: Path | str | None = None, launcher: Path | None = None) -> dict[str, object]:
    """Exercise /wf and /wstep routing from an arbitrary project cwd.

    Dry-run mode does not start an agent or mutate the project.  It proves the
    installed command can import the controller outside the controller repo and
    that positional arguments still map to the intended workflow/skill/config.
    """
    project = project.expanduser().resolve()
    python_cmd = str(python_executable or sys.executable)
    launcher_path = str((launcher or LAUNCHER).resolve())
    cases = {
        "wf": [python_cmd, launcher_path, "/wf", "general-auto-development", "slash command smoke", "--project", str(project), "--dry-run", "--json"],
        "wstep": [python_cmd, launcher_path, "/wstep", "/build", "build.yaml", "slash command smoke", "--project", str(project), "--dry-run", "--json"],
    }
    results: dict[str, object] = {}
    for name, command in cases.items():
        proc = subprocess.run(command, cwd=str(project), capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            raise RuntimeError(f"{name} slash-command route failed ({proc.returncode}): {proc.stderr or proc.stdout}")
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{name} slash-command route returned invalid JSON: {proc.stdout}") from exc
        if payload.get("ok") is not True:
            raise RuntimeError(f"{name} slash-command route did not pass dry-run: {payload}")
        results[name] = payload
    return {"schema": "aiwf.agent-command-verification.v1", "ok": True, "routes": results}


def verify_installed_templates(paths: Iterable[Path]) -> None:
    for path in paths:
        text = path.read_text(encoding="utf-8")
        if "@@AIWF_" in text:
            raise RuntimeError(f"Unresolved template token in {path}")
        if "aiwf_agent_command.py" not in text:
            raise RuntimeError(f"Installed command does not use the stable launcher: {path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install and verify /wf and /wstep custom slash commands for Qwen Code and/or OpenCode.",
    )
    parser.add_argument("--target", choices=("qwen", "opencode", "all"), default="all", help="Agent CLI command format to install.")
    parser.add_argument("--scope", choices=SUPPORTED_SCOPES, default="project", help="Install into the current project or the current user's global command directory.")
    parser.add_argument("--project", default=".", help="Project root used for project-scoped installs and route verification.")
    parser.add_argument("--destination", default=None, help="Optional explicit commands directory. Mostly useful for testing or custom OPENCODE_CONFIG_DIR setups.")
    parser.add_argument("--no-verify", action="store_true", help="Skip the non-mutating /wf and /wstep dry-run verification.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    project = Path(args.project)
    installed = install_commands(
        target=args.target,
        scope=args.scope,
        project=project,
        destination=Path(args.destination) if args.destination else None,
    )
    verify_installed_templates(installed)
    for path in installed:
        print(path)
    if not args.no_verify:
        result = verify_command_routes(project=project)
        print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
