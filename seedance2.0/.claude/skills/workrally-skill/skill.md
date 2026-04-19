---
name: workrally-skill
description: WorkRally CLI (旧名 zencli) 调用技能包。用于 AI 生图、生视频、文件上传/下载的统一调用规范。
---

# WorkRally CLI（workrally）调用技能包

⚠️ **品牌升级公告**（2026-04 更新）
    ZenStudio CLI 已正式更名为 **WorkRally CLI**：
    - 命令名：`zencli` → `workrally`（旧命令 `zencli` 仍在兼容过度期，但建议逐步迁移）
    - npm 包名：`zenstudio-cli` → `workrally`
    - 环境变量：`ZENSTUDIO_API_KEY` → `WORKRALLY_API_KEY`（旧变量仍可用）
    - 产品名：ZenStudio → WorkRally
    - 当前最新版本：**v2.1.0**
    - API 未变，token/密钥无需重新申请

    安装/升级命令：
    ```bash
    npm install -g workrally@latest
    export WORKRALLY_API_KEY=<你的_API_KEY>
    ```

[技能说明]
    封装 workrally 命令行工具的所有调用规范，包括：
    - AI 生图（画布生图）
    - AI 生视频（画布生视频）
    - 任务轮询
    - 文件上传/下载
    - 素材管理

    确保调用方式正确、流程标准化、错误可追踪。

    本 Skill 所有示例统一使用新命令 `workrally`，同时保留旧命令 `zencli` 的兼容备注。

[默认项目配置]

    ⚠️ 默认不传 --project-id 参数（除非用户明确指定要归入某个 WorkRally 项目）。
    如需关联项目，用户会提供 project_id，届时所有 generate image / generate video 命令加上：
    --project-id <用户指定的ID>

[核心调用流程]

    ⚠️ 关键规则：生图/生视频统一使用「提交 → 轮询 → 下载」三步流程。

    第一步：提交任务（不使用 --poll）
        提交生成任务时，不加 --poll 参数，命令返回后立即拿到 task_id。
        
        原因：--poll 模式在长时间排队时容易超时断连，导致结果丢失。
        手动轮询更可靠，且支持多任务并行。

    第二步：轮询任务状态
        使用 `workrally generate task <task_id> -o json` 查询任务状态。
        
        轮询策略：
        - 首次查询：提交后等待 15 秒
        - 后续查询：每 15-30 秒查询一次
        - 超时上限：生图最多等待 3 分钟，生视频最多等待 10 分钟
        - 如果超时仍未完成，向用户报告 task_id，用户可稍后手动查询
        
        状态判断：
        - state_desc 包含 "成功" 或 state 为完成状态 → 提取 asset_id → 进入第三步
        - state_desc 包含 "失败" → 报告失败原因
        - 其他 → 继续轮询

    第三步：下载产物
        使用 `workrally download <asset_id> -d <目标目录>` 下载到本地。
        下载后重命名为项目约定的文件名。

[生图命令]

    工具：workrally generate image（旧名：zencli generate image）
    
    基本命令格式：
    ```bash
    workrally generate image \
      --prompt '<提示词>' \
      --model <model_id> \
      --aspect-ratio <比例> \
      --resolution <分辨率> \
      --name '<素材名称>' \
      -o json
    ```

    可用模型（动态下发，使用前可通过 `workrally generate image-models` 确认最新列表）：
    | model_id      | 名称   | 底层模型  | 最大输入图片数 | 分辨率       |
    |---------------|--------|----------|--------------|-------------|
    | nano-banana1  | 贝宝1  | gemini   | 4            | 1K / 2K     |
    | 314           | 贝宝2  | gemini   | 8            | 1K / 2K     |
    | 317           | 维宝   | vidu     | 4            | 1K / 2K     |

    默认配置：
    - model: 314（贝宝2，当前最佳）
    - aspect-ratio: 16:9
    - resolution: 0（1K/1080P，默认足够）
    - count: 1

    参数说明：
    - --prompt: 图片描述提示词（必填）
    - --model: 模型 ID（必填，默认 314）
    - --aspect-ratio: 宽高比（可选值：21:9 / 16:9 / 4:3 / 1:1 / 3:4 / 9:16）
    - --resolution: 分辨率等级（0=1K, 1=2K）
    - --count: 生成数量（1/2/4）
    - --input-images: 参考图 URL（逗号分隔，需先 upload 获取 URL）
    - --name: 素材名称（便于后续管理）
    - -o json: 输出 JSON 格式（必加，方便解析）

    带参考图的生图流程：
    1. 先用 `workrally upload <本地图片路径> -o json` 上传参考图，拿到 CDN URL
    2. 将 URL 传入 --input-images 参数
    3. 提示词中描述参考图的用途

    返回值解析（JSON）：
    ```json
    {
      "task_id": "xxx",        // 用于轮询的任务 ID
      "message": "已提交..."   // 提示信息
    }
    ```

