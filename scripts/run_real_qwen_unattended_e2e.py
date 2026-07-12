from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.main import app

ROOT = Path(__file__).resolve().parents[1]
CASES_FILE = ROOT / "tests" / "fixtures" / "real_qwen_unattended" / "cases.json"
TERMINAL = {"done", "failed", "cancelled", "waiting_input"}


def require_qwen() -> None:
    binary = os.environ.get("QWEN_BIN") or ("qwen.cmd" if os.name == "nt" else "qwen")
    if shutil.which(binary) is None:
        raise SystemExit(f"Qwen CLI not found: {binary}")


def _write_behavior_check(project: Path, name: str, content: str) -> None:
    check_dir = project / "e2e_checks"
    check_dir.mkdir(exist_ok=True)
    (check_dir / name).write_text(content, encoding="utf-8")


def write_fixture(project: Path, fixture: str) -> None:
    project.mkdir(parents=True, exist_ok=True)
    (project / "tests").mkdir(exist_ok=True)
    if fixture == "bugfix":
        (project / "names.py").write_text("def normalize_name(value):\n    return value.upper()\n", encoding="utf-8")
        (project / "tests" / "test_names.py").write_text(
            "import unittest\nfrom names import normalize_name\n\nclass T(unittest.TestCase):\n"
            "    def test_existing_behavior(self): self.assertEqual(normalize_name('Alice'), 'ALICE')\n",
            encoding="utf-8",
        )
        _write_behavior_check(
            project,
            "check_names.py",
            "from names import normalize_name\nassert normalize_name('  Alice Smith  ') == 'alice smith'\nprint('PASS')\n",
        )
    elif fixture == "multi_file":
        (project / "README.md").write_text("# Task service\nUse only the Python standard library.\n", encoding="utf-8")
        (project / "tests" / "test_task_service.py").write_text(
            "import unittest\nfrom pathlib import Path\n\n"
            "class T(unittest.TestCase):\n"
            "    def test_fixture_is_ready(self): self.assertTrue(Path('README.md').is_file())\n",
            encoding="utf-8",
        )
        _write_behavior_check(
            project,
            "check_task_service.py",
            "import tempfile\nfrom pathlib import Path\nfrom task_repository import JsonTaskRepository\nfrom task_service import TaskService\nwith tempfile.TemporaryDirectory() as folder:\n    service = TaskService(JsonTaskRepository(Path(folder) / 'tasks.json'))\n    service.add('first')\n    assert [item['title'] for item in service.list()] == ['first']\nprint('PASS')\n",
        )
    elif fixture == "project_context":
        (project / ".qwen").mkdir(exist_ok=True)
        (project / ".qwen" / "PROJECT_INSTRUCTIONS.md").write_text(
            "The formatter public function must be named format_ticket and return PREFIX-number using prefix upper-case and number padded to four digits.\n",
            encoding="utf-8",
        )
        (project / "tests" / "test_formatter.py").write_text(
            "import unittest\nfrom pathlib import Path\n\nclass T(unittest.TestCase):\n"
            "    def test_project_context_exists(self): self.assertTrue(Path('.qwen/PROJECT_INSTRUCTIONS.md').is_file())\n",
            encoding="utf-8",
        )
        _write_behavior_check(
            project,
            "check_formatter.py",
            "from formatter import format_ticket\nassert format_ticket('bug', 7) == 'BUG-0007'\nprint('PASS')\n",
        )
    elif fixture == "repair_loop":
        (project / "contract.md").write_text("parse_port accepts integers or digit strings from 1 through 65535. Other values raise ValueError.\n", encoding="utf-8")
        (project / "tests" / "test_ports.py").write_text(
            "import unittest\nfrom pathlib import Path\n\nclass T(unittest.TestCase):\n"
            "    def test_contract_exists(self): self.assertTrue(Path('contract.md').is_file())\n",
            encoding="utf-8",
        )
        (project / "validation.py").write_text(
            "from pathlib import Path\n"
            "assert Path('contract.md').is_file()\n"
            "if Path('ports.py').is_file():\n"
            "    from ports import parse_port\n"
            "    assert parse_port(1) == 1\n"
            "    assert parse_port('443') == 443\n"
            "    assert parse_port(65535) == 65535\n"
            "    for value in (0, 65536, 'bad', None, True):\n"
            "        try:\n"
            "            parse_port(value)\n"
            "        except ValueError:\n"
            "            pass\n"
            "        else:\n"
            "            raise AssertionError(f'Expected ValueError for {value!r}')\n"
            "print('PASS')\n",
            encoding="utf-8",
        )
        _write_behavior_check(
            project,
            "check_ports.py",
            "from ports import parse_port\nassert parse_port('443') == 443\nfor value in (0, 65536, 'bad', None):\n    try:\n        parse_port(value)\n    except ValueError:\n        pass\n    else:\n        raise AssertionError(f'Expected ValueError for {value!r}')\nprint('PASS')\n",
        )
    else:
        raise ValueError(f"Unknown fixture: {fixture}")


def _client_get(client: TestClient, client_lock: threading.Lock, path: str):
    with client_lock:
        return client.get(path)


def _client_post(client: TestClient, client_lock: threading.Lock, path: str, *, json_body: dict[str, Any]):
    with client_lock:
        return client.post(path, json=json_body)


