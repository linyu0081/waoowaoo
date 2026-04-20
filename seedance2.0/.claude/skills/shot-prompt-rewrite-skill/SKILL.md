---
name: shot-prompt-rewrite-skill
description: 分镜提示词改写技能（视频审核不通过时专用）：输入审核失败的 shot JSON + 失败日志（pre-TNS / final-generation-fail），输出已清洗+瘦身+风格锁定的 mainPrompt，可按精简参数（slim）直接重新推池。不改剧情、不改台词、不动挂载/相机/强制声明。
---

# shot-prompt-rewrite-skill — 分镜提示词改写员（审核改写专用）

## 适用场景

仅在分镜视频**生成失败**、需要改写 `mainPrompt` 重新提交时调用。典型场景：

| 失败类型 | 调度器日志特征 | 典型根因 |
|---|---|---|
| **pre-TNS check fail** | `❌ shot-XX pre-check 未通过` | 文案命中敏感词/IP 直呼/风控组合 |
| **final generation fail** | `❌ shot-XX failed: generation failed` | 信息密度过高、描述过长、同义叠词堆叠、模型渲染崩 |
| **slim-retry 仍失败** | 候选池 `autoRetryCount ≥ 2` | mainPrompt 结构性问题，需要人工/agent 改写 |

**不要**用此 skill 处理：
- 首次生成（走 `storyboard-writing-skill`）
- 剧本/台词问题（走 `script-review-skill`）
- 时长超标（走调度器 hard-gate，本 skill 不负责）

## 调用方式

把 `prompt.md` 作为 system prompt，然后把以下 JSON 作为 user 消息：

```json
{
  "projectRoot": "projects/<项目名>",
  "episode": "ep01",
  "shotId": "64",
  "shotJsonPath": "projects/<项目名>/outputs/ep01/06-shots/shot-64.json",
  "shotJson": { /* 当前 shot 文件全量 */ },
  "failureType": "pre-TNS | final-generation-fail | slim-retry-exhausted",
  "failureLog": "原始日志行，含 cost-log + reason",
  "retryHistory": [
    {"ts": "2026-04-20T06:15:10", "model": "seedance2.0fast", "promptMode": "slim", "reason": "text safety check fail"}
  ]
}
```

说明：
- 本 skill **只处理通用审核问题**（敏感词、IP 直呼、预兆玄学词、数值标签、描述密度爆炸、多物件堆叠等），不涉及任何特定项目的画风模板。
- `mainPrompt` 开头的起手句/画风描述句由 skill 原样保留，不重写。若本项目有自定义画风规范，应由调用方在调用前自行完成画风对齐。

## 输出合约

严格 JSON（无 markdown 包裹），字段：

```json
{
  "shotId": "64",
  "status": "rewritten | abort",
  "verdict": "一句话诊断",
  "detectedRisks": [
    {"category": "IP 直呼", "hit": "<原词>", "fixedTo": "<改写后>"},
    {"category": "预兆词", "hit": "<原词>", "fixedTo": "删除"}
  ],
  "rewrittenFields": {
    "mainPrompt": "<改写后的 mainPrompt 全文（起手句原样保留）>"
  },
  "preservedFields": ["titleBar", "mount", "camera", "compulsoryDeclaration", "qualityBaseline", "openingFrame", "closingFrame", "connection", "transition", "assetRefs", "dialogue"],
  "submitConfig": {
    "model": "seedance2.0fast",
    "promptMode": "slim",
    "pinned": true,
    "note": "mainPrompt-rewritten-<ISO时间>"
  },
  "checklistPassed": ["起手句原样", "敏感词清洗", "单段动词≤3", "长度≤450字", "台词原文保留", "挂载未动"]
}
```

- 当 `status === "rewritten"`，调用方直接把 `rewrittenFields.mainPrompt` 覆盖写回 `shotJsonPath`，并按 `submitConfig` 进候选池。
- 当 `status === "abort"`（剧情本身带硬伤，改写救不回），返回 `verdict` 说明原因，交回用户手动定夺。

## 在 seedance2.0 中的归档位置

- shot 原文件：`projects/<项目名>/outputs/<episode>/06-shots/shot-<id>.json`
- 改写前自动备份：`shot-<id>.json.bak.mainprompt-rewrite-<YYYYMMDD>`
- 审核/改写日志归档：`projects/<项目名>/outputs/<episode>/09-rewrite/shot-<id>.rewrite.json`（保留输出合约全量，便于复盘）
- 若本项目存在自定义画风规范（例如 `projects/<项目名>/docs/REWRITE-SPEC-*.md`），由调用方负责画风对齐，本 skill 不读取该文件。

## 与其他 skill 的关系

```
storyboard-writing-skill ──首次生成──► shot 文件
                                        │
                                        ▼
                              video-scheduler（提交 API）
                                        │ 失败
                                        ▼
                          shot-prompt-rewrite-skill ◄── 本 skill
                                        │
                                        ▼
                              候选池（pinned=true, slim）
```
