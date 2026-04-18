---
name: dreamina-video-skill
description: AI 生视频技能。调用即梦（Dreamina）CLI 的 multimodal2video 命令，基于 Seedance 2.0 提示词和参考图素材，逐条生成 AI 视频。
---

# AI 生视频技能（即梦 Dreamina CLI）

[技能说明]
    基于已完成的 Seedance 2.0 提示词（outputs/<集数>/02-seedance-prompts.md）和参考图素材（outputs/<集数>/images/），
    调用即梦 CLI 的 multimodal2video 命令逐条生成 AI 视频。
    
    每个 Shot = 一条提示词 = 一次视频生成任务。
    
    核心准则：
    - 每个视频必须经用户明确同意后才调用，不批量生成，不重复调用
    - 每次生成前必须重新读取 02-seedance-prompts.md 获取最新提示词（禁止使用缓存）
    - 生成完成后自动下载视频到本地

[文件结构]
    dreamina-video-skill/
    └── SKILL.md                            # 本文件（技能流程说明）

[前置依赖]
    - 即梦 CLI 已安装：curl -s https://jimeng.jianying.com/cli | bash
    - 已完成登录：dreamina login --headless
    - PATH 包含：/Users/linyu/.local/bin
    - 已完成分镜编写阶段，存在 outputs/<集数>/02-seedance-prompts.md
    - 已完成 AI 生图阶段，存在 outputs/<集数>/images/ 下的参考图

[默认配置]
    command:        multimodal2video
    model_version:  seedance2.0
    ratio:          16:9
    poll:           180（秒，等待生成完成）
    video_resolution: 720p（Seedance 2.0 仅支持 720p）

[素材对应表解析规则]
    02-seedance-prompts.md 文件头部包含素材对应表，格式如下：
    
    | 引用编号 | 素材类型 | 对应素材 | 声线 |
    |---------|---------|---------|------|
    | @图片1  | 人物参考 | 叶烬（char-叶烬.png） | 声线描述... |
    | @图片8  | 场景参考 | 曙光城中央广场·祭坛（scene-01.png） | — |
    | @图片12 | 关键帧参考 | KF-C01 频率纪元概念图（kf-C01.png） | — |
    
    解析规则：
    - 从"对应素材"列中提取括号内的文件名（如 char-叶烬.png）
    - 文件路径为 outputs/<集数>/images/<文件名>
    - 声线列如果不为"—"，则声线描述已内嵌在提示词中，无需额外处理

[提示词解析规则]
    每个剧情点的提示词块格式如下：
    
    ## P<编号> <标题>
    ### P<编号>-S<Shot编号>（<时长>s）
    **生成模式**：从零生成
    **Seedance 2.0 提示词**：
    以@图片N为xxx参考，@图片M为xxx参考。
    <提示词正文>
    
    解析步骤：
    1. 从标题行提取时长（如 15s → --duration 15）
    2. 从提示词中提取所有 @图片N 引用（如 @图片4、@图片8）
    3. 根据素材对应表，将 @图片N 映射为实际文件路径
    4. 确定 --image 传入顺序（按提示词中 @图片N 出现顺序排列）
    5. ⚠️ **关键规则：重新编号引用**
       即梦的 @图片N 引用是按 --image 上传顺序编号的：
       - 第一个 --image 参数 = @图片1
       - 第二个 --image 参数 = @图片2
       - 依此类推
       
       因此，必须将提示词中的原始 @图片N 编号替换为按传入顺序的新编号。
       
       示例：提示词原文引用 @图片4（大祭司）和 @图片8（场景），
       传入顺序为 --image char-大祭司光耀.png --image scene-01.png，
       则提示词中：
       - @图片4 → 替换为 @图片1
       - @图片8 → 替换为 @图片2
       
    6. **替换后的完整提示词**（包含重新编号的引用声明行 + 全部正文）作为 --prompt 参数
       ⚠️ 引用声明行必须保留在 prompt 中，让即梦模型理解每张传入图片的角色/用途

