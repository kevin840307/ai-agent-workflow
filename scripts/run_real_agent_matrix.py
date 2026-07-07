#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.real_agent_matrix_service import build_real_agent_matrix


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan or run a real-agent smoke matrix across agents/workflows/cases.")
    parser.add_argument("--agent", action="append", dest="agents", help="Agent name. May be repeated.")
    parser.add_argument("--workflow", action="append", dest="workflows", help="Workflow id. May be repeated.")
    parser.add_argument("--case", action="append", dest="cases", help="Case id. May be repeated.")
    parser.add_argument("--mode", choices=["plan", "dry-run", "self-prompt-test"], default="plan")
    parser.add_argument("--execute", action="store_true", help="Execute safe matrix commands. Real modes still require local agent CLI.")
    parser.add_argument("--output", default="", help="Optional JSON output path.")
    args = parser.parse_args()
    matrix = build_real_agent_matrix(agents=args.agents, workflows=args.workflows, cases=args.cases, mode=args.mode)
    if args.execute:
        results = []
        for row in matrix["rows"]:
            proc = subprocess.run(row["argv"], cwd=ROOT, text=True, capture_output=True, timeout=240)
            item = dict(row)
            item.update({"returncode": proc.returncode, "stdout_tail": proc.stdout[-4000:], "stderr_tail": proc.stderr[-4000:], "status": "passed" if proc.returncode == 0 else "failed"})
            results.append(item)
        matrix["rows"] = results
        matrix["summary"]["passed"] = sum(1 for item in results if item["status"] == "passed")
        matrix["summary"]["failed"] = sum(1 for item in results if item["status"] == "failed")
    text = json.dumps(matrix, indent=2, ensure_ascii=False)
    print(text)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    return 0 if not args.execute or matrix["summary"].get("failed", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
