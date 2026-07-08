#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.runtime_modules import api as runtime  # noqa: E402
from app.workflow_runtime.run_consistency import check_store_consistency, render_consistency_report  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Check AI workflow run/store consistency.")
    parser.add_argument("--output", default="reports/run-consistency", help="output directory")
    parser.add_argument("--json", action="store_true", help="print JSON report")
    args = parser.parse_args()
    data = runtime.store.load_sync()
    report = check_store_consistency(data)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    (out / "run-consistency-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "run-consistency-report.md").write_text(render_consistency_report(report), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False) if args.json else render_consistency_report(report))
    return 0 if report.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
