# -*- coding: utf-8 -*-
"""网页版（web/）本地服务 + 存档自动导入（guanxing4.0 新网页，纯静态）。

web/ 里是 guanxing4.0 的网页整站。这版站点**不需要任何服务端接口**：
存档导入只认 `.yanyu`（YANYUPL1 本地加密容器）和明文 JSON，全程离线。

自动导入走站点自带的「last-import 通道」—— home.js 的 initializeHome()
本来就在读 `window.__latestYanyuB64` / `window.__latestPlainSave`；
APK / PC 导出工具的做法是**在 last-import.js 前面拼一行赋值**，
我们用「虚拟路由」原样复刻：请求 /last-import.js 时动态返回
"赋值语句 + 原版 last-import.js"，网页源码一字不动。

向导导入完存档会自动：

    1. 拉起本服务（后台独立进程，不需要命令行窗口）；
    2. 把存档转成 .yanyu（统一格式）并交给 last-import 通道；
    3. 打开浏览器 —— 进去就是「已导入」状态。

服务默认 http://127.0.0.1:8080 （被占自动顺延到 8085），
后台常驻、下次直接复用；不用了跑 `python run.py serve --stop`。

用法::

    python run.py serve             # 起服务并打开浏览器
    python run.py serve --stop      # 停掉工具启动的后台服务
    python run.py serve --no-browser
"""
import argparse
import base64
import json
import os
import socket
import socketserver
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
import zlib
import http.server

from . import ui
from .config import paths

DEFAULT_PORT = 8080          # 与 web/serve.js 一致；被占时自动顺延 8081..8085
PORT_RANGE = 6
# 判断"占着端口的是不是这个站"
PING_PATH = '/'
PING_MARK = 'last-import.js'
# 自动导入走虚拟路由（不往 web/ 里写文件；冻结打包后 web/ 也不可写）
LAST_IMPORT_NAME = 'last-import.js'
LAST_IMPORT_FILE = 'last_import.js'
PID_FILE = 'webserver.pid'

# 与 web/shared/save_decrypt.js 里的键名保持一致（dev/check_site_import.py 会逐字比对）
SAVE_SHARE_KEY = 'yyjh_share_save_v1'
SAVE_SHARE_META_KEY = 'yyjh_share_save_meta_v1'


def web_dir():
    """网页版根目录：exe 内打包的 web/，或开发目录下的 web/。"""
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, 'web')          # noqa: SLF001
    return os.path.join(paths.TOOL_DIR, 'web')


# ───────────────────────── 静态服务（Python 版 serve.js） ─────────────────────────
class Handler(http.server.SimpleHTTPRequestHandler):
    """静态文件 + /last-import.js 自动导入虚拟路由。"""

    def end_headers(self):
        # 不缓存：改完源码刷新即生效
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        super().end_headers()

    def guess_type(self, path):
        lower = str(path).lower()
        if lower.endswith('.wasm'):
            return 'application/wasm'
        if lower.endswith('.mjs') or lower.endswith('.js'):
            return 'application/javascript; charset=utf-8'
        if lower.endswith('.json'):
            return 'application/json; charset=utf-8'
        return super().guess_type(path)

    def do_GET(self):                                     # noqa: N802
        path = self.path.split('?')[0]
        if path == '/' + LAST_IMPORT_NAME:
            # 优先给「自动导入版」（缓存里由 write_last_import 生成）；
            # 没有就回落原版 —— 等于没有自动导入，页面照常可用。
            for p in (os.path.join(paths.CACHE_DIR, LAST_IMPORT_FILE),
                      os.path.join(web_dir(), LAST_IMPORT_NAME)):
                try:
                    with open(p, 'rb') as f:
                        body = f.read()
                    break
                except OSError:
                    body = None
            if body is None:
                self.send_error(404, 'last-import.js not found')
                return
            self.send_response(200)
            self.send_header('Content-Type', 'application/javascript; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, fmt, *args):
        if os.environ.get('YYJH_SERVE_VERBOSE'):
            super().log_message(fmt, *args)


def make_httpd(port=DEFAULT_PORT):
    """构建 HTTP 服务（端口被占自动顺延）。返回 (httpd, 实际端口)。"""
    handler = lambda *a, **kw: Handler(*a, directory=web_dir(), **kw)  # noqa: E731
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    for p in range(port, min(port + PORT_RANGE, 65536)):
        try:
            httpd = socketserver.ThreadingTCPServer(('127.0.0.1', p), handler)
            return httpd, p
        except OSError:                                   # 端口被占，顺延
            continue
    raise ui.UserError(f'端口 {port}-{port + PORT_RANGE - 1} 全部被占用',
                       ['关掉占用端口的程序后重试'])


def serve_forever(port=DEFAULT_PORT, open_browser=False):
    """前台跑服务（`yyjh serve` / 内部子进程都走这里）。"""
    httpd, p = make_httpd(port)
    httpd.daemon_threads = True
    url = f'http://127.0.0.1:{p}/'
    ui.info(f'网页版服务已启动：{url}（停止：python run.py serve --stop）')
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        ui.info('\n已停止服务。')
    return 0


# ───────────────────────── 服务启停 ─────────────────────────
def ping(port):
    """端口上跑的是不是这个站。"""
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}{PING_PATH}',
                                    timeout=0.6) as r:
            return PING_MARK in r.read().decode('utf-8', 'replace')
    except Exception:                                    # noqa: BLE001
        return False


