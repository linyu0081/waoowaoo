---
name: workrally-batch-guide
description: WorkRally 批量生视频操作手册——当需要用 workrally 并发救场／批量复跑一组分镜时遵循此文档。
version: v1.0（2026-04-20）
依赖: workrally-skill（CLI 调用规范）
适用场景:
  - 心跳队列里反复失败、需要 workrally 多图主体驱动兜底的一批分镜
  - 已确认参数 OK 后的并发批量执行（非首跑，首跑需按 workrally-skill 单镜确认流程）
---

# WorkRally 批量生视频操作手册

> 前置阅读：`.claude/skills/workrally-skill/skill.md`
> 本文档只覆盖**批量流程**，不重复 CLI 本身的规范。

---

## 一、触发条件（何时可以批量）

✅ **可以批量**：
  1. 用户明确给出一组 shot-NN 清单（≥2 镜）
  2. 该批次中至少 1 镜已走过 workrally 单镜确认流程，用户确认"效果 OK 可复用该参数方案"
  3. 默认方案固化为：
     - engine = workrally
     - model  = 18（Zen-SD2.0）
     - mode   = SubjectToVideo（全能参考）
     - promptMode = full（完整 18 段；优先读 `.json.bak` 最老备份）
     - `--enable-sound`
     - `duration = min(titleBar解析时长, 15)`

❌ **禁止批量**（必须逐个单镜确认）：
  1. 参考图路径/命名规范未稳定的新项目
  2. 用户未确认任何样片的首跑
  3. 同一批次里有镜头要求特殊参数（e.g. FirstLastFrame / Text 模式混用）
  4. 单批次超过 8 镜一次性提交（API 侧配额风险，建议每批 ≤6）

---

## 二、标准批量流程（4 阶段）

### 阶段 1｜前探查（串行，必做）

对批次内每一镜并行查以下 4 项：

```bash
# 1. 备份是否齐全（优先用 .bak 最老版）
ls -la outputs/<ep>/06-shots/shot-NN.json*

# 2. mount 字段 + assetRefs 完整性
python3 -c "import json;d=json.load(open('.../shot-NN.json.bak'));print(d['mount']);print(d['assetRefs'])"

# 3. 时长（titleBar 第一个"N秒"）
#    若 > 15 → 标记该镜需剪到 15 内再提交（或跳过）

# 4. 首帧资产是否存在（挂载里有 @图片X 指向 tail-frames/tail-shot-M.jpg）
ls outputs/<ep>/tail-frames/tail-shot-M.jpg
```

**前探查报告模板**：
```
| shot | 时长 | 角色 | 场景 | 首帧 | .bak | 备注 |
|------|------|------|------|------|------|------|
| 13   | 12s  | ✅   | ✅   | 无   | ✅   | OK   |
| 16   | 14s  | ✅   | ✅   | @51  | ✅   | OK   |
```

### 阶段 2｜通用单镜执行脚本（已沉淀）

脚本位置：`scripts/_workrally_one_shot.py`

调用：
```bash
python3 scripts/_workrally_one_shot.py <shot_num>
```

脚本内部的完整流程：
1. 读 `shot-N.json.bak`（最老备份）作为 prompt 源
2. **参考图解析**（⚠️ 本文档 v1.0 关键修复项，见"已知陷阱 #1"）
3. 逐一 `workrally upload` 拿 CDN URL，建立 `@图片旧号 → @图片新号` 重编号映射
4. 按 full 模式拼 18 段 prompt（同时把 mainPrompt 里的 @图片N / @音频N 按映射重写）
5. 提交 workrally generate video（默认参数见第一节）
6. 立即把 taskId + 全部 ref URLs 写回 `shot-N.json.videoTask`（status=generating）
7. 15s 间隔轮询（最多 ~15 分钟）
8. SUCCESS → 下载 → ffmpeg 截尾帧 → 回写 status=done + videoFile + tailFrame
9. FAILED  → 回写 status=failed + failReason + needsRework=true + 追加 failHistory
10. 末尾调用 `scripts/cost-logger.py video ...` 记账

### 阶段 3｜并发编排（utilize workrally 多任务并发）

workrally 支持多任务并发，心跳队列**不适用**，改用 shell `setsid` 后台并发：

