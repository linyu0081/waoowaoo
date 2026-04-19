---
name: dreamina-video-skill
description: AI 生视频·即梦（Dreamina）CLI 备选引擎。基于 shot-NN.json + asset-map.json，逐镜调用 `dreamina multimodal2video` 生成视频；下载后立刻截尾帧、记成本、回写 manifest。仅在 ai-producer 选择 engine=dreamina 时使用，默认引擎仍为 workrally。
trigger: ai-producer 选择 engine=dreamina 时；或用户在 `~video dreamina` 指令下触发；或需要排查已提交到即梦的任务
---

# AI 生视频技能 · 即梦 Dreamina CLI（备选引擎）

> 📌 **定位**：本项目默认生视频引擎是 **workrally**（详见 `workrally-skill`）。本 skill 仅在 ai-producer 明确选择 `engine=dreamina` 时被调用，属于**备选路径**，提示词结构、资产解析与成本记账规则与 workrally 保持完全一致，便于双引擎互切。

## 目录

1. 前置依赖与环境要求
2. 路径与数据源约定（本项目 V5 规范）
3. 默认参数
4. 素材解析规则（asset-map.json + shot-NN.json → --image 顺序）
5. 执行流程（单镜完整链路）
6. 分集流水线（配合 ai-producer 的依赖调度）
7. 成本记录（强制）
8. 排错 / 查询历史任务
9. 注意事项

---

## 1. 前置依赖与环境要求

### 1.1 即梦 CLI 安装

官方一键安装：

```bash
curl -s https://jimeng.jianying.com/cli | bash
export PATH="$HOME/.local/bin:$PATH"      # 写进 ~/.zshrc / ~/.bashrc
```

首次登录：

```bash
# 方式一：交互式登录（终端能持续等待时推荐）
dreamina login                # 自动打印授权链接并 poll 等待授权完成

# 方式二：headless 两步登录（Agent / CI 环境推荐）
# 第 1 步：打印授权材料后立即退出（不会 poll）
dreamina login --headless
# → 输出 verification_uri / user_code / device_code
# → 用户在浏览器打开 verification_uri 完成扫码授权

# 第 2 步：用户授权完成后，用 device_code 拉取 token
dreamina login checklogin --device_code=<device_code> --poll=60
# → 成功后输出 "OAuth 登录成功" + user_id / vip_level / total_credit

# 验证登录状态 & 查积分
dreamina user_credit
```

> ⚠️ **踩坑记录**：`--headless` 模式**只打印授权信息就退出**，不会自动 poll 等待用户扫码。必须分两步走：先 `--headless` 拿 `device_code`，用户在浏览器授权后，再执行 `checklogin --device_code=<code> --poll=60` 来完成 token 获取。如果 `checklogin` 返回"等待登录超时"，说明 device_code 已过期，需要重新执行 `dreamina login --headless` 获取新的 device_code。

### 1.2 运行环境

- **OS**：Linux / macOS 均可。
- **glibc**：**必须 ≥ 2.32**（即梦二进制对 libc 版本敏感）。
  - TencentOS 4 集成版（Kernel 6.6 / glibc ≥ 2.34）✅ 兼容
  - TencentOS 3 / CentOS 7 / 旧 TLinux（glibc 2.17~2.28）❌ 直接 `dreamina` 会 Segfault，必须升级系统
  - 校验命令：`ldd --version | head -1`
- **外网**：需要能访问 `*.jianying.com` / 即梦 CDN。
- **积分**：Seedance 2.0 `multimodal2video` 约 120 积分/条。

### 1.3 必须准备好的项目文件

| 文件 | 作用 |
|---|---|
| `projects/<项目>/outputs/<ep>/06-shots/shot-NN.json` | 每镜 20 字段提示词 |
| `projects/<项目>/outputs/<ep>/asset-map.json` | `@图片N / @音频N → 文件路径` 唯一映射表 |
| `projects/<项目>/assets/images/char-*.png / scene-*.png / prop-*.png` | 角色 / 场景 / 道具参考图 |
| `projects/<项目>/outputs/<ep>/tail-frames/tail-shot-NN.jpg` | 前置镜已落盘的尾帧（仅对带"本视频以@图片N为首帧"的镜要求） |

---

## 2. 路径与数据源约定（V5）

所有路径**一律相对项目根** `projects/<项目>/`，不要硬编码本机绝对路径：

