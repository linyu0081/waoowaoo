---
name: scene-extract-skill
description: 从剧本中提取全部有视觉描写的场景，生成场景卡 + 150-220 字空镜 AI 提示词（严禁人物）。
---

# scene-extract-skill — 场景提取引擎

## 调用方式
system = `prompt.md`，user = 剧本全文 markdown。

## 输出
严格 JSON 数组。每个场景字段：
`name / aliases / timeOfDay / atmosphere / materials / landmarks / colorTemperature / visualAnchor / aiPrompt`

## 在 seedance2.0 中的归档
- 合并到 `projects/<项目名>/assets/scenes.json`（按 `name` 去重，同名不同时间段合并）
- 本集新增场景名写入 `outputs/ep{N}/04-new-assets.json.scenes`
- 新增字段 `firstAppearInEpisode: "ep{N}"`
