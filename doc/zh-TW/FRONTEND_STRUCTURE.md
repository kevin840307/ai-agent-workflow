# 前端結構

前端是 FastAPI 提供的 static HTML/CSS/JS。設計原則是保留穩定的 DOM id 與 API endpoint，同時把功能拆成小模組，避免 `workflow-designer.js` 再次變成大型單檔。

```text
index.html                  # workflow runner + chat page
workflow-designer.html      # workflow 設定頁
ai-workflow-assets.html     # .ai-workflow asset library page
styles.css                  # CSS entry, imports css/*

css/
  tokens.css
  layout.css
  projects.css
  header.css
  workflow-runner.css
  workflow-designer.css
  modal.css
  responsive.css

js/
  main.js                   # page router entry
  core/                     # api/context/dom/state/storage
  shared/sidebar.js         # runner/designer 共用 sidebar behavior
  components/sidebar.js     # 舊 sidebar path 的 compatibility facade
  features/                 # runner/chat/config/runs/artifacts modules
  pages/
    workflow-designer.js             # thin page entry
    workflow-designer/
      controller.js                  # page coordination
      layout-renderer.js             # sidebar and top-level labels
      step-settings-renderer.js      # step settings UI
      template-editor.js             # markdown/template editor behavior
      import-export.js               # workflow import/export helpers
      function-catalog.js            # Python function selector helpers
      asset-tools.js                 # asset shortcut utilities
      model.js                       # workflow model helpers
      utils.js                       # escaping/toast/shared helpers
    ai-workflow-assets.js
    ai-workflow-assets/
      asset-manager.js
```

## Workflow Designer sidebar

- System 與 Custom workflow 共用同一個垂直 scroll area。
- 不使用水平卷軸；workflow 名稱超出時用 `...` 省略。
- 左側 workflow item 只顯示名稱，不顯示 description、step count 或 badge。

## Topbar actions

`Assets` 與 `+ New Workflow` 放在同一個 action group 內，視覺上應像同一組操作，而不是兩個分離按鈕。
