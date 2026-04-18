---
name: video-edit-skill
description: 基于 ffmpeg 的轻量视频处理工具。支持多段拼接、裁剪、提取帧（尤其是尾帧用于首帧衔接）、转码、加字幕等。手动触发，也可在生视频流水线中被 ai-producer 调用。
trigger: 用户要求视频处理/编辑/拼接/裁剪/合并、或 ai-producer 流水线需要为已完成分镜截取 tail-frame 时使用
---

# 视频编辑 Skill（基于 ffmpeg）

> ✅ 两种触发方式：
> 1. 用户手动触发（拼接/裁剪/转码等）
> 2. 由 ai-producer 在「单镜视频生成完成后」自动调用，从末帧截取 `tail-shot-NN.jpg`，供后续依赖该首帧的分镜生视频使用（参见 `asset-map.json` 中 `type === 'tail-frame'` 的占位项）

## 环境（跨平台自适应）

本 skill 优先使用系统 PATH 中的 `ffmpeg` / `ffprobe`，不绑死任何绝对路径：

- **Linux**（本项目服务器环境）：`~/.local/bin/ffmpeg`（静态编译版 v7.0.2，已加入 `$PATH`）
- **macOS**：Homebrew 安装路径 `/opt/homebrew/bin/ffmpeg`
- **Windows**：`where ffmpeg` 返回路径

默认输出目录：`projects/<项目名>/outputs/<集数>/videos/`
默认尾帧目录：`projects/<项目名>/outputs/<集数>/tail-frames/`（与 `asset-map.json` 约定一致）

## 【重点】单镜尾帧提取（与 asset-map 联动）

**使用场景**：`ai-producer` 完成第 i 镜视频生成后，立即提取其最末一帧保存为 `tail-shot-{i:02d}.jpg`，供任何 mount 带 `本视频以@图片N为首帧`（N 对应 `type===tail-frame` 且 `fromShot===i` 的编号）的后续分镜使用。

```bash
# 约定：PROJECT_ROOT 为项目根（如 projects/马上看中国史），EP=ep01，IDX=00..NN
PROJECT_ROOT="projects/马上看中国史"
EP="ep01"
IDX="00"
mkdir -p "$PROJECT_ROOT/outputs/$EP/tail-frames"
ffmpeg -sseof -0.1 \
  -i "$PROJECT_ROOT/outputs/$EP/videos/shot-${IDX}.mp4" \
  -frames:v 1 -update 1 -q:v 2 -y \
  "$PROJECT_ROOT/outputs/$EP/tail-frames/tail-shot-${IDX}.jpg"
```

- `-sseof -0.1`：相对文件末尾 -0.1s 开始读，最稳妥拿到

[多段视频拼接]

    将多个 mp4 视频按顺序无缝拼接为一个完整视频。

    方式1：concat demuxer（推荐，无需重编码，速度快）
    适用条件：所有视频的分辨率、帧率、编码格式完全一致

    ```bash
    # 1. 生成文件列表
    cat > /tmp/concat_list.txt << EOF
    file '/absolute/path/to/video1.mp4'
    file '/absolute/path/to/video2.mp4'
    file '/absolute/path/to/video3.mp4'
    EOF

    # 2. 拼接（无重编码）
    ffmpeg -f concat -safe 0 -i /tmp/concat_list.txt -c copy output.mp4

    # 3. 清理
    rm /tmp/concat_list.txt
    ```

    方式2：concat filter（需重编码，兼容性好）
    适用条件：视频格式/分辨率不一致时

    ```bash
    ffmpeg -i video1.mp4 -i video2.mp4 -i video3.mp4 \
      -filter_complex "[0:v:0][0:a:0][1:v:0][1:a:0][2:v:0][2:a:0]concat=n=3:v=1:a=1[outv][outa]" \
      -map "[outv]" -map "[outa]" output.mp4
    ```

    方式3：仅视频无音轨时

    ```bash
    ffmpeg -i video1.mp4 -i video2.mp4 \
      -filter_complex "[0:v][1:v]concat=n=2:v=1:a=0[outv]" \
      -map "[outv]" output.mp4
    ```

