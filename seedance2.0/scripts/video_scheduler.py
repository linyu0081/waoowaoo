#!/usr/bin/env python3
"""
视频候补调度器（Dreamina video waitlist scheduler）。

功能：
1. 读 projects/<项目>/outputs/<ep>/video-queue.json
2. 刷新所有 generating 镜状态（复用 refresh_video_status 逻辑）
3. 按"每模型 slot=maxInflight（默认 1）"循环提交 waitList 中依赖就绪的镜：
   - 即梦同账号+同模型共用一个生成队列；不同模型队列相互独立
   - 一次心跳里可以给不同模型分别提交 1 个（总并发 = 模型数量 × maxInflight）
4. 提交成功/失败后把该镜从 waitList 移除，追加到 history
5. **自动重投**：本轮刷新中新转 failed/stuck 的镜，自动以原引擎对应的默认模型 + slim
   （精简参数）重新入 waitList，最多 2 次（videoTask.autoRetryCount 计数）；
   dreamina → seedance2.0fast，workrally → Zen-SD2.0。
   超限后需人工介入（✏️ 已优化重投 / 🔄 重新生成 会重置计数）。
   关闭开关：queue.autoRequeueOnFail=false；上限配置：queue.autoRequeueMax=2。
6. **waitList 优先级排序**（每次心跳开头执行一次稳定排序）：
   pinned（人工置顶粘性） > ready 且无首帧依赖 > ready 且被下游依赖 > ready（其他） > blocked（沉底）。
   原则：可提交的镜优先，被依赖卡住的镜沉底；blocked 的镜就算在关键路径上也不能排前面（它自己都提不了）。

用法：
    # 单次执行（systemd timer / cron 推荐）
    python3 video_scheduler.py --project "马上看中国史" --ep ep01

    # 常驻循环（开发时调试）
    python3 video_scheduler.py --project "马上看中国史" --ep ep01 --loop --interval 600

video-queue.json 结构：
{
  "maxInflight": 1,          // 【新语义】每个模型的 slot 上限（默认 1）。总并发 ≈ 已用模型数 × maxInflight
  "paused": false,
  "defaultModel": "seedance2.0fast",
  "defaultRatio": "16:9",
  "autoRequeueOnFail": true, // 失败自动重投开关（默认 true）
  "autoRequeueMax": 2,       // 自动重投上限（默认 2，含本次）
  "waitList": [
    {"shot":"02","model":"seedance2.0fast","ratio":"16:9","promptMode":"slim","addedAt":"...","note":"auto-retry #1/2 (from failed)"}
  ],
  "history": [
    {"shot":"00","submit_id":"...","result":"submitted|failed|stuck|done|auto-requeued","reason":"","at":"..."}
  ],
  "inflightByModel": {"seedance2.0fast": 1},  // 心跳每次刷新
  "lastHeartbeat": "2026-04-19T08:00:00+08:00"
}
"""
import json, os, sys, time, datetime, argparse, glob, re, subprocess, shutil, urllib.request, fcntl, shlex

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from video_submit import submit_shot, check_tail_frame_ready  # noqa

PROJECT_ROOT = "/data/workspace/waoowaoo/seedance2.0"

# 提交后多少分钟内 queue_info 仍为空，判为"静默丢单"
STUCK_THRESHOLD_MIN = 10

# WorkRally 默认并发上限（按 engine=workrally 的 generating 总数，与 dreamina 池隔离）
# 可被 queue.maxInflightWorkrally 覆盖
DEFAULT_WORKRALLY_MAX_INFLIGHT = 5

# WorkRally 单镜执行脚本绝对路径
WORKRALLY_ONESHOT_SCRIPT = os.path.join(PROJECT_ROOT, "scripts", "_workrally_one_shot.py")


def _resolve_engine(entry, shots_dir):
    """从 waitList entry 推断 engine（兜底：回读 shot.json / 按 model 名推断）。

    优先级：entry.engine > shot.json.videoTask.engine > model 名推断 > 'dreamina'
    """
    eng = (entry.get("engine") or "").strip().lower()
    if eng:
        return eng
    # 回读 shot.json
    idx = str(entry.get("shot", "")).zfill(2)
    try:
        _d = json.load(open(os.path.join(shots_dir, f"shot-{idx}.json")))
        eng = (_d.get("videoTask") or {}).get("engine", "").strip().lower()
    except Exception:
        pass
    if eng:
        return eng
    # 按 model 名推断
    _m = (entry.get("model") or "").lower()
    if "zen" in _m:
        return "workrally"
    return "dreamina"

# submit 成功后延迟多少秒触发一次 followup 心跳
# 用于覆盖平台 30s 内审核打回的场景（失败后不用干等下一次心跳）
FOLLOWUP_DELAY_SEC = 30


def now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def paths(project, ep):
    pd = f"{PROJECT_ROOT}/projects/{project}"
    return {
        "project_dir": pd,
        "shots_dir": f"{pd}/outputs/{ep}/06-shots",
        "videos_dir": f"{pd}/outputs/{ep}/videos",
        "tails_dir": f"{pd}/outputs/{ep}/tail-frames",
        "queue_file": f"{pd}/outputs/{ep}/video-queue.json",
        "log_file": f"{pd}/outputs/{ep}/video-scheduler.log",
        "lock_file": f"{pd}/outputs/{ep}/.scheduler.lock",
    }


def load_queue(qfile):
    if not os.path.exists(qfile):
        return {
            "maxInflight": 1,
            "maxInflightWorkrally": DEFAULT_WORKRALLY_MAX_INFLIGHT,
            "paused": False,
            "defaultModel": "seedance2.0fast",
            "defaultRatio": "16:9",
            "waitList": [],
            "history": [],
            "lastHeartbeat": "",
        }
    return json.load(open(qfile))


def save_queue(qfile, q):
    os.makedirs(os.path.dirname(qfile), exist_ok=True)
    tmp = qfile + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(q, f, ensure_ascii=False, indent=2)
    os.replace(tmp, qfile)


# ===== 查询与下载（精简版，从 refresh_video_status 迁移） =====
def query_submit(submit_id: str) -> dict:
    r = subprocess.run(["dreamina", "query_result", "--submit_id", submit_id],
                       capture_output=True, text=True, timeout=60)
    out = r.stdout or ""
    m = re.search(r"\{[\s\S]*\}", out)
    if not m:
        return {"_raw": out, "_err": "no-json"}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {"_raw": out, "_err": "json-parse-failed"}


def download(url: str, dst: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=120) as resp, open(dst, "wb") as f:
            shutil.copyfileobj(resp, f)
        return True
    except Exception as e:
        print(f"  download failed: {e}")
        return False


