---
name: script-analysis-skill
description: 编剧导演技能包。包含剧本分析全链的 6 个提示词模板：角色档案、角色视觉、场景分析、道具分析、片段切分、剧本转换。
---

# 编剧导演技能包

[技能说明]
    包含从剧本到结构化数据的完整分析链，6 个提示词模板直接迁移自 waoowaoo 项目。
    每个提示词模板都是独立的 .md 文件，使用 {变量名} 占位符。

[提示词模板]
    | 文件 | 用途 | 核心变量 |
    |------|------|---------|
    | character-profile.md | 角色档案分析（选角指导） | {input}, {characters_lib_info} |
    | character-visual.md | 角色视觉描述生成 | {character_profiles} |
    | location-analysis.md | 场景资产提取 | {input}, {locations_lib_name} |
    | prop-analysis.md | 道具资产提取 | {input}, {props_lib_name} |
    | clip-split.md | 片段预分割 | {input}, {locations_lib_name}, {characters_lib_name}, {characters_introduction}, {props_lib_name} |
    | screenplay-convert.md | 剧本格式转换 | {clip_content}, {locations_lib_name}, {characters_lib_name}, {characters_introduction}, {clip_id} |

[执行流程]
    1. 角色分析（character-profile.md）→ 输出 characters.json
       ★ 输出中每个角色必须包含 voiceLine 字段（≤15字声线描述）
    2. 角色视觉（character-visual.md）→ 补充角色外貌描述到 characters.json
    3. 场景分析（location-analysis.md）→ 输出 locations.json
    4. 道具分析（prop-analysis.md）→ 输出 props.json
    5. 片段切分（clip-split.md）→ 输出 01-clips.json
    6. 剧本转换（screenplay-convert.md，逐片段）→ 输出 02-screenplay.json

[AI 调用参数]
    - temperature: 0.7（集数拆分用 0.3）
    - reasoning: true
    - reasoningEffort: high
    - 输出: 纯 JSON，禁止 markdown 标记
    - 重试: 最多 3 次，指数退避

[角色声线规则 ⭐]
    在角色分析（Step 1）时，为每个角色生成 voiceLine 字段：
    - 控制在 15 个字以内
    - 格式：性别声线 + 年龄音色 + 音质特征
    - 示例：
      "男声，中年音色，沉稳温厚带学究气"
      "女声，青年音色，清冷疏离"
      "男声，少年音色，活泼明朗"
    - 此字段将传递给视频导演，在 Seedance 2.0 生视频时作为声线参考
