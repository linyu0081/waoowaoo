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

# 精简模式：仅保留核心五字段（快打+规避 IP）
SLIM_PROMPT_FIELDS = [
    "mount", "camera", "mainPrompt", "compulsoryDeclaration", "qualityBaseline",
]

# ===== 视频时长上限（2026-04-20 起生效）=====
# 即梦 seedance 系列 duration 字段硬上限 = 15 秒（超过直接被平台静默拒）
# 策略：
#   - 估算 ≤ DURATION_MAX_SEC（15） ：原样传
#   - DURATION_MAX_SEC < 估算 ≤ DURATION_CLAMP_SEC（18）：自动 clamp 为 15 秒提交
#   - 估算 > DURATION_CLAMP_SEC（18）：拒绝进入候选池（入池阶段打 needsRework）
DURATION_MAX_SEC = 15
DURATION_CLAMP_SEC = 18


def parse_duration_raw(title_bar: str) -> int:
    """只解析 titleBar 中的秒数（兜底 15），不做 clamp，用于拦截判断/记账。"""
    m = re.search(r"(\d+)\s*秒", title_bar or "")
    return int(m.group(1)) if m else 15


def parse_duration(title_bar: str) -> int:
    """解析并 clamp 到 DURATION_MAX_SEC 以内，用于实际提交 API。
    注意：此处不拦截 >18s 的情形（拦截发生在入池前），这里只保底确保 API 不报错。
    """
    raw = parse_duration_raw(title_bar)
    return min(raw, DURATION_MAX_SEC)


def check_duration_gate(title_bar: str):
    """入池前的时长闸门。返回 (ok, action, raw_sec, submit_sec, reason).
    action ∈ {'pass', 'clamp', 'reject'}:
      - 'pass'  ：raw ≤ 15，不 clamp，按 raw 提交
      - 'clamp' ：15 < raw ≤ 18，自动 clamp 为 15 秒提交（允许入池）
      - 'reject'：raw > 18，拒绝入池，应让分镜师返工
    """
    raw = parse_duration_raw(title_bar)
    if raw <= DURATION_MAX_SEC:
        return (True, "pass", raw, raw, "")
    if raw <= DURATION_CLAMP_SEC:
        return (True, "clamp", raw, DURATION_MAX_SEC,
                f"时长 {raw}s 超过硬上限 {DURATION_MAX_SEC}s，已自动 clamp 为 {DURATION_MAX_SEC}s 提交")
    return (False, "reject", raw, DURATION_MAX_SEC,
            f"时长 {raw}s 超过最大阈值 {DURATION_CLAMP_SEC}s，建议分镜师拆分镜头（单镜 ≤ {DURATION_MAX_SEC}s）")


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


def _build_prompt(shot: dict, img_nums, aud_nums, prompt_mode: str = "full") -> str:
    fields = SLIM_PROMPT_FIELDS if str(prompt_mode).lower() == "slim" else PROMPT_FIELDS
    parts = []
    for f in fields:
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


VALID_INHERIT_REASONS = {
    "opening-shot",
    "action-continuation",
    "has-scene-ref",
    "same-scene-no-ref",
}


def validate_scene_continuity(shot: dict, idx: int) -> list:
    """
    校验 shot 的 sceneContinuity 字段与 mount 一致性（R1/R2）。
    返回 warnings 列表，空列表表示校验通过。不抛异常，不阻塞提交（上游决定如何处理）。

    R1（承接必标）：inheritFromPrev==true  ⇒ mount 必须以 "｜本视频以@图片N为首帧" 结尾
    R2（不承接必净）：inheritFromPrev==false ⇒ mount 禁止出现 "本视频以@图片N为首帧"
    """
    warnings = []
    sc = shot.get("sceneContinuity")
    mount = shot.get("mount", "")
    mount_has_head = bool(re.search(r"本视频以@图片(\d+)为首帧", mount))

    if sc is None:
        # 未填 sceneContinuity：旧数据兼容，只提示，不拦截
        warnings.append(f"shot-{idx}: 未填 sceneContinuity 字段（新规范要求必填）")
        return warnings

    if not isinstance(sc, dict):
        warnings.append(f"shot-{idx}: sceneContinuity 必须是对象")
        return warnings

    inherit = sc.get("inheritFromPrev")
    reason = sc.get("inheritReason")

    if not isinstance(inherit, bool):
        warnings.append(f"shot-{idx}: sceneContinuity.inheritFromPrev 必须是布尔值")
    if reason not in VALID_INHERIT_REASONS:
        warnings.append(
            f"shot-{idx}: sceneContinuity.inheritReason 非法（{reason!r}），"
            f"应为 {sorted(VALID_INHERIT_REASONS)} 之一"
        )

    # R1 / R2 互锁
    if inherit is True and not mount_has_head:
        warnings.append(
            f"shot-{idx}: [R1 违规] inheritFromPrev=true 但 mount 缺少 '本视频以@图片N为首帧'"
        )
    if inherit is False and mount_has_head:
        warnings.append(
            f"shot-{idx}: [R2 违规] inheritFromPrev=false 但 mount 出现 '本视频以@图片N为首帧'"
        )

    # 首镜校验：idx==0 时 reason 必须是 opening-shot
    if idx == 0 and reason != "opening-shot":
        warnings.append(
            f"shot-{idx}: 首镜 inheritReason 应为 'opening-shot'，当前为 {reason!r}"
        )

    return warnings


