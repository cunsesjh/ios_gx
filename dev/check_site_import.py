# -*- coding: utf-8 -*-
"""自检：工具产出的存档能不能被网页版（web/ 新站部署）直接导入。

用**网站自己的代码**（web/shared/save_decrypt.js）验证，不猜：

  1. 用工具真实产出一份明文 JSON 存档（统一后的存档文件类型）
  2. 丢给 node 跑真正的 save_decrypt.js：
     · 明文 JSON 文件 -> decryptSaveFile（网站「导入数据」路径）
     · saveShareStore -> loadShareStore 回环
     · 工具 pack_save 的压缩注入 -> loadShareStore 能读（自动载入路径）
  3. 共享存储键名以站点实际写入为准，和 webserve 里的一字不差

结论对应「存档文件类型统一」：明文 JSON 就是网站原生支持的导入格式，
自动导入之外，手动「导入数据」选 dat.json 也能进。

跑法::

    python dev/check_site_import.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yyjh import webserve                          # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, 'web', 'shared')

PASS = []
FAIL = []


def check(name, cond, detail=''):
    if cond:
        PASS.append(name)
        print(f'  [OK]   {name}')
    else:
        FAIL.append(name)
        print(f'  [FAIL] {name}  {detail}')


# 网站要求的三个字段（见 web/README.md「存档导入」一节）
SAMPLE = {
    'MainRole': {'Name': '龙炎', 'Level': 89},
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
(async () => {
  try {
    // ① 站点自己的 saveShareStore —— 顺便取它实际用的键名
    sandbox.saveShareStore(inp.sample, { platform: 'ios', format: 'json-local', importedAt: 1 });
    out.shareKeys = [...store.keys()];
    const a = sandbox.loadShareStore();
    out.shareRoundTrip = !!a && JSON.stringify(a.data) === JSON.stringify(inp.sample);

    // ② 工具 pack_save 注入（自动载入页走的路）
    store.clear();
    for (const [k, v] of Object.entries(inp.inject)) store.set(k, v);
    const b = sandbox.loadShareStore();
    out.injectRoundTrip = !!b && JSON.stringify(b.data) === JSON.stringify(inp.sample);

    // ③ 明文 JSON 文件直接「导入数据」
    store.clear();
    const bytes = new TextEncoder().encode(inp.jsonText);
    const file = { name: inp.jsonName, arrayBuffer: async () => bytes.buffer.slice(0) };
    const r = await sandbox.decryptSaveFile(file, undefined);
    out.jsonImport = !!r && !!r.data && JSON.stringify(r.data) === JSON.stringify(inp.sample);
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
        check('站点在 web/（index.html + server.js）',
              os.path.isfile(os.path.join(ROOT, 'web', 'index.html'))
              and os.path.isfile(os.path.join(ROOT, 'web', 'server.js')))
        check('明文 JSON 存档三件套齐全（MainRole/globalVariable/BornTalent）',
              all(k in SAMPLE for k in ('MainRole', 'globalVariable', 'BornTalent')))

        # ── 2. 跑真正的 save_decrypt.js ───────────────────────
        meta = {'version': '00073460', 'platform': 'ios', 'channel': '',
                'format': 'json-local', 'fileName': 'dat.json', 'importedAt': 1}
        inject = {
            webserve.SAVE_SHARE_KEY: webserve.pack_save(SAMPLE),
            webserve.SAVE_SHARE_META_KEY: json.dumps(meta, ensure_ascii=False),
        }
        harness = os.path.join(tmp, 'harness.js')
        inp = os.path.join(tmp, 'inp.json')
        out = os.path.join(tmp, 'out.json')
        with open(harness, 'w', encoding='utf-8') as f:
            f.write(NODE_HARNESS)
        with open(inp, 'w', encoding='utf-8') as f:
            json.dump({'sample': SAMPLE, 'inject': inject,
                       'jsonText': json.dumps(SAMPLE, ensure_ascii=False),
                       'jsonName': '龙炎_20261019_120000.json'}, f)

        node = shutil.which('node') or shutil.which('node.exe')
        if not node:
            check('node 可用（跳过 JS 验证）', False, '没找到 node，装了再跑')
        else:
            r = subprocess.run([node, harness,
                                os.path.join(WEB, 'save_decrypt.js'),
                                os.path.join(WEB, 'pako.min.js'),
                                inp, out],
                               capture_output=True, text=True, timeout=60)
            if r.returncode != 0 or not os.path.exists(out):
                check('JS 验证跑通', False, (r.stderr or r.stdout)[-300:])
            else:
                res = json.load(open(out, encoding='utf-8'))
                check('JS 验证跑通', not res.get('error'), res.get('error'))
                check('明文 JSON 直接导入（网站「导入数据」路径）',
                      bool(res.get('jsonImport')), res.get('jsonImport'))
                check('站点共享存储回环', bool(res.get('shareRoundTrip')),
                      res.get('shareRoundTrip'))
                check('工具 pack_save 注入后站点能读（自动载入路径）',
                      bool(res.get('injectRoundTrip')), res.get('injectRoundTrip'))
                keys = res.get('shareKeys') or []
                check('共享存储键名与 webserve 逐字一致',
                      sorted(keys) == sorted([webserve.SAVE_SHARE_KEY,
                                              webserve.SAVE_SHARE_META_KEY]),
                      (keys, webserve.SAVE_SHARE_KEY, webserve.SAVE_SHARE_META_KEY))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print(f'通过 {len(PASS)} / 失败 {len(FAIL)}')
    for n in FAIL:
        print(f'  失败: {n}')
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
