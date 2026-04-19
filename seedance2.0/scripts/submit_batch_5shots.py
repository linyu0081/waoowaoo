#!/usr/bin/env python3
"""
Batch submit 5 shots to Dreamina CLI with seedance2.0fast.
- Serial submission (parallel-uncertainty, see dreamina-video-skill 3.3)
- For each shot: parse mount → build --image/--audio → renumber @图片N in prompt
- On submit_id captured: write videoTask with status=generating
- Polling disabled (--poll 0): refresh later via batch query_result
"""
import json, re, os, sys, subprocess, datetime, pathlib

PROJECT_ROOT = "/data/workspace/waoowaoo/seedance2.0"
PROJECT = "马上看中国史"
EP = "ep01"
MODEL = "seedance2.0fast"
RATIO = "16:9"

SHOTS = ["00", "07", "10", "13", "14"]

project_dir = f"{PROJECT_ROOT}/projects/{PROJECT}"
shots_dir = f"{project_dir}/outputs/{EP}/06-shots"
asset_map = json.load(open(f"{project_dir}/outputs/{EP}/asset-map.json"))

PROMPT_FIELDS = [
    "titleBar","mount","camera","openingFrame","closingFrame","connection",
    "transition","dualAnchor","mainPrompt","compulsoryDeclaration","mustShow",
    "qualityRoute","imagingStyle","qualityBaseline","reference",
    "microExpressions","nailLines","e15",
]

def parse_duration(title_bar: str) -> int:
    m = re.search(r"(\d+)\s*秒", title_bar)
    return int(m.group(1)) if m else 15

def extract_refs(mount: str):
    imgs, auds = [], []
    for m in re.finditer(r"@图片(\d+)", mount):
        n = m.group(1)
        if n not in imgs: imgs.append(n)
    for m in re.finditer(r"@音频(\d+)", mount):
        n = m.group(1)
        if n not in auds: auds.append(n)
    return imgs, auds

def renumber_prompt(text: str, img_nums, aud_nums):
    img_map = {old: str(i+1) for i, old in enumerate(img_nums)}
    aud_map = {old: str(i+1) for i, old in enumerate(aud_nums)}
    for old in sorted(img_map.keys(), key=lambda x: -int(x)):
        text = text.replace(f"@图片{old}", f"\x01IMG{img_map[old]}\x02")
    text = re.sub(r"\x01IMG(\d+)\x02", r"@图片\1", text)
    for old in sorted(aud_map.keys(), key=lambda x: -int(x)):
        text = text.replace(f"@音频{old}", f"\x01AUD{aud_map[old]}\x02")
    text = re.sub(r"\x01AUD(\d+)\x02", r"@音频\1", text)
    return text

def build_prompt(shot: dict, img_nums, aud_nums) -> str:
    parts = []
    for f in PROMPT_FIELDS:
        v = shot.get(f, "")
        if not v: continue
        v2 = renumber_prompt(v, img_nums, aud_nums)
        parts.append(f"【{f}】{v2}")
    return "\n".join(parts)

def submit_shot(idx: str):
    path = f"{shots_dir}/shot-{idx}.json"
    shot = json.load(open(path))
    vt = shot.get("videoTask") or {}
    if vt.get("status") == "done":
        print(f"[shot-{idx}] already done, skip")
        return None
    mount = shot["mount"]
    img_nums, aud_nums = extract_refs(mount)
    images = [f"{project_dir}/" + asset_map["images"][f"@图片{n}"]["file"] for n in img_nums]
    audios = [f"{project_dir}/" + asset_map["voices"][f"@音频{n}"]["file"] for n in aud_nums]
    duration = parse_duration(shot["titleBar"])
    prompt = build_prompt(shot, img_nums, aud_nums)

    cmd = ["dreamina", "multimodal2video"]
    for p in images: cmd += ["--image", p]
    for p in audios: cmd += ["--audio", p]
    cmd += ["--prompt", prompt,
            "--model_version", MODEL,
            "--duration", str(duration),
            "--ratio", RATIO,
            "--video_resolution", "720p",
            "--poll", "0"]
    log_path = f"{PROJECT_ROOT}/tmp-logs/dreamina-{EP}-{idx}.log"
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    print(f"\n=== [shot-{idx}] submitting (duration={duration}s, images={len(images)}, audios={len(audios)}) ===")
    print("  images:", [os.path.basename(x) for x in images])
    print("  audios:", [os.path.basename(x) for x in audios])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired as e:
        print(f"  ❌ timeout")
        open(log_path,"w").write(str(e))
        return None
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    open(log_path, "w").write(out)

    m = re.search(r'"?submit_id"?\s*[:=]\s*"?([0-9a-f\-]{32,})"?', out, re.I)
    if not m:
        print(f"  ❌ submit failed (rc={proc.returncode}); tail:")
        for line in out.strip().splitlines()[-5:]:
            print("   |", line)
        return None
    submit_id = m.group(1)
    print(f"  ✅ submit_id={submit_id}")

    cm = re.search(r'"credit_count"\s*:\s*(\d+)', out)
    credit = int(cm.group(1)) if cm else None

    shot["videoTask"] = {
        "engine": "dreamina",
        "modelName": MODEL,
        "taskId": submit_id,
        "status": "generating",
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
    return submit_id

if __name__ == "__main__":
    results = []
    for idx in SHOTS:
        sid = submit_shot(idx)
        results.append((idx, sid))
    print("\n=== BATCH RESULT ===")
    for idx, sid in results:
        print(f"  shot-{idx}: {sid or 'FAILED'}")
