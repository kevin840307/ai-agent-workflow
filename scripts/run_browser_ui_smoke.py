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
        "options_collapsed": 'id="composerAdvancedToggle"' in index and "Options" in index,
        "run_center_tabs": all(label in index for label in ("總覽", "變更", "驗證")),
        "current_action_present": 'id="currentActionCard"' in index,
        "diagnostics_drawer_present": 'id="diagnosticsDrawer"' in index and "技術診斷" in index,
        "technical_tabs_hidden_from_main": "Workflow Console" not in index and "Artifact Index" not in index,
        "runs_js_syntax_contract": "renderRunDetail" in runs_js and "renderOverview" in runs_js,
        "compact_recommendation": 'class="planning-recommendation recommendation-chip"' in index and "recommendation-popover" in css,
        "dismissible_setup": 'id="dismissSetupStatus"' in index and "compact-notice" in css,
        "dismissible_center_result_modal": 'class="run-result-modal-backdrop"' in index and ".run-result-modal-backdrop" in css and "place-items: center" in css,
        "stacked_scrollable_diff": "diff-code-row" in runs_js and 'grid-template-areas: "summary" "files" "preview"' in css and "scrollbar-gutter: stable both-edges" in css,
        "selective_patch_review": "data-patch-search" in (STATIC / "js" / "features" / "diagnostics.js").read_text(encoding="utf-8") and 'id="applyDiagnosticPatch"' in index,
        "closable_diagnostics": 'id="closeDiagnostics"' in index and 'id="diagnosticsBackdrop"' in index,
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
        assert page.locator("text=Options").count() >= 1
        assert page.locator("text=總覽").count() >= 1
        assert page.locator("text=技術診斷").count() >= 1
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
