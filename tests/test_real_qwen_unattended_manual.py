from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(os.environ.get("RUN_REAL_QWEN_UNATTENDED") != "1", reason="opt-in real Qwen unattended E2E")
def test_real_qwen_unattended_case_matrix() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/run_real_qwen_unattended_e2e.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=float(os.environ.get("REAL_QWEN_E2E_SUITE_TIMEOUT_SEC", "5400")),
    )
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr


@pytest.mark.skipif(os.environ.get("RUN_REAL_QWEN_UNATTENDED_PARALLEL") != "1", reason="opt-in real Qwen parallel-session E2E")
def test_real_qwen_different_sessions_can_overlap() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_real_qwen_unattended_e2e.py",
            "--parallel",
            "--case",
            "bugfix-existing-python",
            "--case",
            "project-local-agent-context",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=float(os.environ.get("REAL_QWEN_E2E_SUITE_TIMEOUT_SEC", "5400")),
    )
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
