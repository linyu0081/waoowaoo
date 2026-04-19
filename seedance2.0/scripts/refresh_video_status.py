#!/usr/bin/env python3
"""
Refresh queue/generating/done status for all shots whose videoTask.status == 'generating'.

Writes into shot-NN.json.videoTask:
  queueStatus:  'queuing' | 'generating' (only meaningful when status is still 'generating')
  queueIdx:     0-based index in queue (when querying returns queue_info)
  status:       'done' / 'failed' / keep 'generating'
  videoUrl, completedAt, failReason: updated on terminal transitions

For terminal 'done' it also downloads video to projects/<project>/outputs/<ep>/videos/shot-NN.mp4
and tries to capture the tail frame (ffmpeg required).
"""
import json, os, re, glob, subprocess, datetime, sys, shutil, urllib.request

PROJECT_ROOT = "/data/workspace/waoowaoo/seedance2.0"
PROJECT = sys.argv[1] if len(sys.argv) > 1 else "马上看中国史"
EP = sys.argv[2] if len(sys.argv) > 2 else "ep01"

project_dir = f"{PROJECT_ROOT}/projects/{PROJECT}"
shots_dir = f"{project_dir}/outputs/{EP}/06-shots"
videos_dir = f"{project_dir}/outputs/{EP}/videos"
tails_dir = f"{project_dir}/outputs/{EP}/tail-frames"
os.makedirs(videos_dir, exist_ok=True)
os.makedirs(tails_dir, exist_ok=True)

def now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")

def query(submit_id: str) -> dict:
    r = subprocess.run(["dreamina", "query_result", "--submit_id", submit_id],
                       capture_output=True, text=True, timeout=60)
    out = r.stdout or ""
    # The CLI prints a JSON block; try to locate it
    m = re.search(r"\{[\s\S]*\}", out)
    if not m:
        return {"_raw": out, "_err": "no-json"}
    try:
        obj = json.loads(m.group(0))
    except Exception:
        return {"_raw": out, "_err": "json-parse-failed"}
    # queue_info.debug_info might be a stringified JSON; not critical
    return obj

def download(url: str, dst: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=120) as resp, open(dst, "wb") as f:
            shutil.copyfileobj(resp, f)
        return True
    except Exception as e:
        print(f"    download failed: {e}")
        return False

def grab_tail(mp4: str, jpg: str) -> bool:
    if not shutil.which("ffmpeg"):
        return False
    try:
        subprocess.run(
            ["ffmpeg","-y","-sseof","-0.5","-i",mp4,"-vframes","1","-q:v","2",jpg],
            capture_output=True, timeout=60,
        )
        return os.path.exists(jpg)
    except Exception:
        return False


def _parse_duration_from_title(title_bar: str) -> int:
    m = re.search(r"(\d+)\s*秒", title_bar or "")
    return int(m.group(1)) if m else 15


def _cost_log_video(idx: str, vt: dict, title_bar: str):
    """下载成功后调 cost-logger 记账（taskId 幂等）。"""
    try:
        duration = _parse_duration_from_title(title_bar)
        model = vt.get("modelName") or "unknown"
        task_id = vt.get("taskId") or ""
        credit = vt.get("creditCount")
        note = f"auto: refresh download@{now_iso()}"
        if credit is not None:
            note += f"; credit={credit}"
        cmd = ["python3", f"{PROJECT_ROOT}/scripts/cost-logger.py", "video",
               "--project", PROJECT, "--episode", EP,
               "--target", f"shot-{idx}",
               "--model", str(model),
               "--duration", str(duration),
               "--note", note]
        if task_id:
            cmd += ["--task-id", task_id]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        out = (r.stdout or "").strip() or (r.stderr or "").strip()
        print(f"    💰 cost-log: {out}")
    except Exception as e:
        print(f"    ⚠️  cost-log exception: {e}")