```
projects/<项目>/
├── assets/
│   ├── images/                    # char-*.png / scene-*.png / prop-*.png
│   └── audio/                     # voice-*.mp3（通过 --audio 传入，最多 3 个，时长须 2-15 秒）
└── outputs/<ep>/
    ├── 06-shots/shot-NN.json      # ★ 单镜提示词数据源
    ├── asset-map.json             # ★ @图片N/@音频N 唯一编号表
    ├── videos/shot-NN.mp4         # 输出视频
    └── tail-frames/tail-shot-NN.jpg  # ★ 尾帧（本 skill 出完视频后截）
```

---

## 3. 默认参数

| 参数 | 值 | 说明 |
|---|---|---|
| command | `multimodal2video` | 多模态（图+文→视频） |
| `--model_version` | `seedance2.0` | 见下方模型列表 |
| `--ratio` | 取自 shot-NN.json 所在项目 config.videoRatio，默认 `16:9` | |
| `--video_resolution` | `720p` | Seedance 2.0 仅支持 720p（CLI 参数名为 `--video_resolution`，非 `--resolution`） |
| `--duration` | 从 `titleBar` 解析（如"15秒"→15），默认 15 | |
| `--poll` | `180`（秒） | 上限；超时走手动 `query_result` |

### 3.1 支持的模型版本（`--model_version`）

| 模型值 | 说明 | 备注 |
|---|---|---|
| `seedance2.0` | Seedance 2.0 标准版 | 默认推荐，质量最高 |
| `seedance2.0fast` | Seedance 2.0 快速版 | 速度更快，质量略低，适合快速预览 |
| `seedance2.0_vip` | Seedance 2.0 VIP 版 | ⚠️ 需要 VIP 权限，普通用户勿选 |
| `seedance2.0fast_vip` | Seedance 2.0 快速 VIP 版 | ⚠️ 需要 VIP 权限，普通用户勿选 |

> ⚠️ **踩坑记录**：`seedance2.0_vip` 和 `seedance2.0fast_vip` 需要 VIP 会员权限，非 VIP 用户提交会报错或扣更多积分。日常使用请选 `seedance2.0`（质量优先）或 `seedance2.0fast`（速度优先）。

### 3.2 模型选择来源（优先级从高到低）

每次调用时，`--model_version` 的最终值按以下顺序取第一个命中项：

1. **用户本次明确指定**（ai-producer 消息里说"用 seedance2.0-fast 生成"等）
2. **项目级偏好** `projects/<项目>/config.json` 的 `modelPreferences.video.dreamina`
   - 字段缺失或值为空字符串视为"未配置"，继续往下 fallback
   - 写入格式**不限连字符**：`seedance2.0-fast` / `seedance2.0fast` / `seedance2.0_fast` 等都接受；ai-producer 调 CLI 前统一规范化为 CLI 认的值（去掉连字符/下划线，即 `seedance2.0fast`）
3. **skill 默认值**：`seedance2.0`（见上方 3.1 默认推荐）

> 📌 **读取时机**：在第 2 步构造命令**之前**读取 `config.json`，不要缓存；用户可能临时改 config。
> 📌 **图片/workrally 同理**：`modelPreferences.image.*`、`modelPreferences.video.workrally` 对应各自 skill 的读取逻辑，本 skill 不直接消费。

---

## 4. 素材解析规则

### 4.1 加载 asset-map

```
assetMap = json.load(projects/<项目>/outputs/<ep>/asset-map.json)
```

得到 `@图片N → {type, name, file}` 的字典。`file` 是相对项目根的路径。

### 4.2 从 `shot-NN.json.mount` 提取引用

mount 例子：

```
挂载：角色：马上@图片1｜马前卒@图片2｜马后炮@图片3｜场景：演播室-日@图片17｜声音：马上声音@音频1｜马前卒声音@音频2｜马后炮声音@音频3｜本视频以@图片37为首帧
```

解析动作：

1. 用正则 `@图片(\d+)` 依出现顺序取出所有编号，**去重后保留首次出现顺序**
2. 用正则 `@音频(\d+)` 取出音频编号，通过 `assetMap["@音频N"]` 解析到本地音频文件路径，作为 `--audio` 参数传入（CLI 支持 `--audio`，最多 3 个，音频时长须 2-15 秒）
3. 构造 `--audio` 参数：按 mount 中 `@音频N` 的出现顺序，依次将 `assetMap["@音频N"].file` 作为 `--audio` 传入
4. 检查 mount 末尾是否存在 `本视频以@图片N为首帧`：
   - 若有，对应 `assetMap["@图片N"]` 必须满足 `type === "tail-frame"`
   - 该 tail-frame 的 `file` 必须在磁盘上真实存在，否则**中止**本镜生成，向 ai-producer 报"前置依赖未就绪"，由上层调度

