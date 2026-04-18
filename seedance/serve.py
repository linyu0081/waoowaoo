#!/usr/bin/env python3
"""无缓存 HTTP 静态文件服务器 — 用于 Seedance Studio 开发环境"""
import sys
import os
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
try:
    from urllib.parse import urlparse, parse_qs, urlencode, unquote
except ImportError:
    from urlparse import urlparse, parse_qs
    from urllib import urlencode, unquote

class NoCacheHandler(SimpleHTTPRequestHandler):
    """所有响应都带 Cache-Control: no-store，彻底禁止浏览器缓存。
    对 viewer.html 请求如果没有 _t 参数，自动 302 重定向到带时间戳的版本。
    支持 PUT 请求上传/替换文件。"""

    def do_PUT(self):
        """处理文件上传/替换请求"""
        parsed = urlparse(self.path)
        clean_path = unquote(parsed.path.lstrip('/'))
        # 安全检查：只允许上传到 projects/ 目录下的 images 文件夹
        if '..' in clean_path or not clean_path.startswith('projects/'):
            self.send_response(403)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"error":"Forbidden path"}')
            return
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length <= 0 or content_length > 50 * 1024 * 1024:  # 最大 50MB
            self.send_response(413)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"error":"File too large or empty"}')
            return
        body = self.rfile.read(content_length)
        file_path = os.path.join(os.getcwd(), clean_path)
        dir_path = os.path.dirname(file_path)
        try:
            if not os.path.isdir(dir_path):
                os.makedirs(dir_path, exist_ok=True)
            with open(file_path, 'wb') as f:
                f.write(body)
        except PermissionError:
            self.send_response(403)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(('{"error":"Permission denied: %s"}' % clean_path).encode())
            return
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(('{"error":"%s"}' % str(e).replace('"', '\\"')).encode())
            return
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(('{"ok":true,"path":"%s","size":%d}' % (clean_path, len(body))).encode())

    def do_OPTIONS(self):
        """处理 CORS 预检请求"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, PUT, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        # 如果访问 viewer.html 但没有 _t 参数，自动重定向
        if parsed.path in ('/viewer.html', '/viewer.html/'):
            qs = parse_qs(parsed.query)
            if '_t' not in qs:
                new_url = '/viewer.html?_t={}'.format(int(time.time() * 1000))
                self.send_response(302)
                self.send_header('Location', new_url)
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                return
        # 如果访问根路径，也重定向到 viewer.html
        if parsed.path in ('/', '/index.html'):
            new_url = '/viewer.html?_t={}'.format(int(time.time() * 1000))
            self.send_response(302)
            self.send_header('Location', new_url)
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            return
        return SimpleHTTPRequestHandler.do_GET(self)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        SimpleHTTPRequestHandler.end_headers(self)

    def translate_path(self, path):
        """去掉 URL 中的查询参数，避免 SimpleHTTPRequestHandler 找不到文件"""
        parsed = urlparse(path)
        # 用不带查询参数的路径去查找文件
        clean_path = parsed.path
        # 调用父类方法
        self.path_backup = self.path
        self.path = clean_path
        result = SimpleHTTPRequestHandler.translate_path(self, clean_path)
        self.path = self.path_backup
        return result

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8899
    os.chdir(os.path.dirname(os.path.abspath(__file__)) or '.')
    server = HTTPServer(('0.0.0.0', port), NoCacheHandler)
    print('Seedance Studio dev server: http://localhost:{}/viewer.html'.format(port))
    print('  Cache-Control: no-store on ALL responses')
    print('  Auto-redirect viewer.html with cache-busting timestamp')
    print('  Press Ctrl+C to stop')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nServer stopped')
