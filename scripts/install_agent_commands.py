from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
COMMAND_TEMPLATE_ROOT = ROOT / "data" / "agent-commands"

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


def install_commands(*, target: str, scope: str, project: Path, destination: Path | None = None) -> list[Path]:
    installed: list[Path] = []
    project = project.expanduser().resolve()
    for target_name in _targets(target):
        source = COMMAND_TEMPLATE_ROOT / target_name / "commands"
        if not source.exists():
            raise FileNotFoundError(f"Command template directory not found: {source}")
        dest = (destination.expanduser().resolve() if destination else _default_destination(target_name, scope, project))
        dest.mkdir(parents=True, exist_ok=True)
        for template in sorted(source.glob("*.md")):
            output = dest / template.name
            shutil.copy2(template, output)
            installed.append(output)
    return installed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install /wf and /wstep custom slash-command templates for Qwen Code and/or OpenCode.",
    )
    parser.add_argument("--target", choices=("qwen", "opencode", "all"), default="all", help="Agent CLI command format to install.")
    parser.add_argument("--scope", choices=SUPPORTED_SCOPES, default="project", help="Install into the current project or the current user's global command directory.")
    parser.add_argument("--project", default=".", help="Project root used for project-scoped installs. Defaults to the current directory.")
    parser.add_argument("--destination", default=None, help="Optional explicit commands directory. Mostly useful for testing or custom OPENCODE_CONFIG_DIR setups.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    installed = install_commands(
        target=args.target,
        scope=args.scope,
        project=Path(args.project),
        destination=Path(args.destination) if args.destination else None,
    )
    for path in installed:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