### 4.3 构造 `--image` 顺序 & @图片N 重编号（⚠️ 即梦的硬规矩）

即梦 CLI 的 `@图片N` 引用**按 --image 的传入顺序重新编号**：第 1 个 `--image` = `@图片1`，第 2 个 = `@图片2`，依此类推。因此：

1. 按 mount 中 @图片N 的**首次出现顺序**依次排列，得到有序列表 `[N1, N2, ...]`
2. 构造 `images = [assetMap[f"@图片{Ni}"].file for Ni in [N1,N2,...]]`（全部转为相对项目根的路径）
3. 建立重编号映射：`原始编号 Ni → 新编号 i+1`
4. **对 prompt 正文与 mount 引用做整体 `@图片Ni → @图片{i+1}` 替换**（用倒序替换或一次性正则替换避免串号）
5. tail-frame 也是一张图，按它在 mount 中的位置编进 images 列表，不做特殊处理

### 4.4 prompt 组装（与 workrally 对齐的 20 字段拼装）

将 shot-NN.json 的 20 字段按固定顺序拼成一个整体 prompt 文本，作为 `--prompt` 传入：

```
【titleBar】{titleBar}
【mount】{mount}            # ⚠️ 这里的 @图片N 已重编号
【camera】{camera}
【openingFrame】{openingFrame}
【closingFrame】{closingFrame}
【connection】{connection}
【transition】{transition}
【dualAnchor】{dualAnchor}
【mainPrompt】{mainPrompt}   # ⚠️ 这里的 @图片N 已重编号；对白原文保留
【compulsoryDeclaration】{compulsoryDeclaration}
【mustShow】{mustShow}
【qualityRoute】{qualityRoute}
【imagingStyle】{imagingStyle}
【qualityBaseline】{qualityBaseline}
【reference】{reference}
【microExpressions】{microExpressions}
【nailLines】{nailLines}
【e15】{e15}
```

空字段可保留空行或直接省略该字段块（推荐省略）。

---

## 5. 执行流程（单镜完整链路）

> 以下用 shell 伪代码说明；实际执行时由 Agent 动态生成每镜的具体命令。`PROJECT`, `EP`, `IDX` 为三个关键变量（示例：`PROJECT=马上看中国史`, `EP=ep01`, `IDX=07`）。

### 第 0 步 · 自动刷新"生成中"任务（每次生视频前必做）

每次执行生视频前，先扫描所有 shot-NN.json，对 `videoTask.status === "generating"` 的镜批量查询状态：

```bash
# 对每个 generating 的镜：
dreamina query_result --submit_id=<taskId>
```

根据查询结果更新 shot-NN.json：
- **成功** → 下载视频 → 截尾帧 → 更新 `status="done"` + `videoUrl` + `videoFile` + `tailFrame` + `completedAt`
- **失败** → 更新 `status="failed"` + `failReason` + `completedAt`
- **仍在生成** → 保持 `status="generating"`，不动

刷新完毕后向用户汇报：
```
📊 任务状态刷新：
 ✅ shot-03, shot-05 已生成完成（已下载+截尾帧）
 ⏳ shot-07 仍在生成中
 ❌ shot-09 生成失败：<原因>
```

### 第 1 步 · 环境预检

```bash
which dreamina                              # 必须有
dreamina user_credit                        # 必须登录 & 积分 ≥ 120
test -f "projects/$PROJECT/outputs/$EP/06-shots/shot-$IDX.json"
test -f "projects/$PROJECT/outputs/$EP/asset-map.json"
mkdir -p "projects/$PROJECT/outputs/$EP/videos"
mkdir -p "projects/$PROJECT/outputs/$EP/tail-frames"
```

### 第 2 步 · 构造命令并提交

（Agent 在内部解析好 images[]、audios[]、prompt、duration、ratio 后，拼出如下命令）

```bash
dreamina multimodal2video \
  --image "projects/$PROJECT/assets/images/char-马上.png" \
  --image "projects/$PROJECT/assets/images/char-马前卒.png" \
  --image "projects/$PROJECT/assets/images/char-马后炮.png" \
  --image "projects/$PROJECT/assets/images/scene-演播室.png" \
  --image "projects/$PROJECT/outputs/$EP/tail-frames/tail-shot-00.jpg" \
  --audio "projects/$PROJECT/assets/audio/voice-马上.mp3" \
  --audio "projects/$PROJECT/assets/audio/voice-马前卒.mp3" \
  --prompt "$PROMPT_TEXT" \
  --model_version seedance2.0 \
  --duration 15 \
  --ratio 16:9 \
  --poll 180 \
  2>&1 | tee /tmp/dreamina-$EP-$IDX.log | tail -40
```

