#!/usr/bin/env python3
"""
视频候补调度器（Dreamina video waitlist scheduler）。

功能：
1. 读 projects/<项目>/outputs/<ep>/video-queue.json
2. 刷新所有 generating 镜状态（复用 refresh_video_status 逻辑）
3. 若 inflight < maxInflight 且队列未暂停，按 waitList 从头向后找一个
   可提交（首帧依赖就绪）的镜头，调用 video_submit.submit_shot() 提交
4. 提交成功/失败后把该镜从 waitList 移除，追加到 history
5. 失败不自动重试（由人决定是否重新加入）

用法：
    # 单次执行（systemd timer / cron 推荐）
    python3 video_scheduler.py --project "马上看中国史" --ep ep01

    # 常驻循环（开发时调试）
    python3 video_scheduler.py --project "马上看中国史" --ep ep01 --loop --interval 600

video-queue.json 结构：
{
  "maxInflight": 1,
  "paused": false,
  "defaultModel": "seedance2.0fast",
  "defaultRatio": "16:9",
  "waitList": [
    {"shot":"02","model":"seedance2.0fast","ratio":"16:9","addedAt":"...","note":""}
  ],
  "history": [
    {"shot":"00","submit_id":"...","result":"submitted|failed|skipped","reason":"","at":"..."}
  ],
  "lastHeartbeat": "2026-04-19T08:00:00+08:00"
}
"""
import json, os, sys, time, datetime, argparse, glob, re, subprocess, shutil, urllib.request, fcntl

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from video_submit import submit_shot, check_tail_frame_ready  # noqa

PROJECT_ROOT = "/data/workspace/waoowaoo/seedance2.0"

# 提交后多少分钟内 queue_info 仍为空，判为"静默丢单"
STUCK_THRESHOLD_MIN = 10


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
    """扫描所有 generating 镜，更新状态。返回 (inflight_count, transitions)"""
    p = paths(project, ep)
    inflight = 0
    transitions = []
    for fpath in sorted(glob.glob(f"{p['shots_dir']}/shot-*.json")):
        d = json.load(open(fpath))
        vt = d.get("videoTask") or {}
        if vt.get("status") != "generating": continue
        tid = vt.get("taskId")
        if not tid: continue
        idx = re.search(r"shot-(\d+)\.json", fpath).group(1)
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
                inflight += 1
        elif gs in ("fail", "failed") or (fail and not gs):
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
            })
            vt["failHistory"] = fh
            transitions.append(("failed", idx))
            log(f"  ❌ shot-{idx} failed: {fail} | needsRework=true")
        elif gs == "querying":
            qstatus = (qi.get("queue_status") or "").lower()
            if qstatus == "generating":
                vt["queueStatus"] = "generating"
                vt["queueIdx"] = qi.get("queue_idx")
                inflight += 1
                log(f"  ⏳ shot-{idx} rendering")
            elif qi:
                # 有 queue_info 但不是 Generating（通常是 Waiting 等）
                vt["queueStatus"] = "queuing"
                vt["queueIdx"] = qi.get("queue_idx")
                inflight += 1  # 有队列信息说明在排队，占 slot
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
                    inflight += 1
                    log(f"  🕒 shot-{idx} queuing (刚提交不久，给点耐心)")
        else:
            log(f"  ? shot-{idx} gen_status={gs}; treat as inflight")
            inflight += 1

        d["videoTask"] = vt
        json.dump(d, open(fpath, "w"), ensure_ascii=False, indent=2)
    return inflight, transitions


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


def next_submittable(project, ep, waitlist, log):
    """
    向前扫 waitList，找第一个尾帧依赖就绪的镜。找不到返回 (None, None, 'all deps not ready')
    返回 (index_in_list, entry, reason)
    跳过规则：needsRework=true 的镜 / 尾帧未就绪
    """
    skipped = []
    for i, e in enumerate(waitlist):
        idx = str(e["shot"]).zfill(2)
        # 跳过需要返工的镜（分镜师优化 prompt 后会清除该标记）
        if _shot_needs_rework(project, ep, idx):
            skipped.append(f"{idx}(needsRework)")
            continue
        try:
            needs, ready, tail_num = check_tail_frame_ready(PROJECT_ROOT, project, ep, idx)
        except Exception as ex:
            log(f"  shot-{idx}: check deps error: {ex}; skip")
            skipped.append(idx)
            continue
        if not needs or ready:
            return i, e, "ok"
        else:
            skipped.append(f"{idx}(需@图片{tail_num})")
    return None, None, f"all waitlist blocked; skipped: {', '.join(skipped)}"


