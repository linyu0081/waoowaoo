---
name: video-production-skill
description: 视频导演技能包。定义分镜图生成、视频生成、配音合成、口型同步的标准流程。
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

    Step 2: 视频生成
        - 逐镜头执行，每个视频需用户确认后才生成
        - 提示词来源：03-storyboard.json 中的 video_prompt
        - ★ 声线嵌入：在提示词中嵌入角色的 voiceLine（来自 characters.json）
          格式："...(声线：<voiceLine>)"
        - 参考图：分镜图 + 角色图 + 场景图

        默认引擎 zencli（Zen-SD2.0 SubjectToVideo）：
            1. 上传参考图 → zencli upload → 获取 CDN URL
            2. 提交：zencli generate video --model 18 --mode SubjectToVideo
               --reference-assets '[...]' --enable-sound -o json
            3. 轮询：zencli generate task <task_id> -o json
            4. 下载：zencli download <asset_id> -d outputs/<集数>/videos/ -n P<N>-S<M>.mp4

        可选引擎 dreamina（即梦 Seedance 2.0）：
            1. dreamina multimodal2video --image <图1> --image <图2>
               --prompt '<提示词>' --model_version seedance2.0
               --duration <时长> --ratio 16:9 --poll 180
            2. 下载到 outputs/<集数>/videos/

        ★ @图片N 重编号规则：
            按参考图传入顺序重新编号（第1张=@图片1，第2张=@图片2...）

    Step 3: 分镜宫格图（视频下载后自动执行）
        python3 <video-storyboard-skill>/scripts/storyboard.py \
          outputs/<集数>/videos/P<N>-S<M>.mp4 --grid 3x3 --timestamp --index

    Step 4: [可选] 配音合成
        仅当「分离配音」模式或非 SD2.0 模型时执行
        - 读取 04-voice-lines.json
        - 逐台词调用 TTS（voice 从 characters.json 的 voiceLine 推断）
        - 保存到 outputs/<集数>/audio/

    Step 5: [可选] 口型同步
        video + audio → lip sync

    Step 6: [可选] 拼接成片
        ffmpeg 合并所有视频+配音

[Seedance 2.0 音画同出适配]
    - --enable-sound 开启后，视频自带音效
    - 提示词中嵌入声线描述，模型会参考生成对应的语音
    - 仅当用户选择「分离配音」或使用非 SD2.0 模型时，才走 Step 4+5

[manifest.json 更新]
    每次生成新资产后，更新 manifest.json：
    - 新图片 → panels[].image
    - 新视频 → panels[].video
    - 宫格图 → panels[].storyboardGrid
    - 统计更新 → stats.totalPanels, totalVideos, totalDuration
