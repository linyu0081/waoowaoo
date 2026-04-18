---
name: storyboard-writing-skill
description: 分镜提示词 V2 生产引擎：为每个分镜生成 20 字段 JSON（含 7 条铁律 + 字段互锁 + 对白原文 + 硬切过门），字数硬上限 2000。
---

# storyboard-writing-skill — 分镜编写（V2 20 字段）

## 调用方式
system = `prompt.md`，user = 每镜 JSON：

```json
{
  "currentShot": { "scriptContent": "", "title": "", "shotType": "D", "keyBeats": ["..."], "index": 0, "totalShots": 8 },
  "previousShotBrief": { "title": "", "shotType": "", "keyBeats": ["..."] },
  "nextShotBrief": { "title": "", "shotType": "", "keyBeats": ["..."] },
  "storyOverview": { "coreConflict": "", "protagonistMotivation": "", "informationGain": "", "fiveActs": ["..."], "sceneQuality": "" },
  "assets": { "characters": [], "scenes": [], "props": [] },
  "previousContext": { "lastClosingFrame": "", "lastTransition": "", "lastShotSummary": "", "lastScriptTail": "" }
}
```

首镜 `previousShotBrief` 与 `previousContext` 为 `null`；末镜 `nextShotBrief` 为 `null`。

## 输出
20 字段严格 JSON：
`shotType / titleBar / mount / camera / openingFrame / closingFrame / connection / transition / dualAnchor / mainPrompt / compulsoryDeclaration / mustShow / qualityRoute / imagingStyle / qualityBaseline / reference / microExpressions / nailLines / e15 / assetRefs`

## 字段互锁（四重锁定）
camera 构图锚点 ⇄ mustShow ⇄ reference 稳帧点 ⇄ nailLines 第 1-3 行 → 同一关键画面。
落幅接力物必须同时出现在 closingFrame + mustShow + nailLines 第 4 行。

## 硬约束
- 整镜字数 ≤ 2000
- compulsoryDeclaration 与 qualityBaseline 必须原文输出固定文本
- 剧本对白必须用 `**角色名**："原文一字不改"` 嵌入 mainPrompt
- 全片硬切，禁止柔和过渡
- 资产引用语法：`{{character:名}}` / `{{scene:名}}` / `{{prop:名}}`
- 首镜 `connection` 必须为空字符串；末镜 `transition` 必须为空

## 在 seedance2.0 中的归档
- 每镜一个文件：`projects/<项目名>/outputs/ep{N}/06-shots/shot-{NN}.json`（NN = index 补零）
- 逐镜生成时导演按顺序串行调用（当前镜的 `previousContext` 来自上一镜实际生成结果）