def heartbeat(project, ep):
    p = paths(project, ep)

    def log_line(msg, also_stdout=True):
        line = f"[{now_iso()}] {msg}"
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
        _heartbeat_impl(project, ep, p, log_line)
    finally:
        try: fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except Exception: pass
        lock_fd.close()


def _heartbeat_impl(project, ep, p, log):
    q = load_queue(p["queue_file"])
    log("=== heartbeat start ===")
    if q.get("paused"):
        log("queue paused, skip")
        q["lastHeartbeat"] = now_iso()
        save_queue(p["queue_file"], q)
        return

    # 1. 刷新 generating 状态
    inflight, transitions = refresh_generating(project, ep, log)
    # 1.5. 把 done/failed/stuck 的终态回写到 queue.history（便于审计对账）
    _apply_transitions_to_history(q, transitions, project, ep, log=log)
    max_inflight = int(q.get("maxInflight", 1))
    log(f"inflight={inflight}, maxInflight={max_inflight}, waitList={len(q.get('waitList',[]))}")

    # 2. 判断是否有空位
    if inflight >= max_inflight:
        log(f"no slot (inflight>={max_inflight}), skip submit")
        q["lastHeartbeat"] = now_iso()
        save_queue(p["queue_file"], q)
        return

    wl = q.get("waitList", [])
    if not wl:
        log("waitList empty, nothing to submit")
        q["lastHeartbeat"] = now_iso()
        save_queue(p["queue_file"], q)
        return

    # 3. 找第一个可提交的镜
    i, entry, reason = next_submittable(project, ep, wl, log)
    if i is None:
        log(f"no submittable entry: {reason}")
        q["lastHeartbeat"] = now_iso()
        save_queue(p["queue_file"], q)
        return

    idx = str(entry["shot"]).zfill(2)
    model = entry.get("model") or q.get("defaultModel") or "seedance2.0fast"
    ratio = entry.get("ratio") or q.get("defaultRatio") or "16:9"
    log_dir = f"{PROJECT_ROOT}/tmp-logs"
    log(f"→ submitting shot-{idx} (model={model}, ratio={ratio})")
    res = submit_shot(PROJECT_ROOT, project, ep, idx,
                      model=model, ratio=ratio, log_dir=log_dir)

    # 4. 不管成功失败，都从 waitList 移除（失败不自动重试）
    wl.pop(i)
    hist = q.setdefault("history", [])
    if res.get("ok"):
        hist.append({"shot": idx, "submit_id": res.get("submit_id"),
                     "result": "submitted", "reason": "", "at": now_iso(),
                     "model": model})
        log(f"  ✅ submitted shot-{idx}: submit_id={res.get('submit_id')}")
    else:
        hist.append({"shot": idx, "submit_id": None,
                     "result": "failed", "reason": res.get("reason",""),
                     "at": now_iso(), "model": model})
        log(f"  ❌ submit shot-{idx} failed: {res.get('reason','')}")

    q["waitList"] = wl
    q["lastHeartbeat"] = now_iso()
    save_queue(p["queue_file"], q)
    log("=== heartbeat end ===\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--ep", required=True)
    ap.add_argument("--loop", action="store_true", help="常驻循环（否则单次执行）")
    ap.add_argument("--interval", type=int, default=600, help="loop 模式间隔秒数")
    args = ap.parse_args()

    if args.loop:
        while True:
            try: heartbeat(args.project, args.ep)
            except Exception as e: print(f"heartbeat error: {e}")
            time.sleep(args.interval)
    else:
        heartbeat(args.project, args.ep)


if __name__ == "__main__":
    main()