```bash
mkdir -p tmp/wr_logs

# 先单独跑第 1 镜，人肉等出片确认效果
setsid bash -c 'cd $WORKSPACE && python3 scripts/_workrally_one_shot.py 13 \
  > tmp/wr_logs/shot-13.log 2>&1' < /dev/null > /dev/null 2>&1 & disown

# 确认 OK 后再批量起剩余镜（同一 shell 并发一次性 launch）
for n in 16 21 27; do
  setsid bash -c "cd $WORKSPACE && python3 scripts/_workrally_one_shot.py $n \
    > tmp/wr_logs/shot-$n.log 2>&1" < /dev/null > /dev/null 2>&1 & disown
done
```

**进度巡检**：
```bash
for n in 13 16 21 27; do echo "=== shot-$n ==="; tail -5 tmp/wr_logs/shot-$n.log; done
```

**并发上限建议**：单批次后台进程 ≤ 6；再多容易因 CLI 升级提醒 / 网络抖动出现 JSON 解析失败。

### 阶段 4｜收尾（必做，不能省）

无论成功失败，**批次完成后**（所有后台进程结束）统一做：

1. **videoTask 字段规范化**（修 `queueStatus=None` 等历史脏数据）：
```python
vt['queueStatus'] = ''   # 强制空串
vt['queueIdx']    = None # 强制 None
```

2. **失败镜补 needsRework = True**（避免人眼漏掉）：
```python
if vt['status'] == 'failed':
    vt['needsRework'] = True
    # failHistory 追加一条，记清 engine=workrally / promptMode=full / 失败原因
```

3. **manifest.stages.video 差量更新**（脚本未自动维护整体 manifest，批量完要手动一次对齐）：
```python
# done 数 → produced += N, pending -= N, videoUniqueShots += N, videoTotalDurationSec += sum
# fail 数 → 不改 produced，只动 videoGenCount += N
# generating 数 → 按实际剩余轮询中数写回 generating
```

4. **候补池清理**：如批次里的 shot 在 `video-queue.json` 里仍有条目，全部移除（workrally 出的不占候补池 slot，继续留着会误触发 dreamina 重投）。

5. **失败复盘**：`shot-NN` failed 的，**不立即改写**，汇总给用户裁决：
   - `pre-TNS check did not pass` / `输入提示词敏感` → 交给 `shot-prompt-rewrite-skill` 走精简改写
   - `final generation failed` → 可能是 workrally 侧资源问题，用户同意后 retry 1 次

---

## 三、已知陷阱（必读）

### 陷阱 1｜"画外音角色"不在 mount 里会丢参考图 ⚠️

现象：`shot.mount` 只写"李嗣源@图片5｜后唐皇宫大殿@图片20｜马上声音@音频1"，画外音"马上"只挂了音频。

后果：workrally SD2.0 是**全能参考**引擎，参考图越全模型越稳。只挂 2 张会导致风格发散（角色台词里的画外音人物无参考锚点）。

**修复策略**（推荐 A）：
- **A. 脚本自动补**：`_workrally_one_shot.py` 在解析 mount 的 `@图片` 之后，再扫 `assetRefs` 里的 `{{character:xxx}}` / `{{scene:xxx}}` / `{{prop:xxx}}`，反查 asset-map 补齐 character/scene/prop 类目下的形象图。
- **B. 分镜师规范改**：要求 mount 字段里**所有**出现在 assetRefs 里的角色/场景都必须挂 `@图片X`（画外音也挂）。

当前（v1.0）：**尚未实装**。批量前请**人工核对 assetRefs 与 mount 是否对齐**，不对齐的先补 mount。

### 陷阱 2｜workrally pre-TNS 比 dreamina 严

现象：`输入提示词敏感或违反平台规定` 经常出现在军事/政变/打仗类镜（full prompt 词频集中时）。

对策：
- 该镜直接走 `shot-prompt-rewrite-skill` 精简改写（降词频、去敏感词同义替换），然后**依然 workrally 兜底**
- 注意 full prompt 的 `compulsoryDeclaration`、`mustShow` 等字段里如果有"禁止"/"禁止暴力"等带否定词的文字，反而可能提高敏感命中率，必要时可删掉该字段重投

### 陷阱 3｜镜头不动 / 动势偏弱

现象：SD2.0 全能参考在复杂角色场景下容易"锁住"不动。

原因：参考图越多，模型越倾向于 "stick to reference"，导致动势被抹平。