[生视频命令]

    工具：workrally generate video（旧名：zencli generate video）
    
    基本命令格式：
    ```bash
    workrally generate video \
      --prompt '<提示词>' \
      --model <provider_id> \
      --mode <驱动模式> \
      --duration <时长秒数> \
      --single-image-url '<图片URL>' \
      --name '<素材名称>' \
      -o json
    ```

    驱动模式：
    | mode             | 说明           | 必要参数                |
    |------------------|---------------|------------------------|
    | Text             | 文本驱动（可附单图） | --prompt, 可选 --single-image-url |
    | FirstLastFrame   | 首尾帧驱动     | --first-frame-url, --last-frame-url |
    | FrameSequence    | 序列帧驱动     | --sequence-frames (JSON) |
    | SubjectToVideo   | 主体驱动       | --reference-assets (JSON) |

    常用视频模型（文本驱动 Text 模式）：
    | provider | 名称              | 时长选项      | 附图 | 音效  | 推荐 |
    |----------|-------------------|-------------|------|------|------|
    | 2        | Zen-01-1.5pro     | 5/8/10/12s  | 1图  | 支持 | ★推荐 |
    | 1        | Zen-02.3.0        | 5/10/15s    | 1图  | 支持 | 写实  |
    | 202      | Zen-01 [1.0]      | 5/10s       | 1图  | 不支持 | —   |

    Zen-SD2.0 SubjectToVideo（主体驱动）模式——项目默认备选生视频方案：
    | provider | 名称       | 模式              | 时长        | 最大图片 | 最大视频 | 音效  |
    |----------|-----------|-------------------|------------|---------|---------|------|
    | 18       | Zen-SD2.0 | Text/FirstLastFrame/SubjectToVideo | 4-15s | 9       | 3       | 支持 |

    SubjectToVideo 命令格式：
    ```bash
    # 1. 上传参考图拿 CDN URL
    URL1=$(workrally upload <角色图1> -o json 2>&1 | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['url'])")
    URL2=$(workrally upload <场景图> -o json 2>&1 | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['url'])")

    # 2. 提交（不用 --poll）
    workrally generate video \
      --prompt '<提示词>' \
      --model 18 \
      --mode SubjectToVideo \
      --duration <时长> \
      --reference-assets '[{"url":"'$URL1'"},{"url":"'$URL2'"}]' \
      --enable-sound \
      --name '<素材名称>' \
      -o json
    ```

    reference-assets JSON 格式：
    - 数组，每个元素为 `{"url":"<CDN_URL>"}`
    - 最多 9 张图片 + 3 个视频的 URL
    - URL 必须是通过 `workrally upload` 获取的 CDN URL

    ⚠️ SubjectToVideo 与即梦的关键区别：
    - 即梦用 --image 传本地文件路径，workrally 用 --reference-assets 传 CDN URL
    - 即梦的 @图片N 按 --image 顺序编号；workrally 的 @图片N 按 reference-assets 数组顺序编号
    - 提示词中的 @图片N 重编号规则相同：第1个URL=@图片1，第2个=@图片2...

    带参考图的视频流程（Text 模式）：
    1. `workrally upload <本地图片> -o json` → 拿到 CDN URL
    2. 传入 --single-image-url（Text模式）或 --first-frame-url（首尾帧模式）

    可选参数：
    - --enable-sound: 生成音效（仅部分模型支持）
    - --count: 生成数量（1-4）

[任务轮询命令]

    工具：workrally generate task <task_id>（旧名：zencli generate task）
    
    ```bash
    workrally generate task <task_id> -o json
    ```

    也可以用 --poll 自动轮询（但仅推荐在短时任务中使用）：
    ```bash
    workrally generate task <task_id> --poll --poll-interval 5 -o json
    ```

    返回值中关键字段：
    - state_desc: 任务状态描述（"成功" / "失败" / "处理中" 等）
    - asset_id: 成功后的素材 ID（用于下载）

    解析 asset_id 的 grep 方式：
    ```bash
    workrally generate task <task_id> -o json 2>&1 | grep -o '"asset_id": "[^"]*"' | head -1 | cut -d'"' -f4
    ```

