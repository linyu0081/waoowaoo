#!/usr/bin/env python3
"""
Dreamina 单镜提交公共库。供 submit_batch / video_scheduler / 其他脚本复用。

主要函数：
- submit_shot(project_root, project, ep, idx, model="seedance2.0fast", ratio="16:9")
  成功返回 submit_id，失败返回 None。副作用：写入 shot-NN.json 的 videoTask。
- check_tail_frame_ready(project_root, project, ep, idx)
  检查该镜是否依赖前镜尾帧、且尾帧是否已就绪。返回 (needs_tail, tail_ready, tail_ref)。
"""
import json, re, os, subprocess, datetime

PROMPT_FIELDS = [
    "titleBar","mount","camera","openingFrame","closingFrame","connection",
    "transition","dualAnchor","mainPrompt","compulsoryDeclaration","mustShow",
    "qualityRoute","imagingStyle","qualityBaseline","reference",
    "microExpressions","nailLines","e15",
]


def parse_duration(title_bar: str) -> int:
    m = re.search(r"(\d+)\s*秒", title_bar or "")
    return int(m.group(1)) if m else 15


def extract_refs(mount: str):
    imgs, auds = [], []
    for m in re.finditer(r"@图片(\d+)", mount or ""):
        n = m.group(1)
        if n not in imgs: imgs.append(n)
    for m in re.finditer(r"@音频(\d+)", mount or ""):
        n = m.group(1)
        if n not in auds: auds.append(n)
    return imgs, auds


def _renumber(text: str, img_nums, aud_nums) -> str:
    img_map = {old: str(i+1) for i, old in enumerate(img_nums)}
    aud_map = {old: str(i+1) for i, old in enumerate(aud_nums)}
    for old in sorted(img_map.keys(), key=lambda x: -int(x)):
        text = text.replace(f"@图片{old}", f"\x01IMG{img_map[old]}\x02")
    text = re.sub(r"\x01IMG(\d+)\x02", r"@图片\1", text)
    for old in sorted(aud_map.keys(), key=lambda x: -int(x)):
        text = text.replace(f"@音频{old}", f"\x01AUD{aud_map[old]}\x02")
    text = re.sub(r"\x01AUD(\d+)\x02", r"@音频\1", text)
    return text


def _build_prompt(shot: dict, img_nums, aud_nums) -> str:
    parts = []
    for f in PROMPT_FIELDS:
        v = shot.get(f, "")
        if not v: continue
        parts.append(f"【{f}】{_renumber(v, img_nums, aud_nums)}")
    return "\n".join(parts)


def _ep_paths(project_root, project, ep):
    project_dir = f"{project_root}/projects/{project}"
    return {
        "project_dir": project_dir,
        "shots_dir": f"{project_dir}/outputs/{ep}/06-shots",
        "asset_map": f"{project_dir}/outputs/{ep}/asset-map.json",
        "videos_dir": f"{project_dir}/outputs/{ep}/videos",
        "tails_dir": f"{project_dir}/outputs/{ep}/tail-frames",
    }


def check_tail_frame_ready(project_root, project, ep, idx):
    """
    返回 (needs_tail: bool, tail_ready: bool, tail_ref_num: str|None)
    needs_tail=False → 该镜不依赖前镜尾帧，可直接提交
    needs_tail=True, tail_ready=False → 依赖但尾帧未生成，应跳过
    needs_tail=True, tail_ready=True → 依赖且已就绪，可提交
    """
    p = _ep_paths(project_root, project, ep)
    shot = json.load(open(f"{p['shots_dir']}/shot-{idx}.json"))
    mount = shot.get("mount", "")
    m = re.search(r"本视频以@图片(\d+)为首帧", mount)
    if not m:
        return (False, True, None)
    tail_num = m.group(1)
    asset_map = json.load(open(p["asset_map"]))
    entry = asset_map.get("images", {}).get(f"@图片{tail_num}", {})
    if entry.get("type") != "tail-frame":
        # mount 标了首帧但 asset-map 不是 tail-frame，按就绪处理（走用户素材）
        tail_file = entry.get("file", "")
        ready = bool(tail_file) and os.path.exists(f"{p['project_dir']}/{tail_file}")
        return (True, ready, tail_num)
    tail_file = entry.get("file", "")
    ready = bool(tail_file) and os.path.exists(f"{p['project_dir']}/{tail_file}")
    return (True, ready, tail_num)


def submit_shot(project_root, project, ep, idx,
                model="seedance2.0fast", ratio="16:9",
                log_dir=None, dry_run=False):
    """
    提交单镜到 Dreamina。返回 submit_id（成功）或 None（失败）。
    会写入 shot-NN.json 的 videoTask 字段。
    """
    p = _ep_paths(project_root, project, ep)
    path = f"{p['shots_dir']}/shot-{idx}.json"
    shot = json.load(open(path))
    vt = shot.get("videoTask") or {}
    if vt.get("status") in ("generating", "done"):
        return {"ok": False, "reason": f"shot-{idx} already {vt.get('status')}", "submit_id": None}

    mount = shot.get("mount", "")
    img_nums, aud_nums = extract_refs(mount)
    asset_map = json.load(open(p["asset_map"]))
    try:
        images = [f"{p['project_dir']}/" + asset_map["images"][f"@图片{n}"]["file"] for n in img_nums]
        audios = [f"{p['project_dir']}/" + asset_map["voices"][f"@音频{n}"]["file"] for n in aud_nums]
    except KeyError as e:
        return {"ok": False, "reason": f"asset-map miss: {e}", "submit_id": None}

    duration = parse_duration(shot.get("titleBar", ""))
    prompt = _build_prompt(shot, img_nums, aud_nums)

    cmd = ["dreamina", "multimodal2video"]
    for pth in images: cmd += ["--image", pth]
    for pth in audios: cmd += ["--audio", pth]
    cmd += ["--prompt", prompt,
            "--model_version", model,
            "--duration", str(duration),
            "--ratio", ratio,
            "--video_resolution", "720p",
            "--poll", "0"]

    if dry_run:
        return {"ok": True, "reason": "dry-run", "submit_id": None, "cmd": cmd}

    log_path = None
    if log_dir:
        log_path = f"{log_dir}/dreamina-{ep}-{idx}.log"
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired as e:
        if log_path: open(log_path, "w").write(str(e))
        return {"ok": False, "reason": "timeout", "submit_id": None}

    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if log_path: open(log_path, "w").write(out)

    m = re.search(r'"?submit_id"?\s*[:=]\s*"?([0-9a-f\-]{32,})"?', out, re.I)
    if not m:
        tail = "\n".join(out.strip().splitlines()[-5:])
        return {"ok": False, "reason": f"no submit_id; rc={proc.returncode}; tail:{tail}", "submit_id": None}

    submit_id = m.group(1)
    cm = re.search(r'"credit_count"\s*:\s*(\d+)', out)
    credit = int(cm.group(1)) if cm else None

    shot["videoTask"] = {
        "engine": "dreamina",
        "modelName": model,
        "taskId": submit_id,
        "status": "generating",
        "queueStatus": "",
        "queueIdx": None,
        "videoUrl": "",
        "videoFile": "",
        "tailFrame": "",
        "failReason": "",
        "creditCount": credit,
        "submittedAt": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "completedAt": "",
    }
    with open(path, "w") as f:
        json.dump(shot, f, ensure_ascii=False, indent=2)

    return {"ok": True, "reason": "", "submit_id": submit_id}
