---
name: art-design-skill
description: 美术总监技能包。包含角色/场景图片生成的提示词模板。
---

# 美术总监技能包

[技能说明]
    包含角色和场景图片生成所需的提示词模板，迁移自 waoowaoo 项目。

[提示词模板]
    | 文件 | 用途 | 核心变量 |
    |------|------|---------|
    | character-create.md | 角色设定图生成 | {user_input} |
    | character-regenerate.md | 角色设定图重生成 | {character_name}, {change_reason}, {current_descriptions}, {novel_text} |
    | location-create.md | 场景设定图生成 | {user_input} |
    | location-regenerate.md | 场景设定图重生成 | {location_name}, {current_descriptions} |
    | panel-image.md | 分镜图片生成 | {storyboard_text_json_input}, {source_text}, {aspect_ratio}, {style} |

[生图工具]
    默认使用 zencli-skill（贝宝2 模型 314）。
    可选使用 dreamina（即梦）。

[artStyle 后缀规则]
    生成图片时，在提示词末尾追加 artStyle 对应的风格后缀：
    - 漫画风 → ", 日式动漫风格"
    - 精致国漫 → ", 现代高质量漫画风格，动漫风格，细节丰富精致，线条锐利干净，质感饱满，超清，干净的画面风格，2D风格"
    - 日系动漫风 → ", 现代日系动漫风格，赛璐璐上色，清晰干净的线条，视觉小说CG感，高质量2D风格"
    - 真人写实 → ", 真实电影级画面质感，真实现实场景，色彩饱满通透，画面干净精致，真实感"
