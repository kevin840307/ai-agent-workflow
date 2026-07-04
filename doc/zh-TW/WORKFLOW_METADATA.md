# Workflow Metadata

Workflow metadata 放在：

```text
data/ai-workflow/workflows/*.workflow
<project>/.ai-workflow/workflows/*.workflow
```

## 重要欄位

```yaml
id: adaptive-auto-workflow
name: Adaptive Auto Workflow
description: Simple generate / review / validation loop
kind: system
protected: true
deletable: false
active: false
```

| 欄位 | 行為 |
|---|---|
| `id` | UI / API / CLI 使用的穩定 workflow id |
| `name` | workflow 清單顯示名稱 |
| `description` | 詳細說明；左側 compact 清單不顯示 |
| `kind` | `system` 會顯示在 System 清單 |
| `protected` | `true` 代表 UI 與 API 都不可直接編輯 |
| `deletable` | `false` 代表 UI 與 API 都不可刪除 |
| `active` | 顯示狀態；inactive 仍可列出與 duplicate |
| `steps` | step contract 引用清單 |

## System Workflow 行為

符合任一條件就視為 read-only：

- `id: system-controlled-qwen`
- `kind: system`
- `protected: true`
- destructive operation 時 `deletable: false`

System workflow 會顯示在 System 區塊，可以查看、duplicate，但不能直接編輯或刪除。

## Custom Workflow 行為

Custom workflow 預設可編輯；若 metadata 設成 protected，也會以唯讀方式顯示。
