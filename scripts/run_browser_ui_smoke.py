#!/usr/bin/env python3
"""Minimal UI smoke test.

Default mode performs a no-browser structural smoke check that is stable in CI.
Set RUN_PLAYWRIGHT_UI=1 to additionally launch a real browser with Playwright.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC = REPO_ROOT / "static"


def static_smoke() -> dict[str, object]:
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    runs_js = (STATIC / "js" / "features" / "runs.js").read_text(encoding="utf-8")
    css = "\n".join(path.read_text(encoding="utf-8") for path in [STATIC / "styles.css", *sorted((STATIC / "css").glob("*.css"))] if path.exists())
    checks = {
        "index_exists": bool(index),
        "advanced_label_present": ">Advanced<" in index or "Advanced" in index,
        "detail_tab_present": ">Detail<" in index or "Detail" in index,
        "run_detail_word_removed_from_tab": ">Run Detail<" not in index,
        "runs_js_syntax_contract": "renderRunDetail" in runs_js or "runDetail" in runs_js,
        "workflow_console_label": "Workflow Console" in index,
        "workflow_console_sections": "Run Summary / Timeline / Detail / Artifacts" in index,
        "layout_overflow_hardened": "overflow-wrap" in css or "word-break" in css,
    }
    return {"schema": "aiwf.browser-ui-smoke.v1", "mode": "static", "ok": all(checks.values()), "checks": checks}


def browser_smoke(base_url: str) -> dict[str, object]:
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as exc:
        return {"schema": "aiwf.browser-ui-smoke.v1", "mode": "browser", "ok": False, "error": f"Playwright unavailable: {exc}"}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(base_url, wait_until="networkidle")
        assert page.locator("text=Advanced").count() >= 1
        assert page.locator("text=Detail").count() >= 1
        browser.close()
    return {"schema": "aiwf.browser-ui-smoke.v1", "mode": "browser", "ok": True, "baseUrl": base_url}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.environ.get("AIWF_UI_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--browser", action="store_true", default=os.environ.get("RUN_PLAYWRIGHT_UI") == "1")
    args = parser.parse_args()
    result = browser_smoke(args.base_url) if args.browser else static_smoke()
    print(result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
