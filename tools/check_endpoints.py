#!/usr/bin/env python3
"""確認 endpoints.csv 裡的 121 條路徑真的存在，而且一次也不執行任何操作。

直接打端點的問題是：對的請求會真的發訊息、真的刪選單。而 404 又分不出
「這條路由不存在」和「這個資源不存在」——兩者回的都是 {"message":"Not found"}。

所以改用故意錯的 method 探測：

    真路徑 + 不支援的 method → 405 The request method is not supported
    假路徑 + 不支援的 method → 404 Not found

LINE 全部 121 支端點只用 GET / POST / PUT / DELETE，沒有一支用 PATCH，
所以一律送 PATCH：路由層就會擋下來，永遠走不到會真的做事的那一段。
"""
from __future__ import annotations

import csv
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "line-api"
sys.path.insert(0, str(SKILL / "scripts"))

import core  # noqa: E402

core.load_dotenv()
core.use_utf8_stdout()

import re

PROBE_METHOD = "PATCH"          # endpoints.csv 裡一支都沒有，保證不會執行到任何操作

# 路徑參數不能隨便填。LINE 的路由在比對 method 之前先驗參數的形狀，
# 填 "0" 的話 /v2/bot/richmenu/{richMenuId} 會在路由層就 404，
# 看起來像「這條路徑不存在」，其實只是 ID 長得不對。
# 這裡填的都是「格式正確但保證不存在」的值。
HEX32 = "0123456789abcdef0123456789abcdef"
PLACEHOLDERS = {
    "richMenuId": "richmenu-" + HEX32,
    "richMenuAliasId": "alias-does-not-exist",
    "userId": "U" + HEX32,
    "groupId": "C" + HEX32,
    "roomId": "R" + HEX32,
    "messageId": "1234567890123",
    "requestId": HEX32,
    "audienceGroupId": "1234567890123",
    "couponId": HEX32,
    "membershipId": "1234567",
    "liffId": "1234567890-abcdefgh",
    "moduleChannelId": "1234567890",
    "botId": "U" + HEX32,
    "kid": HEX32,
}
DEFAULT_PLACEHOLDER = HEX32


def fill(path: str) -> str:
    return re.sub(r"\{([^}]+)\}",
                  lambda m: PLACEHOLDERS.get(m.group(1), DEFAULT_PLACEHOLDER),
                  path)


def main() -> int:
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    if not token:
        raise SystemExit("需要 LINE_CHANNEL_ACCESS_TOKEN")

    with open(SKILL / "data" / "endpoints.csv", encoding="utf-8", newline="") as f:
        eps = list(csv.DictReader(f))

    assert not any(e["method"] == PROBE_METHOD for e in eps), \
        f"有端點用了 {PROBE_METHOD}，換一個探測用的 method"

    buckets: dict[str, list] = {}
    for e in eps:
        path = e["path"]
        url = e["host"] + fill(path)
        req = urllib.request.Request(url, method=PROBE_METHOD,
                                     headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                status, body = r.status, r.read(200).decode("utf-8", "replace")
        except urllib.error.HTTPError as ex:
            status, body = ex.code, ex.read(200).decode("utf-8", "replace")
        except Exception as ex:
            status, body = -1, f"{type(ex).__name__}: {ex}"

        # 路徑存在的三種訊號。分得出來的關鍵在於「哪一層回的」：
        #   405                      主要 API 的路由層說 method 不對 → 路徑在
        #   400 method not supported OAuth 那幾支是另一套服務，格式不同 → 路徑在
        #   404 resource is not found. 資源層說找不到（注意小寫與句點），
        #                            跟路由層的 {"message":"Not found"} 不是同一句
        if status == 405:
            kind = "exists"
        elif status == 400 and "method not supported" in body:
            kind = "exists"
        elif status == 404 and "resource is not found" in body.lower():
            kind = "exists"
        elif status == 404:
            kind = "MISSING"
        else:
            kind = f"other:{status}"
        buckets.setdefault(kind, []).append(
            {"method": e["method"], "path": path, "host": e["host"],
             "title": e["title"], "status": status, "body": body[:120]})

    total = len(eps)
    print(f"{total} 支端點，全部用 {PROBE_METHOD} 探測（不會執行任何操作）：")
    for kind in sorted(buckets, key=lambda k: (k != "exists", k)):
        print(f"  {kind:14} {len(buckets[kind]):4}")
    print()
    for kind, items in sorted(buckets.items()):
        if kind == "exists":
            continue
        print(f"--- {kind} ---")
        for it in items:
            print(f"  {it['method']:6} {it['path']}")
            print(f"         {it['title']}")
            print(f"         → {it['status']} {it['body']}")
    bad = sum(len(v) for k, v in buckets.items() if k != "exists")
    if not bad:
        print(f"{total} 條路徑全部存在。")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
