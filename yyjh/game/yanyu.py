# -*- coding: utf-8 -*-
"""`.yanyu` 本地导出容器（magic = YANYUPL1）打包/解包。

这是**新网页（guanxing4.0）原生支持**的存档格式 —— 存档统一转成它：
网页「导入数据」直接吃，`window.__latestYanyuB64` 自动导入通道也走它。

容器格式（与 web/tools/yanyu-pack.js、web/shared/save_decrypt.js 逐字节对齐）::

    [0 .. 7]   magic   "YANYUPL1"
    [8]        version 1 = 仅固定口令；2 = 固定口令 + 授权码
    [9]        flags   bit0 = gzip 压缩
    [10 .. 25] salt    16 字节（随机）
    [26 .. 37] nonce   12 字节（随机，AES-GCM IV）
    [38 .. 45] codeTag 8 字节（仅 v2：授权码指纹，溯源用，不是授权码本身）
    [ ... ]    AES-256-GCM( gzip(json) ) || tag(16)

    密钥 v1: PBKDF2-SHA256(SECRET, salt, 120000, 32)
    密钥 v2: PBKDF2-SHA256(SECRET + '\\0' + 授权码, salt, 120000, 32)

依赖 `cryptography`（pip install cryptography）；没有就报人话错误。
"""
import gzip
import hashlib
import json
import os

MAGIC = b'YANYUPL1'
VERSION_PLAIN = 1
VERSION_CODE = 2
FLAG_GZIP = 1
SECRET = 'yanyu-plain-export-v1|7f3c1d9a4e6b2085'
KDF_ITERATIONS = 120000
SALT_BYTES = 16
NONCE_BYTES = 12
TAG_BYTES = 16
CODE_TAG_BYTES = 8


def _aes():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        return AESGCM
    except ImportError as e:
        from .. import ui
        raise ui.UserError('生成 .yanyu 需要 cryptography 库', [
            '安装一下：pip install cryptography',
        ]) from e


def _derive_key(salt, code=''):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    material = (SECRET + '\u0000' + code) if code else SECRET
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                     iterations=KDF_ITERATIONS)
    return kdf.derive(material.encode('utf-8'))


def _code_tag(code):
    """授权码指纹：只用来溯源，无法反推授权码。"""
    return hashlib.sha256(('yanyu-code-tag|' + code).encode('utf-8')).digest()[:CODE_TAG_BYTES]


def pack(data, code=''):
    """把存档 dict 打包成 .yanyu 字节串。给 code 就是 v2（授权码版）。"""
    AESGCM = _aes()
    version = VERSION_CODE if code else VERSION_PLAIN
    raw = json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    body_plain = gzip.compress(raw, 9)
    salt = os.urandom(SALT_BYTES)
    nonce = os.urandom(NONCE_BYTES)
    key = _derive_key(salt, code)
    cipher = AESGCM(key).encrypt(nonce, body_plain, None)   # 输出 = 密文 || tag(16)
    head = MAGIC + bytes([version, FLAG_GZIP]) + salt + nonce
    if version == VERSION_CODE:
        head += _code_tag(code)
    return head + cipher


def unpack(blob, code=''):
    """解回存档 dict（自检/自查用）。失败抛 ValueError。"""
    AESGCM = _aes()
    if not blob or len(blob) < 10 + SALT_BYTES + NONCE_BYTES + TAG_BYTES:
        raise ValueError('不是有效的 .yanyu 存档（文件头不匹配）')
    if blob[:len(MAGIC)] != MAGIC:
        raise ValueError('不是有效的 .yanyu 存档（文件头不匹配）')
    version = blob[len(MAGIC)]
    flags = blob[len(MAGIC) + 1]
    if version not in (VERSION_PLAIN, VERSION_CODE):
        raise ValueError(f'不支持的 .yanyu 版本：{version}')
    if version == VERSION_CODE and not code:
        raise ValueError('YANYU_CODE_REQUIRED')
    p = len(MAGIC) + 2
    salt = blob[p:p + SALT_BYTES]
    nonce = blob[p + SALT_BYTES:p + SALT_BYTES + NONCE_BYTES]
    body = blob[p + SALT_BYTES + NONCE_BYTES:]
    if version == VERSION_CODE:
        body = body[CODE_TAG_BYTES:]
    key = _derive_key(salt, code)
    try:
        plain = AESGCM(key).decrypt(nonce, body, None)
    except Exception as e:                                # noqa: BLE001
        raise ValueError('YANYU_CODE_WRONG' if version == VERSION_CODE
                         else '.yanyu 解密失败：文件已损坏或被修改过') from e
    if flags & FLAG_GZIP:
        plain = gzip.decompress(plain)
    parsed = json.loads(plain.decode('utf-8-sig'))
    data = parsed.get('data') if isinstance(parsed.get('data'), dict) else parsed
    if not isinstance(data, dict) or not data.get('MainRole') or not data.get('globalVariable'):
        raise ValueError('.yanyu 存档缺少必要字段（MainRole / globalVariable）')
    return data