缓解（下次可试）：
- 把 mainPrompt 里"镜头稳定不动"这种字面指令换成"镜头轻微呼吸式前推 5%" 之类**有幅度的微动势描写**
- 必要时去掉其中 1 张次要参考图（e.g. 场景图），只留角色+首帧，给模型更多自由度

### 陷阱 4｜queueStatus=null 脏数据

现象：脚本用 `**cur.get("videoTask", {})` 保留旧字段，旧 shot 的 queueStatus 是 `null` 会被带过来。

修复：阶段 4 收尾必做规范化（见上文）。

### 陷阱 5｜titleBar 时长 > 15s

workrally SD2.0 最长 15s。脚本已 `min(duration, 15)` 夹紧，但：
- **原因 1**：如果分镜本身 18s，截到 15s 会丢台词尾段 → 进批次前应先让分镜师重排节奏
- **原因 2**：批处理前检查，titleBar > 15 的整个跳过，不默默截

---

## 四、上报格式（给用户的最终报告）

```
📊 workrally 批次报告（N 镜）

✅ 成功（M）：
  - shot-13 ·12s · taskId=xxx · video=outputs/ep01/videos/shot-13.mp4
  - shot-27 ·12s · taskId=yyy · video=outputs/ep01/videos/shot-27.mp4

❌ 失败（K）：
  - shot-16 · FAILED · 输入提示词敏感 · 已标记 needsRework=true
    → 建议：走 shot-prompt-rewrite-skill 精简后重投

⏳ 进行中（L）：
  - shot-21 · 25% RUNNING

📦 资产变化：
  - manifest.produced +M，pending -M
  - 候补池清理：M 条

💰 成本：cost-logger 已登记 M 笔
```

---

## 五、禁止事项（硬规则）

1. ❌ **不可擅自批量**：workrally 多图主体驱动每镜耗 credit 不低（SD2.0 · 12s ≈ 60 credit），必须经用户确认首跑效果后再批
2. ❌ **不可跳过 cost-logger**：否则成本 dashboard 会失真
3. ❌ **不可合并 batch 为"一次 shell 全部 launch 同时查"**：必须每镜一个独立的 after-run 回写，才能容错
4. ~~❌ **workrally 出的镜不进心跳候补池**~~：**v1.1 已支持**——候补池 waitList entry 新增 `engine` 字段（`'dreamina'` | `'workrally'`），心跳调度器按 engine 分支派发。WorkRally 并发上限由 `maxInflightWorkrally`（默认 5）控制，与 Dreamina 池隔离。Dashboard 重生成弹窗可选引擎。
5. ❌ **批量失败超过 50%** → 立即停止后续批次，报告用户

---

## 附录 A｜与 workrally-skill 的分工

| 文档 | 覆盖范围 |
|------|----------|
| workrally-skill/skill.md | CLI 命令、单镜规范、字段定义、错误处理 |
| workrally-skill/workrally-batch-guide.md（本文档） | 批量编排、并发策略、批次收尾、陷阱与复盘 |
| shot-prompt-rewrite-skill/prompt.md | 通用审核改写（pre-TNS fail / 提示词敏感） |

---

## 附录 B｜版本更新日志

- v1.1 · 2026-04-20：候补池集成 WorkRally 引擎
  - waitList entry 新增 `engine` 字段（`'dreamina'` | `'workrally'`）
  - `video_scheduler.py`：`refresh_generating` 跳过 workrally 镜（子进程自轮询），只统计 generating 数量用于 slot 判断
  - `video_scheduler.py`：`next_submittable` 按 engine 分别判 slot（dreamina 按模型、workrally 按全局池）
  - `video_scheduler.py`：提交循环按 engine 分支——dreamina→`submit_shot()`、workrally→spawn `_workrally_one_shot.py`
  - `video_scheduler.py`：新增 `_spawn_workrally()` 函数，后台启动 one-shot 子进程
  - `serve.py`：`/api/video-queue/add` 透传 `engine` 字段
  - `dashboard.html`：重生成弹窗新增引擎单选（Dreamina / WorkRally），切换引擎联动模型下拉列表
  - WorkRally 并发上限：`maxInflightWorkrally`（默认 5），可在 `video-queue.json` 中配置
- v1.0 · 2026-04-20：首版沉淀，基于马上看中国史 ep01 shot-11/13/16/21/27 批次实战
