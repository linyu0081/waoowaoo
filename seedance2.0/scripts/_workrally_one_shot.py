#!/usr/bin/env python3
"""
workrally 单镜提交工具（SD2.0 SubjectToVideo · full / slim prompt · 全能参考）
用法：
  python3 scripts/_workrally_one_shot.py <shot_num> [--use-current] [--slim]
例如：
  python3 scripts/_workrally_one_shot.py 13
  python3 scripts/_workrally_one_shot.py 16 --use-current           # mainPrompt 刚改写过，读最新 json
  python3 scripts/_workrally_one_shot.py 16 --use-current --slim    # 读最新 json 且只拼 5 段精简字段（pre-TNS 救场）

流程：
  1) 默认读 shot-N.json.bak（最老备份，full mainPrompt）
     加 --use-current 则读 shot-N.json（改写后的最新版）
  2) 从 mount 字段解析 @图片N（角色+场景+首帧），逐一 workrally upload 拿 URL
  3) @图片N 按 reference-assets 数组顺序重编号，@音频N 同理
  4) 按 full 模式拼 18 段 prompt
  5) workrally generate video --model 18 --mode SubjectToVideo --enable-sound --duration=min(titleBar时长,15)
  6) 把 task_id / ref URLs 写回 shot-N.json.videoTask（status=generating）
  7) 轮询到成功 → workrally download → ffmpeg 截尾帧 → 回写 status=done → cost-logger 记账
  8) 若失败：把 task_id 写到 failHistory，status=failed，报错退出
"""
import json, re, subprocess, sys, time, os, glob

PROJECT_ROOT = "/data/workspace/waoowaoo/seedance2.0"
WORKRALLY_BIN = "/root/.workbuddy/binaries/node/versions/20.18.0/bin/workrally"
EP_ROOT = f"{PROJECT_ROOT}/projects/马上看中国史/outputs/ep01"
SHOTS_DIR = f"{EP_ROOT}/06-shots"
ASSET_MAP = f"{EP_ROOT}/asset-map.json"
PROJECT_ASSETS = f"{PROJECT_ROOT}/projects/马上看中国史"  # asset-map 里 file 字段的 base
TAIL_DIR = f"{EP_ROOT}/tail-frames"
VIDEOS_DIR = f"{EP_ROOT}/videos"

PROMPT_FIELDS = [
    "titleBar","mount","camera","openingFrame","closingFrame","connection",
    "transition","dualAnchor","mainPrompt","compulsoryDeclaration","mustShow",
    "qualityRoute","imagingStyle","qualityBaseline","reference",
    "microExpressions","nailLines","e15",
]

# 精简字段（与 video_submit.py 的 SLIM_PROMPT_FIELDS 对齐）：pre-TNS 救场用
SLIM_PROMPT_FIELDS = [
    "mount", "camera", "mainPrompt", "compulsoryDeclaration", "qualityBaseline",
]

def load_json(p):
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(p, d):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)

def shellrun(cmd, check=True):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if check and r.returncode != 0:
        print("CMD FAIL:", " ".join(cmd[:3]), "...")
        print("STDERR:", r.stderr)
        sys.exit(1)
    return r

def extract_json_block(out):
    """workrally CLI 输出里抓 JSON 块（可能前面有上传动画，后面有提示）。"""
    m = re.search(r'\{[\s\S]*?\}(?=\s*$|\s*\n[^{])', out.strip())
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    # 兜底：逐行找第一个完整的 JSON 顶层 {
    depth = 0; start = -1
    for i, ch in enumerate(out):
        if ch == '{':
            if depth == 0: start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return json.loads(out[start:i+1])
                except Exception:
                    start = -1
    return None

def upload(local):
    r = shellrun([WORKRALLY_BIN, "upload", local, "-o", "json"])
    j = extract_json_block(r.stdout)
    if not j or "url" not in j:
        print("upload 解析失败:", r.stdout); sys.exit(1)
    return j["url"]

def parse_mount_refs(shot):
    """从 shot.mount 解析 (角色, 场景, 首帧) 的 @图片N；顺序固定：角色→场景→首帧。"""
    mount = shot.get("mount", "")
    # @图片N 全部按 mount 里出现顺序
    img_ids = [int(x) for x in re.findall(r"@图片(\d+)", mount)]
    aud_ids = [int(x) for x in re.findall(r"@音频(\d+)", mount)]
    return img_ids, aud_ids

def resolve_image_path(amap, img_no):
    meta = amap["images"].get(f"@图片{img_no}")
    if not meta:
        # 可能是 tail-shot-N.jpg 类的 @图片46/49/51 等在 images 里
        return None, None
    f = meta["file"]
    # 优先在 ep01 下（有些是 tail-frames），否则在项目根
    p1 = os.path.join(EP_ROOT, f)
    p2 = os.path.join(PROJECT_ASSETS, f)
    if os.path.exists(p1): return p1, meta
    if os.path.exists(p2): return p2, meta
    return None, meta

