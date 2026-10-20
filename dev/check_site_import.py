# -*- coding: utf-8 -*-
"""自检：工具产出的存档能不能被新网页（guanxing4.0）直接导入。

用**网站自己的代码**验证，不猜：

  1. 用工具真实产出 dat.json（明文）与 dat.yanyu（统一格式）
  2. 丢给 node 跑真正的 web/shared/save_decrypt.js：
     · dat.yanyu -> decryptSaveBytes（自动导入 __latestYanyuB64 通道同款）
     · dat.json  -> readPlainJsonBytes（网页「导入数据」明文路径）
     · saveShareStore -> 键名与 webserve 里的一字不差
  3. 用官方 web/tools/yanyu-pack.js --unpack 反解我方 dat.yanyu（格式权威对照）

结论对应「存档文件类型统一」：dat.yanyu 就是网页原生格式；
dat.json 是明文备份，网页同样认。

跑法::

    python dev/check_site_import.py
"""
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yyjh import webserve                          # noqa: E402
from yyjh.game import yanyu                        # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, 'web')

PASS = []
FAIL = []


def check(name, cond, detail=''):
    if cond:
        PASS.append(name)
        print(f'  [OK]   {name}')
    else:
        FAIL.append(name)
        print(f'  [FAIL] {name}  {detail}')


# 网站要求的字段（save_decrypt.js：MainRole / globalVariable 必需）
SAMPLE = {
    'MainRole': {'Name': '龙炎', 'Level': 89, 'Platform': 'ios'},
    'globalVariable': {'a': 1, 'b': 'x'},
    'BornTalent': {'Seed': 42},
    'DBVersion': '00073460',
}

NODE_HARNESS = r'''
const fs = require('fs'), vm = require('vm');
const [sdPath, pakoPath, inpPath, outPath] = process.argv.slice(2);
const store = new Map();
const localStorage = {
  getItem: k => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: k => store.delete(k),
};
const sandbox = {
  console, localStorage, sessionStorage: localStorage,
  TextDecoder, TextEncoder, URL, URLSearchParams, Blob, Response,
  DecompressionStream: globalThis.DecompressionStream,
  crypto: require('crypto').webcrypto,
  atob: s => Buffer.from(s, 'base64').toString('binary'),
  btoa: s => Buffer.from(s, 'binary').toString('base64'),
  setTimeout, clearTimeout,
};
sandbox.window = sandbox; sandbox.self = sandbox; sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(pakoPath, 'utf8'), sandbox, { filename: 'pako.min.js' });
vm.runInContext(fs.readFileSync(sdPath, 'utf8'), sandbox, { filename: 'save_decrypt.js' });

const inp = JSON.parse(fs.readFileSync(inpPath, 'utf8'));
const out = {};
const same = (a) => !!a && JSON.stringify(a.data) === JSON.stringify(inp.sample);
(async () => {
  try {
    // ① .yanyu（自动导入 __latestYanyuB64 通道走的就是 decryptSaveBytes）
    const yb = new Uint8Array(Buffer.from(inp.yanyuB64, 'base64'));
    const r1 = await sandbox.decryptSaveBytes(yb, 'dat.yanyu', false);
    out.yanyuImport = same(r1);
    out.yanyuFormat = r1 && r1.format;

    // ② 明文 JSON（网页「导入数据」直接选 dat.json）
    const jb = new TextEncoder().encode(inp.jsonText);
    const r2 = sandbox.readPlainJsonBytes(jb, 'dat.json');
    out.jsonImport = same(r2);
    out.jsonFormat = r2 && r2.format;

    // ③ 共享存储键名以站点实际写入为准
    sandbox.saveShareStore(inp.sample, { platform: 'ios', importedAt: 1 });
    out.shareKeys = [...store.keys()];
    const r3 = sandbox.loadShareStore();
    out.shareRoundTrip = same(r3);
  } catch (e) {
    out.error = String((e && e.stack) || e);
  }
  fs.writeFileSync(outPath, JSON.stringify(out));
})();
'''


