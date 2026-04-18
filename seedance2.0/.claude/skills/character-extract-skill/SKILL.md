---
name: character-extract-skill
description: 从剧本中提取全部有名有姓的角色资产，生成角色卡 + 150-220 字四宫格角色设计图 AI 提示词。
---

# character-extract-skill — 角色提取引擎

## 调用方式
system = `prompt.md`，user = 剧本全文 markdown（可选追加角色档案/风格预设）。

## 输出
严格 JSON 数组，不带 markdown 代码块。每个角色字段：
`name / role / aliases / appearance / clothing / personality / colorPalette / visualAnchor / aiPrompt`

## 在 seedance2.0 中的归档
- 合并到 `projects/<项目名>/assets/characters.json`（按 `name` 去重）
- 本集新增角色名写入 `projects/<项目名>/outputs/ep{N}/04-new-assets.json.characters`
- 每条角色记录新增字段 `firstAppearInEpisode: "ep{N}"`
