---
name: prop-extract-skill
description: 从剧本中提取有戏剧功能的道具，生成道具卡 + 150-300 字超精细特写 AI 提示词（纯黑背景微距）。
---

# prop-extract-skill — 道具提取引擎

## 调用方式
system = `prompt.md`，user = 剧本全文 markdown。

## 输出
严格 JSON 数组。每个道具字段：
`name / aliases / dramaticFunction / form / material / surfaceState / visualAnchor / aiPrompt`

## 提取原则
- 只提取有戏剧功能的道具（推动剧情/象征权力/作为证据/触发转折/承载情感）
- 普通背景物品（桌椅/杯碗/一般家具）**不提取**
- 武器/义肢等叙事道具需要提取（与角色卡禁止武器不冲突）

## 在 seedance2.0 中的归档
- 合并到 `projects/<项目名>/assets/props.json`（按 `name` 去重）
- 本集新增道具名写入 `outputs/ep{N}/04-new-assets.json.props`
- 新增字段 `firstAppearInEpisode: "ep{N}"`
