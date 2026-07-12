from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable

from app.runtime_modules import api as runtime
from app.services.model_circuit_breaker import model_circuit_breaker

_URL_KEYS = {
    "baseurl", "base_url", "apiurl", "api_url", "endpoint", "url", "host",
    "openai_base_url", "openai_api_base",
}
_CONFIG_FILES = (
    "opencode.json", "opencode.jsonc", ".opencode/opencode.json", ".opencode/config.json",
    ".qwen/settings.json", ".qwen/settings.local.json", "qwen.json", ".qwen.json",
)
_ENV_URLS = (
    "OPENAI_BASE_URL", "OPENAI_API_BASE", "QWEN_BASE_URL", "QWEN_API_BASE",
    "OPENCODE_BASE_URL", "AIWF_MODEL_BASE_URL",
)


def _strip_json_comments(text: str) -> str:
    import re
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"(^|\s)//.*$", r"\1", text, flags=re.MULTILINE)
    return text


def _walk_urls(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).replace("-", "_").lower()
            if normalized in _URL_KEYS and isinstance(item, str):
                yield item
            yield from _walk_urls(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_urls(item)


def _normalize_base_url(raw: str) -> str | None:
    value = str(raw or "").strip().rstrip("/")
    if not value:
        return None
    if value.startswith("localhost:") or value.startswith("127.0.0.1:"):
        value = "http://" + value
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return value


def discover_model_endpoints(project_path: str | Path | None = None) -> list[dict[str, str]]:
    found: dict[str, dict[str, str]] = {}

    def add(raw: str, source: str) -> None:
        normalized = _normalize_base_url(raw)
        if normalized:
            found.setdefault(normalized, {"base_url": normalized, "source": source})

    for name in _ENV_URLS:
        if os.environ.get(name):
            add(os.environ[name], f"env:{name}")

    config = runtime.load_settings()
    for url in _walk_urls(config):
        add(url, "controller-settings")

    runtime_config = runtime.qwen_runtime_config()
    for url in _walk_urls(runtime_config):
        add(url, "agent-runtime")

    if project_path:
        project = Path(project_path).expanduser().resolve()
        for relative in _CONFIG_FILES:
            path = project / relative
            if not path.is_file():
                continue
            try:
                data = json.loads(_strip_json_comments(path.read_text(encoding="utf-8-sig")))
            except (OSError, json.JSONDecodeError):
                continue
            for url in _walk_urls(data):
                add(url, f"project:{relative}")

    serve_status = runtime.qwen_serve_status or {}
    if serve_status.get("base_url"):
        add(str(serve_status["base_url"]), "qwen-serve")
    return list(found.values())


def _probe_candidates(base_url: str) -> list[str]:
    parsed = urllib.parse.urlparse(base_url)
    path = parsed.path.rstrip("/")
    origin = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))
    candidates = [base_url]
    if path.endswith("/v1"):
        candidates.insert(0, f"{base_url}/models")
    else:
        candidates.extend([f"{base_url}/health", f"{base_url}/v1/models"])
    if origin != base_url:
        candidates.append(f"{origin}/health")
    return list(dict.fromkeys(candidates))


def _probe_sync(base_url: str, timeout_sec: float) -> dict[str, Any]:
    started = time.monotonic()
    last_error = ""
    for url in _probe_candidates(base_url):
        request = urllib.request.Request(url, method="GET", headers={"User-Agent": "AIWF-Connectivity/1"})
        try:
            with urllib.request.urlopen(request, timeout=timeout_sec) as response:
                return {
                    "state": "online",
                    "reachable": True,
                    "http_status": int(response.status),
                    "probe_url": url,
                    "latency_ms": round((time.monotonic() - started) * 1000, 1),
                }
        except urllib.error.HTTPError as exc:
            # 401/403/404 still prove the model endpoint is reachable. The
            # actual agent owns authentication and model selection.
            if 100 <= int(exc.code) < 500:
                return {
                    "state": "online",
                    "reachable": True,
                    "http_status": int(exc.code),
                    "probe_url": url,
                    "latency_ms": round((time.monotonic() - started) * 1000, 1),
                    "detail": "Endpoint reachable; probe request was not authorized or not supported.",
                }
            last_error = f"HTTP {exc.code}"
        except Exception as exc:  # URL/socket errors vary by platform.
            last_error = str(exc)
    return {
        "state": "offline",
        "reachable": False,
        "latency_ms": round((time.monotonic() - started) * 1000, 1),
        "error": last_error or "Endpoint did not respond.",
    }


