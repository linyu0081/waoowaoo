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
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import unquote


ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECTS_DIR = os.path.join(ROOT, 'projects')


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
    # -------- 通用响应头 --------
    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()

    def log_message(self, format, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), format % args))

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
                return self._send_json(200, {'ok': True, 'dedup': True, 'waitList': q['waitList']})
        entry = {
            'shot': shot,
            'model': p.get('model') or '',
            'ratio': p.get('ratio') or '',
            'note': p.get('note') or '',
            'addedAt': self._now_iso(),
        }
        q.setdefault('waitList', []).append(entry)
        self._save_queue(abs_path, q)
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
        q['waitList'] = new_wl
        self._save_queue(abs_path, q)
        return self._send_json(200, {'ok': True, 'removed': len(wl) - len(new_wl), 'waitList': new_wl})

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
        for k in ('maxInflight','paused','defaultModel','defaultRatio','waitList'):
            if k in patch: q[k] = patch[k]
        self._save_queue(abs_path, q)
        return self._send_json(200, {'ok': True, 'queue': q})

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
