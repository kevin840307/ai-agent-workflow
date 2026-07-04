# Workflow Metadata

Workflow metadata 寫在：

```text
data/ai-workflow/workflows/*.workflow
<project>/.ai-workflow/workflows/*.workflow
```

## 重要欄位

```yaml
id: adaptive-auto-workflow
name: Adaptive Auto Workflow
kind: system
protected: true
deletable: false
active: false
```

| 欄位 | 說明 |
|---|---|
| `id` | workflow 唯一代號，UI / CLI 使用這個 id 執行 |
| `name` | UI 顯示名稱 |
| `description` | UI 顯示描述 |
| `kind` | `system` 會顯示在 System 區塊；其他值視為 custom / asset |
| `protected` | `true` 代表 UI 唯讀，不允許 Save / Reset / Add Step / Edit Step |
| `deletable` | `false` 代表 UI 和 API 不允許刪除 |
| `active` | 顯示狀態；不代表只能執行 active workflow |
| `steps` | step contract 引用清單 |

## System Workflow 行為

符合任一條件就會被視為 read-only system workflow：

- `id: system-controlled-qwen`
- `kind: system`
- `protected: true`

行為：

- Workflow Designer 左側會顯示在 **System** 區塊。
- Runner workflow selector 仍可選擇執行。
- UI 不允許直接修改。
- UI 不允許刪除。
- 可以 Duplicate 成 Custom Draft 後再修改。

## Custom Workflow 行為

```yaml
kind: custom
protected: false
deletable: true
```

行為：

- 顯示在 **Custom** 區塊。
- 可編輯、可儲存、可刪除。
- 可透過 Workflow Designer JSON 或 UI 編輯。

## 建議原則

### 內建流程

公司或平台內建流程建議：

```yaml
kind: system
protected: true
deletable: false
```

### 使用者草稿

使用者自己建立或複製後修改的流程建議：

```yaml
kind: custom
protected: false
deletable: true
```

### 不建議

不要只改 `kind: system`，但保留：

```yaml
protected: false
deletable: true
```

這會造成語意不一致。系統會以安全為優先，將 system workflow 視為 protected / non-deletable。
