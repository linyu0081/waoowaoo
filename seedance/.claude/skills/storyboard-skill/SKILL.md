---
name: storyboard-skill
description: 分镜师技能包。包含 4 阶段分镜的提示词模板：分镜规划、摄影设计、演技指导、分镜细化、台词分析。
---

# 分镜师技能包

[技能说明]
    包含 4 阶段分镜流程和台词分析的提示词模板，迁移自 waoowaoo 项目。

[提示词模板]
    | 文件 | Phase | 核心变量 |
    |------|-------|---------|
    | storyboard-plan.md | Phase1 分镜规划 | {clip_json}, {clip_content}, {characters_lib_name}, {locations_lib_name}, {characters_introduction}, {characters_appearance_list}, {characters_full_description}, {props_description} |
    | cinematography.md | Phase2a 摄影设计 | {panels_json}, {panel_count}, {locations_description}, {characters_info}, {props_description} |
    | acting-direction.md | Phase2b 演技指导 | {panels_json}, {panel_count}, {characters_info} |
    | storyboard-detail.md | Phase3 分镜细化 | {panels_json}, {characters_age_gender}, {locations_description}, {props_description} |
    | voice-analysis.md | 台词分析 | {input}, {characters_lib_name}, {characters_introduction}, {storyboard_json} |

[执行顺序]
    Phase1（分镜规划）
    → Phase2a（摄影设计）+ Phase2b（演技指导）可并行
    → Phase3（分镜细化，依赖 Phase2a + Phase2b）
    → 台词分析（依赖 Phase3）

[关键规则]
    - 每 15 个字符 ≈ 1 个镜头
    - video_prompt 用「年龄段+性别」替代角色名
    - source_text 必填，不得为空
    - JSON 字符串值中引号统一替换为「」
