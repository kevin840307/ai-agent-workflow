#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.services.workflow_asset_validator import validate_all_workflows  # noqa: E402


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Validate workflow assets, contracts, prompts, functions, and retry targets.")
    parser.add_argument("--project-path", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = await validate_all_workflows(args.project_path)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"schema: {result['schema']}")
        print(f"status: {'PASS' if result['ok'] else 'FAIL'}")
        print(f"workflows: {result['workflow_count']} errors: {result['error_count']} warnings: {result['warning_count']}")
        for workflow in result.get("workflows", []):
            status = "PASS" if workflow.get("error_count") == 0 else "FAIL"
            print(f"- {workflow.get('id')}: {status}, errors={workflow.get('error_count')}, warnings={workflow.get('warning_count')}")
            for issue in workflow.get("issues", [])[:8]:
                print(f"  - [{issue.get('severity')}] {issue.get('field')}: {issue.get('message')}")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