def _live_ports():
    return [p for p in range(DEFAULT_PORT, DEFAULT_PORT + PORT_RANGE) if ping(p)]


def _pid_path():
    return os.path.join(paths.CACHE_DIR, PID_FILE)


def stop_server():
    """停掉**由工具启动**的后台服务。返回 True = 停掉了。"""
    pid_file = _pid_path()
    if not os.path.exists(pid_file):
        return False
    try:
        with open(pid_file, encoding='utf-8') as f:
            pid = int(f.read().strip())
    except Exception:                                    # noqa: BLE001
        pid = None
    try:
        os.remove(pid_file)
    except OSError:
        pass
    if not pid:
        return False
    try:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(pid), '/F'],
                           capture_output=True, timeout=10)
        else:
            os.kill(pid, 15)
        return True
    except Exception:                                    # noqa: BLE001
        return False


def _spawn_server(port):
    """后台独立进程起服务：冻结（exe）= 自己带 serve 子命令；开发 = python -m yyjh。"""
    if getattr(sys, 'frozen', False):
        cmd = [sys.executable, 'serve', '--no-browser', '--port', str(port)]
    else:
        cmd = [sys.executable, '-m', 'yyjh', 'serve', '--no-browser',
               '--port', str(port)]
    kwargs = dict(cwd=os.path.dirname(web_dir()) if getattr(sys, 'frozen', False)
                  else paths.TOOL_DIR,
                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                  stderr=subprocess.DEVNULL)
    if os.name == 'nt':
        # 独立后台进程：不弹黑窗口，也不跟着向导一起退出
        kwargs['creationflags'] = (getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
                                   | getattr(subprocess, 'DETACHED_PROCESS', 0))
        kwargs['close_fds'] = True
    else:
        kwargs['start_new_session'] = True
    proc = subprocess.Popen(cmd, **kwargs)
    paths.ensure_dir(paths.CACHE_DIR)
    with open(_pid_path(), 'w', encoding='utf-8') as f:
        f.write(str(proc.pid))


def ensure_server():
    """确保服务在跑，返回 `http://127.0.0.1:<port>/`。

    已经在跑就复用；没在跑就拉起一个**后台独立进程**
    （关掉向导/命令行窗口都不影响）。
    """
    live = _live_ports()
    if live:
        return f'http://127.0.0.1:{live[0]}/'
    if not os.path.isfile(os.path.join(web_dir(), 'index.html')):
        raise ui.UserError('找不到网页版文件（web/index.html）',
                           ['web/ 目录丢了？重新解压工具包'])

    port = DEFAULT_PORT
    for p in range(DEFAULT_PORT, DEFAULT_PORT + PORT_RANGE):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(('127.0.0.1', p))
                port = p
                break
            except OSError:
                continue
    _spawn_server(port)

    for _ in range(80):            # 最多等 8 秒（服务自己还会顺延端口）
        live = _live_ports()
        if live:
            return f'http://127.0.0.1:{live[0]}/'
        time.sleep(0.1)
    raise ui.UserError('网页版服务启动失败', [
        f'手动启动试一下：python run.py serve --port {port}',
    ])


# ───────────────────────── 存档自动导入 ─────────────────────────
def pack_save(data):
    """压成站点 loadShareStore() 认得的形式：base64(zlib(JSON))（备用通道）。"""
    raw = json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return base64.b64encode(zlib.compress(raw, 9)).decode('ascii')


