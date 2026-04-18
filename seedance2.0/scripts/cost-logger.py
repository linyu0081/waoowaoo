#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cost-logger.py —— 成本流水记录器

每次调用 AI 生图 / 生视频后，用这个脚本记一笔。
会自动更新：
  1) projects/<项目>/outputs/<epNN>/07-costs.json  （流水 + 汇总）
  2) projects/<项目>/outputs/<epNN>/manifest.json  （stages.art / stages.video 的成本字段）
"""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def now_iso():
    return dt.datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def costs_path(project, episode):
    return REPO_ROOT / "projects" / project / "outputs" / episode / "07-costs.json"


def manifest_path(project, episode):
    return REPO_ROOT / "projects" / project / "outputs" / episode / "manifest.json"


def load_costs(project, episode):
    p = costs_path(project, episode)
    if p.exists():
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {
        "version": "1.0",
        "project": project,
        "episode": episode,
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
        "summary": {
            "imageGenCount": 0,
            "videoGenCount": 0,
            "videoUniqueShots": 0,
            "videoTotalDurationSec": 0,
            "videoTotalDurationMin": 0.0,
        },
        "byModel": {},
        "records": [],
    }


def save_costs(project, episode, data):
    p = costs_path(project, episode)
    p.parent.mkdir(parents=True, exist_ok=True)
    data["updatedAt"] = now_iso()
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def recompute_summary(data):
    records = data.get("records", [])
    img_cnt = 0
    vid_cnt = 0
    vid_unique = 0
    vid_total_sec = 0
    by_model = {}
    seen_video_targets = set()
    for r in records:
        t = r.get("type")
        m = str(r.get("model", "unknown"))
        if m not in by_model:
            by_model[m] = {"imageCount": 0, "videoCount": 0, "videoDurationSec": 0}
        if t == "image":
            img_cnt += 1
            by_model[m]["imageCount"] += 1
        elif t == "video":
            vid_cnt += 1
            by_model[m]["videoCount"] += 1
            dur = int(r.get("durationSec", 0) or 0)
            by_model[m]["videoDurationSec"] += dur
            target = r.get("target", "")
            if target and target not in seen_video_targets:
                seen_video_targets.add(target)
                vid_unique += 1
                vid_total_sec += dur
    data["summary"] = {
        "imageGenCount": img_cnt,
        "videoGenCount": vid_cnt,
        "videoUniqueShots": vid_unique,
        "videoTotalDurationSec": vid_total_sec,
        "videoTotalDurationMin": round(vid_total_sec / 60.0, 2),
    }
    data["byModel"] = by_model


def update_manifest(project, episode, data):
    mp = manifest_path(project, episode)
    if not mp.exists():
        print(f"[warn] manifest.json not found: {mp}", file=sys.stderr)
        return
    with open(mp, encoding="utf-8") as f:
        manifest = json.load(f)
    stages = manifest.setdefault("stages", {})
    art = stages.setdefault("art", {})
    video = stages.setdefault("video", {})
    s = data["summary"]
    art["imageGenCount"] = s["imageGenCount"]
    video["videoGenCount"] = s["videoGenCount"]
    video["videoUniqueShots"] = s["videoUniqueShots"]
    video["videoTotalDurationSec"] = s["videoTotalDurationSec"]
    video["videoTotalDurationMin"] = s["videoTotalDurationMin"]
    with open(mp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


def cmd_image(args):
    data = load_costs(args.project, args.episode)
    rec = {
        "type": "image",
        "target": args.target,
        "model": args.model,
        "at": now_iso(),
        "note": args.note or "",
    }
    if args.task_id:
        rec["taskId"] = args.task_id
    data["records"].append(rec)
    recompute_summary(data)
    save_costs(args.project, args.episode, data)
    update_manifest(args.project, args.episode, data)
    print(f"[ok] image logged: {args.target} via {args.model}  "
          f"(episode total images={data['summary']['imageGenCount']})")


def cmd_video(args):
    data = load_costs(args.project, args.episode)
    target = args.target
    is_regenerate = any(
        r.get("type") == "video" and r.get("target") == target
        for r in data.get("records", [])
    )
    rec = {
        "type": "video",
        "target": target,
        "model": str(args.model),
        "durationSec": int(args.duration),
        "isRegenerate": is_regenerate,
        "at": now_iso(),
        "note": args.note or "",
    }
    if args.task_id:
        rec["taskId"] = args.task_id
    data["records"].append(rec)
    recompute_summary(data)
    save_costs(args.project, args.episode, data)
    update_manifest(args.project, args.episode, data)
    s = data["summary"]
    tag = "重生" if is_regenerate else "新生"
    print(f"[ok] video logged ({tag}): {target} via model={args.model} dur={args.duration}s  "
          f"(episode: calls={s['videoGenCount']}, uniqueShots={s['videoUniqueShots']}, "
          f"totalMin={s['videoTotalDurationMin']})")


def cmd_recompute(args):
    data = load_costs(args.project, args.episode)
    recompute_summary(data)
    save_costs(args.project, args.episode, data)
    update_manifest(args.project, args.episode, data)
    s = data["summary"]
    print(f"[ok] recomputed for {args.project}/{args.episode}")
    print(f"     images={s['imageGenCount']}  "
          f"videos={s['videoGenCount']} (unique={s['videoUniqueShots']})  "
          f"totalMin={s['videoTotalDurationMin']}")
    by_model = data.get("byModel", {})
    if by_model:
        print("     byModel:")
        for m, v in by_model.items():
            print(f"       - {m}: image={v['imageCount']} video={v['videoCount']} "
                  f"videoSec={v['videoDurationSec']}")


def main():
    p = argparse.ArgumentParser(description="Cost logger for image/video generation.")
    sub = p.add_subparsers(dest="cmd")
    sub.required = True  # py3.6 兼容写法
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project", required=True)
    common.add_argument("--episode", required=True)
    pi = sub.add_parser("image", parents=[common])
    pi.add_argument("--target", required=True)
    pi.add_argument("--model", required=True)
    pi.add_argument("--task-id", default="")
    pi.add_argument("--note", default="")
    pi.set_defaults(func=cmd_image)
    pv = sub.add_parser("video", parents=[common])
    pv.add_argument("--target", required=True)
    pv.add_argument("--model", required=True)
    pv.add_argument("--duration", type=int, required=True)
    pv.add_argument("--task-id", default="")
    pv.add_argument("--note", default="")
    pv.set_defaults(func=cmd_video)
    pr = sub.add_parser("recompute", parents=[common])
    pr.set_defaults(func=cmd_recompute)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