[文件上传命令]

    工具：workrally upload <file_path>（旧名：zencli upload）
    
    ```bash
    workrally upload <本地文件路径> -o json
    ```

    支持格式：
    - 图片：jpg/png/webp/gif/bmp → 自动使用普通上传（type=200）
    - 视频：mp4/mov/avi/mkv/webm → 自动使用私有读（type=210）
    - 音频：mp3/wav/aac/flac/ogg → 自动使用私有读（type=210）

    返回值：CDN URL（可直接用于 --input-images / --single-image-url 等参数）

[文件下载命令]

    工具：workrally download（旧名：zencli download）
    
    通过 asset_id 下载：
    ```bash
    workrally download <asset_id> -d <输出目录>
    ```

    通过 URL 下载：
    ```bash
    workrally download --url <url> -d <输出目录>
    ```

    自定义文件名：
    ```bash
    workrally download <asset_id> -d <输出目录> -n <文件名.扩展名>
    ```

    下载后文件默认命名为 `image_<task_id>.png` 或类似格式，通常需要手动重命名。

[标准工作流示例]

    示例1：生成角色图并下载
    ```bash
    # 1. 提交
    workrally generate image \
      --prompt '真人写实角色设定图...' \
      --model 314 --aspect-ratio 16:9 \
      --name "char-林砚舟" -o json
    # → 拿到 task_id

    # 2. 轮询（等15秒后开始）
    sleep 15
    workrally generate task <task_id> -o json
    # → 拿到 asset_id

    # 3. 下载
    workrally download <asset_id> -d outputs/ep01/images/
    # → 下载后重命名
    mv outputs/ep01/images/image_<task_id>.png outputs/ep01/images/char-林砚舟.png
    ```

    示例2：带参考图生成视频
    ```bash
    # 1. 上传参考图
    workrally upload outputs/ep01/images/char-林砚舟.png -o json
    # → 拿到 CDN URL

    # 2. 提交视频生成
    workrally generate video \
      --prompt '...' \
      --model 2 --mode Text --duration 10 \
      --single-image-url '<CDN URL>' \
      --name "P01-S1" -o json
    # → 拿到 task_id

    # 3. 轮询
    sleep 30
    workrally generate task <task_id> -o json
    # → 拿到 asset_id

    # 4. 下载
    workrally download <asset_id> -d outputs/ep01/videos/ -n P01-S1.mp4
    ```

    示例3：并行提交多个生图任务
    ```bash
    # 同时提交3个（各拿到 task_id）
    T1=$(workrally generate image --prompt '...' --model 314 --name "char-A" -o json 2>&1 | grep -o '"task_id":"[^"]*"' | cut -d'"' -f4)
    T2=$(workrally generate image --prompt '...' --model 314 --name "char-B" -o json 2>&1 | grep -o '"task_id":"[^"]*"' | cut -d'"' -f4)
    T3=$(workrally generate image --prompt '...' --model 314 --name "scene" -o json 2>&1 | grep -o '"task_id":"[^"]*"' | cut -d'"' -f4)

    # 统一轮询
    sleep 20
    workrally generate task $T1 -o json
    workrally generate task $T2 -o json
    workrally generate task $T3 -o json
    ```

