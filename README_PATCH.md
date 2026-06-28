# Workflow JSON Runtime Patch

這包修正三個重點：

1. Workflow Designer 顯示與保存 workflow.json 設定更完整
   - Step list / canvas 顯示 retry target、agent provider。
   - Retry tab 顯示後端實際 retry target。
   - Export JSON 改成明確標示 backend workflow.json payload。

2. 後端執行改為以 workflow.json 為主
   - templatePath / outputFile / filename / agent / provider / command / sources / timeout / expectedFiles / validator / retryFromStepKey 會被 runtime 使用。
   - build / generate_tests / prepare_project 不再固定輸出檔名。
   - artifacts 清單會包含自訂 outputFile、expectedFiles、multi-agent reviewer artifacts。

3. Review Strategy 後端支援三種模式
   - none：略過 review，寫 Status: PASS。
   - current_session：沿用目前 agent session。
   - new_agent：使用 fresh session。
   - multi_agent：依 reviewers 執行多 reviewer，支援 keyword_confidence / majority_vote / all_must_pass。

已檢查：

```powershell
python -m compileall -q app
python -c "import app.runtime; import app.main; print('ok')"
node --check static/js/pages/workflow-designer.js
```

覆蓋方式：

```powershell
cd C:\Users\kevin\testllm
Expand-Archive -Path workflow_json_runtime_patch.zip -DestinationPath . -Force
python -m compileall -q app
python -c "import app.runtime; import app.main; print('ok')"
```
