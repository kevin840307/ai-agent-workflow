# Prompt Template Modal + Params Patch

Fixes:

1. `Edit Template` modal was hidden/covered by the step modal/context menu because the prompt template modal had a lower z-index than other designer overlays.
2. Workflow Designer showed valid backend prompt params as `Unknown params`, including:
   - `{{project_overview}}`
   - `{{architecture}}`
   - `{{test_plan}}`
   - `{{test_result}}`
   - `{{failure_feedback}}`
3. Backend now exposes prompt params through `/api/workflows/functions` as `promptParams` so the frontend list stays aligned with runtime.
4. `{{step_output}}` is now also available in backend `PromptBuilder` values.

Apply from project root:

```powershell
Expand-Archive -Path prompt_template_modal_params_patch.zip -DestinationPath . -Force
python -m compileall -q app
python -c "import app.runtime; import app.main; print('ok')"
```

Also hard-refresh the browser after applying because `workflow-designer.js` and CSS are static files.
