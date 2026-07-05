id: adaptive-auto-workflow
name: Adaptive Auto Workflow
description: 'AI Workflow Controller loop: AI generates short task prompts -> Qwen/OpenCode executes them with real project edits/tests -> AI review plus Python validation gate. Failures retry from prompt generation in the same agent session with concise feedback.'
kind: system
active: true
protected: true
deletable: false
skillRoot: .ai-workflow
promptRoot: steps/
created_at: '2026-07-04T00:00:00+08:00'
updated_at: '2026-07-05T00:00:00+08:00'
steps:
- contract: contracts/adaptive-auto-workflow/generate_task_prompts.yaml
- contract: contracts/adaptive-auto-workflow/auto_generation.yaml
- contract: contracts/adaptive-auto-workflow/ai_review.yaml