[执行流程]

    第一步：环境检查
        - 确认即梦 CLI 可用：which dreamina
        - 确认登录状态：dreamina user_credit
        - 确认积分余额充足（每条视频约消耗 120 积分）
        - 确认 outputs/<集数>/02-seedance-prompts.md 存在
        - 确认 outputs/<集数>/images/ 目录存在且包含参考图
        - 创建视频输出目录：mkdir -p outputs/<集数>/videos/

    第二步：读取最新提示词（每次生成前必须执行）
        ⚠️ 关键规则：禁止使用上下文缓存的提示词内容
        - 使用 read_file 工具重新读取 outputs/<集数>/02-seedance-prompts.md
        - 解析素材对应表，建立 @图片N → 文件路径 的映射
        - 定位到用户指定的剧情点/Shot 的提示词块
        - 提取时长、引用图片列表、提示词正文

    第三步：向用户展示生成计划
        展示以下信息供用户确认：
        - 剧情点编号和标题
        - Shot 编号和时长
        - 将传入的参考图列表（文件名）
        - 提示词摘要（前50字...）
        - 预估积分消耗
        
        ⚠️ 必须等待用户明确回复"确认"/"好"/"继续"等肯定词后才执行生成

    第四步：调用即梦生成视频
        构造并执行命令：
        
        ```bash
        export PATH="/Users/linyu/.local/bin:$PATH"
        dreamina multimodal2video \
          --image <参考图1路径> \
          --image <参考图2路径> \
          ... \
          --prompt '<提示词正文>' \
          --model_version seedance2.0 \
          --duration <时长> \
          --ratio 16:9 \
          --poll 180 \
          2>&1 | tail -30
        ```
        
        注意事项：
        - --image 参数按提示词中 @图片N 出现顺序传入
        - --prompt 必须包含完整提示词（引用声明行 + 正文）
        - ⚠️ prompt 中的 @图片N 编号必须按 --image 上传顺序重新编号：
          第一个 --image = @图片1，第二个 = @图片2，依此类推
          例如原始提示词 "以@图片4为主角，@图片8为场景参考" 
          传入 --image char-大祭司.png --image scene-01.png 时
          prompt 中应改为 "以@图片1为主角，@图片2为场景参考"
        - --duration 从 Shot 标题提取（如 P01-S1（15s） → 15）
        - 提示词中的单引号需转义或改用双引号包裹

    第五步：记录生成结果
        生成命令返回后，解析输出：
        - 提取 submit_id
        - 检查 gen_status：
            - querying：任务排队中/生成中，等待 poll 完成
            - success：生成成功，提取视频 URL
            - fail：生成失败，记录 fail_reason
        - 记录积分消耗（credit_count）

    第六步：下载视频到本地
        生成成功后（gen_status=success 且返回视频 URL）：
        
        ```bash
        curl -L -o outputs/<集数>/videos/P<编号>-S<Shot编号>.mp4 "<视频URL>"
        ```
        
        文件命名规则：P01-S1.mp4、P02-S1.mp4、P07-S2.mp4 等
        
        如果 poll 超时（gen_status 仍为 querying）：
        - 记录 submit_id
        - 告知用户可稍后用 dreamina query_result --submit_id=<id> 查询
        - 或等待后重新查询并下载

    第七步：生成分镜宫格图（视频下载成功后自动执行）
        视频成功下载到本地后，自动调用 video-storyboard-skill 生成 3×3 分镜宫格图：
        
        ```bash
        python3 .claude/skills/video-storyboard-skill/scripts/storyboard.py \
          outputs/<集数>/videos/P<编号>-S<Shot编号>.mp4 \
          --grid 3x3 --timestamp --index
        ```
        
        输出：outputs/<集数>/videos/P<编号>-S<Shot编号>_storyboard_3x3.jpg
        
        该分镜宫格图将作为后续 Shot 的参考图传入（详见下方"分镜宫格图引用处理"）。

    第八步：向用户汇报结果
        展示：
        - 生成状态（成功/排队中/失败）
        - submit_id
        - 积分消耗
        - 本地保存路径（如成功下载）
        - 分镜宫格图路径（如已生成）
        - 询问是否继续下一条

