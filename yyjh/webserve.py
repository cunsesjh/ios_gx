# -*- coding: utf-8 -*-
"""网页版（web/）本地服务 + 存档自动导入（新站离线部署版）。

web/ 里是 https://yanyu-util.pages.dev/ 的完整本地部署（含 server.js）：
站点的算法引擎要先向 `/api/runtime-key` 拿解密密钥，所以**必须**经
server.js 跑，不能纯静态直开。以前要手动双击《点击这个启动.bat》，
现在向导导入完存档会自动：

    1. 拉起 server.js（后台独立进程，不需要命令行窗口）；
    2. 把存档写进站点的共享存储（yyjh_share_save_v1 / _meta_v1）；
    3. 打开浏览器 —— 进去就是「已导入」状态。

服务默认 http://127.0.0.1:8080 （被占自动顺延到 8085），
后台常驻、下次直接复用；不用了跑 `python -m yyjh.webserve --stop`。

用法（一般不用手动跑）::

    python -m yyjh.webserve            # 起服务并打开浏览器
    python -m yyjh.webserve --stop     # 停掉工具启动的后台服务
"""
import argparse
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
import zlib

from . import ui
from .config import paths

DEFAULT_PORT = 8080          # 与 server.js 一致；被占时它自动顺延 8081..8085
PORT_RANGE = 6
# 判断"占着端口的是不是这个站"：server.js 的内置应答
PING_PATH = '/api/runtime-key'
PING_MARK = '"valid":true'
# 自动载入入口页：生成在 web/ 下，web/ 里既有文件一字不动（已 gitignore）
AUTOLOAD_NAME = '_autoload_last.html'
PID_FILE = 'webserver.pid'

# 与 web/shared/save_decrypt.js 里的键名保持一致
SAVE_SHARE_KEY = 'yyjh_share_save_v1'
SAVE_SHARE_META_KEY = 'yyjh_share_save_meta_v1'


def web_dir():
    """网页版根目录（tool_1.1/web，站点整站都在里面）。"""
    return os.path.join(paths.TOOL_DIR, 'web')


def node_bin():
    """Node 解释器：优先 web/bin/node.exe（自带），否则用系统 node。"""
    bundled = os.path.join(web_dir(), 'bin', 'node.exe')
    if os.name == 'nt' and os.path.isfile(bundled):
        return bundled
    for name in ('node', 'node.exe'):
        p = shutil.which(name)
        if p:
            return p
    return None


# ───────────────────────── 服务启停 ─────────────────────────
def ping(port):
    """端口上跑的是不是这个站（server.js 的 /api/runtime-key 应答）。"""
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


