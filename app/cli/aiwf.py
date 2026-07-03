from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Sequence

from app.domain.schemas import CreateRunRequest, CreateSessionRequest
from app.runtime_modules import api as runtime
from app.services import workflow_asset_service, workflow_config_service, workflow_service
from app.services.project_service import create_project


VALUE_OPTIONS = {
    "--workflow",
    "--workflow-id",
    "--validation-script",
    "--test-command",
    "--title",
    "--skill",
    "--config",
    "--project",
    "--project-path",
    "--requirement-file",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aiwf", description="Run Agent Workflow from the same backend used by the Web UI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="Create a session and start a workflow run.")
    run.add_argument("requirement", nargs="?", help="Requirement text. If omitted, use --requirement-file.")
    run.add_argument("--project", "--project-path", dest="project_path", default=".", help="Project directory.")
    run.add_argument("--workflow", "--workflow-id", dest="workflow_id", default=None, help="Workflow id. Defaults to the system workflow.")
    run.add_argument("--skill", default=None, help="Optional workflow skill markdown path or agent slash command.")
    run.add_argument("--config", default=None, help="Optional workflow contract/config yaml/json path.")
    run.add_argument("--title", default="CLI Workflow", help="Session title.")
    run.add_argument("--test-command", default=None, help="Optional test command passed to the workflow.")
    run.add_argument("--validation-script", default=None, help="Optional Python validation script path passed to the workflow.")
    run.add_argument("--requirement-file", default=None, help="Read requirement from a UTF-8 text file.")
    run.add_argument("--wait", action="store_true", help="Wait until the run reaches a terminal or waiting_input state.")
    run.add_argument("--json", action="store_true", help="Print the run as JSON.")

    assets = subparsers.add_parser("assets", help="List .ai-workflow assets using the shared backend resolver.")
    assets.add_argument("--project", "--project-path", dest="project_path", default=None, help="Optional project directory for project-local assets.")

    return parser


def normalize_cli_args(argv: Sequence[str] | None) -> list[str] | None:
    if argv is None:
        return None
    args = list(argv)
    if not args or args[0] in {"run", "assets"}:
        return args
    args = _strip_option_with_value(args, "--engine")
    command = args[0]
    if command in {"/wf", "wf"}:
        return _normalize_workflow_shortcut(args[1:])
    if command in {"/wstep", "wstep", "step"}:
        return _normalize_step_shortcut(args[1:])
    if "--user" in args:
        return _normalize_user_shortcut(args)
    if len(args) >= 2 and not args[0].startswith("-") and not _looks_like_skill_or_config(args[0]):
        return _normalize_workflow_shortcut(args)
    return args


def _normalize_user_shortcut(args: list[str]) -> list[str]:
    user_value, rest = _extract_option_with_value(args, "--user")
    target = "."
    if rest and not rest[0].startswith("-") and not _looks_like_skill_or_config(rest[0]):
        target = rest[0]
        rest = rest[1:]
    normalized = ["run", "--project", target]
    normalized.extend(rest)
    normalized.append(user_value or "")
    return normalized


def _normalize_workflow_shortcut(args: list[str]) -> list[str]:
    user_value, rest = _extract_option_with_value(args, "--user")
    options, positionals = _split_options_and_positionals(rest)
    workflow_id = ""
    requirement_parts: list[str] = []
    if positionals:
        workflow_id = positionals[0]
        requirement_parts = positionals[1:]
    if not user_value:
        user_value = " ".join(requirement_parts)
    normalized = ["run", "--project", "."]
    if workflow_id:
        normalized.extend(["--workflow", workflow_id])
    normalized.extend(options)
    normalized.append(user_value or "")
    return normalized


def _normalize_step_shortcut(args: list[str]) -> list[str]:
    user_value, rest = _extract_option_with_value(args, "--user")
    options, positionals = _split_options_and_positionals(rest)
    skill = positionals[0] if len(positionals) >= 1 else ""
    config = positionals[1] if len(positionals) >= 2 else ""
    if not user_value and len(positionals) >= 3:
        user_value = " ".join(positionals[2:])
    normalized = ["run", "--project", "."]
    if skill:
        normalized.extend(["--skill", skill])
    if config:
        normalized.extend(["--config", config])
    normalized.extend(options)
    normalized.append(user_value or "")
    return normalized


