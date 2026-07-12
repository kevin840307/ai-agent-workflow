#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.real_agent_matrix_service import build_real_agent_matrix, summarize_real_agent_rows


def console_safe(value: str) -> str:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return value.encode(encoding, errors="backslashreplace").decode(encoding)


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan or run a real-agent smoke matrix across agents/workflows/cases.")
    parser.add_argument("--agent", action="append", dest="agents", help="Agent name. May be repeated.")
    parser.add_argument("--workflow", action="append", dest="workflows", help="Workflow id. May be repeated.")
    parser.add_argument("--case", action="append", dest="cases", help="Case id. May be repeated.")
    parser.add_argument("--mode", choices=["plan", "dry-run", "self-prompt-test", "real"], default="plan")
    parser.add_argument("--execute", action="store_true", help="Execute safe matrix commands. Real modes still require local agent CLI.")
    parser.add_argument("--output", default="", help="Optional matrix JSON output path.")
    parser.add_argument("--output-root", default="reports/real-agent-matrix", help="Root directory for per-cell evidence.")
    parser.add_argument("--parallel", type=int, default=2, help="Maximum concurrently running isolated matrix cells.")
    parser.add_argument("--timeout-sec", type=int, default=1200, help="Timeout for each matrix cell.")
    parser.add_argument("--resume", action="store_true", help="Reuse cells whose existing summary.json already reports PASS.")
    args = parser.parse_args()
    matrix = build_real_agent_matrix(
        agents=args.agents, workflows=args.workflows, cases=args.cases, mode=args.mode, output_root=args.output_root
    )
    if args.execute or args.mode == "real":
        def execute_row(row: dict) -> dict:
            started = time.perf_counter()
            item = dict(row)
            summary_path = ROOT / row["output"] / "summary.json"
            if args.resume and summary_path.is_file():
                existing = json.loads(summary_path.read_text(encoding="utf-8"))
                real_acceptance = (
                    args.mode == "real"
                    and existing.get("schema") == "aiwf.real-agent-acceptance-cell.v1"
                    and existing.get("run_status") == "done"
                    and bool((existing.get("acceptance") or {}).get("external_validation_passed"))
                )
                prompt_acceptance = args.mode != "real" and existing.get("status") == "PASS"
                if existing.get("status") == "PASS" and (real_acceptance or prompt_acceptance):
                    item.update({
                        "returncode": 0,
                        "stdout_tail": "",
                        "stderr_tail": "",
                        "status": "passed",
                        "duration_seconds": 0.0,
                        "resumed": True,
                        "result": existing,
                    })
                    return item
            try:
                argv = [sys.executable, str(ROOT / "scripts" / "run_real_agent_smoke.py"), *row["argv"][2:]]
                env = os.environ.copy()
                env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(ROOT), env.get("PYTHONPATH", "")]))
                proc = subprocess.run(argv, cwd=ROOT, env=env, text=True, capture_output=True, timeout=max(30, args.timeout_sec), encoding="utf-8", errors="replace")
                case_summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.is_file() else {}
                item.update({
                    "returncode": proc.returncode,
                    "stdout_tail": proc.stdout[-4000:],
                    "stderr_tail": proc.stderr[-4000:],
                    "status": "passed" if proc.returncode == 0 and case_summary.get("status") == "PASS" else "failed",
                    "duration_seconds": round(time.perf_counter() - started, 3),
                    "result": case_summary,
                })
            except subprocess.TimeoutExpired as exc:
                item.update({
                    "returncode": None,
                    "stdout_tail": str(exc.stdout or "")[-4000:],
                    "stderr_tail": str(exc.stderr or "")[-4000:],
                    "status": "failed",
                    "duration_seconds": round(time.perf_counter() - started, 3),
                    "error_code": "MATRIX_CELL_TIMEOUT",
                })
            return item

        results = []
        with ThreadPoolExecutor(max_workers=max(1, args.parallel)) as pool:
            futures = {pool.submit(execute_row, row): row for row in matrix["rows"]}
            for future in as_completed(futures):
                results.append(future.result())
        results.sort(key=lambda item: (item["agent"], item["workflow_id"], item["case_id"]))
        matrix["rows"] = results
        matrix["summary"]["passed"] = sum(1 for item in results if item["status"] == "passed")
        matrix["summary"]["failed"] = sum(1 for item in results if item["status"] == "failed")
        matrix["summary"]["pass_rate"] = round(matrix["summary"]["passed"] / len(results), 4) if results else 0.0
        matrix["summary"]["parallel"] = max(1, args.parallel)
        matrix["certification"]["metrics"] = summarize_real_agent_rows(results)
    text = json.dumps(matrix, indent=2, ensure_ascii=False)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    print(console_safe(text))
    executed = args.execute or args.mode == "real"
    return 0 if not executed or matrix["summary"].get("failed", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
