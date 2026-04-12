---
name: video-production-skill
description: 视频导演技能包。定义分镜图生成、即梦提示词生成、视频生成、配音合成、口型同步的标准流程。
---

# 视频导演技能包

[技能说明]
    定义从分镜数据到视频成片的完整生产流程。
    实际生图/生视频调用由 zencli-skill 或 dreamina-video-skill 承载。

[生成流程]

    Step 1: 分镜图片生成
        - 逐镜头执行
        - 提示词来源：art-design-skill/prompts/panel-image.md
        - 参考图：角色设定图 + 场景设定图
        - 工具：zencli generate image（默认）
        - 保存：outputs/<集数>/images/P<N>-S<M>.png
        - 可选：按 Clip 生成宫格分镜图（grid-ep01-clipNNN.jpg），再 AI 放大为独立分镜图

    Step 2: 即梦提示词生成（Seedance Prompt）
        ⚠️ 本步骤在 Step 1 完成后、Step 3 视频生成前执行。
        
        目的：根据 03-storyboard.json 中的分镜数据，按即梦单视频最长15秒的限制，
              反推视频分段，生成结构化的 05-seedance-prompt.json。
        
        输入：
            - 03-storyboard.json（分镜数据，含 sync_video_prompt、camera_move、duration_sec）
            - assets/characters.json（角色声线 voiceLine）
            - assets/images/（角色参考图、场景参考图）
            - outputs/<集数>/images/（分镜关键帧图）
        
        生成规则：
            1. 遍历所有 panel，按顺序累加 duration_sec
            2. 当累计超过 15 秒时在上一个 panel 处切断，开始新段
            3. 有台词的 panel 优先独占一段（口型同步需求）
            4. 动作连贯的相邻 panel 尽量合并（如正反打对话）
        
        输出结构（05-seedance-prompt.json）：
            {
              "asset_mapping": {
                "fixed_assets": [
                  { "ref": "@图片1", "type": "人物参考", "asset": "角色名（文件名）", "voice": "声线", "file": "路径" },
                  { "ref": "@图片N", "type": "场景参考", "asset": "场景名（文件名）", "voice": "—", "file": "路径" }
                ],
                "panel_assets": [
                  { "ref": "@图片N+1", "type": "分镜参考", "asset": "Panel-XX 描述（文件名）", "file": "路径" }
                ]
              },
              "segments": [
                {
                  "segment_id": "SEG-01",
                  "clip_id": "clip-001",
                  "panels": [1, 2],
                  "duration_sec": 11,
                  "reference_images": ["@图片1", "@图片4", "@图片5"],
                  "prompt": "以@图片1中的角色名（声线描述）为主角参考，场景参考@图片4。@图片5为首帧参考，{sync_video_prompt内容+camera_move运镜}，电影级真实画质",
                  "camera_moves": ["运镜方式1", "运镜方式2"],
                  "source_text": "对应原文",
                  "keyframes": ["关键帧文件名"],
                  "characters": ["角色名"],
                  "note": "备注"
                }
              ]
            }
        
        提示词组装规则：
            a) 开头：引用角色参考 + 声线 → "以@图片N中的{角色名}（{voiceLine}）为主角参考"
            b) 场景：→ "场景参考@图片N的{场景名}"
            c) ⚠️ 衔接引用（放在角色/场景引用之后、正文之前）：
               如果本段首个panel的 connect_camera_move 不是"硬切"，
               则加入："从上一镜@图片N镜头{connect_camera_move}，"
               将上一段末帧关键帧作为额外参考图传入。
               如果是"硬切"，则不加这段引用，直接进入正文。
            d) 正文：取 sync_video_prompt（含角色名+台词），融合 camera_move 运镜描述
            e) ⚠️ 关键帧引用规则（核心）：
               - 每个关键帧必须在其对应panel的动作描述末尾被引用，不得遗漏
               - 单关键帧段：末尾写 "...最后定格于@图片N"
               - 多关键帧段（2个panel各有关键帧）：
                 第一个panel末尾写 "...参考@图片N"
                 最后一个panel末尾写 "...最后定格于@图片M"
               - 确保模型在对应时间点参考正确的构图
            f) 多panel合并时：用"随后""反打——"等转场词衔接
            g) 结尾："电影级真实画质"
            h) 声线仅在有台词的段落标注
        
        保存：outputs/<集数>/05-seedance-prompt.json
        
        ⚠️ 生成后需用户确认提示词无误，再进入 Step 3

    Step 3: 视频生成
        ⚠️ 默认流程（即梦 Seedance）：
            - 提示词来源：05-seedance-prompt.json 中的 segments[].prompt
            - 参考图：segments[].reference_images 对应 asset_mapping 中的文件
            - 逐段执行，每段需用户确认后才生成
            - 按 segment 顺序生成，命名 SEG-01.mp4, SEG-02.mp4...
        
        即梦生成流程：
            1. 根据 asset_mapping 上传所有参考图 → 获取 CDN URL（或本地路径）
            2. 逐段提交：
               dreamina multimodal2video \
                 --image <参考图1> --image <参考图2> ... \
                 --prompt '<segment.prompt>' \
                 --model_version seedance2.0 \
                 --duration <segment.duration_sec> \
                 --ratio 16:9 --poll 180
            3. 下载到 outputs/<集数>/videos/SEG-XX.mp4
        
        可选流程（zencli 单镜头模式）：
            - 提示词来源：03-storyboard.json 中的 video_prompt（逐镜头）
            - ★ 声线嵌入：在提示词中嵌入角色的 voiceLine
              格式："...(声线：<voiceLine>)"
            - 参考图：分镜图 + 角色图 + 场景图
            - 引擎：zencli generate video --model 18 --mode SubjectToVideo
              --reference-assets '[...]' --enable-sound -o json
            - 轮询 → 下载 → 命名 P<N>-S<M>.mp4
        
        ★ @图片N 重编号规则：
            按参考图传入顺序重新编号（第1张=@图片1，第2张=@图片2...）
            即梦模式下按 asset_mapping 固定编号，无需重编号

    Step 4: [可选] 分镜宫格图（用户要求时执行）
        python3 <video-storyboard-skill>/scripts/storyboard.py \
          outputs/<集数>/videos/<视频文件> --grid 3x3 --timestamp --index

    Step 5: [可选] 配音合成
        仅当「分离配音」模式或非 SD2.0 模型时执行
        - 读取 04-voice-lines.json
        - 逐台词调用 TTS（voice 从 characters.json 的 voiceLine 推断）
        - 保存到 outputs/<集数>/audio/

    Step 6: [可选] 口型同步
        video + audio → lip sync

    Step 7: [可选] 拼接成片
        ffmpeg 按 segment 顺序合并所有视频

