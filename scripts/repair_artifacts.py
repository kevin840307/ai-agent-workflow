#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.runtime_modules import api as runtime  # noqa: E402
from app.workflow_runtime.artifact_repair import repair_run_artifacts  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair standardized artifacts for one or all workflow runs.")
    parser.add_argument("--run-id")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--output", default="reports/artifact-repair")
    args = parser.parse_args()
    if not args.run_id and not args.all:
        parser.error("pass --run-id or --all")
    data = runtime.store.load_sync()
    runs = [run for run in data.get("runs", []) if args.all or run.get("id") == args.run_id]
    results = []
    for run in runs:
        if run.get("workspace"):
            results.append(repair_run_artifacts(run))
    report = {"schema": "aiwf.artifact-repair-batch.v1", "status": "PASS", "count": len(results), "results": results}
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    (out / "artifact-repair-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