def check_tail_frame_ready(project_root, project, ep, idx):
    """
    返回 (needs_tail: bool, tail_ready: bool, tail_ref_num: str|None)
    needs_tail=False → 该镜不依赖前镜尾帧，可直接提交
    needs_tail=True, tail_ready=False → 依赖但尾帧未生成，应跳过
    needs_tail=True, tail_ready=True → 依赖且已就绪，可提交

    判定优先级：
      ① sceneContinuity.inheritFromPrev（结构化字段，v6+ 分镜师规范）
      ② mount 中的 '本视频以@图片N为首帧' 子串（v5 旧数据回退）
    两者同时存在时以 mount 的 tail_num 为准（mount 是送审真相），但会打印一致性警告。
    """
    p = _ep_paths(project_root, project, ep)
    shot = json.load(open(f"{p['shots_dir']}/shot-{idx}.json"))
    mount = shot.get("mount", "")
    sc = shot.get("sceneContinuity") or {}
    sc_inherit = sc.get("inheritFromPrev") if isinstance(sc, dict) else None

    m = re.search(r"本视频以@图片(\d+)为首帧", mount)
    mount_has_head = bool(m)

    # 先做一致性校验（不阻塞，只打印到 stderr 方便排查）
    if sc_inherit is True and not mount_has_head:
        import sys
        print(
            f"[video_submit] shot-{idx} R1 违规：sceneContinuity.inheritFromPrev=true "
            f"但 mount 未标首帧引用",
            file=sys.stderr,
        )
    if sc_inherit is False and mount_has_head:
        import sys
        print(
            f"[video_submit] shot-{idx} R2 违规：sceneContinuity.inheritFromPrev=false "
            f"但 mount 出现首帧引用（将按 mount 为准）",
            file=sys.stderr,
        )

    # 真正的就绪判定仍以 mount 的 tail_num 为准（送审 prompt 才是事实）
    if not mount_has_head:
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
                log_dir=None, dry_run=False, prompt_mode="full"):
    """
    提交单镜到 Dreamina。返回 submit_id（成功）或 None（失败）。
    会写入 shot-NN.json 的 videoTask 字段。
    prompt_mode: 'full'（默认，拼 PROMPT_FIELDS 全部字段）或 'slim'（仅 SLIM_PROMPT_FIELDS）。
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

    # 时长闸门：raw 解析 → clamp 到硬上限（>18s 理论上不应该走到这里，因为入池时已拦截）
    title_bar = shot.get("titleBar", "")
    raw_sec = parse_duration_raw(title_bar)
    duration = min(raw_sec, DURATION_MAX_SEC)
    clamped = raw_sec != duration
    if raw_sec > DURATION_CLAMP_SEC:
        # 兵天降 —— 入池闸门漏了或被 force 绕过，在这里也拒绝提交
        return {
            "ok": False,
            "reason": f"duration {raw_sec}s > {DURATION_CLAMP_SEC}s 硬阈值，拒绝提交（需分镜师返工拆分）",
            "submit_id": None,
            "durationRejected": True,
            "rawSec": raw_sec,
        }
    prompt = _build_prompt(shot, img_nums, aud_nums, prompt_mode=prompt_mode)

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

    # ⚠️ 注意：不能用字面量对象整体覆盖 videoTask，否则会把调度器写入的
    #   autoRetryCount / failHistory / lastAutoRetryAt 等跨提交字段擦掉，
    #   导致 _auto_requeue_failed 永远读到 0，形成死循环重投同一镜。
    shot["videoTask"] = {
        **vt,  # 先保留上一次的所有字段（autoRetryCount / failHistory / lastAutoRetryAt / needsRework 等）
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
        # 显式确保跨提交字段存在且保留
        "autoRetryCount": int(vt.get("autoRetryCount") or 0),
        "failHistory": vt.get("failHistory") or [],
        "lastAutoRetryAt": vt.get("lastAutoRetryAt", ""),
    }
    if clamped:
        # 记录本次提交发生了 duration clamp，方便后续排查
        shot["videoTask"]["_durationClamp"] = {
            "rawSec": raw_sec,
            "clampedSec": duration,
            "clampedAt": shot["videoTask"]["submittedAt"],
            "reason": f"auto-clamp on submit: {raw_sec}s → {duration}s",
        }
    with open(path, "w") as f:
        json.dump(shot, f, ensure_ascii=False, indent=2)

    return {"ok": True, "reason": "", "submit_id": submit_id}