> ⚠️ `--prompt` 的单引号转义：推荐用 Python `subprocess.run(list_args)` 避免 shell 引号地狱；若必须用 shell，统一用双引号包裹并对内部 `"` 做 `\"` 转义。
>
> ⚠️ `--audio` 参数：mount 中的 `@音频N` 引用对应的音频文件通过 `--audio` 传入（最多 3 个），音频时长须在 2-15 秒范围内。`@音频N` 按 `--audio` 传入顺序编号（第 1 个 `--audio` = `@音频1`，第 2 个 = `@音频2`，以此类推），与 `@图片N` 的重编号逻辑一致。
>
> ⚠️ **统一命名**：shot-NN.json 的 mount、asset-map.json 的 voices key、以及提交给即梦 CLI 的 prompt 中，音频引用**统一使用 `@音频N`**（不是 `@声音N`）。这是即梦 CLI 识别音频素材的格式。

### 第 2.5 步 · 写入 videoTask（提交成功后立即执行）

> **提交成功**的判定见下方 3.1 节硬规则：**拿到 submit_id 即算提交成功**，不依赖 `gen_status`；轮询超时不等于提交失败。

提交成功后，立即更新 `shot-NN.json` 的 `videoTask` 字段：

```json
{
  "videoTask": {
    "engine": "dreamina",
    "modelName": "seedance2.0",
    "taskId": "<submit_id>",
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
- 即梦引擎：取 `--model_version` 的值，如 `"seedance2.0"`、`"seedance2.0-fast"`
- 如果用户指定了其他模型版本，如实填写

同时更新 `manifest.stages.video`：
- `generating` 计数 +1
- `pending` 计数 -1
- `videoGenCount` +1

### 第 3 步 · 解析返回

#### 3.1 提交成功的判定（硬规则，别搞混）

**"提交成功" ≠ "视频生成成功"**，必须分两段看：

| 阶段 | 判定信号（同时满足即算成功） | 说明 |
|---|---|---|
| **提交成功**（本 skill 关注） | 日志里拿到合法的 `submit_id`（UUID 形式，如 `c79e1332-20bd-453f-8892-ecc03cd52dd0`），且 CLI 进程返回码为 0，且日志里没有出现 `提交失败` / `submit_fail` / `账号未登录` / `credit` 相关报错 | 说明即梦服务端已收下任务进入队列 |
| **生成成功**（第 6 步关注） | `gen_status=success` + `video_url` 非空 | 说明队列中的任务渲染完毕 |

**实操判定流程**：
1. 先在 `/tmp/dreamina-$EP-$IDX.log` 里 grep `submit_id`（推荐精确匹配 `submit_id=` 或 JSON 里的 `"submit_id"`），拿到 UUID 就算**提交成功**，立刻执行 2.5 步写入 videoTask（`status=generating` + `taskId=<submit_id>`）
2. **不要**把"轮询超时 / `gen_status=querying`"当作提交失败。轮询超时只是"还没渲染完"，这时候 submit_id 已经存在、任务已在即梦队列里
3. **也不要**把"没有 `gen_status=success`"当作提交失败，同理
4. 只有两种情况才算**提交失败**（此时**不写** videoTask，状态保持 `pending`）：
   - 日志里根本没有 `submit_id`
   - 日志里显式出现 `提交失败` / `submit_fail` / 账号或积分相关 ERROR

#### 3.2 常见现象与应对

| 现象 | 分类 | 处理 |
|---|---|---|
| 拿到 submit_id + `gen_status=success` + `video_url` | 提交成功 + 生成成功 | 进入第 4 步 |
| 拿到 submit_id + `gen_status=querying`（达到 `--poll` 上限） | 提交成功 + 渲染中 | videoTask 在 2.5 步已写入 `generating`，留着等第 0 步下次刷新；**不要回滚成 pending** |
| 拿到 submit_id + `gen_status=fail` | 提交成功 + 生成失败 | 更新 `videoTask.status="failed"` + `failReason` + `completedAt`，把 `fail_reason` 丢给 ai-producer，不自动重试 |
| 日志里**没有** submit_id，且有 ERROR | 提交失败 | **不写** videoTask，保持 `pending`；把错误原文丢给 ai-producer，由用户决定是否重试 |
| 多镜批量提交后，只有部分镜拿到 submit_id | 提交失败（部分） | 对没拿到 submit_id 的镜**不写** videoTask；见下方"批量提交排查清单" |

#### 3.3 账号并发上限（已验证实锤）

**结论：即梦同账号 + 同队列（同模型 + 分辨率/尺寸组合）同时只能有 1 个任务真正在"生成中"。**

一次批量提交 5 个 `seedance2.0fast` 任务（2026-04-19 实测），结果：

| 任务 | `gen_status` | `queue_info` |
|---|---|---|
| 第 1 个（最早提交） | `querying` | `queue_status=Generating`, `queue_idx=0`（正在跑） |
| 第 2~5 个 | `querying` | **没返回 queue_info 块**（还没进入调度队列） |

队列标识（从 `debug_info` 读到）：`dreamina_matrix_queue_name=dreamina_fusion_video40`，请求键 `DreaminaFusion:Video40_unified_edit_720p` —— 同模型+同分辨率共用同一个队列。

##### 提交成功 ≠ 正在生成

- **拿到 submit_id 就是提交成功**（参见 3.1 节），这条仍然成立
- 但 `gen_status=querying` 有两种子状态，`query_result` 返回体能区分：
  - `queue_info.queue_status=Generating` → 真正在渲染，等结果就行
  - **没有 queue_info 块** → 还在账号级预队列排队，前面的 Generating 任务跑完才会调度这一批
- 即梦 Web 首页/dashboard 可能**只展示真正 Generating 的 1 个**，其余 4 个任务即使在服务端已经接收，前端也可能不亮—— 这不是提交失败，是展示策略

##### 操作建议

- **不需要**刻意串行提交，5 镜批量一次性提交下去是 OK 的，任务都安全落库了
- 但提交完**别期待**同时看到 5 个视频进度条；预计节奏 ≈ 首镜完成前所有后续镜都在 querying 预队列
- 仪表盘必须识别这三种细分状态并分别显示：`querying(预队列)` / `Generating(渲染中)` / `done` / `failed`
- 轮询刷新脚本读到 `gen_status=querying` 时，看 `queue_info.queue_status` 区分"渲染中 vs 预队列"

##### 查询状态字段速查

| 字段 | 位置 | 含义 |
|---|---|---|
| `gen_status` | 顶层 | `querying` = 在途未出片；`done` = 成功；`fail` / 空 = 失败 |
| `queue_info.queue_status` | 嵌套（可能缺失） | `Generating` = 真正在渲染；缺失 = 还在账号级预队列 |
| `queue_info.queue_idx` | 嵌套 | 0 = 当前正在处理；>0 = 在队列里第 N 位 |
| `video_url` | 顶层 | 出片后有值，拿到就可以下载 |
| `fail_reason` | 顶层 | 失败原因，空串即未失败 |

##### 遗留排查项（仍待后续观察）

- [x] **提交成功 ≠ 入队**：存在服务端静默丢单的情况（见 3.4 节）
- [ ] 不同模型队列是否独立？初步假设 `seedance2.0` 与 `seedance2.0fast` 各占独立队列（可并行），未实测确认
- [ ] 单次批量超过 N 次（N=?）是否会触发额外限流（当前 5 次批量无问题）

#### 3.4 静默丢单（silent drop）与 stuck 状态（已验证实锤）

**现象**：批量提交 5 个任务时，首镜进入 Generating，后 4 个镜 `query_result` 长时间返回：

```
gen_status: "querying"
queue_info: null          ← 关键：完全没有 queue_info 块
result_json.videos: []
fail_reason: null
```

即梦 Web 首页也完全不显示这 4 个任务。**过 10+ 分钟依然无变化** → 判定为服务端静默丢单（不报错、不消耗、不执行）。

##### 判定规则（硬规范）

对 `status="generating"` 的镜，轮询状态时按如下决策：

| `gen_status` | `queue_info` | `提交时间差` | → 判定 | inflight 计数 |
|---|---|---|---|---|
| `success` + 有 `video_url` | — | — | **done** | 0 |
| `fail` / 有 `fail_reason` | — | — | **failed** | 0 |
| `querying` | `queue_status=Generating` | — | **rendering**（真渲染） | 1 |
| `querying` | 有 `queue_info` 但非 Generating（Waiting/Queueing） | — | **queuing**（已入队） | 1 |
| `querying` | `null` / 缺失 | ≤ 10 min | **queuing**（刚提交，耐心等） | 1 |
| `querying` | `null` / 缺失 | > 10 min | **stuck**（静默丢单） | **0** |

`stuck` 是 `videoTask.status` 的合法终态值（与 `done/failed/generating/pending` 并列），不占 inflight，等待人工重投。

##### 调度器行为

- 每次心跳先扫全部 `generating` 镜，按上表更新 `videoTask.status` / `queueStatus` / `queueIdx`
- 遇到 `stuck` 镜：释放 slot + 写 `failReason="提交后 10+ 分钟仍未进入即梦队列，疑似服务端静默丢单"`
- dashboard 候补池面板顶部会显示 `🔴 卡死 N`，卡片显示"🔄 重投到候补池"按钮
- 用户点击重投时：**先清空 videoTask → 再把 shot 推入 waitList 头**，下次心跳自然重新提交（拿新的 submit_id）

---

## 调度器（video_scheduler）使用说明

### 职责

按固定心跳（默认 10min）：
1. 刷新所有 generating 镜状态（按 3.3/3.4 节规则区分 rendering/queuing/stuck）
2. 若 `inflight < maxInflight` 且队列未暂停，从 waitList 头部找第一个"前镜尾帧依赖已就绪"的镜，调用 dreamina CLI 提交
3. 成功/失败都从 waitList 移除并写 history；**失败不自动重试**

### 文件与路径

| 文件 | 作用 |
|---|---|
| `scripts/video_submit.py` | 单镜提交的公共库（构造 prompt/images/audios → 调 CLI → 写 videoTask） |
| `scripts/video_scheduler.py` | 调度器主脚本 |
| `scripts/refresh_video_status.py` | 只刷新不提交（手动查看状态用） |
| `projects/<项目>/outputs/<ep>/video-queue.json` | 候补池清单（人可直接改） |
| `projects/<项目>/outputs/<ep>/video-scheduler.log` | 心跳日志 |
| `scripts/systemd/dreamina-scheduler@.{service,timer}` | systemd 定时器模板 |

### 候补池 JSON 结构

```json
{
  "maxInflight": 1,
  "paused": false,
  "defaultModel": "seedance2.0fast",
  "defaultRatio": "16:9",
  "waitList": [
    {"shot":"02","model":"","ratio":"","note":"","addedAt":"..."}
  ],
  "history": [
    {"shot":"00","submit_id":"...","result":"submitted|failed","reason":"","at":"...","model":"..."}
  ],
  "lastHeartbeat": "..."
}
```

### 运行方式

**单次执行（推荐）**：
```bash
python3 scripts/video_scheduler.py --project "马上看中国史" --ep ep01
```

**systemd user timer（生产推荐，5 分钟周期）**：

> ⚠️ 不要用 `systemd-escape "中文名___epNN"` 做实例名——`%i` 会被 systemd 解析成 `\xHH` 字面字符串传到 shell 拿不回中文，导致路径错乱。
> 本项目采用"英文别名实例 + EnvironmentFile 传真实中文项目名"的方式规避。

```bash
# 1) 建环境文件（每项目一份；实例名任取英文别名）
mkdir -p ~/.config/dreamina-scheduler
cat > ~/.config/dreamina-scheduler/msckcs-ep01.env << 'EOF'
PROJECT=马上看中国史
EP=ep01
EOF

