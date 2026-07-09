from __future__ import annotations

from pathlib import Path
from typing import Any

from app.runtime_modules import api as runtime
from app.services import workflow_asset_validator
from app.workflow_runtime.run_consistency import check_store_consistency


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".aiwf-health-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


async def health_summary(*, deep: bool = False) -> dict[str, Any]:
    store_path = runtime.store_path()
    checks: dict[str, Any] = {
        "storeBackend": runtime.store_backend_name(),
        "storePath": str(store_path),
        "storeReadable": True,
        "storeFileExists": store_path.exists(),
        "dataWritable": _writable(runtime.DATA_DIR),
        "artifactRootWritable": _writable(runtime.DATA_DIR),
        "staticAvailable": (runtime.STATIC_DIR / "index.html").exists(),
        "runningTasks": len(runtime.running_tasks),
        "runningProcesses": len(runtime.running_processes),
    }
    status = "ok"
    try:
        data = await runtime.store.read()
        checks["runCount"] = len(data.get("runs", []))
        active = [run for run in data.get("runs", []) if run.get("status") in {"queued", "running", "waiting_input", "cancelling"}]
        checks["activeRunCount"] = len(active)
        if deep:
            consistency = check_store_consistency(data)
            checks["consistency"] = {
                "status": consistency.get("status"),
                "errorCount": consistency.get("error_count"),
                "warningCount": consistency.get("warning_count"),
            }
            validator = await workflow_asset_validator.validate_all_workflows()
            checks["workflowAssets"] = {
                "status": validator.get("status"),
                "errors": len(validator.get("errors") or []),
                "warnings": len(validator.get("warnings") or []),
            }
    except Exception as exc:
        checks["storeReadable"] = False
        checks["storeError"] = str(exc)
        status = "error"
    if not all(bool(checks.get(key)) for key in ["storeReadable", "dataWritable", "artifactRootWritable", "staticAvailable"]):
        status = "error"
    elif deep:
        if (checks.get("consistency") or {}).get("status") == "FAIL" or (checks.get("workflowAssets") or {}).get("status") == "FAIL":
            status = "warning"
    return {"schema": "aiwf.local-health.v1", "ok": status == "ok", "status": status, "checks": checks}
