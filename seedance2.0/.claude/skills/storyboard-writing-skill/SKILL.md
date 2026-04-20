---
name: storyboard-writing-skill
description: 分镜提示词 V2 生产引擎：为每个分镜生成 20 字段 JSON（含 7 条铁律 + 字段互锁 + 对白原文 + 硬切过门），字数硬上限 2000，单镜时长硬上限 15 秒（titleBar 中的秒数 ∈ {5,10,15}，禁止 16/18/20 秒）。
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
- **挂载规范 v5**：`挂载：角色：名@图片1｜场景：名@图片N｜声音：角色名声音@音频1｜本视频以@图片N为首帧`
  - 段首**不再加** `@`（直接写 `角色：`/`场景：`/`道具：`/`声音：`）；`@` 仅保留在资产引用编号处
  - 声音段只挂角色声线参考，不挂音效；格式固定 `[角色名]声音@音频N`（注意是 `@音频N` 不是 `@声音N`）
  - **变体角色（character-variant）挂载规则**：
    - **图片**：变体角色必须挂载自己的变体图片编号（如 `节度使@图片13`），**禁止**挂载主形象的图片编号（如 `马前卒@图片2`）
    - **声音**：变体角色的声音标注必须用**变体角色名** + 主形象的音频编号（如 `节度使声音@音频2`，而非 `马前卒声音@音频2`）。因为变体角色复用主形象的声线，但即梦 CLI 需要用变体角色名来标注
    - **assetRefs**：变体角色在 assetRefs 中用 `{{character:变体名}}`（如 `{{character:节度使}}`），不用主形象名
  - 当本镜 openingFrame 承接上一镜尾帧时，末尾追加 `本视频以@图片N为首帧`（N 是 assetMap 中对应 tail-frame 的编号）
  - **首帧引用判定（v3 · 基于 sceneContinuity 的 2 问决策）**：每镜必须填 `sceneContinuity` 结构化字段（见下节「首帧承接决策」），当 `sceneContinuity.inheritFromPrev === true` 时 mount **必须**追加 `本视频以@图片N为首帧`，为 false 时 mount **禁止**出现该片段。
  - 下游生视频流水线据此识别首段（无首帧引用的镜独立生成）与依赖链（有首帧引用的镜等前镜渲染完再触发）

## 首帧承接决策（sceneContinuity · v3 必填）

**问题背景**：v2 只靠 mount 字符串里有没有 `本视频以@图片N为首帧` 来判断依赖，分镜师凭经验手写，漏写就翻车（典型：shot-36/37 同场景没场景图、两镜独立生成出了两副监狱）。v3 把决策升级为结构化字段，分镜师每镜**必填** `sceneContinuity`，供下游生视频流水线识别。

### 2 问决策（分镜师写每镜时按顺序自问）

设想两镜剪完后连着播放：

**Q1 · 动作/画面连续性**
本镜的**第一秒画面**，是否由上一镜**最后一秒的最后一幕**直接开启？
（即两镜剪在一起时，中间不能有任何跳帧 / 穿帮 / 不连贯）

- YES → `inheritReason: "action-continuation"`，`inheritFromPrev: true`，**必须**承接尾帧（无论本镜 mount 里有没有场景参考图）
- NO  → 进入 Q2

**Q2 · 同场景无参考图**
本镜和上一镜是否属于**同一个物理场景**（同屋 / 同街 / 同演播室…），且本镜 mount **没有** `场景：…@图片N` 参考图？

- YES → `inheritReason: "same-scene-no-ref"`，`inheritFromPrev: true`，**必须**承接尾帧（让模型抄上一镜的背景）
- NO  → `inheritReason: "independent"`，`inheritFromPrev: false`，不承接

**前置特判**：本镜是全片/全集首镜（无上一镜）→ `inheritReason: "opening-shot"`，`inheritFromPrev: false`

### 4 枚举值（inheritReason 四选一）

| 枚举值 | 触发条件 | 是否承接 |
|---|---|---|
| `opening-shot` | 全片首镜，无上一镜 | 否 |
| `action-continuation` | 本镜首秒由上一镜末秒最后一幕直接开启（剪辑连续性刚需） | **是** |
| `same-scene-no-ref` | 同场景 + 本镜 mount 无场景参考图（背景锚定刚需） | **是** |
| `independent` | 切新场景 / 或同场景但本镜 mount 已有场景参考图 | 否 |

### sceneContinuity 字段格式

```jsonc
"sceneContinuity": {
  "inheritFromPrev": true,
  "inheritReason": "same-scene-no-ref",
  "notes": "同监狱场景，本镜 mount 无监狱参考图，承接 shot-36 尾帧以锁背景"
}
```

- `inheritFromPrev`（必填，boolean）：是否承接上一镜尾帧
- `inheritReason`（必填，string）：四个枚举值之一
- `notes`（选填，string）：一句话判断依据，便于审稿；`opening-shot` / `independent` 可省略

### 硬规则（机器校验，违反直接拒收）

```
R1（承接必标）：
  inheritFromPrev == true
  ⇒ mount 必须以 "｜本视频以@图片N为首帧" 结尾
  ⇒ @图片N 在 assetMap.images 中必须 type=='tail-frame' 且 fromShot == 上一镜 index

R2（不承接必净）：
  inheritFromPrev == false
  ⇒ mount 禁止出现 "本视频以@图片N为首帧" 子串
```

### 判断原则（纠结时的优先级）

- **宁可多承接，不可漏承接**——错承接顶多浪费一点模型泛化度，漏承接会翻车（shot-36/37 案例）
- `action-continuation` 优先于 `same-scene-no-ref`——前者是剪辑刚需，后者是背景兜底
- **`reference` 字段里提到的风格参照不算场景参考图**——只有 `mount` 里的 `场景：…@图片N` 才计入 Q2 判定
- **mainPrompt 正文规范 v3**：角色 / 场景 / 道具**全部直接写名字**，不再用 `{{character:名}}` / `{{scene:名}}` / `{{prop:名}}` 包裹
- assetRefs 仍须列出完整的 `{{character:名}}` / `{{scene:名}}` / `{{prop:名}}` 标签（用于下游索引）
- 首镜 `connection` 必须为空字符串；末镜 `transition` 必须为空
- **🚫 版权红线**：所有 18 个 prompt 字段（含 reference，它也进送审 prompt）禁止出现知名作品名（《三国演义》《大闹天宫》《葫芦兄弟》《没头脑和不高兴》《中华勤学故事》《黑猫警长》《英雄联盟》《马男波杰克》《脱口秀大会》《小黄人》《火影》《海贼王》等）、品牌/节目名（BBC / TED / CNN / CCTV / Discovery / 国家地理等）、知名 IP 角色名（小黄人 / 刀妹 / 孙悟空 / 哆啦A梦等）。改用"时代+画种+题材"抽象风格描述（如"80年代国产二维手绘厚涂历史纪录风"）

## 首帧资产物理约定
- 前镜尾帧截图路径：`projects/<项目名>/outputs/<episode>/tail-frames/tail-shot-{前镜index:02d}.jpg`
- 前镜视频渲染完成后由流水线自动截取末帧保存
- 本镜 mount 中 `本视频以@图片N为首帧` 的 `@图片N` 实际指向该 tail-frame 文件

## 在 seedance2.0 中的归档
- 每镜一个文件：`projects/<项目名>/outputs/ep{N}/06-shots/shot-{NN}.json`（NN = index 补零）
- 逐镜生成时导演按顺序串行调用（当前镜的 `previousContext` 来自上一镜实际生成结果）
