# -*- coding: utf-8 -*-
"""自检：工具产出的存档能不能被新网页（guanxing4.0）直接导入。

用**网站自己的代码**验证，不猜：

  1. 用工具真实产出 dat.json（唯一存档格式，不再出 dat.yanyu）
  2. 丢给 node 跑真正的 web/shared/save_decrypt.js：
     · dat.json -> readPlainJsonBytes（网页「导入数据」明文路径）
     · saveShareStore / loadShareStore -> 键名与 webserve 里的一字不差
  3. 自动导入通道：webserve.write_last_import 生成的 `__latestPlainSave`
     载荷与 dat.json 逐字一致（home.js 的明文分支直接吃）

结论对应「存档只出 dat.json」：明文存档就是网页原生吃的格式，
网页「导入数据」与自动导入通道都认。

跑法::

    python dev/check_site_import.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yyjh import report, webserve                          # noqa: E402
from yyjh.model import SaveResult                          # noqa: E402

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
    // ① 明文 JSON（网页「导入数据」直接选 dat.json）
    const jb = new TextEncoder().encode(inp.jsonText);
    const r1 = sandbox.readPlainJsonBytes(jb, 'dat.json');
    out.jsonImport = same(r1);
    out.jsonFormat = r1 && r1.format;

    // ② 自动导入通道：home.js 的明文分支 = saveShareStore(payload.data, …)
    sandbox.saveShareStore(inp.autoData, {
      version: '明文', platform: inp.autoPlatform || '', channel: '', format: 'plain-json',
    });
    out.shareKeys = [...store.keys()];
    const r2 = sandbox.loadShareStore();
    out.shareRoundTrip = same(r2);
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
        need = ['index.html', 'last-import.js', os.path.join('shared', 'save_decrypt.js')]
        check('4.0 站点在 web/（关键文件齐全）',
              all(os.path.isfile(os.path.join(WEB, f)) for f in need), need)

        # ── 2. 工具真实产出：只出 dat.json ─────────────────────
        res = SaveResult(kind='har', runtime='ios', server='3', version='00073460')
        res.data = dict(SAMPLE)
        outs = report.write_all(res, outdir=tmp)
        check('工具产出 dat.json', 'json' in outs and os.path.exists(outs['json']),
              outs)
        snap = os.path.dirname(outs.get('json') or tmp)
        check('不再产出 dat.yanyu', 'yanyu' not in outs
              and not os.path.exists(os.path.join(snap, 'dat.yanyu')),
              sorted(os.listdir(snap)))
        with open(outs['json'], encoding='utf-8') as f:
            json_text = f.read()
        check('dat.json 与存档逐字一致', json.loads(json_text) == SAMPLE)

        # ── 3. 自动导入脚本：明文通道，载荷 = dat.json ─────────
        row = {'json': outs['json'], 'db': None, 'meta': {'runtime': 'ios'}}
        page = webserve.write_last_import(row)
        check('write_last_import 生成成功', bool(page) and os.path.exists(page), page)
        with open(page, encoding='utf-8') as f:
            head = f.readline()
        m = re.match(r'window\.__latestPlainSave=(.*);\s*$', head)
        check('自动导入走 __latestPlainSave 明文通道', bool(m), head[:80])
        payload = json.loads(m.group(1)) if m else {}
        check('自动导入载荷 = dat.json（逐字一致）',
              payload.get('data') == SAMPLE, payload.get('data'))

        # ── 4. 跑真正的 save_decrypt.js ───────────────────────
        harness = os.path.join(tmp, 'harness.js')
        inp = os.path.join(tmp, 'inp.json')
        out = os.path.join(tmp, 'out.json')
        with open(harness, 'w', encoding='utf-8') as f:
            f.write(NODE_HARNESS)
        with open(inp, 'w', encoding='utf-8') as f:
            json.dump({'sample': SAMPLE,
                       'jsonText': json_text,
                       'autoData': payload.get('data') or {},
                       'autoPlatform': payload.get('platform') or ''}, f)

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
                res_js = json.load(open(out, encoding='utf-8'))
                check('JS 验证跑通', not res_js.get('error'), res_js.get('error'))
                check('dat.json 被站点解出（导入数据）',
                      bool(res_js.get('jsonImport')), res_js.get('jsonImport'))
                check('自动导入载荷被站点存下并回读一致',
                      bool(res_js.get('shareRoundTrip')), res_js.get('shareRoundTrip'))
                keys = res_js.get('shareKeys') or []
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