# 2) 安装 unit（service 里已显式写 PATH=/root/.local/bin:...，保证 dreamina CLI 可见）
cp scripts/systemd/dreamina-scheduler@.service ~/.config/systemd/user/
cp scripts/systemd/dreamina-scheduler@.timer   ~/.config/systemd/user/
systemctl --user daemon-reload

# 3) 启动 timer（实例名 = env 文件 basename）
systemctl --user enable --now dreamina-scheduler@msckcs-ep01.timer

# 4) 开 linger，退出登录后 timer 继续跑
loginctl enable-linger root

# 查看
systemctl --user list-timers 'dreamina-scheduler@*'
journalctl --user -u dreamina-scheduler@msckcs-ep01.service -n 30 --no-pager
```

**Dashboard 立即触发**：视频 tab 候补池面板右侧"⚡ 立即心跳"按钮（走 `POST /api/video-queue/trigger`，服务端 fork 异步跑）。

**Dashboard 修改心跳周期**：候补池面板右侧"⏱ 周期"输入框（1-120 分钟）+ "保存周期"按钮（走 `POST /api/scheduler/config {action:set, intervalMin}`，会改 `.timer` 文件 + `daemon-reload` + `restart timer`）。默认实例名 `msckcs-ep01`，如有多项目需在 serve 端扩展。

**Dashboard 视频 tab 顶部状态筛选条**：支持 `全部 / 已完成 / 进行中 / 候补 / ⚡可立即提交 / 待处理 / 失败/卡死` 几个类别一键筛选。
- **⚡可立即提交**：pending 态且"首帧依赖已就绪"（无依赖 OR 依赖源 shot 已 done OR 走用户素材）—— 对应调度器 `next_submittable` 判定，便于人工挑选下一批要入池的镜。

### 首帧依赖调度策略

- waitList 按顺序扫描，**跳过**尾帧未就绪的镜（不阻塞后面的无依赖镜）
- 当所有候选都被依赖阻塞时本轮不提交
- 这样可以把"必须先跑完 shot-5 才能跑 shot-6"这种链式依赖和"独立无依赖"的镜混在同一个 waitList 里自然调度

### Dashboard 操作入口（视频 tab）

- 卡片"⬜ 待提交" → 点"📋 加入候补池"
- 卡片"❌ 失败/🔴 卡死" → 点"🔄 重投到候补池"（自动清 videoTask 再入池）
- 卡片"📋 候补中" → 点"✖ 移出候补池"
- 候补池面板 → "⏸ 暂停 / ▶ 恢复 / ⚡ 立即心跳"

### 第 4 步 · 下载到本项目路径

```bash
curl -L -o "projects/$PROJECT/outputs/$EP/videos/shot-$IDX.mp4" "$VIDEO_URL"
```

> 命名一律 `shot-NN.mp4`（两位前导零），与 `shot-NN.json` / `tail-shot-NN.jpg` 三件套对齐，不再使用旧的 `P<X>-S<Y>.mp4` 命名。

### 第 5 步 · 截尾帧（硬规范）

下载成功后立即截取尾帧，路径必须与 `asset-map.json` 里对应 `type==="tail-frame" && fromShot===NN` 条目的 `file` 完全一致：

```bash
ffmpeg -sseof -0.1 \
  -i "projects/$PROJECT/outputs/$EP/videos/shot-$IDX.mp4" \
  -frames:v 1 -update 1 -q:v 2 -y \
  "projects/$PROJECT/outputs/$EP/tail-frames/tail-shot-$IDX.jpg"
