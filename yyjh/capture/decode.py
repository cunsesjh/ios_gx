# -*- coding: utf-8 -*-
"""抓包 HAR -> 存档（SaveResult）。

关键点：**外层解开后拿到的 base64 文本就是"初版" content**
（网络外层用的是服务器下发的 realKey，正好替代了那个每账号随机、
 只存在内存里的"外层密钥"），所以不需要重新加密任何数据。
"""
import os

from .. import model
from ..core import codecs, xxtea
from ..game import player as player_mod
from ..game import protocol, savefmt
from .har import Har


def pick_entry(har, index=None):
    ups = har.uploads()
    if not ups:
        raise ValueError('HAR 里没有 upload 请求（抓包时游戏没上传存档？）')
    if index is not None:
        if not (0 <= index < len(ups)):
            raise ValueError(f'--index 超范围（共 {len(ups)} 个）')
        return ups[index], len(ups)
    return max(ups, key=har.body_len), len(ups)


def inner_body(har_path, index=None, real_key=None, steps=None):
    """HAR -> 只做到「初版 content」为止。

    返回 dict: version / body / runtime / account / save_id / server / content
    其中 body 是**内层 XXTEA 密文** —— 缺内层密钥时拿它去爆破
    （`yyjh key crack --har` 就是这么干的）。

    为什么单独抽出来：内层密钥不知道时，外层其实已经能免费解开 ——
    抓包里的 realKey 顶替了那把只存在内存里的「外层密钥」，
    所以「密钥表过期」根本不该妨碍我们从抓包里拿到爆破靶子。
    """
    say = steps or (lambda *a, **k: None)
    har = Har(har_path)
    say('HAR', f'{os.path.basename(har_path)}  共 {len(har.entries)} 条记录')

    entry, total = pick_entry(har, index)
    if total > 1:
        say('选择 upload',
            f'共 {total} 个，选请求体最大的（{har.body_len(entry):,} 字符）')

    acc = har.account(entry)
    if not acc:
        raise ValueError('upload 请求里没有 acc 请求头')
    runtime = 'ios' if protocol.is_ios(acc) else 'android'
    server = har.server(entry) or ''
    say('账号 acc', f'{acc}   平台 = {runtime}   服 = {server or "?"}')
    save_id = savefmt.save_id_of(acc)
    say('save.id', f'md5(acc) = {save_id}')

    # ── 协议密钥 ──
    if real_key:
        say('realKey', f'{real_key}  (命令行指定)')
    else:
        k = har.k_header()
        if not k:
            raise ValueError('HAR 里没有带 k 的响应头 —— 请从"打开游戏之前"开始抓，'
                             '或用 --real-key 手动指定')
        keys = protocol.derive(acc, k)
        say('key0', keys['key0'])
        say('innerK', repr(keys['inner_k']))
        say('realKey', keys['real_key'])
        real_key = keys['real_key']

    # ── 外层 -> 初版 content ──
    body = Har.body(entry)
    cipher = body if isinstance(body, (bytes, bytearray)) else codecs.b64d(body)
    if cipher is None:
        raise ValueError('upload 请求体不是合法 base64')
    x = xxtea.decrypt(bytes(cipher), real_key)
    if x is None:
        raise ValueError('外层解密失败（realKey 不对）')
    try:
        content = x.decode('ascii')
    except UnicodeDecodeError:
        raise ValueError('外层解出的不是 ASCII base64（realKey 不对？）')
    say('外层解密', f'{len(cipher):,}B -> {len(content):,} 字符 base64  ← 即初版 content')

    version, inner = savefmt.parse_old(content)
    say('版本号', version)
    return {'version': version, 'body': inner, 'runtime': runtime, 'account': acc,
            'save_id': save_id, 'server': server, 'content': content,
            # realKey 就是「外层密钥」那把（它只存在服务器的响应里，
            # 本地存档要解时得去内存挖）—— 白送的，调用方可以记下来复用
            'outer_key': real_key}


def decode(har_path, index=None, real_key=None, inner_key=None,
           avatar_field='auto'):
    """返回 SaveResult。"""
    r = model.SaveResult(source=har_path, kind='har')
    info = inner_body(har_path, index=index, real_key=real_key, steps=r.step)
    version, inner = info['version'], info['body']
    r.account, r.runtime = info['account'], info['runtime']
    r.server, r.save_id = info['server'], info['save_id']
    r.content, r.version = info['content'], version
    r.outer_key = info.get('outer_key') or ''

    # ── 内层 -> JSON ──
    cands = savefmt.inner_candidates(r.runtime, version, inner_key)
    data, used = savefmt.try_inner(inner, cands)
    if data is None:
        raise savefmt.InnerKeyMissing(version, r.runtime,
                                      tried=len(cands), fmt=savefmt.OLD)
    r.data = data
    r.inner_key = used
    r.step('内层密钥', f'{used}  ({len(cands)} 个候选中命中)')
    r.step('解密结果', f'{len(data)} 个字段   角色 = {r.nick!r}')

    r.player = player_mod.build(data, version, avatar_field)
    r.step('player 摘要', r.player)

    enc = data.get('EncryptID')
    if enc and enc != info['account']:
        r.warn(f'JSON 里的 EncryptID（{enc}）与 acc 不一致')
    return r