def ensure_server():
    """确保服务在跑，返回 `http://127.0.0.1:<port>/`。

    已经在跑就复用（不管是工具拉起的还是手动《启动.bat》开的）；
    没在跑就拉起一个**后台独立进程**（关掉向导/命令行窗口都不影响）。
    """
    live = _live_ports()
    if live:
        return f'http://127.0.0.1:{live[0]}/'

    node = node_bin()
    if not node:
        raise ui.UserError('找不到 Node 运行环境（网页版要靠它跑 server.js）', [
            '把 node.exe 放到 web\\bin\\ 下（ios_gx 仓库里自带），或安装 Node.js',
        ])
    if not os.path.isfile(os.path.join(web_dir(), 'server.js')):
        raise ui.UserError('找不到 web/server.js（站点部署不完整）',
                           ['重新解压工具包 / 同步 ios_gx 的网站资源'])

    env = dict(os.environ, YYJH_NO_BROWSER='1')      # 见 server.js 的补丁
    kwargs = dict(cwd=web_dir(), env=env, stdin=subprocess.DEVNULL,
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.name == 'nt':
        # 独立后台进程：不弹黑窗口，也不跟着向导一起退出
        kwargs['creationflags'] = (getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
                                   | getattr(subprocess, 'DETACHED_PROCESS', 0))
        kwargs['close_fds'] = True
    else:
        kwargs['start_new_session'] = True
    proc = subprocess.Popen([node, 'server.js', str(DEFAULT_PORT)], **kwargs)

    paths.ensure_dir(paths.CACHE_DIR)
    with open(_pid_path(), 'w', encoding='utf-8') as f:
        f.write(str(proc.pid))

    for _ in range(50):            # 最多等 5 秒（server.js 自己还会顺延端口）
        live = _live_ports()
        if live:
            return f'http://127.0.0.1:{live[0]}/'
        time.sleep(0.1)
    raise ui.UserError('网页版服务启动失败', [
        f'手动启动试一下：web\\点击这个启动.bat，或 node server.js {DEFAULT_PORT}',
    ])


# ───────────────────────── 存档自动导入 ─────────────────────────
def pack_save(data):
    """压成站点 loadShareStore() 认得的形式：base64(zlib(JSON))。

    web 端解压走 pako.inflate / DecompressionStream('deflate')，
    与 Python 的 zlib 是同一个容器格式（RFC1950 头 + adler32 尾），两边互通。
    （已用站点自己的 save_decrypt.js 实测互通）
    """
    raw = json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return base64.b64encode(zlib.compress(raw, 9)).decode('ascii')


def write_autoload(row):
    """生成「自动载入」入口页 web/_autoload_last.html，返回路径（不行返回 None）。

    把 web/index.html 原样复制一份，只在 </head> 前插一段脚本把存档写进
    localStorage —— 打开它就等于「已经导入过」。web/ 里既有文件一字不动。
    """
    from . import report
    src = os.path.join(web_dir(), 'index.html')
    json_path = row.get('json')
    if not os.path.exists(src) or not json_path or not os.path.exists(json_path):
        return None
    with open(json_path, encoding='utf-8') as f:
        data = json.load(f)
    with open(src, encoding='utf-8') as f:
        html = f.read()

    old = row.get('meta') or {}
    seed = {
        'version': str(old.get('version') or ''),
        'platform': report.platform_tag(
            old.get('runtime') or old.get('platform') or ''),
        'channel': str(old.get('channel') or ''),
        'format': 'json-local',
        'fileName': os.path.basename(json_path),
        'importedAt': int(time.time() * 1000),
    }
    script = ''.join([
        '<script>(function(){try{',
        'localStorage.setItem(', json.dumps(SAVE_SHARE_KEY), ',',
        json.dumps(pack_save(data)), ');',
        'localStorage.setItem(', json.dumps(SAVE_SHARE_META_KEY), ',',
        json.dumps(json.dumps(seed, ensure_ascii=False)), ');',
        '}catch(e){document.addEventListener("DOMContentLoaded",function(){',
        'var m=document.getElementById("homeImportMessage");',
        'if(m){m.textContent="自动载入存档失败："+((e&&e.message)||e);',
        'm.classList.add("is-error");}});}})();</script>',
    ])
    out = os.path.join(web_dir(), AUTOLOAD_NAME)
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
        f.write(html.replace('</head>', script + '\n</head>', 1))
    return out


def open_site(snapshot=None):
    """起服务（如需）→ 自动载入存档（如给了）→ 打开浏览器。"""
    base = ensure_server()
    target = base
    if snapshot:
        try:
            if write_autoload(snapshot):
                target = base + AUTOLOAD_NAME
            else:
                ui.debug('这条记录没有明文 JSON，开普通入口页（手动导入）')
        except Exception as e:                           # noqa: BLE001
            ui.warn(f'生成自动载入页失败，改开普通入口页：{e}')
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
            ui.info('  在网页里点「导入数据」，选存档目录里的明文 JSON。')
    else:
        ui.warn('没能自动打开浏览器，请手动打开：')
        ui.info(f'  {target}')
    return ok


# ───────────────────────── 子命令 ─────────────────────────
def main(argv=None):
    ui.configure()          # 单独跑 `python -m yyjh.webserve` 时也要有控制台输出
    ap = argparse.ArgumentParser(
        prog='python -m yyjh.webserve',
        description='网页版本地服务（向导会自动拉起，这里一般只用来手动启停）')
    ap.add_argument('--stop', action='store_true', help='停掉工具启动的后台服务后退出')
    ap.add_argument('--no-browser', action='store_true', help='不自动打开浏览器')
    args = ap.parse_args(sys.argv[1:] if argv is None else list(argv))

    if args.stop:
        if stop_server():
            ui.ok('后台服务已停止')
        else:
            ui.info('没有由工具启动的后台服务（《启动.bat》开的服务请关掉它的窗口）')
        return 0

    url = ensure_server()
    ui.info(f'网页版：{url}')
    if not args.no_browser:
        open_site()
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except ui.UserError as e:
        ui.report_error(e, ui.is_verbose())
        sys.exit(2)
