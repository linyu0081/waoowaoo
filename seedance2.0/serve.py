#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Seedance2.0 Dashboard 本地开发服务器（无缓存 + 轻量编辑 API）
用法：
    python3 serve.py            # 默认端口 8765
    python3 serve.py 8080       # 自定义端口
端点：
    GET  /*                     → 静态文件（no-cache）
    POST /api/save-json         → body: { path, content(JSON) } 覆写 assets 或 outputs 下的 json
    POST /api/upload            → multipart/form-data 上传图片到指定路径（字段 path + file）
所有路径参数必须位于 seedance2.0/projects/ 子树内，越界拒绝。
"""
import os
import sys
import json
import shutil
import cgi
import re
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import unquote


ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECTS_DIR = os.path.join(ROOT, 'projects')

# 视频时长上限（与 scripts/video_submit.py 保持一致）
# - raw ≤ 15s：直接入池
# - 15 < raw ≤ 18s：允许入池，提交时 clamp 为 15s
# - raw > 18s：拒绝入池，并回写 needsRework
DURATION_MAX_SEC = 15
DURATION_CLAMP_SEC = 18


def _parse_title_duration(title_bar: str) -> int:
    m = re.search(r"(\d+)\s*秒", title_bar or "")
    return int(m.group(1)) if m else 15


def _safe_resolve(rel_path: str):
    """把前端传入的相对路径解析为绝对路径，拒绝越界到 projects/ 之外。"""
    rel_path = unquote(rel_path or '').lstrip('/')
    # 允许 projects/... 开头；其它一律拒
    if not rel_path.startswith('projects/'):
        return None
    abs_path = os.path.abspath(os.path.join(ROOT, rel_path))
    if not abs_path.startswith(PROJECTS_DIR + os.sep) and abs_path != PROJECTS_DIR:
        return None
    return abs_path


class NoCacheHandler(SimpleHTTPRequestHandler):
    # 媒体类扩展名：这类文件需要支持 HTTP Range（拖进度条），且允许短缓存（避免 seek 重下）
    MEDIA_EXTS = ('.mp4', '.webm', '.mov', '.m4v', '.mp3', '.wav', '.m4a', '.ogg')

    # -------- 通用响应头 --------
    def end_headers(self):
        # 对媒体文件跳过 no-cache，避免浏览器每次 seek 都重新全量拉取
        path_lower = (getattr(self, 'path', '') or '').lower().split('?', 1)[0]
        is_media = any(path_lower.endswith(ext) for ext in self.MEDIA_EXTS)
        if not is_media:
            self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Expires', '0')
        super().end_headers()

    def log_message(self, format, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), format % args))

    # -------- GET 路由：拦截媒体文件请求，支持 HTTP Range（拖进度条） --------
    def do_GET(self):
        # 只有媒体类文件走自定义分段响应，其它一切走默认实现
        path_only = unquote(self.path.split('?', 1)[0])
        ext = os.path.splitext(path_only)[1].lower()
        if ext in self.MEDIA_EXTS:
            try:
                return self._serve_media_with_range(path_only, ext)
            except Exception as e:
                sys.stderr.write(f"[serve.py] media range failed for {path_only}: {e}\n")
                # 失败回落到默认实现
        return super().do_GET()

    def _guess_media_ctype(self, ext: str) -> str:
        return {
            '.mp4':  'video/mp4',
            '.m4v':  'video/mp4',
            '.mov':  'video/quicktime',
            '.webm': 'video/webm',
            '.mp3':  'audio/mpeg',
            '.wav':  'audio/wav',
            '.m4a':  'audio/mp4',
            '.ogg':  'audio/ogg',
        }.get(ext, 'application/octet-stream')

    def _serve_media_with_range(self, url_path: str, ext: str):
        """对媒体文件支持 Range 请求：若带 Range 头返回 206 Partial Content，否则 200 全量。"""
        # 解析到绝对路径：复用 SimpleHTTPRequestHandler 的 translate_path
        fs_path = self.translate_path(url_path)
        if not os.path.isfile(fs_path):
            self.send_error(404, 'File not found')
            return
        file_size = os.path.getsize(fs_path)
        ctype = self._guess_media_ctype(ext)
        range_header = self.headers.get('Range') or self.headers.get('range')

        if not range_header:
            # 无 Range：仍然返回 200，但带 Accept-Ranges，方便后续 seek
            self.send_response(200)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(file_size))
            self.send_header('Accept-Ranges', 'bytes')
            # 媒体允许短缓存（60s），交给 end_headers 里跳过 no-cache 分支
            self.send_header('Cache-Control', 'public, max-age=60')
            self.end_headers()
            if self.command == 'HEAD':
                return
            with open(fs_path, 'rb') as f:
                shutil.copyfileobj(f, self.wfile, length=64 * 1024)
            return

        # 解析 Range: bytes=start-end
        start, end = 0, file_size - 1
        try:
            units, _, rng = range_header.partition('=')
            if units.strip().lower() != 'bytes':
                raise ValueError('only bytes unit supported')
            # 暂不支持多段（逗号分隔），浏览器视频 seek 也只用单段
            first_range = rng.split(',', 1)[0].strip()
            s_str, _, e_str = first_range.partition('-')
            if s_str == '':
                # suffix-byte-range-spec: "-N" → 取最后 N 字节
                n = int(e_str)
                if n <= 0:
                    raise ValueError('invalid suffix length')
                start = max(0, file_size - n)
                end = file_size - 1
            else:
                start = int(s_str)
                end = int(e_str) if e_str else (file_size - 1)
            if start > end or start >= file_size:
                self.send_response(416)
                self.send_header('Content-Range', f'bytes */{file_size}')
                self.end_headers()
                return
            end = min(end, file_size - 1)
        except Exception:
            self.send_response(416)
            self.send_header('Content-Range', f'bytes */{file_size}')
            self.end_headers()
            return

        length = end - start + 1
        self.send_response(206)
        self.send_header('Content-Type', ctype)
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Range', f'bytes {start}-{end}/{file_size}')
        self.send_header('Content-Length', str(length))
        self.send_header('Cache-Control', 'public, max-age=60')
        self.end_headers()

        if self.command == 'HEAD':
            return
        with open(fs_path, 'rb') as f:
            f.seek(start)
            remaining = length
            chunk_size = 64 * 1024
            while remaining > 0:
                buf = f.read(min(chunk_size, remaining))
                if not buf:
                    break
                try:
                    self.wfile.write(buf)
                except (BrokenPipeError, ConnectionResetError):
                    # 用户拖进度条/换分段时浏览器主动断开是常态，静默
                    return
                remaining -= len(buf)

    # -------- 工具：JSON 响应 --------
    def _send_json(self, code: int, obj: dict):
        data = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # -------- POST 路由 --------
    def do_POST(self):
        try:
            if self.path == '/api/save-json':
                return self._handle_save_json()
            if self.path == '/api/upload':
                return self._handle_upload()
            if self.path == '/api/video-queue/add':
                return self._handle_queue_add()
            if self.path == '/api/video-queue/remove':
                return self._handle_queue_remove()
            if self.path == '/api/video-queue/update':
                return self._handle_queue_update()
            if self.path == '/api/video-queue/trigger':
                return self._handle_queue_trigger()
            if self.path == '/api/video-queue/deps':
                return self._handle_queue_deps()
            if self.path == '/api/scheduler/config':
                return self._handle_scheduler_config()
            self._send_json(404, {'ok': False, 'error': 'unknown endpoint'})
        except Exception as e:
            self._send_json(500, {'ok': False, 'error': str(e)})

    # -------- PUT 路由：兼容 dashboard uploadImageFile 直接按 URL 路径写文件 --------
    def do_PUT(self):
        try:
            rel_path = unquote(self.path).lstrip('/')
            abs_path = _safe_resolve(rel_path)
            if abs_path is None:
                return self._send_json(403, {'ok': False, 'error': 'path not in projects/'})
            ext = os.path.splitext(abs_path)[1].lower()
            if ext not in ('.png', '.jpg', '.jpeg', '.webp', '.mp3', '.wav', '.m4a', '.ogg'):
                return self._send_json(400, {'ok': False, 'error': f'PUT only for images/audio, got {ext}'})
            length = int(self.headers.get('Content-Length') or 0)
            if length <= 0:
                return self._send_json(400, {'ok': False, 'error': 'empty body'})
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, 'wb') as out:
                remaining = length
                while remaining > 0:
                    chunk = self.rfile.read(min(65536, remaining))
                    if not chunk:
                        break
                    out.write(chunk)
                    remaining -= len(chunk)
            return self._send_json(200, {'ok': True, 'path': rel_path, 'size': os.path.getsize(abs_path)})
        except Exception as e:
            self._send_json(500, {'ok': False, 'error': str(e)})

    # -------- /api/save-json --------
    def _handle_save_json(self):
        length = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(length) if length > 0 else b''
        try:
            payload = json.loads(raw.decode('utf-8'))
        except Exception as e:
            return self._send_json(400, {'ok': False, 'error': f'invalid json body: {e}'})

        rel_path = payload.get('path')
        content = payload.get('content')
        if not rel_path or content is None:
            return self._send_json(400, {'ok': False, 'error': 'missing path or content'})
        if not rel_path.endswith('.json'):
            return self._send_json(400, {'ok': False, 'error': 'only .json files are writable'})

        abs_path = _safe_resolve(rel_path)
        if abs_path is None:
            return self._send_json(403, {'ok': False, 'error': 'path not in projects/'})
        if not os.path.exists(abs_path):
            return self._send_json(404, {'ok': False, 'error': 'file not found'})

        # 备份 → 原子替换
        backup = abs_path + '.bak'
        try:
            shutil.copy2(abs_path, backup)
            tmp = abs_path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(content, f, ensure_ascii=False, indent=2)
            os.replace(tmp, abs_path)
        except Exception as e:
            # 回滚
            if os.path.exists(backup):
                shutil.copy2(backup, abs_path)
            return self._send_json(500, {'ok': False, 'error': f'write failed: {e}'})

        return self._send_json(200, {'ok': True, 'path': rel_path})

    # -------- /api/upload --------
    def _handle_upload(self):
        ctype = self.headers.get('Content-Type', '')
        if 'multipart/form-data' not in ctype:
            return self._send_json(400, {'ok': False, 'error': 'must be multipart/form-data'})

        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={'REQUEST_METHOD': 'POST', 'CONTENT_TYPE': ctype}
        )
        rel_path = form.getvalue('path')
        file_field = form['file'] if 'file' in form else None
        if not rel_path or file_field is None or not getattr(file_field, 'file', None):
            return self._send_json(400, {'ok': False, 'error': 'missing path or file'})

        abs_path = _safe_resolve(rel_path)
        if abs_path is None:
            return self._send_json(403, {'ok': False, 'error': 'path not in projects/'})

        # 只允许写入图片 / 音频常见扩展名
        ext = os.path.splitext(abs_path)[1].lower()
        if ext not in ('.png', '.jpg', '.jpeg', '.webp', '.mp3', '.wav', '.m4a', '.ogg'):
            return self._send_json(400, {'ok': False, 'error': f'unsupported ext: {ext}'})

        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        try:
            with open(abs_path, 'wb') as out:
                shutil.copyfileobj(file_field.file, out)
        except Exception as e:
            return self._send_json(500, {'ok': False, 'error': f'write failed: {e}'})

        return self._send_json(200, {'ok': True, 'path': rel_path, 'bytes': os.path.getsize(abs_path)})

    # -------- /api/video-queue/* 共享工具 --------
    def _read_body_json(self):
        length = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(length) if length > 0 else b''
        return json.loads(raw.decode('utf-8') or '{}')

    def _queue_file(self, project, ep):
        rel = f'projects/{project}/outputs/{ep}/video-queue.json'
        abs_path = _safe_resolve(rel)
        return rel, abs_path

    def _load_queue(self, abs_path):
        if not os.path.exists(abs_path):
            return {
                'maxInflight': 1, 'paused': False,
                'defaultModel': 'seedance2.0fast', 'defaultRatio': '16:9',
                'waitList': [], 'history': [], 'lastHeartbeat': '',
            }
        with open(abs_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _save_queue(self, abs_path, q):
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        tmp = abs_path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(q, f, ensure_ascii=False, indent=2)
        os.replace(tmp, abs_path)

    def _now_iso(self):
        import datetime as _dt
        return _dt.datetime.now().astimezone().isoformat(timespec='seconds')

    def _audit_log_queue(self, project, ep, msg):
        """把 waitList 手工变更（add/remove/update）写入与 scheduler 共用的日志文件，
        便于事后对账"shot-XX 怎么没了"这种问题。非关键路径，静默失败。"""
        try:
            rel = f'projects/{project}/outputs/{ep}/video-scheduler.log'
            abs_path = _safe_resolve(rel)
            if abs_path is None:
                return
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            line = f"[{self._now_iso()}] [dashboard] {msg}\n"
            with open(abs_path, 'a', encoding='utf-8') as f:
                f.write(line)
        except Exception:
            pass

    # -------- /api/video-queue/add --------
    def _handle_queue_add(self):
        """payload: { project, ep, shot, model?, ratio?, note? }"""
        p = self._read_body_json()
        project = p.get('project'); ep = p.get('ep'); shot = p.get('shot')
        if not (project and ep and shot):
            return self._send_json(400, {'ok': False, 'error': 'missing project/ep/shot'})
        shot = str(shot).zfill(2)
        rel, abs_path = self._queue_file(project, ep)
        if abs_path is None:
            return self._send_json(403, {'ok': False, 'error': 'path out of projects/'})
        # 拒绝标记为 needsRework 的镜入池（除非请求里显式传 force=true）
        force = bool(p.get('force'))
        shot_json_rel = f'projects/{project}/outputs/{ep}/06-shots/shot-{shot}.json'
        shot_json_abs = _safe_resolve(shot_json_rel)
        # —— 时长闸门（入池前检查）：>18s 拒绝，[16,18] 放行但 clamp；<=15 直接通过 ——
        if shot_json_abs and os.path.exists(shot_json_abs):
            try:
                with open(shot_json_abs, 'r', encoding='utf-8') as f:
                    shot_data_pre = json.load(f)
                title_bar_pre = (shot_data_pre.get('titleBar') or '')
                raw_sec_pre = _parse_title_duration(title_bar_pre)
                if raw_sec_pre > DURATION_CLAMP_SEC and not force:
                    # 给分镜师打 needsRework 标记（回写 shot-NN.json.videoTask）
                    try:
                        vt_pre = shot_data_pre.get('videoTask') or {}
                        fail_reason_msg = (
                            f'时长超标：titleBar 估算 {raw_sec_pre}s > {DURATION_CLAMP_SEC}s 最大阈值，'
                            f'需分镜师拆分镜头使单镜 ≤ {DURATION_MAX_SEC}s 后重新入池'
                        )
                        vt_pre['needsRework'] = True
                        vt_pre['failReason'] = fail_reason_msg
                        fh = list(vt_pre.get('failHistory') or [])
                        fh.append({
                            'taskId': '',
                            'failReason': fail_reason_msg,
                            'submittedAt': self._now_iso(),
                            'failedAt': self._now_iso(),
                            'model': vt_pre.get('modelName') or '',
                            'kind': 'duration-gate-reject',
                            'rawSec': raw_sec_pre,
                        })
                        vt_pre['failHistory'] = fh
                        shot_data_pre['videoTask'] = vt_pre
                        with open(shot_json_abs, 'w', encoding='utf-8') as f:
                            json.dump(shot_data_pre, f, ensure_ascii=False, indent=2)
                    except Exception:
                        pass
                    self._audit_log_queue(project, ep, f"add shot-{shot} REJECTED (duration {raw_sec_pre}s > {DURATION_CLAMP_SEC}s, marked needsRework)")
                    return self._send_json(409, {
                        'ok': False,
                        'needsRework': True,
                        'durationRejected': True,
                        'rawSec': raw_sec_pre,
                        'maxSec': DURATION_MAX_SEC,
                        'clampSec': DURATION_CLAMP_SEC,
                        'error': fail_reason_msg,
                    })
            except Exception:
                pass
        if not force and shot_json_abs and os.path.exists(shot_json_abs):
            try:
                with open(shot_json_abs, 'r', encoding='utf-8') as f:
                    shot_data = json.load(f)
                vt = shot_data.get('videoTask') or {}
                if vt.get('needsRework'):
                    fh = vt.get('failHistory') or []
                    last_fail = fh[-1].get('failReason', '') if fh else vt.get('failReason', '')
                    return self._send_json(409, {
                        'ok': False,
                        'needsRework': True,
                        'error': f'shot-{shot} 被标记为需返工（上次失败：{last_fail}）。请让分镜师优化 prompt 后，清除 needsRework 或 force=true 重投。',
                        'failHistory': fh,
                    })
            except Exception:
                pass
        q = self._load_queue(abs_path)
        # 去重：同 shot 已在 waitList 则跳过
        for e in q.get('waitList', []):
            if str(e.get('shot','')).zfill(2) == shot:
                self._audit_log_queue(project, ep, f"add shot-{shot} → dedup (already in waitList, waitList={len(q['waitList'])})")
                return self._send_json(200, {'ok': True, 'dedup': True, 'waitList': q['waitList']})
        entry = {
            'shot': shot,
            'engine': p.get('engine') or '',
            'model': p.get('model') or '',
            'ratio': p.get('ratio') or '',
            'note': p.get('note') or '',
            'promptMode': p.get('promptMode') or '',
            'addedAt': self._now_iso(),
        }
        before = len(q.get('waitList', []) or [])
        q.setdefault('waitList', []).append(entry)
        self._save_queue(abs_path, q)
        note = entry.get('note') or ''
        self._audit_log_queue(project, ep, f"add shot-{shot} (model={entry['model'] or '-'}, promptMode={entry['promptMode'] or 'full'}, note={note or '-'}) waitList {before} → {len(q['waitList'])}")
        return self._send_json(200, {'ok': True, 'entry': entry, 'waitList': q['waitList']})

    # -------- /api/video-queue/remove --------
    def _handle_queue_remove(self):
        """payload: { project, ep, shot }"""
        p = self._read_body_json()
        project = p.get('project'); ep = p.get('ep'); shot = p.get('shot')
        if not (project and ep and shot):
            return self._send_json(400, {'ok': False, 'error': 'missing project/ep/shot'})
        shot = str(shot).zfill(2)
        rel, abs_path = self._queue_file(project, ep)
        if abs_path is None:
            return self._send_json(403, {'ok': False, 'error': 'path out of projects/'})
        q = self._load_queue(abs_path)
        wl = q.get('waitList', [])
        new_wl = [e for e in wl if str(e.get('shot','')).zfill(2) != shot]
        removed = len(wl) - len(new_wl)
        q['waitList'] = new_wl
        self._save_queue(abs_path, q)
        if removed > 0:
            self._audit_log_queue(project, ep, f"remove shot-{shot} (hit) waitList {len(wl)} → {len(new_wl)}")
        else:
            self._audit_log_queue(project, ep, f"remove shot-{shot} (not found, no-op) waitList={len(wl)}")
        return self._send_json(200, {'ok': True, 'removed': removed, 'waitList': new_wl})

    # -------- /api/video-queue/update --------
    def _handle_queue_update(self):
        """payload: { project, ep, patch: {maxInflight?, paused?, defaultModel?, defaultRatio?, waitList?} }
        waitList 传入则整体替换（用于拖拽排序）。"""
        p = self._read_body_json()
        project = p.get('project'); ep = p.get('ep'); patch = p.get('patch') or {}
        if not (project and ep):
            return self._send_json(400, {'ok': False, 'error': 'missing project/ep'})
        rel, abs_path = self._queue_file(project, ep)
        if abs_path is None:
            return self._send_json(403, {'ok': False, 'error': 'path out of projects/'})
        q = self._load_queue(abs_path)
        before_wl = [str(e.get('shot','')).zfill(2) for e in (q.get('waitList') or [])]
        # 入口校验：waitList 传入必须是 list，且每一项必须是 dict 且含 shot 字段
        # 防止半成品字符串（如 ['09','10']）写入后把 scheduler 心跳整体打崩
        if 'waitList' in patch:
            wl_in = patch.get('waitList')
            if not isinstance(wl_in, list):
                return self._send_json(400, {'ok': False, 'error': 'waitList must be a list'})
            bad = [(i, type(e).__name__, e) for i, e in enumerate(wl_in)
                   if not (isinstance(e, dict) and 'shot' in e)]
            if bad:
                return self._send_json(400, {
                    'ok': False,
                    'error': f'waitList contains malformed entries (must be dict with "shot"): {bad[:5]}'
                })
        changed_keys = []
        for k in ('maxInflight','paused','defaultModel','defaultRatio','waitList'):
            if k in patch:
                q[k] = patch[k]
                changed_keys.append(k)
        self._save_queue(abs_path, q)
        # 审计日志：若 waitList 有变更，详细记录顺序 diff（置顶、排序等）
        if 'waitList' in patch:
            after_wl = [str(e.get('shot','')).zfill(2) for e in (q.get('waitList') or [])]
            if before_wl != after_wl:
                # 识别首位变化（置顶最常见）
                head_before = before_wl[0] if before_wl else '-'
                head_after = after_wl[0] if after_wl else '-'
                extra = ''
                if head_before != head_after and head_after in before_wl:
                    extra = f' [top→shot-{head_after}]'
                self._audit_log_queue(project, ep, f"update waitList{extra} len {len(before_wl)} → {len(after_wl)}, order: {','.join(before_wl)} → {','.join(after_wl)}")
        other_keys = [k for k in changed_keys if k != 'waitList']
        if other_keys:
            kv = ', '.join(f'{k}={q[k]!r}' for k in other_keys)
            self._audit_log_queue(project, ep, f"update config: {kv}")
        return self._send_json(200, {'ok': True, 'queue': q})

    # -------- /api/video-queue/deps --------
    def _handle_queue_deps(self):
        """payload: { project, ep }
        即时计算当前 waitList 中每一镜的依赖就绪状态（不修改 queue 文件）。
        复用 video_scheduler.compute_waitlist_deps。用于 dashboard 在不触发心跳
        的前提下即时刷新 🔒/🟢 徽章（例如刚点完"置顶"想立刻看到效果）。
        返回：{ ok, depStatus: { "shot-XX": {ready, blocker, tailNum, fromShot, reason} } }
        """
        p = self._read_body_json()
        project = p.get('project'); ep = p.get('ep')
        if not (project and ep):
            return self._send_json(400, {'ok': False, 'error': 'missing project/ep'})
        rel, abs_path = self._queue_file(project, ep)
        if abs_path is None:
            return self._send_json(403, {'ok': False, 'error': 'path out of projects/'})
        q = self._load_queue(abs_path)
        try:
            # 延迟 import 避免 serve.py 启动时依赖 dreamina 等
            sys.path.insert(0, os.path.join(ROOT, 'scripts'))
            from video_scheduler import compute_waitlist_deps  # type: ignore
            deps = compute_waitlist_deps(project, ep, q.get('waitList') or [])
            return self._send_json(200, {'ok': True, 'depStatus': deps, 'skipLog': q.get('skipLog') or []})
        except Exception as e:
            return self._send_json(500, {'ok': False, 'error': f'compute deps failed: {e}'})

    # -------- /api/video-queue/trigger --------
    def _handle_queue_trigger(self):
        """payload: { project, ep } 立即触发一次调度器心跳（非阻塞）。"""
        p = self._read_body_json()
        project = p.get('project'); ep = p.get('ep')
        if not (project and ep):
            return self._send_json(400, {'ok': False, 'error': 'missing project/ep'})
        # 异步触发，避免请求长时间阻塞
        try:
            import subprocess as _sp
            script = os.path.join(ROOT, 'scripts', 'video_scheduler.py')
            _sp.Popen(
                ['python3', script, '--project', project, '--ep', ep],
                stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
                close_fds=True,
            )
            return self._send_json(200, {'ok': True, 'triggered': True})
        except Exception as e:
            return self._send_json(500, {'ok': False, 'error': str(e)})

    # -------- /api/scheduler/config --------
    def _handle_scheduler_config(self):
        """payload: { action: 'get'|'set', instance?: 'msckcs-ep01', intervalMin?: 5 }
        读/写 systemd user timer 的 OnUnitActiveSec。
        action=get: 读取当前配置
        action=set: 改写 timer 文件 → daemon-reload → restart timer
        """
        p = self._read_body_json()
        action = p.get('action') or 'get'
        instance = p.get('instance') or 'msckcs-ep01'
        # 安全校验：实例名不能含特殊字符
        import re as _re
        if not _re.match(r'^[A-Za-z0-9_\-]+$', instance):
            return self._send_json(400, {'ok': False, 'error': 'invalid instance name'})

        home = os.path.expanduser('~')
        timer_path = os.path.join(home, '.config/systemd/user/dreamina-scheduler@.timer')
        env_path = os.path.join(home, f'.config/dreamina-scheduler/{instance}.env')

        if not os.path.exists(timer_path):
            return self._send_json(404, {
                'ok': False, 'error': 'timer unit not installed',
                'hint': f'请先按 skill 文档安装 dreamina-scheduler@.timer 并建 env 文件 {env_path}',
            })

        # 读当前周期
        import re as _re2
        timer_text = open(timer_path, 'r', encoding='utf-8').read()
        m = _re2.search(r'OnUnitActiveSec\s*=\s*(\S+)', timer_text)
        cur_val = m.group(1) if m else '5min'

        def _parse_min(v):
            vv = str(v).strip().lower()
            if vv.endswith('min'): return int(vv[:-3])
            if vv.endswith('m'):   return int(vv[:-1])
            if vv.endswith('s'):   return max(1, int(int(vv[:-1]) / 60))
            return int(vv)

        cur_min = _parse_min(cur_val)

        # 查状态（best effort）
        import subprocess as _sp
        def _sh(cmd):
            try:
                r = _sp.run(cmd, capture_output=True, text=True, timeout=5)
                return r.stdout + r.stderr
            except Exception as e:
                return f'error: {e}'
        timer_unit = f'dreamina-scheduler@{instance}.timer'
        status_out = _sh(['systemctl', '--user', 'list-timers', timer_unit, '--no-pager'])
        # 用 show 查真实 ActiveState（list-timers 不含这个字段）
        show_out = _sh(['systemctl', '--user', 'show', timer_unit, '--no-pager',
                        '--property=ActiveState,SubState,NextElapseUSecRealtime'])
        active = 'ActiveState=active' in show_out
        next_trigger = ''
        # 解析 NEXT 列（非常粗）
        for line in status_out.splitlines():
            if 'dreamina-scheduler@' in line:
                parts = line.split()
                if len(parts) >= 2:
                    next_trigger = ' '.join(parts[:3])
                break

        if action == 'get':
            return self._send_json(200, {
                'ok': True,
                'instance': instance,
                'intervalMin': cur_min,
                'active': active,
                'nextTrigger': next_trigger,
                'envFile': env_path,
                'envExists': os.path.exists(env_path),
            })

        # action == 'set'
        try:
            new_min = int(p.get('intervalMin') or cur_min)
        except Exception:
            return self._send_json(400, {'ok': False, 'error': 'invalid intervalMin'})
        if new_min < 1 or new_min > 120:
            return self._send_json(400, {'ok': False, 'error': 'intervalMin out of range (1-120)'})

        # 改写 timer 文件
        new_val = f'{new_min}min'
        new_text = _re2.sub(r'OnUnitActiveSec\s*=\s*\S+', f'OnUnitActiveSec={new_val}', timer_text)
        # Description 里的注释也尝试更新（非强制）
        new_text = _re2.sub(r'every \d+\s*min', f'every {new_min} min', new_text)
        if new_text == timer_text:
            return self._send_json(500, {'ok': False, 'error': 'failed to patch timer file'})
        with open(timer_path, 'w', encoding='utf-8') as f:
            f.write(new_text)

        # daemon-reload + restart timer
        out1 = _sh(['systemctl', '--user', 'daemon-reload'])
        out2 = _sh(['systemctl', '--user', 'restart', timer_unit])

        # 再读一次状态
        status_out2 = _sh(['systemctl', '--user', 'list-timers', timer_unit, '--no-pager'])
        return self._send_json(200, {
            'ok': True,
            'instance': instance,
            'intervalMin': new_min,
            'reload': out1.strip()[:200],
            'restart': out2.strip()[:200] or 'ok',
            'timersOut': status_out2[:500],
        })


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    os.chdir(ROOT)
    httpd = HTTPServer(('0.0.0.0', port), NoCacheHandler)
    print(f"[seedance2.0] Serving {ROOT} on http://0.0.0.0:{port}")
    print(f"[seedance2.0] Dashboard: http://localhost:{port}/dashboard.html")
    print(f"[seedance2.0] API: POST /api/save-json  /api/upload  /api/video-queue/{{add,remove,update,trigger}}  /api/scheduler/config")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[seedance2.0] Server stopped.")


if __name__ == '__main__':
    main()