[切分场景宫格图]

    将一张场景宫格图（如 3×4、3×3）中的每个格子单独放大为高清独立图片。
    ⚠️ 不使用 Python PIL 像素切分（分辨率太低），改用 AI 逐格放大。

    流程：
    1. 上传宫格图：`workrally upload <scene-grid.png路径> -o json` → 拿到 CDN URL
    2. 逐格提交 AI 放大任务：
       - 对每个非空格子，调用 `workrally generate image`
       - --prompt 中说明宫格布局、目标格子位置、格子内容描述
       - --input-images 传入宫格图的 CDN URL
       - --model 314 --aspect-ratio 16:9（场景图统一横版）
    3. 轮询全部任务，拿到 asset_id 后下载

    提示词模板：
    ```
    这是一张{行数}x{列数}宫格场景图，请将第{N}行第{M}格的场景单独放大为一张完整的高清图片。
    该格子是{场景简要描述}。保持原有风格和细节，放大至高清。禁止输出任何描述文字
    ```

    格子位置对应（以3×4为例，3列×4行）：
    | 格号 | 行 | 列 | 位置描述 |
    |------|----|----|---------|
    | 格1  | 1  | 1  | 第1行第1格 |
    | 格2  | 1  | 2  | 第1行第2格 |
    | 格3  | 1  | 3  | 第1行第3格 |
    | 格4  | 2  | 1  | 第2行第1格 |
    | 格5  | 2  | 2  | 第2行第2格 |
    | 格6  | 2  | 3  | 第2行第3格 |
    | 格7  | 3  | 1  | 第3行第1格 |
    | 格8  | 3  | 2  | 第3行第2格 |
    | 格9  | 3  | 3  | 第3行第3格 |
    | 格10 | 4  | 1  | 第4行第1格 |
    | 格11 | 4  | 2  | 第4行第2格（留空则跳过） |
    | 格12 | 4  | 3  | 第4行第3格（留空则跳过） |

    命名规则：scene-{编号两位}-{场景中文名}.png
    示例：scene-01-陵宫.png, scene-02-山间小院.png

    完整示例（10格宫格图切分）：
    ```bash
    # 1. 上传宫格图
    IMG_URL=$(workrally upload outputs/ep01/images/scene-grid.png -o json 2>&1 \
      | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['url'])")

    # 2. 逐格提交（可并行）
    T1=$(workrally generate image \
      --prompt '这是一张3x4宫格场景图，请将第1行第1格的场景单独放大为一张完整的高清图片。该格子是XXX。保持原有风格和细节。禁止输出任何描述文字' \
      --model 314 --aspect-ratio 16:9 --input-images "$IMG_URL" \
      --name "scene-01-XXX" -o json 2>&1 \
      | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['task_ids'][0])")
    # ... 重复其余格子 ...

    # 3. 统一轮询
    sleep 25
    for TID in $T1 $T2 ... $T10; do
      workrally generate task $TID -o json 2>&1 \
        | python3 -c "import sys,json;d=json.load(sys.stdin);aid=d['output_assets'][0]['asset_id'];print(aid)"
    done

    # 4. 逐个下载
    workrally download <asset_id> -d outputs/ep01/images/ -n scene-01-XXX.png
    ```

    优势对比：
    | 方式 | 分辨率 | 质量 | 场景一致性 |
    |------|--------|------|-----------|
    | PIL 像素切分 | ~300×300（极低） | 模糊 | 高（原图裁切） |
    | AI 逐格放大 | 1K+（~1920×1080） | 高清 | 高（参考原图风格） |

[错误处理]

    常见错误及对策：
    
    | 错误现象 | 原因 | 对策 |
    |---------|------|------|
    | --poll 超时无返回 | 排队时间过长 | 改用「提交→轮询」三步流程 |
    | task 查询返回失败 | 提示词违规或模型故障 | 检查提示词，重试 |
    | download 文件名不可控 | 默认命名规则 | 用 -n 指定文件名，或下载后 mv 重命名 |
    | upload 返回空 | 文件格式不支持 | 确认文件扩展名在支持列表中 |
    | model_id 无效 | 模型列表动态更新 | 用 `workrally generate image-models` 重新获取 |
    | JSON 解析失败（Extra data） | workrally 输出末尾追加升级提醒干扰 JSON | 用 `sed '/─/,$d'` 过滤升级提醒后再解析 |
    | upload 返回非 JSON（含进度条） | upload 输出混合了进度信息和 JSON | 用 `grep -o '"url": "[^"]*"'` 提取 URL，不要直接 json.load |

    ⚠️ workrally 输出清洗规则（重要）：
    workrally 命令的 -o json 输出可能混入非 JSON 内容（上传进度条、版本升级提醒等），
    直接用 python3 json.load 会报错。统一使用以下清洗管道：

    ```bash
    # 方式1：过滤升级提醒（推荐）
    workrally <命令> -o json 2>&1 | sed '/─/,$d' | python3 -c "import sys,json;..."

    # 方式2：提取特定字段（upload 专用）
    workrally upload <file> -o json 2>&1 | grep -o '"url": "[^"]*"' | head -1 | cut -d'"' -f4

    # 方式3：提取 task_id（generate 专用）
    workrally generate video ... -o json 2>&1 | sed '/─/,$d' | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['task_ids'][0])"
    ```