```

> 参考 `video-edit-skill` 的「单镜尾帧提取」。失败需在本镜返回体里标 `tailFrameFailed=true`，由 ai-producer 决定是否回退整个镜。

### 第 6 步 · 记账（强制）

读取 shot-NN.json 的 titleBar 得到 duration（秒），然后：

```bash
python scripts/cost-logger.py video \
  --project "$PROJECT" \
  --episode "$EP" \
  --target "shot-$IDX" \
  --model dreamina-seedance2.0 \
  --duration $DURATION \
  --task-id "$SUBMIT_ID" \
  --note "dreamina multimodal2video"
```

> - `--model` 统一填 `dreamina-seedance2.0`（与 workrally 区分）
> - 同一 shot 重复调用脚本会自动识别 `isRegenerate=true`，不计入去重成片数与总时长
> - 失败任务不登记；仅在视频真正下载 + 尾帧成功 时登记

### 第 6.5 步 · 更新 videoTask 为完成状态

下载 + 截尾帧 + 记账全部成功后，更新 `shot-NN.json` 的 `videoTask`：

```json
{
  "videoTask": {
    "engine": "dreamina",
    "modelName": "seedance2.0",
    "taskId": "<submit_id>",
    "status": "done",
    "videoUrl": "<远端URL>",
    "videoFile": "outputs/<ep>/videos/shot-NN.mp4",
    "tailFrame": "outputs/<ep>/tail-frames/tail-shot-NN.jpg",
    "failReason": "",
    "creditCount": 120,
    "submittedAt": "<提交时间>",
    "completedAt": "<当前ISO时间>"
  }
}
```

同时更新 `manifest.stages.video`：
- `produced` +1
- `generating` -1

### 第 7 步 · 返回给 ai-producer

```json
{
  "index": NN,
  "status": "done",
  "engine": "dreamina",
  "modelName": "seedance2.0",
  "videoFile": "outputs/<ep>/videos/shot-NN.mp4",
  "tailFrame": "outputs/<ep>/tail-frames/tail-shot-NN.jpg",
  "submitId": "…",
  "creditCount": 120,
  "durationSec": 15
}
```

---

## 6. 分集流水线（配合 ai-producer）

- **串行模式**（`parallel=false`，推荐）：按 IDX 升序逐镜走上面的 1→7；尾帧按镜自然满足下一镜首帧依赖。
- **并行模式**（`parallel=true`）：
  1. 先把 mount 里**不含**"本视频以@图片N为首帧"的镜全部并发提交
  2. 监听 shot-NN.mp4 落盘事件，每落盘一条立即截尾帧
  3. 对带首帧依赖的镜：遍历依赖边 `shot-X 依赖 shot-Y 的 tail-frame`；当 `tail-shot-YY.jpg` 就绪，再提交 shot-X
- **断点续做**：`startShot=NN` 时，如果 shot-NN 的 mount 含首帧依赖，ai-producer 必须先确认 `tail-shot-(N-?).jpg` 已存在于磁盘，否则直接报错

---

## 7. 成本记录约定

统一用 `scripts/cost-logger.py`：

| 场景 | 命令 |
|---|---|
| 生成 1 条视频并下载成功 | `python scripts/cost-logger.py video --project <项目> --episode <epNN> --target shot-NN --model dreamina-seedance2.0 --duration <秒> --task-id <submit_id>` |
| 重新生成同一 shot | 同上；脚本自动标 `isRegenerate=true`，不影响去重成片数 |
| 失败 / 超时未下载成功 | **不登记** |

流水会落盘到 `projects/<项目>/outputs/<ep>/07-costs.json` 并自动回写 `manifest.stages.video`，dashboard 直接消费。

---

## 8. 历史任务查询

```bash
# 查单条
dreamina query_result --submit_id=<submit_id>