def grab_tail(mp4: str, jpg: str) -> bool:
    if not shutil.which("ffmpeg"): return False
    try:
        subprocess.run(
            ["ffmpeg","-y","-sseof","-0.5","-i",mp4,"-vframes","1","-q:v","2",jpg],
            capture_output=True, timeout=60,
        )
        return os.path.exists(jpg)
    except Exception:
        return False


def _parse_duration_from_title(title_bar: str) -> int:
    """从 titleBar 解析时长（兜底 15 秒）。与 video_submit.parse_duration 同逻辑。"""
    m = re.search(r"(\d+)\s*秒", title_bar or "")
    return int(m.group(1)) if m else 15


def cost_log_video(project, ep, idx, vt, log=print):
    """
    下载成功 = 真正出视频 = 即梦已扣积分，自动记一笔到 07-costs.json。
    幂等由 cost-logger.py 基于 taskId 保证，这里只负责组参数。
    vt: 该镜 videoTask 字典（应已含 modelName / taskId）
    """
    try:
        title_bar = ""
        shot_fp = f"{PROJECT_ROOT}/projects/{project}/outputs/{ep}/06-shots/shot-{idx}.json"
        if os.path.exists(shot_fp):
            try:
                title_bar = json.load(open(shot_fp)).get("titleBar", "")
            except Exception:
                pass
        duration = _parse_duration_from_title(title_bar)
        model = vt.get("modelName") or "unknown"
        task_id = vt.get("taskId") or ""
        credit = vt.get("creditCount")
        note = f"auto: scheduler download@{now_iso()}"
        if credit is not None:
            note += f"; credit={credit}"
        cmd = ["python3", f"{PROJECT_ROOT}/scripts/cost-logger.py", "video",
               "--project", project, "--episode", ep,
               "--target", f"shot-{idx}",
               "--model", str(model),
               "--duration", str(duration),
               "--note", note]
        if task_id:
            cmd += ["--task-id", task_id]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        out = (r.stdout or "").strip() or (r.stderr or "").strip()
        if r.returncode == 0:
            log(f"  💰 cost-log shot-{idx}: {out}")
        else:
            log(f"  ⚠️  cost-log shot-{idx} rc={r.returncode}: {out}")
    except Exception as e:
        log(f"  ⚠️  cost-log shot-{idx} exception: {e}")


def _apply_transitions_to_history(q, transitions, project, ep, log=print):
    """
    把 refresh_generating 返回的 transitions 回填到 video-queue.json 的 history[]。
    规则：
      - 从 shot-json 取 taskId，在 history 里找最后一条 submit_id==taskId 且 result=='submitted' 的记录
      - 把 result 改为 'done' / 'failed' / 'stuck'，补 endAt、durationSec（failed/stuck 留 0）
      - 找不到匹配（比如历史没记提交）就 skip（非致命）
    """
    if not transitions:
        return 0
    p = paths(project, ep)
    hist = q.get("history", [])
    updated = 0
    for state, idx in transitions:
        shot_fp = f"{p['shots_dir']}/shot-{idx}.json"
        if not os.path.exists(shot_fp):
            continue
        try:
            shot = json.load(open(shot_fp))
        except Exception:
            continue
        vt = shot.get("videoTask") or {}
        tid = vt.get("taskId")
        if not tid:
            continue
        # 从后往前找第一条匹配的 submitted 记录（同一 shot 可能多次提交）
        target = None
        for h in reversed(hist):
            if h.get("submit_id") == tid and h.get("result") == "submitted":
                target = h
                break
        if target is None:
            continue
        target["result"] = state  # 'done' / 'failed' / 'stuck'
        target["endAt"] = now_iso()
        if state == "done":
            title = shot.get("titleBar", "")
            target["durationSec"] = _parse_duration_from_title(title)
        else:
            target.setdefault("durationSec", 0)
            fr = vt.get("failReason")
            if fr:
                target["reason"] = fr
        updated += 1
    if updated:
        log(f"  📝 history 回填 {updated} 条终态")
    return updated


