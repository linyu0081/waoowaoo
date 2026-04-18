---
name: character-extract-skill
description: 从剧本中提取全部有名有姓的角色资产，生成角色卡 + 150-220 字四宫格角色设计图 AI 提示词；支持同一角色的"年龄段 / 穿搭 / COS / 形态"变体关联。
---

# character-extract-skill — 角色提取引擎

## 调用方式
system = `prompt.md`，user = 剧本全文 markdown（可选追加角色档案/风格预设）。

## 输出
严格 JSON 数组，不带 markdown 代码块。每个角色字段：

**主角色**：
`name / role / aliases / appearance / clothing / personality / colorPalette / visualAnchor / aiPrompt`

**变体**（同主角色但不同年龄段/穿搭/COS/形态）：
在主角色字段基础上额外包含：
- `baseCharacter`: 主角色的 name（必填，必须与顶层某个主角色 name 一致）
- `variantType`: 变体类型（童年 / 老年 / 黄袍加身 / 扮演黑猫警长 / Lv.2觉醒 ...）

> 变体 `aiPrompt` 强制以 "参考上传图片角色，生成……" 开头，字数 80-180 字，只描写与主角色的差异。

## 在 seedance2.0 中的归档
- 合并到 `projects/<项目名>/assets/characters.json`（按 `name` 去重，主角色与变体都作为顶层条目存在）
- 本集新增角色名写入 `projects/<项目名>/outputs/ep{N}/04-new-assets.json.characters`
- 每条角色记录新增字段 `firstAppearInEpisode: "ep{N}"`

## 生图阶段的配合约定
美术指导（art-director）在调用 workrally-skill 生图时必须：
1. **先**生成所有"主角色"的四宫格图（不含 baseCharacter 字段的角色）
2. **再**为每个"变体"生成图，把其 `baseCharacter` 指向的主角色图作为参考图一并上传
3. 文件命名：主角色 `char-<name>.png`；变体 `char-<name>.png`（`name` 已含"·变体标签"）