[默认模式 vs 可选模式]
    
    默认模式（即梦 Seedance）：
        Step 1 → Step 2 → Step 3（即梦）→ Step 4
        - 提示词从 05-seedance-prompt.json 读取
        - 按 segment 分段生成（每段 ≤15s，可含多个 panel）
        - 使用 sync_video_prompt（含角色名+台词，支持口型同步）
        - 音画同出，无需额外配音
    
    可选模式（zencli 单镜头）：
        Step 1 → Step 3（zencli）→ Step 4 → Step 5 + Step 6
        - 跳过 Step 2，提示词从 03-storyboard.json 的 video_prompt 读取
        - 逐 panel 生成（每镜头独立一段视频）
        - 使用 video_prompt（年龄段+性别替代角色名）
        - 可选 --enable-sound 或分离配音

[Seedance 2.0 音画同出适配]
    - 即梦默认开启音画同出，视频自带音效和对话
    - 提示词中声线描述写在角色名后括号内，模型会参考生成对应的语音
    - zencli 模式下通过 --enable-sound 开启
    - 仅当用户选择「分离配音」或使用非 SD2.0 模型时，才走 Step 5+6

[manifest.json 更新]
    每次生成新资产后，更新 manifest.json：
    - 新图片 → panels[].image
    - 新视频 → panels[].video / segments[].video
    - 宫格图 → panels[].storyboardGrid
    - 提示词 → 05-seedance-prompt.json 路径
    - 统计更新 → stats.totalPanels, totalVideos, totalDuration
