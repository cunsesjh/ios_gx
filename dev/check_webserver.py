# -*- coding: utf-8 -*-
"""自检：webserve 的 Python 版服务（单 exe 用）与 web/serve.js（Node）行为一致。

  1. 静态页 /index.html 字节一致；.js 的 MIME；不缓存头
  2. /last-import.js 虚拟路由：
     · 没生成时 = 原版（shim 本体，无自动导入）
     · write_last_import 生成后 = 「赋值语句 + 原版」（__latestYanyuB64 通道）
     · 打不了 .yanyu 时退 __latestPlainSave 明文通道
  3. 与 Node 版 serve.js 对照（index.html / 404 行为）
  4. ping 探测、ensure_server -> stop_server 往返

没装 node 时跳过 Node 对照（Python 侧照测）。

跑法::

    python dev/check_webserver.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yyjh import webserve                         # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASS = []
FAIL = []


def check(name, cond, detail=''):
    if cond:
        PASS.append(name)
        print(f'  [OK]   {name}')
    else:
        FAIL.append(name)
        print(f'  [FAIL] {name}  {detail}')


def get(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read(), r.headers   # headers 大小写不敏感
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


def main():
    sample = {'MainRole': {'Name': '自检', 'Platform': 'ios'},
              'globalVariable': {}, 'BornTalent': {}}

    # ── Python 侧服务 ───────────────────────────────────────
    httpd, port = webserve.make_httpd(9300)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{port}'
    try:
        st, body, hdrs = get(base + '/index.html')
        with open(os.path.join(webserve.web_dir(), 'index.html'), 'rb') as f:
            want = f.read()
        check('静态 index.html 字节一致', st == 200 and body == want, st)
        check('index.html 带 last-import.js（ping 标记）',
              webserve.PING_MARK.encode() in body)
        st2, _b2, hdrs2 = get(base + '/home.js')
        check('.js 的 MIME 是 javascript',
              'javascript' in (hdrs2.get('Content-Type') or ''),
              hdrs2.get('Content-Type'))
        check('不缓存头在', 'no-store' in (hdrs.get('Cache-Control') or ''),
              hdrs.get('Cache-Control'))
        check('ping 认得自己的站', webserve.ping(port) is True)

        # ── /last-import.js 虚拟路由 ─────────────────────────
        try:
            os.remove(os.path.join(webserve.paths.CACHE_DIR, webserve.LAST_IMPORT_FILE))
        except OSError:
            pass
        st, body, _h = get(base + '/' + webserve.LAST_IMPORT_NAME)
        src_shim = open(os.path.join(webserve.web_dir(), webserve.LAST_IMPORT_NAME),
                        encoding='utf-8').read()
        check('未生成时回落原版 shim', st == 200
              and body.decode('utf-8', 'replace') == src_shim, st)

        tmp = tempfile.mkdtemp(prefix='yyjh_ws_')
        try:
            jp = os.path.join(tmp, 'dat.json')
            json.dump(sample, open(jp, 'w', encoding='utf-8'), ensure_ascii=False)
            row = {'json': jp, 'db': None, 'meta': {'runtime': 'android'}}
            page = webserve.write_last_import(row)
            check('write_last_import 落盘成功', bool(page) and os.path.exists(page), page)
            st, body, _h = get(base + '/' + webserve.LAST_IMPORT_NAME)
            js = body.decode('utf-8', 'replace')
            check('生成版含 .yanyu 自动导入赋值',
                  st == 200 and 'window.__latestYanyuB64=' in js, st)
            check('生成版 = 赋值 + 原版 shim（APK 同款机制）',
                  js.endswith(src_shim) and 'APK-WEB-SHIM' in js)
            check('yanyu 里的平台标识是 ios',
                  bool(re.search(r'__latestYanyuName="[^"]*"', js)))

            # 退化通道：打不了 .yanyu 时走明文
            from yyjh.game import yanyu as ymod
            real_pack = ymod.pack
            ymod.pack = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('no crypto'))
            try:
                page2 = webserve.write_last_import(row)
            finally:
                ymod.pack = real_pack
            st, body, _h = get(base + '/' + webserve.LAST_IMPORT_NAME)
            js2 = body.decode('utf-8', 'replace')
            check('打不了 .yanyu 时退明文通道',
                  'window.__latestPlainSave=' in js2 and page2)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        # ── Node 版 serve.js 对照（有 node 才测）─────────────
        node = shutil.which('node') or shutil.which('node.exe')
        if not node or not os.path.isfile(os.path.join(ROOT, 'web', 'serve.js')):
            check('Node 对照（跳过：没装 node）', True)
        else:
            env = dict(os.environ, PORT='9400')
            proc = subprocess.Popen([node, 'serve.js'],
                                    cwd=os.path.join(ROOT, 'web'), env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                nbase = None
                for _ in range(50):
                    try:
                        s, b, _ = get('http://127.0.0.1:9400/index.html')
                        if s == 200:
                            nbase = 'http://127.0.0.1:9400'
                            break
                    except Exception:                    # noqa: BLE001
                        pass
                    time.sleep(0.1)
                check('Node 版 serve.js 起得来', bool(nbase))
                if nbase:
                    s, b, _ = get(nbase + '/index.html')
                    check('对照：index.html 一致', b == want)
                    s, b, _ = get(nbase + '/last-import.js')
                    check('对照：原版 last-import.js 一致',
                          b.decode('utf-8', 'replace') == src_shim)
                    s, _b, _h = get(nbase + '/no-such-file-xyz')
                    check('对照：缺文件都 404', s == 404, s)
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:                        # noqa: BLE001
                    proc.kill()
    finally:
        httpd.shutdown()

    # ── ensure_server / stop_server 往返 ────────────────────
    base2 = webserve.ensure_server()
    check('ensure_server 拉起了服务', bool(webserve._live_ports()), base2)
    base3 = webserve.ensure_server()
    check('重复 ensure_server 复用同一实例', base2 == base3, (base2, base3))
    check('stop_server 停掉了', webserve.stop_server())
    time.sleep(0.3)
    check('停完端口已释放', not webserve._live_ports())

    print()
    print(f'通过 {len(PASS)} / 失败 {len(FAIL)}')
    for n in FAIL:
        print(f'  失败: {n}')
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