def refresh_generating(project, ep, log):
    """扫描所有 generating 镜，更新状态。

    返回 (inflight_by_model, transitions, workrally_generating)：
      - inflight_by_model: {model_name: count}（仅 dreamina 镜：按模型分组的占位数）
      - transitions:       [(state, shot_idx), ...]（仅 dreamina 分支）
      - workrally_generating: int（正在 generating 的 workrally 镜数量，只计数）

    workrally 分支不在心跳里直接调 workrally CLI 查状态：因为 _workrally_one_shot.py
    子进程自己会轮询 + 写回 shot.json。心跳只负责：
      1) 数 generating 数量用于 slot 判断
      2) 换遍一无 generating 的 dreamina，走原有查询流程
    “workrally 绝期 stuck”的兼容毕竟子进程内已有 80×15s 的轮询上限。
    """
    p = paths(project, ep)
    inflight_by_model = {}
    def bump(model):
        m = model or "unknown"
        inflight_by_model[m] = inflight_by_model.get(m, 0) + 1
    transitions = []
    workrally_generating = 0
    for fpath in sorted(glob.glob(f"{p['shots_dir']}/shot-*.json")):
        d = json.load(open(fpath))
        vt = d.get("videoTask") or {}
        if vt.get("status") != "generating": continue
        tid = vt.get("taskId")
        if not tid: continue
        # ⭐ engine=workrally 的镜：子进程自己轮询写回 done/failed，
        #    心跳额外查一次进度（兜底 + 供 dashboard 展示）
        if (vt.get("engine") or "") == "workrally":
            idx = re.search(r"shot-(\d+)\.json", fpath).group(1)
            # 查 WorkRally 进度（非阻塞，失败不影响心跳）
            _wr_handled = False  # 标记是否已处理终态（SUCCESS/FAIL）
            try:
                _wr_bin = "/root/.workbuddy/binaries/node/versions/20.18.0/bin/workrally"
                _wr_r = subprocess.run(
                    [_wr_bin, "generate", "task", tid, "-o", "json"],
                    capture_output=True, text=True, timeout=30,
                )
                _wr_j = None
                _wr_m = re.search(r'\{[\s\S]*\}', _wr_r.stdout or "")
                if _wr_m:
                    try: _wr_j = json.loads(_wr_m.group(0))
                    except Exception: pass
                if _wr_j:
                    _wr_progress = _wr_j.get("progress", 0)
                    _wr_state = _wr_j.get("state")
                    vt["progress"] = _wr_progress
                    vt["progressUpdatedAt"] = now_iso()

                    if _wr_state == 4:
                        # ===== SUCCESS：兜底下载视频 + 截尾帧 + 写回 done =====
                        # 子进程可能崩溃未完成下载，心跳在此兜底
                        log(f"  ✅ shot-{idx} workrally SUCCESS (progress={_wr_progress}), 兜底下载...")
                        _wr_handled = True
                        try:
                            _out_assets = _wr_j.get("output_assets") or []
                            _asset_id = _out_assets[0]["asset_id"] if _out_assets else ""
                            if _asset_id:
                                os.makedirs(p["videos_dir"], exist_ok=True)
                                _dl_mp4 = f"{p['videos_dir']}/shot-{idx}.mp4"
                                _dl_r = subprocess.run(
                                    [_wr_bin, "download", _asset_id, "-d", p["videos_dir"] + "/", "-n", f"shot-{idx}.mp4"],
                                    capture_output=True, text=True, timeout=300,
                                )
                                if os.path.exists(_dl_mp4) and os.path.getsize(_dl_mp4) > 0:
                                    # 截尾帧
                                    os.makedirs(p["tails_dir"], exist_ok=True)
                                    _dl_jpg = f"{p['tails_dir']}/tail-shot-{idx}.jpg"
                                    grab_tail(_dl_mp4, _dl_jpg)
                                    vt.update({
                                        "status": "done",
                                        "videoFile": f"outputs/{ep}/videos/shot-{idx}.mp4",
                                        "tailFrame": f"outputs/{ep}/tail-frames/tail-shot-{idx}.jpg" if os.path.exists(_dl_jpg) else "",
                                        "assetId": _asset_id,
                                        "completedAt": now_iso(),
                                    })
                                    transitions.append(("done", idx))
                                    log(f"  ✅ shot-{idx} workrally done (兜底下载 {os.path.getsize(_dl_mp4)//1024}KB)")
                                    cost_log_video(project, ep, idx, vt, log=log)
                                else:
                                    log(f"  ⚠️ shot-{idx} workrally download 失败或文件为空，保持 generating")
                                    _wr_handled = False
                            else:
                                log(f"  ⚠️ shot-{idx} workrally SUCCESS 但无 asset_id，保持 generating")
                                _wr_handled = False
                        except Exception as _dl_e:
                            log(f"  ⚠️ shot-{idx} workrally 兜底下载异常: {_dl_e}，保持 generating")
                            _wr_handled = False

                    elif _wr_state in (5, 6, 7):
                        # ===== FAIL 类：兜底写回 failed =====
                        _wr_handled = True
                        _wr_msg = _wr_j.get("message") or _wr_j.get("state_desc") or "workrally task failed"
                        vt["status"] = "failed"
                        vt["failReason"] = _wr_msg
                        vt["completedAt"] = now_iso()
                        fh = vt.get("failHistory") or []
                        fh.append({
                            "taskId": tid,
                            "failReason": _wr_msg,
                            "submittedAt": vt.get("submittedAt", ""),
                            "failedAt": now_iso(),
                            "model": vt.get("modelName", ""),
                            "kind": "workrally-fail",
                        })
                        vt["failHistory"] = fh
                        transitions.append(("failed", idx))
                        log(f"  ❌ shot-{idx} workrally FAILED (state={_wr_state}): {_wr_msg}")

                    else:
                        log(f"  🔄 shot-{idx} workrally progress={_wr_progress} (state={_wr_state})")

                    d["videoTask"] = vt
                    json.dump(d, open(fpath, "w"), ensure_ascii=False, indent=2)
            except Exception as _we:
                log(f"  ⚠️ shot-{idx} workrally progress query failed: {_we}")
            # 未处理终态的（仍在 generating）才计入 inflight
            if not _wr_handled:
                workrally_generating += 1
            continue
        idx = re.search(r"shot-(\d+)\.json", fpath).group(1)
        shot_model = vt.get("modelName") or ""
        resp = query_submit(tid)
        gs = resp.get("gen_status", "")
        qi = resp.get("queue_info") or {}
        url = ""
        try:
            vids = (resp.get("result_json") or {}).get("videos") or []
            if vids: url = vids[0].get("video_url") or ""
        except Exception:
            pass
        fail = resp.get("fail_reason") or ""

        # 识别 API 参数错误/预提交校验失败等"硬终态"关键词
        # （平台偶发：gen_status 为空 or querying，但 fail_reason 已经写明错误，
        #  此时不应等 10min STUCK 才释放 slot）
        _fail_lower = (fail or "").lower()
        _api_error_keywords = (
            "参数错误", "参数非法", "参数不合法", "参数校验",
            "invalid param", "invalid parameter", "param error",
            "duration", "时长", "过长", "超出", "超过",
            "违规", "审核", "风控", "敏感", "pre-tns", "tns",
            "不支持", "unsupported", "illegal",
        )
        _is_api_error = bool(fail) and any(kw in _fail_lower or kw in fail for kw in _api_error_keywords)

        if gs == "success" and url:
            mp4 = f"{p['videos_dir']}/shot-{idx}.mp4"
            os.makedirs(p["videos_dir"], exist_ok=True)
            ok = download(url, mp4)
            if ok:
                os.makedirs(p["tails_dir"], exist_ok=True)
                jpg = f"{p['tails_dir']}/tail-shot-{idx}.jpg"
                grab_tail(mp4, jpg)
                vt.update({
                    "status": "done",
                    "queueStatus": "",
                    "queueIdx": None,
                    "videoUrl": url,
                    "videoFile": f"outputs/{ep}/videos/shot-{idx}.mp4",
                    "tailFrame": f"outputs/{ep}/tail-frames/tail-shot-{idx}.jpg" if os.path.exists(jpg) else "",
                    "completedAt": now_iso(),
                })
                transitions.append(("done", idx))
                log(f"  ✅ shot-{idx} done ({os.path.getsize(mp4)//1024}KB)")
                # 自动记账（taskId 幂等，重复调用安全）
                cost_log_video(project, ep, idx, vt, log=log)
            else:
                log(f"  ⚠️  shot-{idx} url ready but download failed; keep generating")
                bump(shot_model)
        elif gs in ("fail", "failed") or (fail and not gs) or _is_api_error:
            vt["status"] = "failed"
            vt["queueStatus"] = ""
            vt["failReason"] = fail or "unknown"
            vt["completedAt"] = now_iso()
            # 标记需返工 + 追加失败历史（供分镜师审计）
            vt["needsRework"] = True
            fh = vt.get("failHistory") or []
            fh.append({
                "taskId": tid,
                "failReason": fail or "unknown",
                "submittedAt": vt.get("submittedAt", ""),
                "failedAt": now_iso(),
                "model": vt.get("modelName", ""),
                "kind": "api_error" if _is_api_error and gs not in ("fail", "failed") else "fail",
            })
            vt["failHistory"] = fh
            transitions.append(("failed", idx))
            if _is_api_error and gs not in ("fail", "failed"):
                log(f"  ❌ shot-{idx} API参数错误(立即终态，不等STUCK): {fail} | needsRework=true")
            else:
                log(f"  ❌ shot-{idx} failed: {fail} | needsRework=true")
        elif gs == "querying":
            qstatus = (qi.get("queue_status") or "").lower()
            if qstatus == "generating":
                vt["queueStatus"] = "generating"
                vt["queueIdx"] = qi.get("queue_idx")
                bump(shot_model)
                log(f"  ⏳ shot-{idx} rendering")
            elif qi:
                # 有 queue_info 但不是 Generating（通常是 Waiting 等）
                vt["queueStatus"] = "queuing"
                vt["queueIdx"] = qi.get("queue_idx")
                bump(shot_model)  # 有队列信息说明在排队，占 slot
                log(f"  🕒 shot-{idx} queuing (queue_status={qstatus})")
            else:
                # ⚠️ queue_info 为空：可能在预队列，也可能服务端静默丢单
                # 以提交时间为准做超时判定
                submitted = vt.get("submittedAt", "")
                stuck = False
                if submitted:
                    try:
                        t0 = datetime.datetime.fromisoformat(submitted)
                        mins = (datetime.datetime.now(t0.tzinfo) - t0).total_seconds() / 60
                        if mins > STUCK_THRESHOLD_MIN:
                            stuck = True
                    except Exception:
                        pass
                if stuck:
                    # 判为静默丢单（stuck 不标 needsRework，分镜无责任，直接重投即可）
                    vt["status"] = "stuck"
                    vt["queueStatus"] = ""
                    vt["failReason"] = f"提交后 {STUCK_THRESHOLD_MIN}+ 分钟仍未进入即梦队列，疑似服务端静默丢单"
                    vt["completedAt"] = now_iso()
                    fh = vt.get("failHistory") or []
                    fh.append({
                        "taskId": tid,
                        "failReason": vt["failReason"],
                        "submittedAt": vt.get("submittedAt", ""),
                        "failedAt": now_iso(),
                        "model": vt.get("modelName", ""),
                        "kind": "stuck",
                    })
                    vt["failHistory"] = fh
                    transitions.append(("stuck", idx))
                    log(f"  🔴 shot-{idx} STUCK (queue_info 空且已过 {STUCK_THRESHOLD_MIN}min)，释放 slot")
                else:
                    vt["queueStatus"] = "queuing"
                    vt["queueIdx"] = None
                    bump(shot_model)
                    log(f"  🕒 shot-{idx} queuing (刚提交不久，给点耐心)")
        else:
            log(f"  ? shot-{idx} gen_status={gs}; treat as inflight")
            bump(shot_model)

        d["videoTask"] = vt
        json.dump(d, open(fpath, "w"), ensure_ascii=False, indent=2)
    return inflight_by_model, transitions, workrally_generating


