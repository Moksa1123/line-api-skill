#!/usr/bin/env python3
"""
discover_pages.py — 掃出 developers.line.biz 上所有 /en/ 頁面。

為什麼需要它
------------
fetch_sources.py 原本是從 llms.txt 的種子出發，再沿著「Markdown 內文的
交叉連結」BFS。但網站的側邊導覽是在 HTML 裡的，只靠導覽才到得了的頁面
就永遠不會被發現。這支工具改從 HTML 抓連結，把整個 /en/ 樹走過一遍，
再跟 .docs-cache/raw 已有的檔案比對，列出漏掉的頁面。

用法
    python tools/discover_pages.py            # 只報告落差
    python tools/discover_pages.py --write    # 把完整清單寫進 .docs-cache/urls_all.txt
"""
from __future__ import annotations

import argparse
import queue
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CACHE = REPO / ".docs-cache"
RAW = CACHE / "raw"
BASE = "https://developers.line.biz"
UA = {"User-Agent": "Mozilla/5.0 (+line-api-skill page discovery)"}
WORKERS = 6

# HTML 裡的站內連結。只收 /en/ 開頭、不含副檔名與 query 的路徑。
HREF_RE = re.compile(r'href="(/en/[A-Za-z0-9\-_/]*)"')

# 這些區段不是 API 文件，抓了只會稀釋資料集
SKIP_PREFIXES = (
    "en/news",          # 公告，數百頁且會一直長
    "en/reference/android-sdk",
    "en/reference/ios-sdk",
    "en/reference/unity-sdk",
    "en/reference/liff-v1",   # 已停止服務
)


def fetch(url: str, tries: int = 3) -> str | None:
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return None
            time.sleep(1.5 * (attempt + 1))
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    return None


def skip(rel: str) -> bool:
    return any(rel.startswith(p) for p in SKIP_PREFIXES)


def crawl(seeds: list[str]) -> set[str]:
    """從 HTML 逐頁抓 href，走遍整個 /en/ 樹。"""
    seen: set[str] = set()
    found: set[str] = set()
    lock = threading.Lock()
    q: queue.Queue[str] = queue.Queue()

    for s in seeds:
        rel = s.strip("/")
        if rel not in seen:
            seen.add(rel)
            q.put(rel)

    def worker():
        while True:
            try:
                rel = q.get(timeout=8)
            except queue.Empty:
                return
            try:
                html = fetch(BASE + "/" + rel + "/")
                if not html:
                    continue
                with lock:
                    found.add(rel)
                for href in HREF_RE.findall(html):
                    child = href.strip("/")
                    if not child or skip(child):
                        continue
                    with lock:
                        if child in seen:
                            continue
                        seen.add(child)
                    q.put(child)
            finally:
                q.task_done()

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(WORKERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return found


def already_have() -> set[str]:
    if not RAW.exists():
        return set()
    return {p.relative_to(RAW).as_posix()[:-3] for p in RAW.rglob("*.md")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help="把完整清單寫進 .docs-cache/urls_all.txt")
    args = ap.parse_args()

    seeds = [
        "en", "en/docs", "en/reference/messaging-api", "en/reference/liff",
        "en/reference/liff-server", "en/reference/line-login",
        "en/reference/line-login-v2", "en/reference/line-mini-app",
        "en/reference/partner-docs", "en/reference/line-notification-messages",
        "en/docs/messaging-api", "en/docs/liff", "en/docs/line-login",
        "en/docs/line-mini-app", "en/docs/partner-docs", "en/docs/basics",
        "en/docs/line-developers-console", "en/docs/line-social-plugins",
        "en/glossary", "en/faq", "en/services",
    ]
    print(f"從 {len(seeds)} 個種子開始掃描整站 /en/ 樹 ...")
    found = crawl(seeds)
    have = already_have()
    missing = sorted(f for f in found if f not in have)

    print(f"\n站上找到 {len(found)} 個頁面｜已抓 {len(have)} 個｜未抓 {len(missing)} 個")
    if missing:
        print("\n未抓到的頁面：")
        by_section: dict[str, list[str]] = {}
        for m in missing:
            key = "/".join(m.split("/")[:3])
            by_section.setdefault(key, []).append(m)
        for key in sorted(by_section):
            items = by_section[key]
            print(f"\n  [{key}] {len(items)} 頁")
            for it in items[:12]:
                print(f"      {it}")
            if len(items) > 12:
                print(f"      … 另有 {len(items) - 12} 頁")

    if args.write:
        out = CACHE / "urls_all.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(sorted(found)), encoding="utf-8")
        print(f"\n完整清單已寫入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