[videoTask 读写规范（生视频专用）]

    ⚠️ 以下规范仅适用于 workrally 生视频场景（generate video），生图不涉及。

    ### 每次生视频前：自动刷新"生成中"任务

    扫描 `06-shots/` 下所有 shot-NN.json，对 `videoTask.status === "generating"` 的镜批量查询：

    ```bash
    workrally generate task <taskId> -o json
    ```

    根据查询结果更新 shot-NN.json 的 videoTask：
    - **成功**（state_desc 含"成功"）→ 提取 asset_id → 下载视频 → 截尾帧 → 更新 `status="done"` + `videoUrl` + `videoFile` + `tailFrame` + `completedAt`
    - **失败**（state_desc 含"失败"）→ 更新 `status="failed"` + `failReason` + `completedAt`
    - **仍在处理** → 保持 `status="generating"`

    刷新完毕后汇报：
    ```
    📊 任务状态刷新：
     ✅ shot-03, shot-05 已生成完成（已下载+截尾帧）
     ⏳ shot-07 仍在生成中
     ❌ shot-09 生成失败：<原因>
    ```

    ### 提交视频后：立即写入 videoTask

    提交成功拿到 task_id 后，立即更新 shot-NN.json：

    ```json
    {
      "videoTask": {
        "engine": "workrally",
        "modelName": "Zen-SD2.0",
        "taskId": "<task_id>",
        "status": "generating",
        "videoUrl": "",
        "videoFile": "",
        "tailFrame": "",
        "failReason": "",
        "creditCount": null,
        "submittedAt": "<当前ISO时间>",
        "completedAt": ""
      }
    }
    ```

    **modelName 取值约定**：
    - provider 18 → `"Zen-SD2.0"`
    - provider 2 → `"Zen-01-1.5pro"`
    - provider 1 → `"Zen-02.3.0"`
    - provider 202 → `"Zen-01"`
    - 其他 → 直接填 provider id

    同时更新 `manifest.stages.video`：
    - `generating` +1、`pending` -1、`videoGenCount` +1

    ### 视频下载成功后：更新 videoTask 为完成

    ```json
    {
      "videoTask": {
        "status": "done",
        "videoUrl": "<远端URL>",
        "videoFile": "outputs/<ep>/videos/shot-NN.mp4",
        "tailFrame": "outputs/<ep>/tail-frames/tail-shot-NN.jpg",
        "completedAt": "<当前ISO时间>"
      }
    }
    ```

    同时更新 `manifest.stages.video`：`produced` +1、`generating` -1

    ### videoTask 字段完整定义

    | 字段 | 类型 | 说明 |
    |------|------|------|
    | engine | string | `"workrally"` 或 `"dreamina"` |
    | modelName | string | 模型名称，如 `"Zen-SD2.0"`、`"seedance2.0"` |
    | taskId | string | workrally 的 task_id 或 dreamina 的 submit_id |
    | status | string | `"pending"` / `"generating"` / `"done"` / `"failed"` |
    | videoUrl | string | 远端视频 URL（成功后填入） |
    | videoFile | string | 本地落盘路径 |
    | tailFrame | string | 尾帧路径 |
    | failReason | string | 失败原因（仅 failed 时有值） |
    | creditCount | number/null | 消耗积分 |
    | submittedAt | string | 提交时间 ISO |
    | completedAt | string | 完成时间 ISO |

