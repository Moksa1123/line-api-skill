#!/usr/bin/env python3
"""拿實際發佈的 LIFF SDK 驗證 liff-api.csv。

LIFF 沒有可以送去驗證的伺服器端點，訊息與圖文選單那套對照方法用不上。
但有更直接的東西：瀏覽器真正載入的那份 SDK。它才是「這個 API 存不存在」
的最終答案——文件可能還沒更新，SDK 不會騙人。

    python tools/check_liff_sdk.py            # 抓 edge/2（最新）
    python tools/check_liff_sdk.py --version 2.22.3

注意命名空間 API：liff.permission.query() 在壓縮後不會有這個完整字串，
只會看到葉節點 query，所以要拆開來找。第一版沒拆，7 個 API 全被誤判成
「SDK 裡沒有」。
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "line-api"

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

EDGE = "https://static.line-scdn.net/liff/edge/2/sdk.js"
FIXED = "https://static.line-scdn.net/liff/edge/versions/{v}/sdk.js"


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "line-api-skill/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", help="指定 PATCH 版本，例如 2.22.3")
    args = ap.parse_args()

    url = FIXED.format(v=args.version) if args.version else EDGE
    print(f"抓 {url}")
    js = fetch(url)
    m = re.search(r'"?version"?\s*[:=]\s*"(\d+\.\d+\.\d+)"', js)
    ver = m.group(1) if m else "?"
    print(f"  {len(js):,} bytes，版本 {ver}\n")

    with open(SKILL / "data" / "liff-api.csv", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    missing = []
    for r in rows:
        name = r["name"]
        # liff.permission.query() → 逐段找。壓縮過的程式碼裡只留得下葉節點
        parts = [p for p in name.replace("()", "").split(".") if p and p != "liff"]
        leaf = parts[-1] if parts else ""
        if not leaf:
            continue
        if not re.search(r"\b" + re.escape(leaf) + r"\b", js):
            missing.append(name)

    print(f"liff-api.csv 有 {len(rows)} 個 API，SDK {ver} 裡：")
    print(f"  找得到  {len(rows) - len(missing)}")
    print(f"  找不到  {len(missing)}")
    if missing:
        print("\n這些在資料集裡有、但實際 SDK 裡找不到——可能已經被移除，"
              "或是我們把名字記錯了：")
        for x in missing:
            print("   ", x)
        return 1
    print("\n每一個都在。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