# 列出本机已保存的成功任务
dreamina list_task --gen_status=success
```

轮询超时后重新查并下载的路径不变（第 4→5→6 步一致）。

---

## 9. 注意事项

1. **每条视频必须经 ai-producer 或用户明确同意后才调**，不批量盲跑
2. **每次调用前必须 re-read `shot-NN.json` 与 `asset-map.json`**，严禁使用上下文缓存——用户随时可能改文件
3. 不重复生成已成功的 shot（除非用户明确 "重做 shot-NN"）
4. `--poll` 超时 ≠ 失败；任务可能仍在即梦侧生成中，按"8. 历史任务查询"走
4.1 **提交成功 ≠ 生成成功**：前者只看日志里是否拿到 `submit_id`（见"第 3 步 · 3.1 提交成功的判定"硬规则），后者看 `gen_status=success` + `video_url`；两件事不要搞混，也不要因为轮询超时就回滚 videoTask 成 pending
5. prompt 里**保留对白原文**（中文"xxx"："xxx"这种），不要删
6. 本 skill **不处理剪辑 / 拼接 / 字幕**，相关需求走 `video-edit-skill`
7. 旧版 skill 里的 `P<X>-S<Y>.mp4` 命名已废弃；统一 `shot-NN.mp4`
8. 旧版里的 `outputs/<ep>/images/` 路径已废弃；本项目真实资产目录是 `projects/<项目>/assets/images/`（跨集池化）
9. dashboard / manifest / cost 等所有下游消费者只认 `shot-NN.mp4` + `tail-shot-NN.jpg` 的命名，请务必保持一致

---

## 附录 A · workrally vs dreamina 双引擎对照

| 维度 | workrally（默认） | dreamina（备选） |
|---|---|---|
| CLI | `workrally generate video --model 18 --mode SubjectToVideo` | `dreamina multimodal2video --model_version seedance2.0` |
| 参考图传法 | 先 upload 拿 CDN URL，再 `--reference-assets '[{"url":...}]'` | 直接 `--image 本地路径`（多次） |
| 流程 | 提交→轮询→下载三步 | 单条命令 `--poll` 一把梭（超时走手动 query） |
| 对白保留 | 一致 | 一致 |
| 尾帧截取 | 视频落盘后立即 ffmpeg 截 | 视频落盘后立即 ffmpeg 截 |
| 成本 `--model` 填 | `18`（provider id） | `dreamina-seedance2.0` |
| tail-frame 文件命名 | `tail-shot-NN.jpg` | `tail-shot-NN.jpg` |
| videoTask.engine | `"workrally"` | `"dreamina"` |
| videoTask.modelName | `"Zen-SD2.0"` / `"Zen-01-1.5pro"` / `"Zen-02.3.0"` 等 | `"seedance2.0"` / `"seedance2.0fast"` 等（取 `--model_version` 的值） |
| videoTask.taskId 来源 | `task_id`（generate video 返回） | `submit_id`（multimodal2video 返回） |
| 状态查询 | `workrally generate task <taskId> -o json` | `dreamina query_result --submit_id=<taskId>` |

切换方式：由 ai-producer 根据用户在 `~video workrally` / `~video dreamina` 时传入的 engine 决定；单镜失败可回退另一引擎重试。