[注意事项]

    1. ⚠️ 永远不要在 generate image / generate video 中使用 --poll
       改用 generate task <task_id> 手动轮询，更可靠
    2. 所有命令末尾加 `-o json` 确保返回 JSON，便于解析
    3. ⚠️ 解析 JSON 前必须先清洗输出（见上方「workrally 输出清洗规则」），否则会因升级提醒等非 JSON 内容导致解析失败
    4. 模型列表是动态下发的，不要硬编码，每次项目初始化时可用
       `workrally generate image-models` 和 `workrally generate video-models` 确认
    5. upload 返回的 URL 有时效性，建议上传后立即使用
    6. 并行提交多个生图任务可以大幅提升效率（见示例3）
    7. 下载后务必重命名为项目约定的文件名（如 char-角色名.png, scene-grid.png 等）
    8. ⚠️ 所有 generate image / generate video 命令必须带 --project-id（见[默认项目配置]）
    9. upload 命令分步执行更可靠——不要用 $(...) 嵌套在其他命令中，容易因进度条输出导致变量为空
    10. ⚠️ **成本记录（强制）**：每次下载完成（即真正出图/出视频）之后必须立即调用 `scripts/cost-logger.py` 记一笔，用于 dashboard 成本核算。
        - 生图：`python scripts/cost-logger.py image --project <项目> --episode <epNN> --target <char-xx/scene-xx/prop-xx> --model nano-banana2 --task-id <taskId> [--note "..."]`
          - 贝宝1 → `nano-banana1`；贝宝2（即 model 314）→ `nano-banana2`
        - 生视频：`python scripts/cost-logger.py video --project <项目> --episode <epNN> --target shot-XX --model <providerId> --duration <实际秒数> --task-id <taskId> [--note "..."]`
          - 视频模型直接填 provider id（2/1/202/18）
          - 同一 shot 重复生视频，脚本会自动识别为 isRegenerate，不计入去重成片数与总时长
          - ⚡ **走 dreamina 的视频**：`video_scheduler.py`（心跳）/ `refresh_video_status.py` 下载成功时会自动调 cost-logger（按 taskId 幂等），**无需手动记**
        - `--task-id` 强烈建议填：脚本据此幂等，重复调用会 `[skip]` 不改 07-costs
        - 失败的任务不要登记；只在下载成功（拿到图/视频文件）后登记
   10. ⚠️ 品牌升级兼容说明：旧命令 `zencli` 和旧环境变量 `ZENSTUDIO_API_KEY` 仍可用（过渡期），
       但新项目/新脚本请优先使用 `workrally` 和 `WORKRALLY_API_KEY`

[媒资管理]

    workrally v2.1.0+ 提供媒资管理能力，可在项目中管理已生成的素材。（旧命令 zencli v1.3.3+ 也支持）

    搜索项目媒资：
    ```bash
    workrally asset search --project-id <项目ID> -t image -k "角色" -o json
    ```
    参数：--project-id（必填）、-t 类型（image/video/audio）、-k 关键词、-p 页码

    通过 URL 入库素材：
    ```bash
    workrally asset create --url <CDN_URL> --project-id <项目ID> --name "P01-S1" -o json
    ```
    用途：将 upload 得到的 CDN URL 正式入库为项目素材，获得 asset_id

    获取素材详情（支持批量）：
    ```bash
    workrally asset get <asset_id1> <asset_id2> -o json
    ```

    重命名素材：
    ```bash
    workrally asset update <asset_id> --name "新名称"
    ```

[资产库管理]

    管理角色/道具/场景等资产，以树形目录结构组织。

    列出目录内容：
    ```bash
    # 根目录 ID：role_person(人物), role_prop(道具), role_scene(场景), root(网盘)
    workrally material list role_person -o json
    ```

    批量创建素材/文件夹：
    ```bash
    workrally material add --json-list '[{...}]' --project-ids <项目ID> --source 1
    ```

    获取素材详情/面包屑路径：
    ```bash
    workrally material get <material_id> -o json
    workrally material breadcrumb <material_id> -o json
    ```

[角色资产详情]

    获取角色的完整信息（描述、关联项目、提示词、LoRA 版本、训练状态等）：
    ```bash
    workrally role get <role_id> -o json
    ```

[无限画布管理]

    管理无限画布项目，支持增量构建画布草稿。

    画布 CRUD：
    ```bash
    workrally canvas list -o json
    workrally canvas create "画布名称" -o json
    workrally canvas get <canvas_id> -o json
    workrally canvas delete <canvas_id>
    ```

    构建画布草稿（增量合并节点）：
    ```bash
    # 支持节点类型：image/video/audio/artboard/text/freehand
    workrally canvas build-draft <canvas_id> --nodes '[{"type":"image","url":"...","x":0,"y":0}]'
    # 或从文件读取
    workrally canvas build-draft <canvas_id> --file nodes.json
    # 删除节点
    workrally canvas build-draft <canvas_id> --delete-node-ids "node1,node2"
    ```

[URL 工具]

    离线可用，无需登录。解析/构建 WorkRally 前端 URL。
    ```bash
    workrally url parse "https://workrally.xxx/..."    # 解析 URL 对应的功能页
    workrally url build "项目详情"                       # 根据功能名构建 URL
    workrally url list                                   # 列出所有可用页面路由
    ```