async def connectivity_status(project_path: str | None = None, agent: str | None = None) -> dict[str, Any]:
    selected = (agent or runtime.qwen_runtime_config().get("agents", {}).get("default") or "qwen").strip().lower()
    runtime_config = runtime.qwen_runtime_config()
    providers = (runtime_config.get("agents") or {}).get("providers") or {}
    provider = dict(providers.get(selected) or {})
    binary = str(provider.get("bin") or ("qwen.cmd" if selected == "qwen" and os.name == "nt" else selected))
    cli_ready = bool(provider.get("mock") or provider.get("exists") or shutil.which(binary))
    endpoints = discover_model_endpoints(project_path)
    probes: list[dict[str, Any]] = []
    timeout = max(0.2, min(float(os.environ.get("AIWF_CONNECTIVITY_TIMEOUT_SEC", "1.5")), 10.0))
    if endpoints:
        probes = await asyncio.gather(*[
            asyncio.to_thread(_probe_sync, item["base_url"], timeout) for item in endpoints[:8]
        ])
        for item, result in zip(endpoints, probes):
            result.update(item)
    reachable = [item for item in probes if item.get("reachable")]
    if reachable:
        state = "online"
    elif probes:
        state = "offline"
    elif cli_ready:
        state = "unknown"
    else:
        state = "unavailable"
    if state == "online":
        circuit = await model_circuit_breaker.record_success(selected)
    else:
        circuit = await model_circuit_breaker.snapshot(selected)
    return {
        "schema": "aiwf.provider-connectivity.v2",
        "state": state,
        "online": state == "online",
        "agent": selected,
        "cli_ready": cli_ready,
        "binary": binary,
        "project_path": project_path,
        "endpoints": probes,
        "checked_at": runtime.utc_now(),
        "retry_recommended": state in {"offline", "unknown"},
        "circuit": circuit,
    }


async def wait_for_connectivity(
    project_path: str | Path | None = None,
    agent: str | None = None,
    *,
    timeout_sec: float | None = None,
    poll_sec: float | None = None,
    on_status: Any = None,
) -> dict[str, Any]:
    """Wait for an explicitly configured local endpoint to return.

    Unknown means the CLI is available but no endpoint can be discovered, so
    waiting would only burn a retry budget. Offline endpoints are polled with a
    low-frequency loop suitable for local llama.cpp/LM Studio/Ollama restarts.
    """
    timeout = max(0.0, float(timeout_sec if timeout_sec is not None else os.environ.get("AIWF_PROVIDER_RECONNECT_TIMEOUT_SEC", "600") or 600))
    interval = max(1.0, float(poll_sec if poll_sec is not None else os.environ.get("AIWF_PROVIDER_RECONNECT_POLL_SEC", "3") or 3))
    started = time.monotonic()
    announced = False
    while True:
        status = await connectivity_status(str(project_path) if project_path else None, agent)
        if status.get("state") in {"online", "unknown"}:
            return status
        elapsed = time.monotonic() - started
        if timeout <= 0 or elapsed >= timeout:
            return {**status, "wait_timed_out": True, "waited_sec": round(elapsed, 2)}
        if on_status and not announced:
            result = on_status("Model endpoint is offline. Waiting for automatic reconnection without consuming agent retries...")
            if hasattr(result, "__await__"):
                await result
            announced = True
        await asyncio.sleep(min(interval, max(0.1, timeout - elapsed)))


__all__ = ["connectivity_status", "discover_model_endpoints", "wait_for_connectivity"]