def wait_run(client: TestClient, client_lock: threading.Lock, run_id: str, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = _client_get(client, client_lock, f"/api/workflow-runs/{run_id}")
        response.raise_for_status()
        run = response.json()
        if run.get("status") in TERMINAL:
            return run
        time.sleep(0.5)
    raise TimeoutError(f"Run {run_id} did not finish in {timeout}s")


def execute_case(
    client: TestClient,
    client_lock: threading.Lock,
    case: dict[str, Any],
    root: Path,
    timeout: float,
) -> dict[str, Any]:
    project = root / case["id"]
    write_fixture(project, case["fixture"])
    started = time.time()
    profile_response = _client_post(
        client,
        client_lock,
        "/api/project-validation-profile/verify",
        json_body={"project_path": str(project), "timeout_sec": min(300, int(timeout))},
    )
    profile_response.raise_for_status()
    profile = profile_response.json().get("profile") or {}
    if profile.get("status") not in {"verified", "trusted"}:
        raise AssertionError(f"{case['id']} baseline validation profile is not verified: {profile.get('status')}")
    session_response = _client_post(
        client, client_lock, "/api/sessions", json_body={"title": case["id"], "project_path": str(project)}
    )
    session_response.raise_for_status()
    session = session_response.json()
    body = {
            "workflow_id": case["workflow"],
            "project_path": str(project),
            "requirement": case["requirement"],
            "test_command": case.get("test_command"),
            "validation_script": case.get("validation_script"),
            "agent": "qwen",
            "unattended": True,
            "autopilotMode": "safe_apply",
            "patchMode": "atomic_apply",
        }
    response = _client_post(
        client, client_lock, f"/api/sessions/{session['id']}/workflow-runs", json_body=body
    )
    response.raise_for_status()
    run = wait_run(client, client_lock, response.json()["id"], timeout)
    ended = time.time()
    if run.get("status") != "done":
        raise AssertionError(f"{case['id']} failed: {run.get('error')}")
    effective_cwd = Path(str(run.get("project_path") or "")).expanduser().resolve()
    isolated_cwd = Path(str(run.get("isolated_project_path") or "")).expanduser().resolve()
    original_project = Path(str(run.get("original_project_path") or "")).expanduser().resolve()
    if effective_cwd != isolated_cwd:
        raise AssertionError(f"{case['id']} Agent cwd was not the isolated project path: {effective_cwd} != {isolated_cwd}")
    if original_project != project.resolve():
        raise AssertionError(f"{case['id']} original project path changed: {original_project} != {project.resolve()}")
    if case.get("fixture") == "project_context":
        config_path = effective_cwd / ".qwen" / "PROJECT_INSTRUCTIONS.md"
        if not config_path.is_file():
            raise AssertionError(f"{case['id']} project-local Qwen config was not copied into Agent cwd")
    for rel in case.get("expected_files") or []:
        if not (project / rel).is_file():
            raise AssertionError(f"{case['id']} missing Agent-generated file: {rel}")
    behavior = subprocess.run(
        case["behavior_check"],
        cwd=project,
        shell=True,
        capture_output=True,
        text=True,
        timeout=min(300, timeout),
    )
    if behavior.returncode != 0:
        raise AssertionError(f"{case['id']} behavior check failed:\n{behavior.stdout}\n{behavior.stderr}")
    return {
        "case": case["id"],
        "run_id": run["id"],
        "session_id": session["id"],
        "status": run["status"],
        "started_at": started,
        "ended_at": ended,
        "duration_sec": round(ended - started, 3),
        "project": str(project),
        "effective_cwd": str(effective_cwd),
        "isolated_project": str(isolated_cwd),
        "original_project": run.get("original_project_path"),
        "qwen_session_id": run.get("qwen_session_id"),
        "validation_profile_status": profile.get("status"),
        "behavior_check": case["behavior_check"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run opt-in real Qwen unattended workflow E2E cases.")
    parser.add_argument("--case", action="append", dest="case_ids", help="Run only selected case id; repeatable.")
    parser.add_argument("--timeout", type=float, default=float(os.environ.get("REAL_QWEN_E2E_TIMEOUT_SEC", "1200")))
    parser.add_argument("--parallel", action="store_true", help="Run selected cases concurrently in different sessions/projects.")
    parser.add_argument("--output", default=str(ROOT / "reports" / "real-qwen-unattended-e2e.json"))
    args = parser.parse_args()
    require_qwen()
    payload = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    cases = payload["cases"]
    if args.case_ids:
        wanted = set(args.case_ids)
        cases = [case for case in cases if case["id"] in wanted]
        missing = wanted - {case["id"] for case in cases}
        if missing:
            raise SystemExit(f"Unknown case(s): {', '.join(sorted(missing))}")
    if not cases:
        raise SystemExit("No cases selected")
    os.environ["QWEN_MOCK"] = "0"
    with tempfile.TemporaryDirectory(prefix="aiwf-real-qwen-e2e-") as tmp, TestClient(app) as client:
        root = Path(tmp)
        client_lock = threading.Lock()
        if args.parallel:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(cases))) as pool:
                futures = [pool.submit(execute_case, client, client_lock, case, root, args.timeout) for case in cases]
                results = [future.result() for future in futures]
        else:
            results = [execute_case(client, client_lock, case, root, args.timeout) for case in cases]
    if args.parallel and len(results) > 1:
        session_ids = {row["session_id"] for row in results}
        if len(session_ids) != len(results):
            raise AssertionError("Concurrent runs did not use distinct workflow sessions")
        qwen_session_ids = [str(row.get("qwen_session_id") or "") for row in results]
        if any(not value for value in qwen_session_ids) or len(set(qwen_session_ids)) != len(results):
            raise AssertionError("Concurrent runs did not use distinct Qwen CLI sessions")
        overlap = any(
            left["started_at"] < right["ended_at"] and right["started_at"] < left["ended_at"]
            for index, left in enumerate(results) for right in results[index + 1 :]
        )
        if not overlap:
            raise AssertionError("Concurrent cases did not overlap in execution")
    report = {"schema": payload["schema"], "parallel": args.parallel, "results": results, "passed": len(results)}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
