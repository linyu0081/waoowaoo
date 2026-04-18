#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Seedance2.0 Dashboard 本地开发服务器（无缓存）
用法：
    python3 serve.py            # 默认端口 8765
    python3 serve.py 8080       # 自定义端口
所有响应都带 no-store 头，避免浏览器/VSCode 端口转发层缓存。
"""
import os
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler


class NoCacheHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()

    def log_message(self, format, *args):
        # 简化日志，避免 HEAD 404 刷屏
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), format % args))


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    root = os.path.dirname(os.path.abspath(__file__))
    os.chdir(root)
    httpd = HTTPServer(('0.0.0.0', port), NoCacheHandler)
    print(f"[seedance2.0] Serving {root} on http://0.0.0.0:{port}")
    print(f"[seedance2.0] Dashboard: http://localhost:{port}/dashboard.html")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[seedance2.0] Server stopped.")


if __name__ == '__main__':
    main()