def refresh_shot(path: str):
    shot = json.load(open(path))
    vt = shot.get("videoTask") or {}
    if vt.get("status") != "generating":
        return None
    tid = vt.get("taskId")
    if not tid:
        return None
    idx = re.search(r"shot-(\d+)\.json", path).group(1)
    resp = query(tid)
    gs = resp.get("gen_status", "")
    qi = resp.get("queue_info") or {}
    # 视频 URL 在 result_json.videos[0].video_url（不是顶层）
    url = ""
    try:
        rj = resp.get("result_json") or {}
        vids = rj.get("videos") or []
        if vids:
            url = vids[0].get("video_url") or ""
    except Exception:
        url = ""
    fail = resp.get("fail_reason") or ""

    if gs == "success" and url:
        # 成功出片：下载并截尾帧
        mp4 = f"{videos_dir}/shot-{idx}.mp4"
        ok = download(url, mp4)
        if ok:
            jpg = f"{tails_dir}/tail-shot-{idx}.jpg"
            grab_tail(mp4, jpg)
            vt["videoUrl"] = url
            vt["videoFile"] = f"outputs/{EP}/videos/shot-{idx}.mp4"
            vt["tailFrame"] = f"outputs/{EP}/tail-frames/tail-shot-{idx}.jpg" if os.path.exists(jpg) else ""
            vt["status"] = "done"
            vt["queueStatus"] = ""
            vt["queueIdx"] = None
            vt["completedAt"] = now_iso()
            print(f"  ✅ shot-{idx} done ({os.path.getsize(mp4)//1024}KB)")
            # 自动记账（taskId 幂等）
            _cost_log_video(idx, vt, shot.get("titleBar", ""))
        else:
            print(f"  ⚠️  shot-{idx} url ok but download failed")
    elif gs in ("fail", "failed") or (fail and not gs):
        vt["status"] = "failed"
        vt["failReason"] = fail or "unknown"
        vt["queueStatus"] = ""
        vt["completedAt"] = now_iso()
        print(f"  ❌ shot-{idx} failed: {fail}")
    elif gs == "querying":
        qstatus = (qi.get("queue_status") or "").lower()
        if qstatus == "generating":
            vt["queueStatus"] = "generating"
            vt["queueIdx"] = qi.get("queue_idx")
            print(f"  ⏳ shot-{idx} rendering (queue_idx={qi.get('queue_idx')})")
        elif qi:
            vt["queueStatus"] = "queuing"
            vt["queueIdx"] = qi.get("queue_idx")
            print(f"  🕒 shot-{idx} queuing (queue_status={qstatus})")
        else:
            # queue_info 为空；看提交时间判 stuck
            submitted = vt.get("submittedAt", "")
            stuck = False
            if submitted:
                try:
                    t0 = datetime.datetime.fromisoformat(submitted)
                    mins = (datetime.datetime.now(t0.tzinfo) - t0).total_seconds() / 60
                    if mins > 10:
                        stuck = True
                except Exception:
                    pass
            if stuck:
                vt["status"] = "stuck"
                vt["queueStatus"] = ""
                vt["failReason"] = "提交后 10+ 分钟仍未进入即梦队列，疑似服务端静默丢单"
                vt["completedAt"] = now_iso()
                print(f"  🔴 shot-{idx} STUCK (queue_info 空且已过 10min)")
            else:
                vt["queueStatus"] = "queuing"
                vt["queueIdx"] = None
                print(f"  🕒 shot-{idx} queuing (no queue_info yet, 刚提交)")
    else:
        print(f"  ? shot-{idx} gen_status={gs}")

    shot["videoTask"] = vt
    json.dump(shot, open(path, "w"), ensure_ascii=False, indent=2)
    return vt.get("status")

if __name__ == "__main__":
    files = sorted(glob.glob(f"{shots_dir}/shot-*.json"))
    generating = []
    for f in files:
        d = json.load(open(f))
        if (d.get("videoTask") or {}).get("status") == "generating":
            generating.append(f)
    print(f"Found {len(generating)} generating shots; refreshing...")
    stats = {"done":0,"failed":0,"queuing":0,"rendering":0,"other":0}
    for f in generating:
        s = refresh_shot(f)
        if s == "done": stats["done"] += 1
        elif s == "failed": stats["failed"] += 1
        elif s == "generating":
            # 再判细分
            d = json.load(open(f))
            qs = (d["videoTask"].get("queueStatus") or "")
            if qs == "queuing": stats["queuing"] += 1
            elif qs == "generating": stats["rendering"] += 1
            else: stats["other"] += 1
    print("\n=== SUMMARY ===")
    for k,v in stats.items(): print(f"  {k}: {v}")