def _split_options_and_positionals(args: list[str]) -> tuple[list[str], list[str]]:
    options: list[str] = []
    positionals: list[str] = []
    index = 0
    while index < len(args):
        value = args[index]
        if value in VALUE_OPTIONS:
            options.append(value)
            if index + 1 < len(args):
                options.append(args[index + 1])
                index += 2
                continue
            index += 1
            continue
        if value.startswith("-"):
            options.append(value)
            index += 1
            continue
        positionals.append(value)
        index += 1
    return options, positionals


def _extract_option_with_value(args: list[str], option: str) -> tuple[str | None, list[str]]:
    value: str | None = None
    rest: list[str] = []
    index = 0
    while index < len(args):
        item = args[index]
        if item == option:
            value = args[index + 1] if index + 1 < len(args) else ""
            index += 2
            continue
        else:
            rest.append(item)
            index += 1
    return value, rest


def _strip_option_with_value(args: list[str], option: str) -> list[str]:
    result: list[str] = []
    skip_next = False
    for value in args:
        if skip_next:
            skip_next = False
            continue
        if value == option:
            skip_next = True
            continue
        result.append(value)
    return result


def _looks_like_skill_or_config(value: str) -> bool:
    return _looks_like_config(value) or _looks_like_skill(value)


def _looks_like_config(value: str) -> bool:
    normalized = str(value or "").strip().replace("\\", "/")
    return normalized.startswith("contracts/") or normalized.startswith(".ai-workflow/contracts/") or Path(normalized).suffix.lower() in {".yaml", ".yml", ".json"}


def _looks_like_skill(value: str) -> bool:
    normalized = str(value or "").strip().replace("\\", "/")
    return normalized.startswith("/") or normalized.startswith("steps/") or normalized.startswith(".ai-workflow/steps/") or Path(normalized).suffix.lower() in {".md", ".markdown", ".txt"}


async def _init_runtime() -> None:
    runtime.ensure_dirs()
    runtime.store.load_sync()
    runtime.mark_interrupted_runs()
    workflow_asset_service.ensure_asset_dirs()
    workflow_config_service.ensure_system_workflow()
    workflow_config_service.ensure_sample_workflow()


def _read_requirement(args: argparse.Namespace) -> str:
    if args.requirement_file:
        return Path(args.requirement_file).expanduser().read_text(encoding="utf-8-sig")
    return args.requirement or ""


async def _wait_for_run(run_id: str) -> dict:
    while True:
        run = await workflow_service.get_run(run_id)
        if run.get("status") in {"done", "passed", "failed", "cancelled", "waiting_input"}:
            return run
        await asyncio.sleep(0.25)


async def run_cli(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(normalize_cli_args(argv))
    await _init_runtime()

    if args.command == "assets":
        payload = workflow_asset_service.list_assets(args.project_path)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    if args.command == "run":
        requirement = _read_requirement(args).strip()
        if not requirement:
            parser.error("requirement or --requirement-file is required")
        session = await create_project(CreateSessionRequest(project_path=args.project_path, title=args.title))
        run = await workflow_service.create_workflow_run(
            session["id"],
            CreateRunRequest(
                requirement=requirement,
                project_path=args.project_path,
                workflow_id=args.workflow_id,
                skill=args.skill,
                config=args.config,
                test_command=args.test_command,
                validation_script=args.validation_script,
            ),
        )
        if args.wait:
            run = await _wait_for_run(run["id"])
        if args.json:
            print(json.dumps(run, indent=2, ensure_ascii=False))
        else:
            print(f"run_id={run['id']}")
            print(f"session_id={run['session_id']}")
            print(f"status={run.get('status')}")
            print(f"project_path={run.get('project_path')}")
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(run_cli(argv))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
