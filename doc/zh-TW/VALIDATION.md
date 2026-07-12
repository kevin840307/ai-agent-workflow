# 驗證機制

## 驗證層級

```text
Build → 受影響測試 → 完整測試 → Lint → Type Check → 設定檢查
→ 可選的不可變更 Validation Script → Completion Gate
```

支援 Python、Maven、Gradle、.NET、Node、YAML/XML、SQL、Docker/Kubernetes 與自訂 Validator Plugin。受影響測試只用來快速回饋，最後仍必須跑完整 Gate。

## Validation Script 契約

Validation Script 是專案擁有的確定性驗收程式，例如 `validation.py`。平台先執行：

```text
python validation.py --project <project_path> --workspace <run_workspace> --output <output_dir>
```

只有腳本明確拒絕參數時才退回：

```text
python validation.py
```

Run 開始時會記錄雜湊，執行前後再次驗證。Agent 可以讀取驗收行為，但不得修改它。

## 完整範例

```python
import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project")
    parser.add_argument("--workspace")
    parser.add_argument("--output")
    args = parser.parse_args()

    project = Path(args.project or ".").resolve()
    expected_file = project / "sort_utils.py"

    if not expected_file.exists():
        print(f"FAIL: missing file: {expected_file}")
        return 1

    source = expected_file.read_text(encoding="utf-8")
    if "def bubble_sort" not in source:
        print("FAIL: bubble_sort was not implemented")
        return 1

    print("PASS: validation completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

## 候選腳本

```yaml
fallbackValidationScripts:
  - validation.py
  - validate.py
  - verify.py
  - check.py
```

只有 `requiresValidationScript: false` 才能接受找不到腳本。AI Review 永遠不能覆蓋確定性驗證失敗。

## 可重用 Project Validation Profile

Validation Script 仍是不可被 AI 自我核准的業務驗收程式；Project Validation Profile 則是另一份可重用的工程驗證計畫，用於 Build／Test／Lint／Type Check 與 Environment Preflight。

- 預設保存於 Controller 資料目錄，不寫入使用者專案。
- 自動偵測後為 `Draft`。
- 成功執行一次為 `Verified`，三次為 `Trusted`。
- Build／Test／Validation Descriptor 變更後為 `Stale`。
- 所有 Command 都從有效 Project Path cwd 執行。
- 既有失敗會記入 Baseline；最終只阻擋新增／惡化的失敗與未完成 Acceptance。

進階使用者可在 Project Validation 對話框以 JSON 編輯 Phase／Category／Environment／Scope；編輯後會失去 Trusted 狀態，必須重新驗證。