[视频裁剪]

    截取视频的某一时间段。

    ```bash
    # 从第 3 秒开始，截取 5 秒
    ffmpeg -ss 3 -i input.mp4 -t 5 -c copy output.mp4

    # 从第 3 秒到第 8 秒
    ffmpeg -ss 3 -to 8 -i input.mp4 -c copy output.mp4
    ```

    ⚠️ -ss 放在 -i 前面是快速定位（关键帧对齐），放在 -i 后面是精确定位（但较慢）。
    精确裁剪（需重编码）：

    ```bash
    ffmpeg -i input.mp4 -ss 3 -to 8 -c:v libx264 -c:a aac output.mp4
    ```

[提取帧]

    提取单帧：
    ```bash
    # 提取第 5 秒的帧
    ffmpeg -ss 5 -i input.mp4 -frames:v 1 -update 1 -q:v 2 frame.png

    # 提取最后一帧（tail-frame 的官方推荐写法）
    ffmpeg -sseof -0.1 -i input.mp4 -frames:v 1 -update 1 -q:v 2 lastframe.png
    # 或 JPEG（本项目 tail-shot-NN.jpg 约定用此格式，体积小）
    ffmpeg -sseof -0.1 -i input.mp4 -frames:v 1 -update 1 -q:v 2 lastframe.jpg

    # 提取第一帧
    ffmpeg -i input.mp4 -frames:v 1 -update 1 -q:v 2 firstframe.png
    ```

    提取多帧（每秒1帧）：
    ```bash
    ffmpeg -i input.mp4 -vf "fps=1" frames_%03d.png
    ```

    提取多帧（每N秒1帧）：
    ```bash
    ffmpeg -i input.mp4 -vf "fps=1/3" frames_%03d.png  # 每3秒1帧
    ```

[视频信息查看]

    ```bash
    ffprobe -v quiet -print_format json -show_format -show_streams input.mp4 \
      | python3 -c "
    import sys,json;d=json.load(sys.stdin)
    vs=[s for s in d['streams'] if s['codec_type']=='video'][0]
    dur=float(d['format']['duration'])
    print(f'分辨率: {vs[\"width\"]}x{vs[\"height\"]}')
    print(f'帧率: {vs[\"r_frame_rate\"]}')
    print(f'时长: {dur:.1f}s')
    print(f'编码: {vs[\"codec_name\"]}')
    print(f'文件大小: {int(d[\"format\"][\"size\"])/1024/1024:.1f}MB')
    "
    ```

[转码/调整分辨率]

    ```bash
    # 转为 1080p
    ffmpeg -i input.mp4 -vf "scale=1920:1080" -c:v libx264 -crf 18 -c:a aac output_1080p.mp4

    # 转为 720p（保持宽高比）
    ffmpeg -i input.mp4 -vf "scale=-2:720" -c:v libx264 -crf 18 -c:a aac output_720p.mp4

    # 调整帧率（如 24fps → 30fps）
    ffmpeg -i input.mp4 -r 30 -c:v libx264 -crf 18 -c:a aac output_30fps.mp4
    ```

[添加转场]

    两段视频之间加淡入淡出转场：
    ```bash
    # 假设 video1 时长 15s，video2 时长 15s，转场 1s
    ffmpeg -i video1.mp4 -i video2.mp4 \
      -filter_complex " \
        [0:v]trim=0:15,setpts=PTS-STARTPTS[v0]; \
        [1:v]trim=0:15,setpts=PTS-STARTPTS[v1]; \
        [v0][v1]xfade=transition=fade:duration=1:offset=14[outv]; \
        [0:a][1:a]acrossfade=d=1[outa]" \
      -map "[outv]" -map "[outa]" output.mp4
    ```

    可用转场效果：fade, wipeleft, wiperight, wipeup, wipedown, slideleft, slideright,
    circlecrop, rectcrop, dissolve, pixelize, diagtl, diagtr, diagbl, diagbr,
    hlslice, hrslice, vuslice, vdslice, smoothleft, smoothright, smoothup, smoothdown

[添加文字水印/字幕]

    ```bash
    # 添加固定文字（左上角白色）
    ffmpeg -i input.mp4 \
      -vf "drawtext=text='龙脉 EP01':fontsize=24:fontcolor=white:x=20:y=20" \
      -c:v libx264 -crf 18 -c:a copy output.mp4
    ```