def write_last_import(row):
    """生成「自动导入版」last-import.js（缓存目录，经 /last-import.js 虚拟路由提供）。

    与 APK / PC 导出工具的做法一致：在原版 last-import.js **前面**拼一行赋值，
    home.js 的 initializeHome() 读到就把存档接进来。web/ 里既有文件一字不动。

    首选 `window.__latestYanyuB64`（.yanyu 统一格式）；
    打不了包（缺 cryptography 等）就退 `window.__latestPlainSave`（明文）。
    """
    from . import report
    from .game import yanyu
    json_path = row.get('json')
    if not json_path or not os.path.exists(json_path):
        return None
    with open(json_path, encoding='utf-8') as f:
        data = json.load(f)
    try:
        src_path = os.path.join(web_dir(), LAST_IMPORT_NAME)
        with open(src_path, encoding='utf-8') as f:
            shim = f.read()
    except OSError:
        shim = ''

    old = row.get('meta') or {}
    name = os.path.basename(row.get('yanyu') or 'dat.yanyu')
    try:
        b64 = base64.b64encode(yanyu.pack(data)).decode('ascii')
        head = (f'window.__latestYanyuB64={json.dumps(b64)};'
                f'window.__latestYanyuName={json.dumps(name)};\n')
    except Exception as e:                                # noqa: BLE001
        ui.debug(f'打 .yanyu 失败，退明文通道：{e}')
        payload = {'data': data, 'platform': report.platform_tag(
            old.get('runtime') or ''), 'version': '明文'}
        head = f'window.__latestPlainSave={json.dumps(payload, ensure_ascii=False)};\n'

    out = os.path.join(paths.CACHE_DIR, LAST_IMPORT_FILE)
    paths.ensure_dir(paths.CACHE_DIR)
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
        f.write(head + shim)
    return out


def open_site(snapshot=None):
    """起服务（如需）→ 自动导入存档（如给了）→ 打开浏览器。"""
    base = ensure_server()
    target = base
    if snapshot:
        try:
            if write_last_import(snapshot):
                target = base + LAST_IMPORT_NAME
            else:
                ui.debug('这条记录没有明文 JSON，开普通入口页（手动导入）')
        except Exception as e:                           # noqa: BLE001
            ui.warn(f'生成自动导入脚本失败，改开普通入口页：{e}')
    ok = False
    try:
        ok = bool(webbrowser.open(target))
    except Exception as e:                               # pragma: no cover
        ui.debug(f'webbrowser.open 失败: {e}')
    if ok:
        ui.ok('已用默认浏览器打开网页版模拟器')
        if target != base:
            ui.info('  存档已自动载入，进去就能直接用。')
        else:
            ui.info('  在网页里点「导入数据」，选存档目录里的 dat.yanyu。')
    else:
        ui.warn('没能自动打开浏览器，请手动打开：')
        ui.info(f'  {target}')
    return ok


# ───────────────────────── 子命令 ─────────────────────────
def add_parsers(sub):
    p = sub.add_parser('serve', help='网页版本地服务（向导会自动拉起）')
    p.add_argument('--port', type=int, default=DEFAULT_PORT,
                   help=f'监听端口（默认 {DEFAULT_PORT}）')
    p.add_argument('--no-browser', action='store_true', help='不自动打开浏览器')
    p.add_argument('--stop', action='store_true', help='停掉工具启动的后台服务后退出')
    p.set_defaults(func=cmd_serve)
    return p


def cmd_serve(args):
    if getattr(args, 'stop', False):
        if stop_server():
            ui.ok('后台服务已停止')
        else:
            ui.info('没有由工具启动的后台服务')
        return 0
    return serve_forever(port=getattr(args, 'port', DEFAULT_PORT),
                         open_browser=not getattr(args, 'no_browser', False))


def main(argv=None):
    """`python -m yyjh.webserve` 的入口（与 `yyjh serve` 等价）。"""
    ui.configure()
    ap = argparse.ArgumentParser(
        prog='python -m yyjh.webserve',
        description='网页版本地服务（向导会自动拉起，这里一般只用来手动启停）')
    ap.add_argument('--port', type=int, default=DEFAULT_PORT)
    ap.add_argument('--no-browser', action='store_true')
    ap.add_argument('--stop', action='store_true')
    args = ap.parse_args(sys.argv[1:] if argv is None else list(argv))
    return cmd_serve(args)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except ui.UserError as e:
        ui.report_error(e, ui.is_verbose())
        sys.exit(2)