def _shot_needs_rework(project, ep, idx):
    """读 shot.json 判断 needsRework。不存在或读不到则返回 False。"""
    p = paths(project, ep)
    fp = f"{p['shots_dir']}/shot-{idx}.json"
    if not os.path.exists(fp): return False
    try:
        d = json.load(open(fp))
        return bool((d.get("videoTask") or {}).get("needsRework"))
    except Exception:
        return False


def compute_waitlist_deps(project, ep, waitlist):
    """
    为 waitList 中每一镜计算依赖状态，供 dashboard 徽章渲染与 scheduler skip-log 复用。
    返回 dict: {
      "shot-XX": {
        "ready": bool,          # 可否立即提交
        "blocker": "needsRework"|"dep-missing"|"dep-err"|"" ,
        "tailNum": "46" | None,   # 依赖的 tail 引用号（若存在）
        "fromShot": "10" | None,  # 依赖的前镜
        "reason": "人类可读的简短说明",
      }
    }
    """
    result = {}
    p = paths(project, ep)
    # 读 asset-map 一次（用于反查 tail-frame 的 fromShot）
    asset_map = {}
    am_fp = f"{p['project_dir']}/outputs/{ep}/asset-map.json"
    if os.path.exists(am_fp):
        try: asset_map = json.load(open(am_fp))
        except Exception: pass
    images = (asset_map.get("images") or {})

    for e in waitlist or []:
        # 防御：允许 waitList 里出现脏条目（字符串/None 等），避免把心跳整体打崩
        if not isinstance(e, dict):
            key = f"malformed-{len(result)}"
            result[key] = {
                "ready": False, "blocker": "malformed",
                "tailNum": None, "fromShot": None,
                "reason": f"waitList 存在非法条目: type={type(e).__name__} value={e!r}",
            }
            continue
        idx = str(e.get("shot", "")).zfill(2)
        info = {"ready": False, "blocker": "", "tailNum": None, "fromShot": None, "reason": ""}

        # 1) needsRework 最优先
        if _shot_needs_rework(project, ep, idx):
            info["blocker"] = "needsRework"
            info["reason"] = "分镜被标记为需返工，清除 needsRework 后才能提交"
            result[f"shot-{idx}"] = info
            continue

        # 2) 首帧依赖
        try:
            needs, ready, tail_num = check_tail_frame_ready(PROJECT_ROOT, project, ep, idx)
        except Exception as ex:
            info["blocker"] = "dep-err"
            info["reason"] = f"依赖检查异常：{ex}"
            result[f"shot-{idx}"] = info
            continue

        if not needs:
            info["ready"] = True
            info["reason"] = "无首帧依赖，可直接提交"
            result[f"shot-{idx}"] = info
            continue

        info["tailNum"] = tail_num
        # 反查 fromShot（用于 UI 更友好地说"等 shot-10 出片"）
        if tail_num:
            entry = images.get(f"@图片{tail_num}") or {}
            if entry.get("type") == "tail-frame":
                fs = entry.get("fromShot")
                if fs is not None:
                    info["fromShot"] = str(fs).zfill(2)

        if ready:
            info["ready"] = True
            info["reason"] = f"首帧 @图片{tail_num} 就绪（来自 shot-{info['fromShot'] or '?'}）"
        else:
            info["blocker"] = "dep-missing"
            from_shot_desc = f"shot-{info['fromShot']}" if info["fromShot"] else f"@图片{tail_num}"
            info["reason"] = f"等 {from_shot_desc} 出片后才能提交"

        result[f"shot-{idx}"] = info
    return result


def _compute_shots_with_downstream(project, ep):
    """
    扫 06-shots/*.json 的 mount 字段，解析 "本视频以@图片N为首帧"，
    反查 asset-map.json 把 @图片N 映射到 fromShot，得到"被下游依赖"的 shot 集合。

    返回：set[str]  形如 {"10", "36", ...}（零补两位）
    用途：waitList 排序时把"需产出尾帧（下游在等我）"的镜优先排前面。
    """
    p = paths(project, ep)
    am_fp = f"{p['project_dir']}/outputs/{ep}/asset-map.json"
    images = {}
    if os.path.exists(am_fp):
        try:
            images = (json.load(open(am_fp)).get("images") or {})
        except Exception:
            images = {}

    downstream = set()
    for fpath in sorted(glob.glob(f"{p['shots_dir']}/shot-*.json")):
        try:
            d = json.load(open(fpath))
        except Exception:
            continue
        mount = d.get("mount") or ""
        m = re.search(r"本视频以@图片(\d+)为首帧", mount)
        if not m:
            continue
        tail_num = m.group(1)
        entry = images.get(f"@图片{tail_num}") or {}
        if entry.get("type") != "tail-frame":
            continue
        fs = entry.get("fromShot")
        if fs is None:
            continue
        downstream.add(str(fs).zfill(2))
    return downstream


