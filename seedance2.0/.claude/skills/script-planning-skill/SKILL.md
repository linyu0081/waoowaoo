---
name: script-planning-skill
description: 微短剧剧本规划（第一轮）：根据灵感/参数输入，输出方向确认 + 三幕骨架 + 角色档案 + 分集提纲的结构化规划文本。
---

# script-planning-skill — 剧本规划师

## 调用方式
把 `prompt.md` 作为 system prompt，再把以下 JSON 作为 user 消息发送给大模型：

```json
{
  "mode": "domestic|overseas",
  "duration": "30s|1min|2min|3min",
  "genres": ["主题材", "副题材"],
  "audience": "male|female|all",
  "tone": "爽燃|甜虐|搞笑|暗黑|温情",
  "ending": "大团圆|开放式|反转式|悲剧",
  "episodes": 1,
  "inputSummary": "灵感一句话",
  "stylePreset": "可选",
  "customStyle": "可选"
}
```

> 缺省字段模型会自动按 inputSummary 推断；mode 缺省按 `domestic` 处理。

## 输出
规划正文（纯文本，非 JSON），包含以下章节：
一、方向确认 · 二、故事核心 · 三、角色档案 · 四、关系矩阵 · 五、三幕结构 · 六、分集提纲 · 七、爽点分布总览 · 八、合规自查（国内模式）

## 在 seedance2.0 中的归档
- 首次产出 → `projects/<项目名>/outputs/ep{N}/01-planning.txt`
- 质检 FAIL 回到规划阶段时 → `01-planning.v{n}.txt`（保留历史版本）