def renumber(text, img_remap, aud_remap):
    text = re.sub(r"@图片(\d+)", lambda m: f"@图片{img_remap.get(int(m.group(1)), int(m.group(1)))}", text)
    text = re.sub(r"@音频(\d+)", lambda m: f"@音频{aud_remap.get(int(m.group(1)), int(m.group(1)))}", text)
    return text

def build_prompt(shot, img_remap, aud_remap, slim=False):
    fields = SLIM_PROMPT_FIELDS if slim else PROMPT_FIELDS
    parts = []
    for fld in fields:
        v = shot.get(fld, "")
        if not v: continue
        parts.append(f"【{fld}】{renumber(v, img_remap, aud_remap)}")
    return "\n".join(parts)

def parse_duration_from_titlebar(tb):
    m = re.search(r"(\d+)秒", tb or "")
    if m: return int(m.group(1))
    return 12

def main():
    if len(sys.argv) < 2:
        print("用法: python3 _workrally_one_shot.py <shot_num> [--use-current]"); sys.exit(2)
    n = int(sys.argv[1])
    use_current = "--use-current" in sys.argv[2:]
    slim_mode   = "--slim" in sys.argv[2:]
    shot_json_path = f"{SHOTS_DIR}/shot-{n}.json"
    shot_bak_path = f"{SHOTS_DIR}/shot-{n}.json.bak"

    if use_current:
        # 显式要求用最新 shot-N.json 作为 prompt 源（e.g. 刚改写过 mainPrompt 的情况）
        print(f"[shot-{n}] --use-current：用最新 shot-{n}.json 作为 prompt 源")
        src_path = shot_json_path
    else:
        # 备份选择：优先 shot-N.json.bak（最早的 full 版）；否则挑 shot-N.json.bak.* 中 mtime 最老的
        if not os.path.exists(shot_bak_path):
            candidates = sorted(glob.glob(f"{SHOTS_DIR}/shot-{n}.json.bak.*"), key=os.path.getmtime)
            if not candidates:
                print(f"缺少 {shot_bak_path}（且无 .bak.* 兜底）"); sys.exit(1)
            shot_bak_path = candidates[0]
            print(f"[shot-{n}] .bak 不存在，回落到最老备份 {os.path.basename(shot_bak_path)}")
        src_path = shot_bak_path
    shot = load_json(src_path)
    cur = load_json(shot_json_path)  # 要把结果写回这个
    amap = load_json(ASSET_MAP)

    # Step 1: 解析 mount 里的 @图片N（保持顺序=角色→场景→首帧）
    img_ids, aud_ids = parse_mount_refs(shot)
    print(f"[shot-{n}] mount @图片 = {img_ids} | @音频 = {aud_ids}")
    if not img_ids:
        print("未从 mount 解析到 @图片N"); sys.exit(1)

    # Step 2: 逐一上传，建立重编号映射
    ref_assets = []
    img_remap = {}
    for new_no, old_no in enumerate(img_ids, start=1):
        local, meta = resolve_image_path(amap, old_no)
        if not local:
            print(f"找不到 @图片{old_no} 的本地文件"); sys.exit(1)
        url = upload(local)
        role = f"{meta.get('type','?')}-{meta.get('name','?')}" if meta else "?"
        ref_assets.append({"role": role, "url": url, "srcImg": f"@图片{old_no}"})
        img_remap[old_no] = new_no
        print(f"  @图片{old_no} -> @图片{new_no} ({role}) {local}")

    aud_remap = {}
    for new_no, old_no in enumerate(aud_ids, start=1):
        aud_remap[old_no] = new_no

    # Step 3: 拼 prompt
    prompt = build_prompt(shot, img_remap, aud_remap, slim=slim_mode)
    duration_raw = parse_duration_from_titlebar(shot.get("titleBar",""))
    duration = min(duration_raw, 15)
    mode_tag = "slim" if slim_mode else "full"
    print(f"[shot-{n}] prompt {len(prompt)} 字 · mode={mode_tag} · duration={duration}s (orig {duration_raw}s)")

    # Step 4: 提交
    ref_json = json.dumps([{"url": a["url"]} for a in ref_assets], ensure_ascii=False)
    cmd = [
        WORKRALLY_BIN,"generate","video",
        "--prompt", prompt,
        "--model","18",
        "--mode","SubjectToVideo",
        "--duration", str(duration),
        "--reference-assets", ref_json,
        "--enable-sound",
        "--name", f"shot-{n}-workrally-{mode_tag}",
        "-o","json",
    ]
    r = shellrun(cmd)
    j = extract_json_block(r.stdout)
    if not j or "task_ids" not in j:
        print("提交失败:", r.stdout); sys.exit(1)
    task_id = j["task_ids"][0]
    print(f"[shot-{n}] task_id = {task_id}")

    # Step 5: 写回 videoTask（generating）
    now = time.strftime("%Y-%m-%dT%H:%M:%S+08:00", time.localtime())
    old_hist = cur.get("videoTask", {}).get("failHistory", [])
    cur["videoTask"] = {
        **cur.get("videoTask", {}),
        "engine": "workrally",
        "modelName": "Zen-SD2.0",
        "taskId": task_id,
        "status": "generating",
        "videoUrl": "",
        "videoFile": "",
        "tailFrame": "",
        "failReason": "",
        "submittedAt": now,
        "completedAt": "",
        "promptMode": mode_tag,
        "workrallyMode": "SubjectToVideo",
        "workrallyReferenceAssets": [{"role": a["role"], "url": a["url"], "srcImg": a["srcImg"]} for a in ref_assets],
        "failHistory": old_hist,
    }
    save_json(shot_json_path, cur)

    # Step 6: 轮询
    print(f"[shot-{n}] 轮询中 ...", flush=True)
    success_asset = None
    for _ in range(80):   # 最多 ~15 分钟
        time.sleep(15)
        r = shellrun([WORKRALLY_BIN,"generate","task", task_id, "-o","json"], check=False)
        tj = extract_json_block(r.stdout)
        if not tj:
            print("  轮询响应解析失败, retry"); continue
        st = tj.get("state")
        progress = tj.get("progress", 0)
        desc = tj.get("state_desc","")
        print(f"  state={st} {desc} progress={progress}", flush=True)
        # 实时写回进度到 shot.json（供心跳 / dashboard 读取）
        try:
            _cur = load_json(shot_json_path)
            _vt = _cur.get("videoTask") or {}
            _vt["progress"] = progress
            _vt["progressUpdatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S+08:00", time.localtime())
            _cur["videoTask"] = _vt
            save_json(shot_json_path, _cur)
        except Exception as _pe:
            print(f"  ⚠️ 写回进度失败: {_pe}")
        if st == 4:  # SUCCESS
            success_asset = tj["output_assets"][0]
            break
        if st in (5, 6, 7):  # FAIL 类
            print(f"[shot-{n}] 任务失败: {tj}")
            cur["videoTask"]["status"] = "failed"
            cur["videoTask"]["failReason"] = tj.get("message","failed")
            cur["videoTask"]["completedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S+08:00", time.localtime())
            save_json(shot_json_path, cur)
            sys.exit(3)

    if not success_asset:
        print(f"[shot-{n}] 超时未成功"); sys.exit(4)

    asset_id = success_asset["asset_id"]
    print(f"[shot-{n}] SUCCESS asset_id={asset_id}")

    # Step 7: 下载
    os.makedirs(VIDEOS_DIR, exist_ok=True)
    shellrun([WORKRALLY_BIN,"download", asset_id, "-d", VIDEOS_DIR+"/", "-n", f"shot-{n}.mp4"])

    # Step 8: 截尾帧
    os.makedirs(TAIL_DIR, exist_ok=True)
    video_fp = f"{VIDEOS_DIR}/shot-{n}.mp4"
    tail_fp = f"{TAIL_DIR}/tail-shot-{n}.jpg"
    shellrun(["ffmpeg","-sseof","-0.1","-i",video_fp,"-vframes","1","-q:v","2","-y",tail_fp], check=False)

    # Step 9: 回写 done
    cur["videoTask"]["status"] = "done"
    cur["videoTask"]["videoFile"] = f"outputs/ep01/videos/shot-{n}.mp4"
    cur["videoTask"]["tailFrame"] = f"outputs/ep01/tail-frames/tail-shot-{n}.jpg"
    cur["videoTask"]["assetId"] = asset_id
    cur["videoTask"]["completedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S+08:00", time.localtime())
    save_json(shot_json_path, cur)

    # Step 10: cost-log
    shellrun([
        "python3","scripts/cost-logger.py","video",
        "--project","马上看中国史","--episode","ep01",
        "--target", f"shot-{n}",
        "--model","18","--duration", str(duration),
        "--task-id", task_id,
        "--note", f"workrally Zen-SD2.0 SubjectToVideo · {mode_tag} prompt · 批量救场"
    ], check=False)

    print(f"[shot-{n}] ✅ ALL DONE  video={video_fp}  tail={tail_fp}")

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise  # 保留 sys.exit() 的退出码
    except Exception:
        import traceback
        traceback.print_exc()
        # 尝试将 shot.json 的 videoTask.status 写回 failed，防止状态卡在 pending/generating
        try:
            n = int(sys.argv[1]) if len(sys.argv) > 1 else None
            if n is not None:
                _path = f"{SHOTS_DIR}/shot-{n}.json"
                if os.path.exists(_path):
                    _d = load_json(_path)
                    _vt = _d.get("videoTask") or {}
                    if _vt.get("status") in ("pending", "generating"):
                        _vt["status"] = "failed"
                        _vt["failReason"] = f"子进程异常崩溃: {traceback.format_exc()[-200:]}"
                        _vt["completedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S+08:00", time.localtime())
                        _d["videoTask"] = _vt
                        save_json(_path, _d)
                        print(f"[shot-{n}] ⚠️ 已将 videoTask.status 写回 failed")
        except Exception as _inner:
            print(f"⚠️ 写回 failed 状态也失败了: {_inner}")
        sys.exit(99)
