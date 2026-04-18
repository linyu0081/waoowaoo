---
name: script-review-skill
description: 微短剧剧本质检（七维度百分制）：输入剧本 + 规划 + 配置，输出 JSON 审核报告（含 problems/suggestions/priority/rewriteExample/surgeryTable）。
---

# script-review-skill — 剧本质检员

## 调用方式
把 `prompt.md` 作为 system prompt，然后把以下 JSON 作为 user 消息：

```json
{
  "mode": "domestic|overseas",
  "duration": "2分钟",
  "inputSummary": "剧情描述",
  "scriptBody": "<剧本全文 md>",
  "planning": "<规划全文，可选>",
  "reviewThreshold": 62
}
```

## 七维度（满分 100）
| 维度 | 满分 |
|------|------|
| 故事推进 | 20 |
| 角色与情感 | 15 |
| 对话质量 | 15 |
| 节奏控制 | 15 |
| 追读力 | 15 |
| 去AI味 | 10 |
| 格式规范 | 10 |

- 总分 ≥ reviewThreshold（默认 62）→ `status: "passed"`
- < 阈值 → `status: "failed"` 并提供完整的 `problems`/`suggestions`/`priority`/`rewriteExample`/`surgeryTable`

## 输出
严格 JSON（无 markdown 包裹），字段：`score` / `status` / `overallVerdict` / `dimensions[]` / `problems[]` / `suggestions[]` / `priority[]` / `rewriteExample` / `surgeryTable[]` / `revisionPath[]`。详细字段约束见 `prompt.md` 的"输出合约"章节。

## 在 seedance2.0 中的归档
- `projects/<项目名>/outputs/ep{N}/03-review.json`（覆盖写）
- 保留历史：`03-review.v{n}.json`
- 若 `status === "failed"`，导演将本 JSON 的 problems/suggestions/priority 拼入修订提示词，回送 `script-planning-skill` 重新规划。