def _sort_waitlist_by_priority(waitlist, deps, downstream_set, log=print):
    """
    waitList 稳定排序。优先级（数字越小越靠前）：
      1. pinned=true（人工置顶粘性，永远第一）
      2. ready 且无首帧依赖（立即可提交，且不拖累）
      3. ready 且被下游依赖（立即可提交 + 解锁后续镜头）
      4. ready（其他可提交镜）
      5. blocked（有首帧依赖未就绪、needsRework 等，沉底等依赖）
      6. 其余（维持原插入顺序，由稳定排序保证）

    核心原则：
      - "是否 ready 当下就能提交" 是第一档筛子，blocked 的镜一律沉底
      - 没 ready 的镜就算是"下游关键路径"也不能排前面，因为它自己都卡住
      - 稳定排序保证同档次保留原插入顺序

    约束：
      - malformed 条目（非 dict）原地保留在末尾，避免 key 函数炸
    """
    if not waitlist:
        return waitlist
    clean = [e for e in waitlist if isinstance(e, dict)]
    trash = [e for e in waitlist if not isinstance(e, dict)]

    def rank(e):
        idx = str(e.get("shot", "")).zfill(2)
        info = (deps or {}).get(f"shot-{idx}") or {}
        pinned = e.get("pinned") is True
        ready = info.get("ready") is True
        has_tail_dep = bool(info.get("tailNum"))  # 本镜有首帧依赖
        unlocks_downstream = idx in downstream_set  # 本镜产出的尾帧被下游引用

        # 分档（从小到大）
        if pinned:
            tier = 0
        elif ready and not has_tail_dep:
            # ready 的无依赖镜：排最前（立即提交 + 没拖累）
            tier = 1
        elif ready and unlocks_downstream:
            # ready 且能解锁下游：次优
            tier = 2
        elif ready:
            # 普通 ready
            tier = 3
        else:
            # blocked（needsRework / dep-missing / dep-err）统一沉底
            tier = 4
        return (tier,)

    before = [str(e.get("shot", "")).zfill(2) for e in clean]
    clean.sort(key=rank)
    after = [str(e.get("shot", "")).zfill(2) for e in clean]
    if before != after:
        log(f"  📊 waitList 重排: {','.join(before[:10])}{'...' if len(before) > 10 else ''} → {','.join(after[:10])}{'...' if len(after) > 10 else ''}")
    return clean + trash


def next_submittable(project, ep, waitlist, log,
                     inflight_by_model=None, per_model_limit=1,
                     default_model="seedance2.0fast",
                     workrally_generating=0, workrally_max=5):
    """
    向前扫 waitList，找第一个 **依赖就绪 且 所用引擎/模型还有 slot** 的镜。
    找不到返回 (None, None, reason)。
    跳过规则：
      - needsRework=true
      - 首帧依赖未就绪
      - engine=dreamina 且该模型 inflight 已达 per_model_limit
      - engine=workrally 且 workrally_generating 已达 workrally_max
    """
    if inflight_by_model is None:
        inflight_by_model = {}
    reserved = {}
    wr_reserved = 0  # 本轮已预留的 workrally slot

    p = paths(project, ep)
    shots_dir = p["shots_dir"]

    def _has_slot(e):
        nonlocal wr_reserved
        eng = _resolve_engine(e, shots_dir)
        if eng == "workrally":
            return (workrally_generating + wr_reserved) < workrally_max
        m = e.get("model") or default_model
        used = inflight_by_model.get(m, 0) + reserved.get(m, 0)
        return used < per_model_limit

    deps = compute_waitlist_deps(project, ep, waitlist)
    skipped = []
    for i, e in enumerate(waitlist):
        if not isinstance(e, dict):
            skipped.append(f"[{i}]malformed({type(e).__name__})")
            continue
        idx = str(e.get("shot", "")).zfill(2)
        eng = _resolve_engine(e, shots_dir)
        entry_model = e.get("model") or default_model
        info = deps.get(f"shot-{idx}") or {}
        if info.get("ready"):
            if _has_slot(e):
                return i, e, "ok"
            # slot 满了，跳过但继续找别的引擎/模型
            if eng == "workrally":
                skipped.append(f"{idx}(workrally满)")
            else:
                skipped.append(f"{idx}(模型{entry_model}满)")
            continue
        # skip（依赖/返工原因）
        if info.get("blocker") == "needsRework":
            skipped.append(f"{idx}(needsRework)")
        elif info.get("blocker") == "dep-missing":
            fs = info.get("fromShot")
            if fs:
                skipped.append(f"{idx}(待shot-{fs})")
            else:
                skipped.append(f"{idx}(需@图片{info.get('tailNum')})")
        elif info.get("blocker") == "dep-err":
            skipped.append(f"{idx}(dep-err)")
        else:
            skipped.append(idx)
    return None, None, f"all waitlist blocked; skipped: {', '.join(skipped)}"


