---
name: storyboard-planning-skill
description: 分镜大纲规划：基于剧本+时长+资产，输出 coreConflict/protagonistMotivation/fiveActs/shots 的分镜大纲 JSON。单镜时长硬上限 15 秒，按每镜 15 秒估算镜数，禁止规划 >15 秒的单镜。
---

# storyboard-planning-skill — 分镜规划

## 调用方式
system = `prompt.md`，user = JSON：

```json
{
  "scriptBody": "<02-script.md 全文>",
  "duration": "2分钟",
  "assets": "<projects/<项目名>/assets/{characters,scenes,props}.json 合并后的字符串>"
}
```

## 分镜数量
每镜约 15 秒：30s→2 / 1min→4 / 2min→8 / 3min→12 / 5min→20。

## 输出
严格 JSON：
```json
{
  "coreConflict": "",
  "protagonistMotivation": "",
  "informationGain": "",
  "fiveActs": ["...", "...", "...", "...", "..."],
  "sceneQuality": "电影感，写实，8k超高清",
  "totalShots": 8,
  "shots": [
    { "index": 0, "title": "", "scriptContent": "<剧本原文摘录>", "shotType": "D", "keyBeats": ["动作1", "动作2"] }
  ]
}
```

## 在 seedance2.0 中的归档
- `projects/<项目名>/outputs/ep{N}/05-storyboard-plan.json`
- 生成后导演询问用户确认，确认后进入 storyboard-writing-skill 逐镜生成