[分镜宫格图引用处理]
    当提示词中包含分镜宫格图引用（如"@图片X为上一段视频(P07-S1)的分镜图"）时：
    
    1. 识别引用：解析提示词中的分镜图占位符，提取对应的 Shot 编号
    2. 定位文件：查找 outputs/<集数>/videos/P<编号>-S<Shot编号>_storyboard_3x3.jpg
    3. 作为 --image 传入：将分镜宫格图文件加入 --image 参数列表
    4. 重新编号：按 --image 上传顺序重新编号（分镜图 = @图片N，N 取决于它在 --image 列表中的位置）
    5. 替换提示词：将占位符中的原始 @图片编号替换为按上传顺序的新编号
    
    示例：
    提示词原文引用 @图片1（叶烬）、@图片2（灵曦）、@图片X（P07-S1分镜图）
    --image 顺序：char-叶烬.png, char-灵曦.png, P07-S1_storyboard_3x3.jpg
    → prompt 中：@图片1=叶烬，@图片2=灵曦，@图片3=分镜图

[查询已提交任务]
    如果需要查询之前提交的任务状态：
    
    ```bash
    dreamina query_result --submit_id=<submit_id>
    ```
    
    批量查看已保存任务：
    ```bash
    dreamina list_task --gen_status=success
    ```

[积分参考]
    - Seedance 2.0 multimodal2video：约 120 积分/次
    - 查询余额：dreamina user_credit

[注意事项]
    1. 每个视频必须经用户明确同意后才调用，绝不批量生成
    2. 每次生成前必须 read_file 重新读取最新提示词，禁止用缓存
    3. 不重复调用同一个 Shot（除非用户明确要求重新生成）
    4. 如果用户修改了提示词文件，下次生成时自动使用最新版本
    5. 生成失败时记录原因，不自动重试（等用户指示）
    6. poll 超时不等于失败，任务可能仍在生成中
    7. 视频文件保存在 outputs/<集数>/videos/ 目录下
    8. 文件命名格式：P<剧情点编号>-S<Shot编号>.mp4

[生成引擎切换]

    默认引擎：即梦 Dreamina CLI（dreamina multimodal2video, Seedance 2.0）
    备选引擎：ZenStudio CLI（zencli generate video, Zen-SD2.0, SubjectToVideo 主体驱动模式）

    用户可通过以下方式切换：
    - 「用 Zen 生成」「切换 Zen」「用 zencli 生成」→ 切换为 Zen-SD2.0
    - 「用即梦生成」「切回即梦」「用 dreamina 生成」→ 切回即梦（默认）
    - 未指定时默认使用即梦

    切换为 Zen-SD2.0 时的执行差异：
    
    1. 环境检查：改为 `which zencli`
    2. 素材上传：需先 `zencli upload` 所有参考图拿 CDN URL（即梦用本地路径，Zen 用 CDN URL）
    3. 命令构造：
       ```bash
       zencli generate video \
         --prompt '<提示词>' \
         --model 18 \
         --mode SubjectToVideo \
         --duration <时长> \
         --reference-assets '[{"url":"<URL1>"},{"url":"<URL2>"}]' \
         --enable-sound \
         --name '<Shot名称>' \
         -o json
       ```
    4. @图片N 重编号规则不变：按 reference-assets 数组中 URL 顺序重编号
    5. 任务轮询：改用 `zencli generate task <task_id> -o json`（提交→轮询→下载三步流程）
    6. 下载：改用 `zencli download <asset_id> -d <目录> -n <文件名>`
    7. 分镜宫格图生成：不变（同样调用 video-storyboard-skill）

    Zen-SD2.0 的优势：
    - 支持最多 9 张参考图（即梦也支持但有内容长度限制）
    - 支持 4-15s 灵活时长
    - SubjectToVideo 主体驱动模式更好保持角色一致性
    - 支持同时传入视频参考（最多 3 个）

    Zen-SD2.0 的注意事项：
    - 需要先 upload 获取 CDN URL，不能直接传本地路径
    - 不使用 --poll，改用 generate task 手动轮询（参见 zencli-skill）
    - reference-assets 格式为 JSON 数组：[{"url":"<CDN_URL>"}, ...]
