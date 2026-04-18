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
dreamina login --headless     # 扫码
dreamina user_credit          # 验证登录状态 & 查积分
```

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
| `projects/<项目>/outputs/<ep>/asset-map.json` | `@图片N / @声音N → 文件路径` 唯一映射表 |
| `projects/<项目>/assets/images/char-*.png / scene-*.png / prop-*.png` | 角色 / 场景 / 道具参考图 |
| `projects/<项目>/outputs/<ep>/tail-frames/tail-shot-NN.jpg` | 前置镜已落盘的尾帧（仅对带"本视频以@图片N为首帧"的镜要求） |

---

## 2. 路径与数据源约定（V5）

所有路径**一律相对项目根** `projects/<项目>/`，不要硬编码本机绝对路径：

```
projects/<项目>/
├── assets/
│   ├── images/                    # char-*.png / scene-*.png / prop-*.png
│   └── audio/                     # voice-*.mp3（本 skill 不传音频，仅 asset-map 里做映射）
└── outputs/<ep>/
    ├── 06-shots/shot-NN.json      # ★ 单镜提示词数据源
    ├── asset-map.json             # ★ @图片N/@声音N 唯一编号表
    ├── videos/shot-NN.mp4         # 输出视频
    └── tail-frames/tail-shot-NN.jpg  # ★ 尾帧（本 skill 出完视频后截）
```

---

## 3. 默认参数

| 参数 | 值 | 说明 |
|---|---|---|
| command | `multimodal2video` | 多模态（图+文→视频） |
| `--model_version` | `seedance2.0` | 与 workrally Zen-SD2.0 对齐的同源能力 |
| `--ratio` | 取自 shot-NN.json 所在项目 config.videoRatio，默认 `16:9` | |
| `--resolution` | `720p` | Seedance 2.0 仅支持 720p |
| `--duration` | 从 `titleBar` 解析（如"15秒"→15），默认 15 | |
| `--poll` | `180`（秒） | 上限；超时走手动 `query_result` |

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
挂载：角色：马上@图片1｜马前卒@图片2｜马后炮@图片3｜场景：演播室-日@图片17｜声音：马上声音@声音1｜马前卒声音@声音2｜马后炮声音@声音3｜本视频以@图片37为首帧
```

解析动作：

1. 用正则 `@图片(\d+)` 依出现顺序取出所有编号，**去重后保留首次出现顺序**
2. 用正则 `@声音(\d+)` 取出声音编号（仅做映射记录，不传给 `--image`）
3. 检查 mount 末尾是否存在 `本视频以@图片N为首帧`：
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

（Agent 在内部解析好 images[]、prompt、duration、ratio 后，拼出如下命令）

```bash
dreamina multimodal2video \
  --image "projects/$PROJECT/assets/images/char-马上.png" \
  --image "projects/$PROJECT/assets/images/char-马前卒.png" \
  --image "projects/$PROJECT/assets/images/char-马后炮.png" \
  --image "projects/$PROJECT/assets/images/scene-演播室.png" \
  --image "projects/$PROJECT/outputs/$EP/tail-frames/tail-shot-00.jpg" \
  --prompt "$PROMPT_TEXT" \
  --model_version seedance2.0 \
  --duration 15 \
  --ratio 16:9 \
  --poll 180 \
  2>&1 | tee /tmp/dreamina-$EP-$IDX.log | tail -40
```

> ⚠️ `--prompt` 的单引号转义：推荐用 Python `subprocess.run(list_args)` 避免 shell 引号地狱；若必须用 shell，统一用双引号包裹并对内部 `"` 做 `\"` 转义。

### 第 3 步 · 解析返回

从日志里抓 `submit_id` / `gen_status` / `fail_reason` / `video_url` / `credit_count`。

- `gen_status=success` → 进入第 4 步
- `gen_status=querying` + 达到 `--poll` 上限 → 记 `submit_id` 挂起（交 ai-producer 决定是否继续轮询或跳过）
- `gen_status=fail` → 把 `fail_reason` 丢给 ai-producer，不自动重试

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

### 第 7 步 · 返回给 ai-producer

```json
{
  "index": NN,
  "status": "done",
  "engine": "dreamina",
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

切换方式：由 ai-producer 根据用户在 `~video workrally` / `~video dreamina` 时传入的 engine 决定；单镜失败可回退另一引擎重试。
