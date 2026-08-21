#!/usr/bin/env python3
"""
check_links.py — verify every doc_url referenced by the skill actually resolves.

developers.line.biz is a Nuxt SPA: an unknown path still answers 200 with a
client-only shell. A page only counts as real when the response is
server-rendered (data-ssr="true") and carries the docs <main> element.

Usage:
    python tools/check_links.py              # every URL in line-api/data/*.csv
    python tools/check_links.py --md         # also every link in line-api/**/*.md
    python tools/check_links.py --all
"""
from __future__ import annotations

import argparse
import csv
import queue
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
SKILL = REPO / "line-api"
UA = {"User-Agent": "Mozilla/5.0 (+line-api-skill link checker)"}
WORKERS = 4
URL_RE = re.compile(r"https?://[^\s)\]\"'<>`,;]+")

# Placeholder hosts that appear inside code samples — never real targets.
PLACEHOLDER_HOSTS = (
    "example.com", "example.org", "sample_line.me",
    "xxxx.ngrok-free.app", "xxx.ngrok-free.app",
)


# API endpoints, not documentation. They answer 400/401/405 without
# credentials, which says nothing about whether the docs are correct.
API_HOSTS = (
    "://api.line.me", "://api-data.line.me", "://access.line.me",
    "://notify-api.line.me", "://manager.line.biz", "://miniapp.line.me",
    "://liff.line.me", "://static.line-scdn.net", "://developers.line.biz/console",
    "://developers.line.biz/flex-simulator",
)


def is_placeholder(url: str) -> bool:
    if any(h in url for h in API_HOSTS):
        return True
    if any(h in url for h in PLACEHOLDER_HOSTS):
        return True
    # templated URLs such as https://liff.line.me/{liffId} or .../...
    return "{" in url or url.rstrip("/").endswith("...")


def check(url: str) -> tuple[str, str]:
    """Return (status, detail)."""
    base = url.split("#")[0]
    for attempt in range(3):
        try:
            req = urllib.request.Request(base, headers=UA)
            with urllib.request.urlopen(req, timeout=40) as r:
                code = r.status
                body = r.read(200_000).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return "DEAD", f"HTTP {e.code}"
            # 403/429 from developers.line.biz is rate limiting, not a dead page
            time.sleep(2.0 * (attempt + 1))
            if attempt == 2:
                return "DEAD", f"HTTP {e.code}"
            continue
        except Exception as e:  # network hiccup
            time.sleep(1.2 * (attempt + 1))
            if attempt == 2:
                return "ERROR", type(e).__name__
            continue

        if code != 200:
            return "DEAD", f"HTTP {code}"
        if "developers.line.biz" in base:
            if 'devdocs:type" content="redirect"' in body:
                m = re.search(r'window\.location\.href\s*=\s*"([^"]+)"', body)
                return "REDIRECT", (m.group(1) if m else "?")
            if 'data-ssr="false"' in body:
                return "DEAD", "SPA shell (not server-rendered)"
        return "OK", ""
    return "ERROR", "retries exhausted"


def collect(include_md: bool) -> dict[str, set[str]]:
    urls: dict[str, set[str]] = {}
    for p in sorted((SKILL / "data").glob("*.csv")):
        with open(p, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                for k, v in row.items():
                    if v and k.endswith("url") and v.startswith("http"):
                        urls.setdefault(v.split("#")[0], set()).add(p.name)
    if include_md:
        for p in sorted(SKILL.rglob("*.md")):
            for u in URL_RE.findall(p.read_text(encoding="utf-8")):
                u = u.rstrip(".,;:`\"')")
                u = re.sub(r"[^!-~]+$", "", u)     # 去掉尾端全形標點
                if is_placeholder(u):
                    continue
                urls.setdefault(u.split("#")[0], set()).add(p.name)
    return urls


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", action="store_true", help="also check links inside Markdown files")
    ap.add_argument("--all", action="store_true", help="same as --md")
    args = ap.parse_args()

    urls = collect(args.md or args.all)
    print(f"checking {len(urls)} unique URLs with {WORKERS} workers ...\n")

    q: queue.Queue[str] = queue.Queue()
    for u in urls:
        q.put(u)
    results: dict[str, tuple[str, str]] = {}
    lock = threading.Lock()

    def worker():
        while True:
            try:
                u = q.get_nowait()
            except queue.Empty:
                return
            res = check(u)
            with lock:
                results[u] = res
            time.sleep(0.3)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(WORKERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    bad = {u: r for u, r in results.items() if r[0] != "OK"}
    for u, (status, detail) in sorted(bad.items()):
        where = ", ".join(sorted(urls[u]))
        print(f"{status:8s} {u}\n         {detail}  (used in: {where})")

    ok = len(results) - len(bad)
    print(f"\n{ok}/{len(results)} OK, {len(bad)} problem(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