[音频处理]

    ```bash
    # 提取音频
    ffmpeg -i input.mp4 -vn -c:a copy output.aac

    # 静音视频
    ffmpeg -i input.mp4 -an -c:v copy output_mute.mp4

    # 替换音频
    ffmpeg -i video.mp4 -i audio.mp3 -c:v copy -c:a aac -map 0:v:0 -map 1:a:0 output.mp4

    # 调整音量（2倍）
    ffmpeg -i input.mp4 -af "volume=2.0" -c:v copy output.mp4
    ```

[速度调整]

    ```bash
    # 2倍速
    ffmpeg -i input.mp4 -filter_complex "[0:v]setpts=0.5*PTS[v];[0:a]atempo=2.0[a]" \
      -map "[v]" -map "[a]" output_2x.mp4

    # 0.5倍慢放
    ffmpeg -i input.mp4 -filter_complex "[0:v]setpts=2.0*PTS[v];[0:a]atempo=0.5[a]" \
      -map "[v]" -map "[a]" output_slow.mp4
    ```

[常用组合操作]

    EP 拼接完整流程（本项目常用）：
    ```bash
    cd /path/to/project

    # 1. 查看所有视频信息确认格式一致
    for f in outputs/ep01/videos/P0{1,2,3}-S1.mp4; do
      echo "=== $f ===" && ffprobe -v quiet -print_format json -show_streams "$f" \
        | python3 -c "import sys,json;s=[x for x in json.load(sys.stdin)['streams'] if x['codec_type']=='video'][0];print(f'{s[\"width\"]}x{s[\"height\"]} {s[\"r_frame_rate\"]} {s[\"codec_name\"]}')"
    done

    # 2. 生成拼接列表
    cat > /tmp/ep01_concat.txt << EOF
    file '$(pwd)/outputs/ep01/videos/P01-S1.mp4'
    file '$(pwd)/outputs/ep01/videos/P02-S1.mp4'
    file '$(pwd)/outputs/ep01/videos/P03-S1.mp4'
    EOF

    # 3. 拼接
    ffmpeg -f concat -safe 0 -i /tmp/ep01_concat.txt -c copy outputs/ep01/videos/EP01-full.mp4

    # 4. 清理
    rm /tmp/ep01_concat.txt
    ```

[注意事项]

    1. 无重编码拼接（-c copy）要求所有视频的分辨率/帧率/编码完全一致
       - 本项目 Zen-SD2.0 输出统一为 1280×720, 24fps, h264 → 可直接用 -c copy
       - 即梦 Dreamina 输出也是 1280×720, 60fps, h264 → 注意帧率可能不同
       - 如果帧率不一致，用 concat filter 方式（方式2）
    2. -y 参数自动覆盖输出文件，非交互环境必须加
    3. 所有路径使用绝对路径，避免 concat demuxer 找不到文件
    4. 提取帧时用 -update 1 避免 image2 muxer 警告
    5. 重编码时 -crf 18 是高质量（范围 0-51，越小越好，18-23 常用）
    6. ffmpeg 路径跨平台：本 skill 不写死绝对路径，依赖 $PATH；Linux 服务器已安装静态编译版于 ~/.local/bin

[与 asset-map / storyboard 流水线联动]

    1. storyboard 阶段：asset-map.json 在生成时已为每镜预占一个 `type === 'tail-frame'` 占位
       （文件路径形如 outputs/<集数>/tail-frames/tail-shot-NN.jpg）。
    2. 某镜 mount 末尾出现 `本视频以@图片N为首帧` 时，N 对应 asset-map 中的某个 tail-frame 占位。
    3. video 阶段：ai-producer 完成第 i 镜视频生成后，应立即调用本 skill 的「单镜尾帧提取」命令段
       （`ffmpeg -sseof -0.1 ... tail-frames/tail-shot-NN.jpg`），把末帧落盘到约定路径，供任何依赖
       该首帧的后续镜（mount 中含 `本视频以@图片N为首帧`）触发生视频任务。
    4. 依赖判定：下游流水线在组装某镜的生视频任务时，先扫 mount，若存在 `本视频以@图片N为首帧`，
       则要求对应 tail-frame 文件存在；不存在则判定为"前置依赖未就绪"，挂起等待。
    5. 幂等：同一镜重复截尾帧应使用 `-y` 覆写，确保最终写入的是最新一次渲染结果。
