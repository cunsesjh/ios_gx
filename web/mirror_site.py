# -*- coding: utf-8 -*-
"""递归镜像 yanyu-util.pages.dev 静态资源到本地"""
import os, re, sys, time, urllib.request, urllib.error, concurrent.futures

ROOT = r"C:\Users\lx\DoubaoWork\chats\2026-09-24\new-chat-1\yanyu-local"
BASE = "https://yanyu-util.pages.dev/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

os.makedirs(ROOT, exist_ok=True)
downloaded = set()
missing = set()
failed = set()
# 已知需要额外下载的资产（混淆 JS 动态引用的路径）
EXTRA = [
    "protected/algorithm_bundle.enc",
    "protected/wash_engine.enc",
    "protected/equipment_engine.enc",
    "protected/hengshan_engine.enc",
    "protected/drop_engine.enc",
    "downloads/yanyu-cxk-v2.9.0.apk",
]

def resolve(ref, referrer):
    """把相对引用解析为站点相对路径"""
    if ref.startswith(("data:", "blob:", "javascript:", "mailto:", "#")):
        return None
    if ref.startswith(BASE):
        ref = ref[len(BASE):]
    elif ref.startswith(("http://", "https://")):
        return None
    ref = ref.split("#")[0].split("?")[0]
    if not ref:
        return None
    if referrer == BASE:
        base_dir = ""
    else:
        base_dir = os.path.dirname(referrer[len(BASE):]).replace("\\", "/")
    url = ref[2:] if ref.startswith("./") else ref
    if url.startswith("/"):
        base_dir, url = "", url[1:]
    full = base_dir + "/" + url if base_dir else url
    full = full.replace("\\", "/")
    parts = full.split("/")
    out = []
    for p in parts:
        if p == "..":
            if out: out.pop()
        elif p and p != ".":
            out.append(p)
    return "/".join(out)

def scan(path):
    """扫描一个文件中的所有引用"""
    refs = []
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception:
        return refs
    rel = os.path.relpath(path, ROOT).replace("\\", "/")
    referrer = BASE if rel == "index.html" else BASE + rel
    for m in re.finditer(r'(?:src|href)\s*=\s*["\']([^"\'#]+?)(?:["\']|#|&)', content):
        r = resolve(m.group(1).strip(), referrer)
        if r: refs.append(r)
    for m in re.finditer(r'url\(\s*["\']?([^"\')\s]+)', content):
        r = resolve(m.group(1).strip(), referrer)
        if r: refs.append(r)
    for m in re.finditer(r'["\'](\.{1,2}/[^"\']+)["\']', content):
        r = resolve(m.group(1), referrer)
        if r: refs.append(r)
    return refs

def download(url, outpath):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": BASE})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        os.makedirs(os.path.dirname(outpath), exist_ok=True)
        with open(outpath, "wb") as f:
            f.write(data)
        return len(data)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            missing.add(url.replace(BASE, ""))
        else:
            failed.add((url, e.code))
        return None
    except Exception as e:
        failed.add((url, str(e)[:60]))
        return None

def main():
    # 初始队列：扫描本地已有文件 + EXTRA
    queue = set()
    for dp, dn, fn in os.walk(ROOT):
        for name in fn:
            if name.endswith((".html", ".css", ".js")):
                queue.update(scan(os.path.join(dp, name)))
    for e in EXTRA:
        queue.add(e)

    rounds = 0
    while queue and rounds < 12:
        rounds += 1
        todo = sorted(queue - downloaded)
        if not todo:
            break
        print(f"[round {rounds}] {len(todo)} files to download...", flush=True)
        def work(item):
            out = os.path.join(ROOT, item.replace("/", os.sep))
            if os.path.exists(out):
                return item, "exists"
            return item, download(BASE + item, out)
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
            results = list(ex.map(work, todo))
        for item, r in results:
            downloaded.add(item)
        # 新下载文件的引用入队（仅文本类）
        new_files = [os.path.join(ROOT, it.replace("/", os.sep)) for it, r in results
                     if r not in ("exists", None) and it.endswith((".html", ".css", ".js"))]
        for p in new_files:
            queue.update(scan(p))
        time.sleep(0.3)

    print(f"\n=== DONE: downloaded={len(downloaded)} rounds={rounds} ===")
    print("=== MISSING(404) ===")
    for m in sorted(missing): print(m)
    print("=== FAILED ===")
    for u, c in sorted(failed): print(u, c)

if __name__ == "__main__":
    main()
