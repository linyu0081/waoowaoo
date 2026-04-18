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
- **挂载规范 v4**：`挂载：角色：名@图片1｜场景：名@图片N｜声音：角色名声音@声音1｜本视频以@图片N为首帧`
  - 段首**不再加** `@`（直接写 `角色：`/`场景：`/`道具：`/`声音：`）；`@` 仅保留在资产引用编号处
  - 声音段只挂角色声线参考，不挂音效；格式固定 `[角色名]声音@声音N`
  - 当本镜 openingFrame 承接上一镜尾帧时，末尾追加 `本视频以@图片N为首帧`（N 是本镜最后一个图片编号）
  - 下游生视频流水线据此识别首段（无首帧引用的镜独立生成）与依赖链（有首帧引用的镜等前镜渲染完再触发）
- **mainPrompt 正文规范 v3**：角色 / 场景 / 道具**全部直接写名字**，不再用 `{{character:名}}` / `{{scene:名}}` / `{{prop:名}}` 包裹
- assetRefs 仍须列出完整的 `{{character:名}}` / `{{scene:名}}` / `{{prop:名}}` 标签（用于下游索引）
- 首镜 `connection` 必须为空字符串；末镜 `transition` 必须为空

## 首帧资产物理约定
- 前镜尾帧截图路径：`projects/<项目名>/outputs/<episode>/tail-frames/tail-shot-{前镜index:02d}.jpg`
- 前镜视频渲染完成后由流水线自动截取末帧保存
- 本镜 mount 中 `本视频以@图片N为首帧` 的 `@图片N` 实际指向该 tail-frame 文件

## 在 seedance2.0 中的归档
- 每镜一个文件：`projects/<项目名>/outputs/ep{N}/06-shots/shot-{NN}.json`（NN = index 补零）
- 逐镜生成时导演按顺序串行调用（当前镜的 `previousContext` 来自上一镜实际生成结果）
