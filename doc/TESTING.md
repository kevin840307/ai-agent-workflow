# Testing

## Daily commands

```bash
python -m unittest discover -s tests -v
PYTHONPATH=. pytest -q tests/test_prompt_builder.py tests/test_agent_runner.py
```

## Real Qwen opt-in scenarios

Set these only when you want to run actual Qwen/OpenCode integration tests instead of mock tests:

```bash
RUN_REAL_QWEN=1
RUN_REAL_QWEN_FULL=1
RUN_REAL_QWEN_STABILITY=1
RUN_CLEAN_REPO_SMOKE=1
RUN_PLAYWRIGHT_UI=1
```

Run all 8 opt-in actual scenarios once.

Clean up Linux/macOS environment variables:

```bash
unset RUN_REAL_QWEN RUN_REAL_QWEN_FULL RUN_REAL_QWEN_STABILITY
unset RUN_CLEAN_REPO_SMOKE RUN_PLAYWRIGHT_UI
```

Clean up Windows PowerShell environment variables:

```powershell
Remove-Item Env:RUN_CLEAN_REPO_SMOKE
Remove-Item Env:RUN_PLAYWRIGHT_UI
```

## Mock scenarios

```bash
QWEN_MOCK=1 QWEN_MOCK_SCENARIO=fail_final_review_once python -m unittest discover -s tests -v
QWEN_MOCK=1 QWEN_MOCK_SCENARIO=generate_tests_no_files python -m unittest discover -s tests -v
```
