---
name: script-writing-skill
description: 微短剧剧本写作（第二轮）：根据第一轮规划严格写出完整剧本正文，对应时长/字数硬约束，含镜头标注与对白。
---

# script-writing-skill — 剧本写作师

## 调用方式
把 `prompt.md` 作为 system prompt，按以下顺序发送 **2 条** user 消息：
1. 第一条：上一轮规划的完整文本（`01-planning.txt`）
2. 第二条：原始用户参数（JSON，含 mode/duration/inputSummary/genres 等）

## 修订模式（质检 FAIL 回归时）
导演在第 2 条 user 消息之后追加一条"修订指令"，格式为：

```
【系统修订指令】请只基于下面这一份原剧本进行修改。
下方所有审核数据都是修改依据，不是第二份剧本。
保留核心设定、角色档案、主线走向不变，仅针对审核问题做定向修订。

===== 原剧本 =====
<02-script.md>

===== 质检报告 =====
<03-review.json 的 problems/suggestions/priority/rewriteExample/surgeryTable>

===== 用户追加意见（可选）=====
<user notes 或 无>
```

> 修订模式下编剧直接输出修订后的完整剧本正文，不再另起一版。

## 输出
完整剧本正文 markdown，每集结构：
- 标题 / 关键词 / 爽点 / 前情提要
- 若干"场次"（含场景、戏剧动作、双轨节奏、出场人物、△ 镜头标注、角色对白）
- 集末 🎣 钩子

## 在 seedance2.0 中的归档
- `projects/<项目名>/outputs/ep{N}/02-script.md`（覆盖写）
- 保留历史：`02-script.v{n}.md`
