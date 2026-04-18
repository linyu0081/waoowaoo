#!/usr/bin/env python3
"""
workrally 批量生图 + 轮询 + 下载工具
用法：
  python3 art_gen.py submit <任务定义json>     # 提交一批任务
  python3 art_gen.py poll <tasks_state.json>  # 轮询并下载
"""
import json, os, sys, subprocess, time, re
from pathlib import Path

def run(cmd):
    """Py3.6 兼容：替代 capture_output=True"""
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)

PROJECT = Path("/data/workspace/waoowaoo/seedance2.0/projects/马上看中国史")
IMAGES = PROJECT / "assets/images"
STATE = PROJECT / "outputs/ep01/.art-tasks.json"
WORKRALLY = "/data/home/allenyulin/.workbuddy/binaries/node/versions/20.18.0/bin/workrally"

def load_json(p: Path):
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def clean(out: str) -> str:
    """去掉 workrally 升级提醒等非 JSON 内容"""
    lines = []
    for ln in out.splitlines():
        if "─" in ln or "升级" in ln or "update" in ln.lower() and "available" in ln.lower():
            break
        lines.append(ln)
    return "\n".join(lines)

def parse_json(raw: str):
    raw = clean(raw).strip()
    # 找到第一个 { 或 [ 开始的部分
    m = re.search(r"[\{\[]", raw)
    if not m:
        return None
    return json.loads(raw[m.start():])

def submit(task):
    """
    task: {
      "name": "char-马上",
      "filename": "char-马上.png",
      "prompt": "...",
      "model": "314",
      "aspect_ratio": "16:9",
      "resolution": "0",
      "input_images": ["url1", ...]  # 可选
    }
    """
    cmd = [WORKRALLY, "generate", "image",
           "--prompt", task["prompt"],
           "--model", task.get("model", "314"),
           "--aspect-ratio", task.get("aspect_ratio", "16:9"),
           "--resolution", str(task.get("resolution", "0")),
           "--name", task["name"],
           "-o", "json"]
    if task.get("input_images"):
        cmd += ["--input-images", ",".join(task["input_images"])]
    print(f"📤 提交: {task['name']}")
    r = run(cmd)
    data = parse_json((r.stdout or '') + (r.stderr or ''))
    if not data:
        print(f"  ❌ 无法解析返回: {r.stdout[:200]} | err={r.stderr[:200]}")
        return None
    # 兼容 task_id / task_ids
    tid = data.get("task_id") or (data.get("task_ids") or [None])[0]
    print(f"  ✅ task_id={tid}")
    return tid

def poll_one(task_id):
    cmd = [WORKRALLY, "generate", "task", task_id, "-o", "json"]
    r = run(cmd)
    data = parse_json((r.stdout or '') + (r.stderr or ''))
    if not data:
        return None, "解析失败"
    state = data.get("state_desc") or data.get("state") or ""
    # asset_id 可能在 output_assets[0] 或顶层
    asset_id = None
    if "output_assets" in data and data["output_assets"]:
        asset_id = data["output_assets"][0].get("asset_id")
    if not asset_id:
        asset_id = data.get("asset_id")
    return {"state": state, "asset_id": asset_id, "raw": data}, None

def download(asset_id, filename):
    IMAGES.mkdir(parents=True, exist_ok=True)
    cmd = [WORKRALLY, "download", asset_id, "-d", str(IMAGES), "-n", filename]
    r = run(cmd)
    final = IMAGES / filename
    if final.exists():
        return final
    # 兼容自动命名
    print(f"  stdout: {r.stdout[:300]}")
    print(f"  stderr: {r.stderr[:300]}")
    return None

def upload(filepath):
    cmd = [WORKRALLY, "upload", str(filepath), "-o", "json"]
    r = run(cmd)
    merged = (r.stdout or '') + "\n" + (r.stderr or '')
    # 优先 grep url
    m = re.search(r'"url"\s*:\s*"([^"]+)"', merged)
    if m:
        return m.group(1)
    return None

def cmd_submit(tasks_file):
    tasks = load_json(Path(tasks_file))
    results = []
    for t in tasks:
        tid = submit(t)
        results.append({**t, "task_id": tid, "status": "submitted" if tid else "failed"})
        time.sleep(1)  # 温和节流
    save_json(STATE, results)
    print(f"\n📝 state 写入: {STATE}")
    print(f"共 {sum(1 for r in results if r['task_id'])}/{len(results)} 任务提交成功")

def cmd_poll(timeout=300):
    results = load_json(STATE)
    pending = [r for r in results if r.get("task_id") and r.get("status") != "done"]
    print(f"🔄 待轮询 {len(pending)} 个任务，最长等 {timeout}s")
    start = time.time()
    while pending and (time.time() - start) < timeout:
        still_pending = []
        for r in pending:
            info, err = poll_one(r["task_id"])
            if err:
                print(f"  ⚠️ {r['name']}: {err}")
                still_pending.append(r)
                continue
            state = info["state"]
            if "成功" in state or info["asset_id"]:
                print(f"  ✅ {r['name']} -> asset_id={info['asset_id']}, 开始下载")
                path = download(info["asset_id"], r["filename"])
                if path:
                    print(f"     📥 下载到 {path}")
                    r["status"] = "done"
                    r["asset_id"] = info["asset_id"]
                    r["local_path"] = str(path)
                else:
                    print(f"     ❌ 下载失败")
                    r["status"] = "download_failed"
                    r["asset_id"] = info["asset_id"]
            elif "失败" in state:
                print(f"  ❌ {r['name']}: {state}")
                r["status"] = "failed"
                r["error"] = state
            else:
                still_pending.append(r)
        save_json(STATE, results)
        pending = still_pending
        if pending:
            print(f"  ⏳ 还有 {len(pending)} 个处理中，等 20s ...")
            time.sleep(20)
    print("\n==== 结果汇总 ====")
    for r in results:
        print(f"  [{r.get('status','?'):15s}] {r['name']} -> {r.get('local_path') or r.get('error') or '-'}")

if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action == "submit":
        cmd_submit(sys.argv[2])
    elif action == "poll":
        cmd_poll(int(sys.argv[2]) if len(sys.argv) > 2 else 300)
    elif action == "upload":
        print(upload(sys.argv[2]))
    else:
        print(__doc__)
