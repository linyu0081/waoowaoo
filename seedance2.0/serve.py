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


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    os.chdir(ROOT)
    httpd = HTTPServer(('0.0.0.0', port), NoCacheHandler)
    print(f"[seedance2.0] Serving {ROOT} on http://0.0.0.0:{port}")
    print(f"[seedance2.0] Dashboard: http://localhost:{port}/dashboard.html")
    print(f"[seedance2.0] API: POST /api/save-json  POST /api/upload  PUT /projects/...")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[seedance2.0] Server stopped.")


if __name__ == '__main__':
    main()
