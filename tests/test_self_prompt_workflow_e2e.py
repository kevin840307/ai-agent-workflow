from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_self_prompt_sorting_runs_general_and_adaptive_workflows(tmp_path: Path) -> None:
    output = tmp_path / "self-prompt-logs"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    process_log = tmp_path / "self-prompt-subprocess.log"
    with process_log.open("w", encoding="utf-8") as log_file:
        proc = subprocess.run(
            [sys.executable, "scripts/run_self_prompt_workflow_e2e.py", str(output), "--timeout-sec", "90"],
            cwd=str(Path(__file__).resolve().parents[1]),
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
    assert proc.returncode == 0, process_log.read_text(encoding="utf-8")
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "PASS"
    workflows = {item["workflow_id"]: item for item in summary["results"]}
    assert set(workflows) == {"general-auto-development", "adaptive-auto-workflow"}
    for item in workflows.values():
        assert item["status"] == "done"
        assert item["checks"]["source_exists"]
        assert item["checks"]["tests_exist"]
        assert item["checks"]["all_functions_present"]
        assert item["checks"]["manual_validation_returncode"] == 0
        assert "self-prompt sorting validation ok" in item["checks"]["manual_validation_stdout"]
