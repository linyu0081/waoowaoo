---
name: video-production-skill
description: 视频导演技能包。定义分镜图生成、视频生成（seedance模式/其他模式）、配音合成、口型同步的标准流程。seedance模式下由ai-video-director规划、video-director执行。
---

# 视频导演技能包

[技能说明]
    定义从分镜数据到视频成片的完整生产流程。
    
    seedance 模式（默认）：
        - 规划阶段由 ai-video-director 执行（见 ai-video-director-skill/SKILL.md）
        - 执行阶段由 video-director 执行（调用 zencli-skill）
    其他模式：
        - 全部由 video-director 执行（调用 zencli-skill / dreamina-video-skill）
    
    ⭐ 提示词方法论：video-production-skill/seedance-prompt-methodology.md
    该文件包含 Seedance 2.0 提示词的完整方法论（第一性原则、@引用语法、提示词结构、
    运镜词汇、动作词汇、12类型写作方法论、超写实大片专项、画面质量后缀等），
    编写 05-seedance-prompt.json 时必须遵循。

[画面质量后缀（全局规则）]
    所有视频提示词的末尾必须统一追加以下固定文案：
    "差异化建模，画面稳定流畅，无闪烁无重影，人物结构正常，动作自然不僵硬，4K 高清细节清晰。
    禁止：水印、字幕、重复的模型。"
    - 追加在"电影级真实画质"等风格描述之后
    - 所有 Shot / Segment 统一使用，固定不变
    - 与超写实大片模式的负向标签可叠加

[生成流程]

    ═══════════════════════════════════════════
    ▶ seedance 模式（默认，Q3=seedance）
    ═══════════════════════════════════════════

    Step 1: [可选] 分镜图片生成（已有则跳过）
        - 逐镜头或宫格模式
        - 提示词来源：art-design-skill/prompts/panel-image.md
        - 参考图：角色设定图 + 场景设定图
        - 工具：zencli generate image（默认）
        - 保存：outputs/<集数>/images/
        - 可选宫格模式：按 Clip 生成宫格分镜图 → AI 放大为独立分镜图

    Step 2: AI视频导演规划（由 ai-video-director 执行）
        ⚠️ 详细规范见 ai-video-director-skill/SKILL.md

        Phase 1: 视频分段规划（含时长重估）
            - 按台词语速精确计算：正常3-4字/秒、激动5-6字/秒、缓慢2字/秒
            - 动作时长：2-2.5秒/动作 + 安全区1s
            - 尽量贴满15s合并，硬切不强制分段（段内用"镜头硬切至"描述）
            - 只在 Clip 边界强制分段
            - 按 ≤15s 切段（长台词独占段允许略超）

        Phase 2: 已有资产引用分析
            - 复用已有角色图/场景图/分镜图，不额外生图
            - 跨段复用分镜图确保视觉一致性

        Phase 3: 提示词生成
            - 按 seedance-prompt-methodology.md 方法论
            - 输出 05-seedance-prompt.json → 提交用户确认

    Step 3: 视频生成执行（由 video-director 执行）
        - 提示词来源：05-seedance-prompt.json 中的 segments[].prompt
        - 参考图：segments[].reference_images 对应 asset_mapping 中的文件
        - 逐段执行，每段需用户确认后才生成
        - 按 segment 顺序生成，命名 SEG-01.mp4, SEG-02.mp4...
        - ⚠️ 每段生成后 ffmpeg 提取末帧截图（供下段衔接）
        - 生成引擎默认 zencli（Zen-SD2.0 SubjectToVideo + --enable-sound）

        ★ @图片N 重编号规则：
            按参考图传入顺序重新编号（第1张=@图片1，第2张=@图片2...）

    Step 4: [可选] 分镜宫格图（用户要求时执行）
        python3 <video-storyboard-skill>/scripts/storyboard.py \
          outputs/<集数>/videos/<视频文件> --grid 3x3 --timestamp --index

    Step 5: [可选] 拼接成片
        ffmpeg 按 segment 顺序合并所有视频

    ═══════════════════════════════════════════
    ▶ 其他模式（Q3=其他）
    ═══════════════════════════════════════════

    Step 1: 分镜图片生成
        - 逐镜头执行
        - 提示词来源：art-design-skill/prompts/panel-image.md
        - 工具：zencli generate image

    Step 2: 视频生成（逐镜头）
        - 提示词来源：03-storyboard.json 中的 video_prompt
        - ★ 声线嵌入：在提示词中嵌入角色的 voiceLine
        - 引擎：zencli generate video --model 18 --mode SubjectToVideo
        - 轮询 → 下载 → 命名 P<N>-S<M>.mp4

    Step 3: 配音合成
        - 读取 04-voice-lines.json
        - 逐台词调用 TTS
        - 保存到 outputs/<集数>/audio/

    Step 4: 口型同步
        video + audio → lip sync

    Step 5: [可选] 拼接成片
        ffmpeg 合并视频+配音

[seedance 模式 vs 其他模式]
    
    seedance 模式（默认，Q3=seedance）：
        Step 1（可选）→ Step 2（ai-video-director）→ Step 3（video-director 执行）
        - ai-video-director 负责分段规划+时长重估+引用分析+提示词生成
        - video-director 读取 05-seedance-prompt.json 执行生成
        - 按 segment 分段生成（每段 ≤15s，可含多个 panel）
        - 使用 sync_video_prompt（含角色名+台词，支持口型同步）
        - 音画同出，无需额外配音
    
    其他模式（Q3=其他）：
        Step 1 → Step 2（逐镜头视频）→ Step 3（配音）→ Step 4（口型）
        - video-director 全权负责
        - 逐 panel 生成（每镜头独立一段视频）
        - 使用 video_prompt（年龄段+性别替代角色名）
        - 分离配音 + 口型同步

[Seedance 2.0 音画同出适配]
    - seedance 模式默认开启音画同出（--enable-sound），视频自带音效和对话
    - 提示词中声线描述写在角色名后括号内，模型会参考生成对应的语音
    - 其他模式不开启 --enable-sound，走分离配音流程

[manifest.json 更新]
    每次生成新资产后，更新 manifest.json：
    - 新图片 → panels[].image
    - 新视频 → panels[].video / segments[].video
    - 宫格图 → panels[].storyboardGrid
    - 提示词 → 05-seedance-prompt.json 路径
    - 统计更新 → stats.totalPanels, totalVideos, totalDuration