def heartbeat(project, ep, followup_only=False):
    """一次心跳。
    followup_only=True 表示本次是 submit 成功后的 30s 延迟追击心跳，
    本次即使再次 submit 成功也不再递归 spawn 下一个 followup（防级联）。
    """
    p = paths(project, ep)

    tag = "[followup] " if followup_only else ""
    def log_line(msg, also_stdout=True):
        line = f"[{now_iso()}] {tag}{msg}"
        with open(p["log_file"], "a", encoding="utf-8") as f: f.write(line + "\n")
        if also_stdout: print(line)

    # 并发锁：同一 ep 只允许一个心跳进程（避免 submit 期间的竞态重复扣 credit）
    os.makedirs(os.path.dirname(p["lock_file"]), exist_ok=True)
    lock_fd = open(p["lock_file"], "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log_line("⏸ another heartbeat running, skip")
        lock_fd.close()
        return

    try:
        try:
            _heartbeat_impl(project, ep, p, log_line, followup_only=followup_only)
        except Exception as e:
            # 异常写进心跳日志，避免静默崩溃只抛到 stderr（systemd journal）
            import traceback
            log_line(f"💥 heartbeat crashed: {type(e).__name__}: {e}")
            log_line("traceback:\n" + traceback.format_exc())
            raise
    finally:
        try: fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except Exception: pass
        lock_fd.close()


# workrally / node 所在目录，spawn 子进程时需要注入到 PATH
_WORKRALLY_BIN_DIR = "/root/.workbuddy/binaries/node/versions/20.18.0/bin"


def _spawn_workrally(project, ep, idx, prompt_mode, log):
    """后台 spawn _workrally_one_shot.py 子进程。

    返回 {"ok": True, "pid": <int>} 或 {"ok": False, "reason": "..."}。
    子进程自己负责轮询 + 写回 shot.json（done/failed），心跳只负责数 generating 数量。
    spawn 成功后会立即将 shot.json 的 videoTask.status 标记为 generating（防止子进程崩溃导致状态卡 pending）。
    """
    if not os.path.exists(WORKRALLY_ONESHOT_SCRIPT):
        return {"ok": False, "reason": f"script not found: {WORKRALLY_ONESHOT_SCRIPT}"}
    try:
        log_dir = os.path.join(PROJECT_ROOT, "tmp", "wr_logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f"shot-{idx}-heartbeat.log")
        cmd = ["python3", WORKRALLY_ONESHOT_SCRIPT, str(int(idx)), "--use-current"]
        if prompt_mode == "slim":
            cmd.append("--slim")
        # 确保子进程 PATH 包含 node / workrally 所在目录（systemd 环境下 PATH 受限）
        child_env = os.environ.copy()
        cur_path = child_env.get("PATH", "")
        if _WORKRALLY_BIN_DIR not in cur_path:
            child_env["PATH"] = f"{_WORKRALLY_BIN_DIR}:{cur_path}"
        with open(log_file, "a") as lf:
            proc = subprocess.Popen(
                cmd,
                stdout=lf, stderr=subprocess.STDOUT,
                close_fds=True, start_new_session=True,
                cwd=PROJECT_ROOT,
                env=child_env,
            )
        log(f"  🚀 WorkRally spawned: pid={proc.pid}, log={log_file}")
        # spawn 成功后立即将 shot.json 标记为 generating（不等子进程自己写回，防止崩溃卡 pending）
        try:
            pd = f"{PROJECT_ROOT}/projects/{project}"
            shot_path = f"{pd}/outputs/{ep}/06-shots/shot-{str(idx).zfill(2)}.json"
            if os.path.exists(shot_path):
                with open(shot_path, "r", encoding="utf-8") as f:
                    sd = json.load(f)
                vt = sd.get("videoTask") or {}
                if vt.get("status") != "generating":
                    vt["status"] = "generating"
                    vt["engine"] = "workrally"
                    vt["modelName"] = "Zen-SD2.0"
                    vt["submittedAt"] = vt.get("submittedAt") or now_iso()
                    sd["videoTask"] = vt
                    with open(shot_path, "w", encoding="utf-8") as f:
                        json.dump(sd, f, ensure_ascii=False, indent=2)
                    log(f"  📝 shot-{idx} videoTask.status → generating (pre-set)")
        except Exception as e:
            log(f"  ⚠️ pre-set generating status failed: {e}")
        return {"ok": True, "pid": proc.pid}
    except Exception as e:
        return {"ok": False, "reason": str(e)}


def _spawn_followup(project, ep, log):
    """spawn 一个后台子进程，sleep FOLLOWUP_DELAY_SEC 秒后再跑一次心跳。

    目的：提交成功后平台可能在 30s 内做审核打回，打回后 refresh_generating 会把
    任务标为 failed 释放 slot。若只靠下一次常规心跳（周期可能 10 分钟）填补，
    会白白空转。用延迟子进程主动追击一次即可补齐空档。
    """
    try:
        import subprocess as _sp
        script = os.path.abspath(__file__)
        # setsid 脱离当前进程组 + close_fds 避免继承父 fd（flock 不会被子进程带走）
        cmd = [
            "sh", "-c",
            f"sleep {FOLLOWUP_DELAY_SEC}; exec python3 {shlex.quote(script)} "
            f"--project {shlex.quote(project)} --ep {shlex.quote(ep)} --followup-only",
        ]
        _sp.Popen(
            cmd,
            stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
            close_fds=True, start_new_session=True,
        )
        log(f"  ⏱ scheduled followup heartbeat in {FOLLOWUP_DELAY_SEC}s (覆盖平台审核打回空档)")
    except Exception as e:
        log(f"  ⚠️ spawn followup failed: {e}")


def _auto_requeue_failed(q, transitions, project, ep, log):
    """把本轮刚转为 failed/stuck 的镜自动重新入池。

    策略：
      - 触发条件：transitions 中 state ∈ {"failed", "stuck"}
      - 重试上限：shot.videoTask.autoRetryCount ≤ 2（即最多自动重投 2 次）
      - 保留原 engine，按引擎选默认模型：dreamina → seedance2.0fast，workrally → Zen-SD2.0
      - 强制参数：promptMode = "slim"（精简参数，规避大段正文引发的 TNS 打回）
      - 清零 needsRework（否则 next_submittable 会直接拦截），归零 videoTask 到 pending
      - 保留 engine / modelName / failHistory / autoRetryCount，其余清空
      - 开关：queue.autoRequeueOnFail=false 可关闭；默认开启

    🛑 新增跳过：pre-TNS / 敏感 / 违规 / 审核 / 风控 类文本内容失败不自动重投。
       这些失败切 slim 重投几乎必然再次打回，只会死磕 slot + 烧配额。
       直接保留 needsRework=True，交 shot-prompt-rewrite-skill 人工/agent 改写。

    返回：本轮自动重投的 shot 数量。
    """
    if not transitions:
        return 0
    if not q.get("autoRequeueOnFail", True):
        return 0

    p = paths(project, ep)
    wl = q.setdefault("waitList", [])
    hist = q.setdefault("history", [])
    # 已在候补池里的 shot 集合（避免同一镜同时出现两条 entry）
    in_waitlist = {str(e.get("shot")).zfill(2) for e in wl if isinstance(e, dict)}

    max_auto_retry = int(q.get("autoRequeueMax", 2))
    ratio_default = q.get("defaultRatio") or "16:9"
    requeued = 0

    for state, idx in transitions:
        if state not in ("failed", "stuck"):
            continue
        idx = str(idx).zfill(2)
        if idx in in_waitlist:
            log(f"  ⏭ auto-requeue skip shot-{idx}: 已在 waitList 里")
            continue

        shot_fp = f"{p['shots_dir']}/shot-{idx}.json"
        if not os.path.exists(shot_fp):
            continue
        try:
            shot = json.load(open(shot_fp))
        except Exception as e:
            log(f"  ⚠️ auto-requeue skip shot-{idx}: read shot.json fail ({e})")
            continue

        vt = shot.get("videoTask") or {}
        prev_count = int(vt.get("autoRetryCount") or 0)
        if prev_count >= max_auto_retry:
            log(f"  🚫 auto-requeue skip shot-{idx}: autoRetryCount={prev_count} 已达上限 {max_auto_retry}，需人工介入")
            continue

        # 🚫 pre-TNS / 审核 / 敏感 / 违规 / 风控 类失败属于"文本内容敏感"，
        #    单纯切 slim 模式重投 99% 还是同样打回，只会白白浪费 slot 与配额。
        #    直接保留 needsRework=True（上一步 refresh_generating 已写入），
        #    交由分镜师 shot-prompt-rewrite-skill 改写剧情/台词后再入池。
        _fail_reason_lower = (vt.get("failReason") or "").lower()
        _content_block_keywords = (
            "pre-tns", "tns", "敏感", "违规", "审核", "风控",
            "sensitive", "policy", "违反平台",
        )
        _is_content_block = any(kw in _fail_reason_lower or kw in (vt.get("failReason") or "")
                                for kw in _content_block_keywords)
        if _is_content_block:
            log(f"  🛑 auto-requeue skip shot-{idx}: 内容审核类失败(pre-TNS/敏感/违规/审核/风控)，"
                f"保留 needsRework，交 shot-prompt-rewrite-skill 改写 | reason={vt.get('failReason','')[:60]}")
            continue

        new_count = prev_count + 1
        # 归零 videoTask，保留：engine / modelName / failHistory；清除：needsRework
        cleared = {
            "engine": vt.get("engine", ""),
            "modelName": vt.get("modelName", ""),
            "taskId": "",
            "status": "pending",
            "queueStatus": "",
            "queueIdx": None,
            "videoUrl": "",
            "videoFile": "",
            "tailFrame": "",
            "failReason": "",
            "creditCount": None,
            "submittedAt": "",
            "completedAt": "",
            "failHistory": vt.get("failHistory") or [],
            "autoRetryCount": new_count,
            "lastAutoRetryAt": now_iso(),
            # needsRework: 有意不写（清除）
        }
        shot["videoTask"] = cleared
        try:
            json.dump(shot, open(shot_fp, "w"), ensure_ascii=False, indent=2)
        except Exception as e:
            log(f"  ⚠️ auto-requeue skip shot-{idx}: write shot.json fail ({e})")
            continue

        # 入 waitList：保留原 engine，按引擎选默认模型 + slim
        orig_engine = (vt.get("engine") or "").strip().lower() or "dreamina"
        retry_model = "Zen-SD2.0" if orig_engine == "workrally" else "seedance2.0fast"
        wl.append({
            "shot": idx,
            "engine": orig_engine,
            "model": retry_model,
            "ratio": ratio_default,
            "promptMode": "slim",
            "addedAt": now_iso(),
            "note": f"auto-retry #{new_count}/{max_auto_retry} (from {state})",
        })
        in_waitlist.add(idx)
        # 审计：queue.history 记一条 auto-requeued
        hist.append({
            "shot": idx,
            "submit_id": None,
            "result": "auto-requeued",
            "reason": f"from {state}; retry={new_count}/{max_auto_retry}",
            "at": now_iso(),
            "model": retry_model,
            "engine": orig_engine,
            "promptMode": "slim",
        })
        requeued += 1
        log(f"  🔁 auto-requeue shot-{idx} [{state} → waitList] "
            f"({orig_engine} · {retry_model} · slim · retry {new_count}/{max_auto_retry})")

    if requeued:
        log(f"  🔁 本轮自动重投 {requeued} 镜")
    return requeued


def _heartbeat_impl(project, ep, p, log, followup_only=False):
    q = load_queue(p["queue_file"])
    log("=== heartbeat start ===")
    if q.get("paused"):
        log("queue paused, skip")
        q["lastHeartbeat"] = now_iso()
        save_queue(p["queue_file"], q)
        return

    # 1. 刷新 generating 状态
    inflight_by_model, transitions, workrally_generating = refresh_generating(project, ep, log)
    # 1.5. 把 done/failed/stuck 的终态回写到 queue.history（便于审计对账）
    _apply_transitions_to_history(q, transitions, project, ep, log=log)
    # 1.6. 自动重投：failed/stuck 且 autoRetryCount < 2 → 重新加入 waitList（seedance2.0fast + slim）
    _auto_requeue_failed(q, transitions, project, ep, log)
    # maxInflight 的**新语义**：每模型的 slot 上限（默认 1）。
    # 即梦同账号+同模型共用一个生成队列；不同模型队列相互独立。
    per_model_limit = int(q.get("maxInflight", 1))
    # WorkRally 并发上限（全 engine 维度，不分 model）
    wr_max = int(q.get("maxInflightWorkrally", DEFAULT_WORKRALLY_MAX_INFLIGHT))
    default_model = q.get("defaultModel") or "seedance2.0fast"
    total_inflight = sum(inflight_by_model.values())
    if inflight_by_model:
        breakdown = ", ".join(f"{m}={n}" for m, n in sorted(inflight_by_model.items()))
    else:
        breakdown = "(none)"
    log(f"inflight dreamina={total_inflight} by_model=[{breakdown}], perModelLimit={per_model_limit}")
    log(f"inflight workrally={workrally_generating}/{wr_max}, waitList={len(q.get('waitList',[]))}")

    # 1.6. 为 waitList 每一镜计算依赖状态（无论是否会提交都写入，供 dashboard UI 渲染徽章）
    wl_now = q.get("waitList", []) or []
    dep_snapshot = compute_waitlist_deps(project, ep, wl_now)
    # 1.7. 按优先级重排 waitList：pinned > 被下游依赖 > 无首帧依赖 > 原顺序
    #     目的：让"需产出尾帧（解锁后续镜头）"和"无依赖可即刻提交"的镜优先出手
    try:
        downstream_set = _compute_shots_with_downstream(project, ep)
        wl_sorted = _sort_waitlist_by_priority(wl_now, dep_snapshot, downstream_set, log=log)
        q["waitList"] = wl_sorted
        wl_now = wl_sorted
    except Exception as e:
        log(f"  ⚠️ waitList 重排失败（忽略，保持原顺序）：{e}")
    q["depStatus"] = dep_snapshot
    # 把 per-model inflight 快照也挂到 queue 上，dashboard 可用于展示
    q["inflightByModel"] = inflight_by_model
    blocked = [k for k, v in dep_snapshot.items() if not v.get("ready")]
    if blocked:
        log(f"  🔒 blocked in waitList: {', '.join(blocked)}")

    # 2. 判断是否所有引擎 slot 都已占满（全队列无法提交任何新任务）
    if wl_now:
        has_any_free_slot = False
        for e in wl_now:
            if not isinstance(e, dict):
                continue
            eng = _resolve_engine(e, p["shots_dir"])
            if eng == "workrally":
                if workrally_generating < wr_max:
                    has_any_free_slot = True
                    break
            else:
                m = e.get("model") or default_model
                if inflight_by_model.get(m, 0) < per_model_limit:
                    has_any_free_slot = True
                    break
        if not has_any_free_slot:
            log(f"no slot across waitList (dreamina models filled to {per_model_limit}, workrally {workrally_generating}/{wr_max}), skip submit")
            q["lastHeartbeat"] = now_iso()
            save_queue(p["queue_file"], q)
            return

    wl = q.get("waitList", [])
    if not wl:
        log("waitList empty, nothing to submit")
        q["lastHeartbeat"] = now_iso()
        save_queue(p["queue_file"], q)
        return

    # 3. 循环：每轮找一个"所用模型尚有 slot"的可提交镜头；直到没有空闲模型 slot 或 waitList 走完
    #    同一心跳里同一模型只会被提交 1 次（next_submittable 里的 reserved 机制在单轮生效，
    #    这里每轮外层也会把已提交成功的计入 inflight_by_model 再次判断）
    hist = q.setdefault("history", [])
    skiplog = q.setdefault("skipLog", [])
    submitted_any = False
    submitted_detail = []  # [(idx, model), ...]

    # skipLog 只在本心跳首轮记录一次（避免多轮循环时重复记录同一镜被 skip）
    first_pass_skip_recorded = False

    while True:
        # 每轮：用最新的 inflight_by_model / workrally_generating 判 slot
        i, entry, reason = next_submittable(
            project, ep, wl, log,
            inflight_by_model=inflight_by_model,
            per_model_limit=per_model_limit,
            default_model=default_model,
            workrally_generating=workrally_generating,
            workrally_max=wr_max,
        )

        # 首轮把被跳过的镜记进 skipLog（便于 dashboard"为什么一直没轮到我"）
        if not first_pass_skip_recorded:
            for idx_str in list(dep_snapshot.keys())[: (i if i is not None else len(dep_snapshot))]:
                info = dep_snapshot[idx_str]
                if info.get("ready"):
                    continue
                skiplog.append({
                    "at": now_iso(),
                    "shot": idx_str.replace("shot-", ""),
                    "blocker": info.get("blocker", ""),
                    "reason": info.get("reason", ""),
                })
            if len(skiplog) > 50:
                q["skipLog"] = skiplog[-50:]
            first_pass_skip_recorded = True

        if i is None:
            if not submitted_any:
                log(f"no submittable entry: {reason}")
            else:
                log(f"no more submittable entries this round: {reason}")
            break

        idx = str(entry["shot"]).zfill(2)
        engine = _resolve_engine(entry, p["shots_dir"])
        model = entry.get("model") or default_model
        ratio = entry.get("ratio") or q.get("defaultRatio") or "16:9"
        prompt_mode = entry.get("promptMode") or "full"
        log_dir = f"{PROJECT_ROOT}/tmp-logs"
        log(f"  engine resolved: entry.engine={entry.get('engine','(空)')!r} → {engine}")

        if engine == "workrally":
            # ===== WorkRally 分支：spawn _workrally_one_shot.py 后台进程 =====
            log(f"→ submitting shot-{idx} via WorkRally (promptMode={prompt_mode})")
            wr_res = _spawn_workrally(project, ep, idx, prompt_mode, log)
            wl.pop(i)
            if wr_res.get("ok"):
                hist.append({"shot": idx, "submit_id": f"wr-{idx}-{now_iso()}",
                             "result": "submitted", "reason": "", "at": now_iso(),
                             "model": "Zen-SD2.0", "engine": "workrally"})
                log(f"  ✅ WorkRally spawned shot-{idx} (pid={wr_res.get('pid')})")
                submitted_any = True
                submitted_detail.append((idx, "workrally"))
                workrally_generating += 1
            else:
                hist.append({"shot": idx, "submit_id": None,
                             "result": "failed", "reason": wr_res.get("reason", ""),
                             "at": now_iso(), "model": "Zen-SD2.0", "engine": "workrally"})
                log(f"  ❌ WorkRally spawn shot-{idx} failed: {wr_res.get('reason','')}")
        else:
            # ===== Dreamina 分支（原逻辑） =====
            log(f"→ submitting shot-{idx} (model={model}, ratio={ratio}, promptMode={prompt_mode})")
            res = submit_shot(PROJECT_ROOT, project, ep, idx,
                              model=model, ratio=ratio, log_dir=log_dir,
                              prompt_mode=prompt_mode)

            # 4. 不管成功失败，都从 waitList 移除（失败不自动重试）
            wl.pop(i)
            submitted_ok = bool(res.get("ok"))
            if submitted_ok:
                hist.append({"shot": idx, "submit_id": res.get("submit_id"),
                             "result": "submitted", "reason": "", "at": now_iso(),
                             "model": model, "engine": "dreamina"})
                log(f"  ✅ submitted shot-{idx}: submit_id={res.get('submit_id')}")
                submitted_any = True
                submitted_detail.append((idx, model))
                # 本轮提交成功 → 更新 inflight_by_model，供下一轮 slot 判断
                inflight_by_model[model] = inflight_by_model.get(model, 0) + 1
            else:
                hist.append({"shot": idx, "submit_id": None,
                             "result": "failed", "reason": res.get("reason",""),
                             "at": now_iso(), "model": model, "engine": "dreamina"})
                log(f"  ❌ submit shot-{idx} failed: {res.get('reason','')}")
                # 失败不占 slot，继续下一轮（可能别的镜还能上）

    q["waitList"] = wl
    q["inflightByModel"] = inflight_by_model  # 刷新 dashboard 展示
    q["lastHeartbeat"] = now_iso()
    save_queue(p["queue_file"], q)

    if submitted_detail:
        log(f"  📤 本轮共提交 {len(submitted_detail)} 镜: " +
            ", ".join(f"shot-{i}({m})" for i, m in submitted_detail))

    # 5. 只要本心跳有任何提交成功 → 30s 后追击一次心跳，覆盖平台审核打回的空档
    # 仅在正常心跳中触发；followup 心跳本身不再递归 spawn（防级联）
    # queue 开关：followupAfterSubmit=false 可关闭该特性
    if submitted_any and not followup_only and q.get("followupAfterSubmit", True):
        _spawn_followup(project, ep, log)

    log("=== heartbeat end ===\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--ep", required=True)
    ap.add_argument("--loop", action="store_true", help="常驻循环（否则单次执行）")
    ap.add_argument("--interval", type=int, default=600, help="loop 模式间隔秒数")
    ap.add_argument("--followup-only", action="store_true",
                    help="内部用：submit 成功后的 30s 延迟追击心跳，本次不再递归 spawn followup")
    args = ap.parse_args()

    if args.loop:
        while True:
            try: heartbeat(args.project, args.ep)
            except Exception as e: print(f"heartbeat error: {e}")
            time.sleep(args.interval)
    else:
        heartbeat(args.project, args.ep, followup_only=args.followup_only)


if __name__ == "__main__":
    main()
