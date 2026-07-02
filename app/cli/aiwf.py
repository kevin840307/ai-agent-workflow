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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aiwf", description="Run Agent Workflow from the same backend used by the Web UI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="Create a session and start a workflow run.")
    run.add_argument("requirement", nargs="?", help="Requirement text. If omitted, use --requirement-file.")
    run.add_argument("--project", "--project-path", dest="project_path", default=".", help="Project directory.")
    run.add_argument("--workflow", "--workflow-id", dest="workflow_id", default=None, help="Workflow id. Defaults to the system workflow.")
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
    if not args or args[0] in {"run", "assets"} or "--user" not in args:
        return args
    target = args[0]
    rest = args[1:]
    normalized = ["run", "--project", target]
    skip_next = False
    for index, value in enumerate(rest):
        if skip_next:
            skip_next = False
            continue
        if value == "--user":
            if index + 1 >= len(rest):
                normalized.append("")
            else:
                normalized.append(rest[index + 1])
                skip_next = True
            continue
        if value == "--engine":
            skip_next = True
            continue
        normalized.append(value)
    return normalized


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
        if run.get("status") in {"passed", "failed", "cancelled", "waiting_input"}:
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