def main():
    tmp = tempfile.mkdtemp(prefix='yyjh_site_')
    try:
        # ── 1. 站点部署完整性 ─────────────────────────────────
        need = ['index.html', 'last-import.js', os.path.join('shared', 'save_decrypt.js'),
                os.path.join('tools', 'yanyu-pack.js')]
        check('4.0 站点在 web/（关键文件齐全）',
              all(os.path.isfile(os.path.join(WEB, f)) for f in need), need)

        # ── 2. 产一份工具真实输出 ─────────────────────────────
        yb = yanyu.pack(SAMPLE)
        check('dat.yanyu 打包成功（YANYUPL1 v1）',
              yb[:8] == b'YANYUPL1' and yb[8] == 1, yb[:10])
        check('yanyu.unpack 回环一致', yanyu.unpack(yb) == SAMPLE)

        # ── 3. 跑真正的 save_decrypt.js ───────────────────────
        harness = os.path.join(tmp, 'harness.js')
        inp = os.path.join(tmp, 'inp.json')
        out = os.path.join(tmp, 'out.json')
        with open(harness, 'w', encoding='utf-8') as f:
            f.write(NODE_HARNESS)
        with open(inp, 'w', encoding='utf-8') as f:
            json.dump({'sample': SAMPLE,
                       'yanyuB64': base64.b64encode(yb).decode('ascii'),
                       'jsonText': json.dumps(SAMPLE, ensure_ascii=False)}, f)

        node = shutil.which('node') or shutil.which('node.exe')
        if not node:
            check('node 可用（跳过 JS 验证）', False, '没找到 node，装了再跑')
        else:
            r = subprocess.run([node, harness,
                                os.path.join(WEB, 'shared', 'save_decrypt.js'),
                                os.path.join(WEB, 'shared', 'pako.min.js'),
                                inp, out],
                               capture_output=True, text=True, timeout=120)
            if r.returncode != 0 or not os.path.exists(out):
                check('JS 验证跑通', False, (r.stderr or r.stdout)[-300:])
            else:
                res = json.load(open(out, encoding='utf-8'))
                check('JS 验证跑通', not res.get('error'), res.get('error'))
                check('dat.yanyu 被站点解出（自动导入通道）',
                      bool(res.get('yanyuImport')), res.get('yanyuImport'))
                check('dat.json 明文被站点认（手动导入）',
                      bool(res.get('jsonImport')), res.get('jsonImport'))
                keys = res.get('shareKeys') or []
                check('共享存储键名与 webserve 逐字一致',
                      sorted(keys) == sorted([webserve.SAVE_SHARE_KEY,
                                              webserve.SAVE_SHARE_META_KEY]),
                      (keys, webserve.SAVE_SHARE_KEY, webserve.SAVE_SHARE_META_KEY))

            # ── 4. 官方打包器权威对照（--unpack 反解我方产物）──
            yp = os.path.join(WEB, 'tools', 'yanyu-pack.js')
            yf = os.path.join(tmp, 'dat.yanyu')
            jf = os.path.join(tmp, 'dat.json')
            with open(yf, 'wb') as f:
                f.write(yb)
            r = subprocess.run([node, yp, '--unpack', yf, jf],
                               capture_output=True, text=True, timeout=120)
            ok = False
            if r.returncode == 0 and os.path.exists(jf):
                try:
                    got = json.load(open(jf, encoding='utf-8'))
                    ok = got == SAMPLE
                except Exception:                        # noqa: BLE001
                    ok = False
            check('官方 yanyu-pack.js 能反解我方 dat.yanyu', ok,
                  (r.returncode, (r.stdout or '')[-120:], (r.stderr or '')[-120:]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print(f'通过 {len(PASS)} / 失败 {len(FAIL)}')
    for n in FAIL:
        print(f'  失败: {n}')
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
