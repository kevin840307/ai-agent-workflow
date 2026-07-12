#!/usr/bin/env python3
"""V22 Workflow Runner UI smoke.

The default mode validates static contracts. ``--browser`` renders the real
HTML/CSS in Chromium and checks Patch Review, Validation, Execution Artifacts,
and Run Center geometry with large synthetic evidence.  The synthetic data is
DOM-only and never creates or edits project files.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC = REPO_ROOT / "static"


def _sources() -> tuple[str, str, str, str]:
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    runs = (STATIC / "js" / "features" / "runs.js").read_text(encoding="utf-8")
    patch = (STATIC / "js" / "features" / "patch-review.js").read_text(encoding="utf-8")
    artifacts = (STATIC / "js" / "features" / "artifacts.js").read_text(encoding="utf-8")
    return index, runs, patch, artifacts


def static_smoke() -> dict[str, object]:
    index, runs, patch, artifacts = _sources()
    css = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [STATIC / "styles.css", *sorted((STATIC / "css").glob("*.css"))]
        if path.exists()
    )
    checks = {
        "index_exists": bool(index),
        "two_run_center_tabs": len(re.findall(r'class="tab(?: active)?" data-tab=', index)) == 2
        and all(label in index for label in ("總覽", "驗證"))
        and 'data-tab="changesPanel"' not in index,
        "overview_patch_entry": 'id="overviewChangeCard"' in index and "查看並審核變更" in runs,
        "patch_review_workbench": all(
            token in index
            for token in (
                'id="diffDialog"',
                'id="diffDialogFileList"',
                'id="diffDialogContent"',
                'id="patchReviewFooter"',
                'id="patchRejectStep"',
            )
        )
        and ".diff-dialog.patch-review-workbench" in css,
        "patch_review_not_in_diagnostics": 'id="diagnosticPatch"' not in index
        and "applyDiagnosticPatch" not in index,
        "separate_approval_actions": 'id="approvePatch"' in index
        and 'id="approveApplyPatch"' in index
        and 'id="rejectPatch"' in index,
        "partial_patch_revalidation": "/patch/validate-selection" in patch
        and "selection_hash" in patch
        and "validation_evidence_hash" in patch,
        "explicit_reject_target": "rejectStep" in patch and "producer_step_key" in patch,
        "fullscreen_diff": "width: calc(100vw - 16px)" in css
        and "height: calc(100dvh - 16px)" in css,
        "diff_focus_and_sidebar": "focus-mode" in patch
        and "files-collapsed" in patch
        and "patchViewMode" in patch,
        "bounded_diff_rendering": "DIFF_PAGE_ROWS = 1500" in patch
        and "data-diff-load-more" in patch
        and "content-visibility: auto" in css,
        "remembered_patch_preferences": "patchSidebarWidth" in patch
        and "patchFilesCollapsed" in patch,
        "execution_artifacts": "執行產物" in index
        and 'id="diagnosticArtifacts"' in index
        and 'class="artifact-viewer-layout"' in index,
        "artifact_master_detail": ".artifact-viewer-layout" in css
        and "display_order" in artifacts
        and "producer_step_key" in artifacts
        and "media_type" in artifacts,
        "artifact_segmented_preview": "PREVIEW_CHUNK_CHARS = 500_000" in artifacts
        and 'id="artifactLoadMore"' in index,
        "artifact_storage_summary": "artifactStorageSummary" in artifacts
        and 'id="artifactStorageSummary"' in index,
        "artifact_no_filename_semantics": all(
            token not in artifacts
            for token in ('name.includes("test")', 'name.includes("review")', 'name.includes("log")', 'endsWith("spec.md")')
        ),
        "validation_evidence_cards": "validation-evidence-grid" in runs
        and "blocks_apply" in runs
        and "executed" in runs,
        "diagnostics_remains_technical": all(
            label in index for label in ("執行時間線", "Agent 原始輸出", "完整 Logs", "執行產物", "修復策略", "系統健康")
        ),
        "step_scoped_artifact_preview": "stepFilesModalBackdrop" in artifacts and "僅顯示此 Step" in artifacts and "config.outputs" in artifacts,
        "equal_split_columns": "split-diff-grid" in patch and "flex: 0 0 50%" in css and "width: 50%" in css,
        "cache_v22": "20260712-ui-v21" not in index and "20260712-ui-v22" in index,
    }
    return {"schema": "aiwf.browser-ui-smoke.v22", "mode": "static", "ok": all(checks.values()), "checks": checks}


def _inline_document() -> str:
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    index = re.sub(r'<link[^>]+rel=["\']stylesheet["\'][^>]*>', "", index, flags=re.IGNORECASE)
    index = re.sub(r'<script\b[^>]*>.*?</script>', "", index, flags=re.IGNORECASE | re.DOTALL)
    css = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [STATIC / "styles.css", *sorted((STATIC / "css").glob("*.css"))]
        if path.exists()
    )
    return f"<style>{css}</style>{index}"


def browser_smoke(base_url: str) -> dict[str, object]:
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as exc:
        return {"schema": "aiwf.browser-ui-smoke.v22", "mode": "browser", "ok": False, "error": f"Playwright unavailable: {exc}"}

    executable = os.environ.get("AIWF_BROWSER_EXECUTABLE") or next(
        (path for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable") if (path := shutil.which(name))),
        None,
    )
    with sync_playwright() as playwright:
        options: dict[str, object] = {"headless": True}
        if executable:
            options["executable_path"] = executable
        try:
            browser = playwright.chromium.launch(**options)
        except Exception as exc:
            return {
                "schema": "aiwf.browser-ui-smoke.v22",
                "mode": "browser",
                "ok": False,
                "error": f"Chromium unavailable: {exc}",
                "executable": executable,
            }
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        navigation_mode = "server"
        try:
            page.goto(base_url, wait_until="domcontentloaded", timeout=12_000)
            page.wait_for_selector("#diffDialog", timeout=5_000)
        except Exception:
            navigation_mode = "inline-layout"
            try:
                page.close()
            except Exception:
                pass
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            page.set_content(_inline_document(), wait_until="domcontentloaded")

        artifact_module = (STATIC / "js" / "features" / "artifacts.js").read_text(encoding="utf-8")
        artifact_module = artifact_module.replace("export function createArtifacts", "function createArtifacts", 1)
        page.add_script_tag(content=artifact_module + "\nwindow.__createArtifactsV22 = createArtifacts;")

        geometry = page.evaluate(
            r"""
            async () => {
              document.body.classList.remove('details-collapsed');
              document.body.classList.add('advanced-mode');

              document.querySelectorAll('.panel').forEach((panel) => {
                panel.hidden = true;
                panel.classList.remove('active');
              });
              const validationPanel = document.querySelector('#validationPanel');
              validationPanel.hidden = false;
              validationPanel.classList.add('active');
              document.querySelectorAll('.run-center-tabs .tab').forEach((tab) => tab.classList.remove('active'));
              document.querySelector('[data-tab="validationPanel"]')?.classList.add('active');
              document.querySelector('#validationList').innerHTML = Array.from({length: 36}, (_, i) => `
                <article class="validation-row status-${i % 5 === 0 ? 'failed' : 'passed'}">
                  <header><strong>Validator ${i}</strong><span>${i % 5 === 0 ? 'FAILED' : 'PASS'}</span></header>
                  <div><code>python validation-${i}.py</code><small>Exit ${i % 5 === 0 ? 1 : 0} · Required · Blocks Apply</small></div>
                </article>`).join('');
              const tabs = document.querySelector('.run-center-tabs').getBoundingClientRect();
              const validation = validationPanel.getBoundingClientRect();
              const validationList = document.querySelector('#validationList');

              const patchBackdrop = document.querySelector('#diffDialogBackdrop');
              const patchDialog = document.querySelector('#diffDialog');
              patchBackdrop.hidden = false;
              document.body.classList.add('diff-dialog-open');
              document.querySelector('#diffDialogSummary').innerHTML = '<span>120 files</span><span>+5200</span><span>-1700</span>';
              document.querySelector('#diffDialogFileList').innerHTML = Array.from({length: 120}, (_, i) => `
                <div class="patch-workbench-file"><button><span class="change-kind modified">修改</span><span class="patch-file-name"><strong>src/feature-${i}.py</strong><small>+40 / -8</small></span></button></div>`).join('');
              document.querySelector('#diffDialogContent').innerHTML = `
                <article class="patch-workbench-review"><header><div><h3>src/feature-0.py</h3></div></header>
                <div class="diff-code unified">${Array.from({length: 700}, (_, i) => `<div class="diff-code-row ${i % 4 === 0 ? 'added' : 'context'}"><span>${i}</span><span>${i}</span><code>${i % 4 === 0 ? '+' : ' '} line ${i}</code></div>`).join('')}</div></article>`;
              document.querySelector('#patchReviewSelection').innerHTML = '<strong>120 / 120</strong><span>完整 Patch</span>';
              document.querySelector('#patchReviewValidation').innerHTML = '<div><strong>完整 Patch 驗證通過</strong><small>6 項 Required Evidence 可用</small></div>';
              const patchBox = patchDialog.getBoundingClientRect();
              const patchHeader = patchDialog.querySelector('.patch-review-toolbar').getBoundingClientRect();
              const patchFooter = document.querySelector('#patchReviewFooter').getBoundingClientRect();
              const patchFiles = document.querySelector('#diffDialogFileList');
              const patchSidebar = document.querySelector('#diffDialogFiles').getBoundingClientRect();
              const patchContent = document.querySelector('#diffDialogContent').getBoundingClientRect();
              const patchCode = document.querySelector('#diffDialogContent .diff-code');
              const patchMetrics = {
                width: patchBox.width,
                height: patchBox.height,
                headerHeight: patchHeader.height,
                footerHeight: patchFooter.height,
                sidebarWidth: patchSidebar.width,
                contentWidth: patchContent.width,
                filesScrollable: patchFiles.scrollHeight > patchFiles.clientHeight,
                filesClient: patchFiles.clientHeight,
                filesScroll: patchFiles.scrollHeight,
                codeScrollable: patchCode.scrollHeight > patchCode.clientHeight,
                codeClient: patchCode.clientHeight,
                codeScroll: patchCode.scrollHeight,
                contentClient: document.querySelector('#diffDialogContent').clientHeight,
                reviewClient: document.querySelector('.patch-workbench-review').clientHeight,
                bodyClient: document.querySelector('.patch-review-body').clientHeight,
              };
              document.querySelector('#diffDialogContent').innerHTML = `
                <article class="patch-workbench-review"><header><div><h3>src/split.py</h3></div></header>
                <div class="split-diff" style="--split-side-min:620px"><div class="split-diff-grid">
                  <div class="split-diff-labels"><span>Before</span><span>After</span></div>
                  <div class="split-diff-row"><div class="split-diff-cell removed"><span>1</span><code>short</code></div><div class="split-diff-cell added"><span>1</span><code>${'long content '.repeat(100)}</code></div></div>
                </div></div></article>`;
              const splitCells = [...document.querySelectorAll('#diffDialogContent .split-diff-cell')].map((node) => node.getBoundingClientRect().width);
              const splitLabels = [...document.querySelectorAll('#diffDialogContent .split-diff-labels > span')].map((node) => node.getBoundingClientRect().width);

              const beforeFocusWidth = patchContent.width;
              patchDialog.classList.add('focus-mode');
              await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
              const focusContentWidth = document.querySelector('#diffDialogContent').getBoundingClientRect().width;
              const focusFooterDisplay = getComputedStyle(document.querySelector('#patchReviewFooter')).display;
              patchDialog.classList.remove('focus-mode');
              patchBackdrop.hidden = true;
              document.body.classList.remove('diff-dialog-open');

              const diagnosticsBackdrop = document.querySelector('#diagnosticsBackdrop');
              const diagnostics = document.querySelector('#diagnosticsDrawer');
              diagnosticsBackdrop.hidden = false;
              diagnostics.classList.add('maximized');
              document.querySelectorAll('.diagnostic-section').forEach((section) => {
                section.hidden = true;
                section.classList.remove('active');
              });
              const artifactsSection = document.querySelector('#diagnosticArtifacts');
              artifactsSection.hidden = false;
              artifactsSection.classList.add('active');
              document.querySelector('#artifacts').innerHTML = Array.from({length: 120}, (_, i) => `
                <button class="artifact-list-item"><span class="artifact-role-icon">A</span><span><strong>Artifact ${i}</strong><small>validation · test-result</small><em>12 KB · validate-${i}</em></span></button>`).join('');
              document.querySelector('#artifactContent').textContent = Array.from({length: 700}, (_, i) => `${i + 1} evidence line`).join('\n');
              const artifactLayout = document.querySelector('.artifact-viewer-layout').getBoundingClientRect();
              const artifactList = document.querySelector('#artifacts');
              const artifactPane = document.querySelector('.artifact-preview-pane').getBoundingClientRect();
              const artifactContent = document.querySelector('#artifactContent');
              const initialArtifactListScrollable = artifactList.scrollHeight > artifactList.clientHeight;
              const initialArtifactContentScrollable = artifactContent.scrollHeight > artifactContent.clientHeight;

              const artifactRow = {
                id: 'run-ui:output|step-result.md', run_id: 'run-ui', path: 'output/step-result.md',
                category: 'step', role: 'step-output', visibility: 'supporting', display_order: 500,
                display_name: 'Build · step-result.md', producer_step_key: 'build',
                media_type: 'text/markdown', preview_kind: 'markdown', size: 32
              };
              const featureState = {activeRunId: 'run-ui', currentArtifacts: [artifactRow], selectedStepArtifactId: null};
              const artifactFeature = window.__createArtifactsV22({
                api: {request: async () => ({...artifactRow, content: '# Step document\n\nScoped preview works.'})},
                state: featureState,
                ui: {
                  byKey: (key) => document.getElementById(key),
                  escapeHtml: (value = '') => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;'),
                  emptyState: (title, detail) => `<div><strong>${title}</strong><span>${detail}</span></div>`,
                },
                features: {console: {append: () => {}}, runs: {openStepDetailModal: () => {}}},
              });
              artifactFeature.render([artifactRow]);
              await artifactFeature.open(artifactRow.id, {activateArtifactsTab: false});
              const globalArtifactPreviewWorks = document.querySelector('#artifactRenderedContent')?.textContent.includes('Scoped preview works');
              await artifactFeature.openStepFilesModal(
                {id: 'run-ui', artifacts: [artifactRow]},
                {key: 'build', title: 'Build', config: {outputs: ['step-result.md']}},
                {preview: true, artifactId: artifactRow.id},
              );
              const stepBackdrop = document.querySelector('#stepFilesModalBackdrop');
              const stepDialogVisible = Boolean(stepBackdrop && !stepBackdrop.hidden);
              const stepDialogTitle = document.querySelector('#stepFilesModalTitle')?.textContent || '';
              const stepDialogTabs = document.querySelectorAll('#stepFilesTabs .step-files-tab').length;
              const stepDialogPreviewWorks = document.querySelector('#stepFilesRendered')?.textContent.includes('Scoped preview works');
              artifactFeature.closeStepFilesModal();

              return {
                viewport: {width: innerWidth, height: innerHeight},
                tabCount: document.querySelectorAll('.run-center-tabs .tab').length,
                changesTabCount: document.querySelectorAll('[data-tab="changesPanel"]').length,
                tabsHeight: tabs.height,
                validationBelowTabs: validation.y >= tabs.y + tabs.height - 1,
                validationScrollable: validationList.scrollHeight > validationList.clientHeight,
                patchWidth: patchMetrics.width,
                patchHeight: patchMetrics.height,
                patchHeaderHeight: patchMetrics.headerHeight,
                patchFooterHeight: patchMetrics.footerHeight,
                patchSidebarWidth: patchMetrics.sidebarWidth,
                patchContentWidth: patchMetrics.contentWidth,
                patchFilesScrollable: patchMetrics.filesScrollable,
                patchFilesClient: patchMetrics.filesClient,
                patchFilesScroll: patchMetrics.filesScroll,
                patchCodeScrollable: patchMetrics.codeScrollable,
                patchCodeClient: patchMetrics.codeClient,
                patchCodeScroll: patchMetrics.codeScroll,
                patchContentClient: patchMetrics.contentClient,
                patchReviewClient: patchMetrics.reviewClient,
                patchBodyClient: patchMetrics.bodyClient,
                splitCellWidths: splitCells,
                splitLabelWidths: splitLabels,
                splitColumnsEqual: splitCells.length === 2 && splitLabels.length === 2 && Math.abs(splitCells[0] - splitCells[1]) <= 1 && Math.abs(splitLabels[0] - splitLabels[1]) <= 1 && Math.abs(splitCells[0] - splitLabels[0]) <= 1,
                focusContentExpanded: focusContentWidth > beforeFocusWidth,
                focusFooterHidden: focusFooterDisplay === 'none',
                artifactLayoutWidth: artifactLayout.width,
                artifactListWidth: artifactList.getBoundingClientRect().width,
                artifactPaneWidth: artifactPane.width,
                artifactListScrollable: initialArtifactListScrollable,
                artifactContentScrollable: initialArtifactContentScrollable,
                diagnosticPatchCount: document.querySelectorAll('#diagnosticPatch').length,
                rejectTargetPresent: Boolean(document.querySelector('#patchRejectStep')),
                artifactStorageSummaryPresent: Boolean(document.querySelector('#artifactStorageSummary')),
                artifactLoadMorePresent: Boolean(document.querySelector('#artifactLoadMore')),
                globalArtifactPreviewWorks,
                stepDialogVisible,
                stepDialogTitle,
                stepDialogTabs,
                stepDialogPreviewWorks,
              };
            }
            """
        )
        browser.close()

    checks = {
        "two_tabs": geometry["tabCount"] == 2 and geometry["changesTabCount"] == 0,
        "validation_layout": geometry["validationBelowTabs"] and geometry["validationScrollable"],
        "near_fullscreen_patch": geometry["patchWidth"] >= geometry["viewport"]["width"] - 24
        and geometry["patchHeight"] >= geometry["viewport"]["height"] - 24,
        "compact_patch_chrome": 44 <= geometry["patchHeaderHeight"] <= 72 and 48 <= geometry["patchFooterHeight"] <= 90,
        "patch_master_detail": 220 <= geometry["patchSidebarWidth"] <= 320
        and geometry["patchContentWidth"] > geometry["patchSidebarWidth"],
        "independent_patch_scroll": geometry["patchFilesScrollable"] and geometry["patchCodeScrollable"],
        "equal_split_columns": geometry["splitColumnsEqual"],
        "focus_mode": geometry["focusContentExpanded"] and geometry["focusFooterHidden"],
        "artifact_master_detail": geometry["artifactPaneWidth"] > geometry["artifactListWidth"]
        and geometry["artifactLayoutWidth"] >= geometry["artifactPaneWidth"] + geometry["artifactListWidth"] - 2,
        "artifact_independent_scroll": geometry["artifactListScrollable"] and geometry["artifactContentScrollable"],
        "patch_removed_from_diagnostics": geometry["diagnosticPatchCount"] == 0,
        "explicit_reject_target": geometry["rejectTargetPresent"],
        "artifact_storage_controls": geometry["artifactStorageSummaryPresent"] and geometry["artifactLoadMorePresent"],
        "artifact_preview_content": geometry["globalArtifactPreviewWorks"],
        "step_scoped_artifact_dialog": geometry["stepDialogVisible"]
        and "Build" in geometry["stepDialogTitle"]
        and geometry["stepDialogTabs"] == 1
        and geometry["stepDialogPreviewWorks"],
    }
    return {
        "schema": "aiwf.browser-ui-smoke.v22",
        "mode": "browser",
        "ok": all(checks.values()),
        "baseUrl": base_url,
        "browserExecutable": executable or "playwright-managed",
        "navigationMode": navigation_mode,
        "checks": checks,
        "geometry": geometry,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.environ.get("AIWF_UI_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--browser", action="store_true", default=os.environ.get("RUN_PLAYWRIGHT_UI") == "1")
    args = parser.parse_args()
    result = browser_smoke(args.base_url) if args.browser else static_smoke()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
