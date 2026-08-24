#!/usr/bin/env python3
"""實戰問題基準：做 LINE SaaS 真的會問的問題，技能答不答得出來。

## 為什麼要有這支

前面量過的都是「內部一致性」——驗證器與 LINE 官方判斷一致（700 筆）、
搜尋召回率（3500 列）、端點存在（121 條）。那些證明資料是對的，
但沒有回答另一個問題：**有人拿它來做東西時，問得到答案嗎**。

這份題目全部來自兩個真實的 LINE SaaS 專案實際碰到的事：多租戶 webhook
轉發、圖文選單驗證、Flex 組建、LIFF 會員綁定、服務訊息、優惠券、
推播額度。每一題都有一個「答案裡必須出現什麼」的判準——
只有「有回傳結果」不算對，回錯答案跟沒答案一樣糟。

    python tools/benchmark.py            # 跑全部
    python tools/benchmark.py --verbose  # 連答錯的細節一起看
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "line-api" / "scripts"))

import core  # noqa: E402

core.use_utf8_stdout()

# (問題, 答案裡必須出現的字串, 分類)
# 「必須出現」是逐題人工確認過的——不是先跑再抄結果，那樣等於沒有測。
CASES: list[tuple[str, str, str]] = [
    # ---- webhook：多租戶轉發、簽章、重送 ----
    ("webhook 簽章怎麼算", "x-line-signature", "webhook"),
    ("webhook 事件有哪些型別", "postback", "webhook"),
    ("postback 事件有哪些欄位", "postback", "webhook"),
    ("webhookEventId", "webhookEventId", "webhook"),
    ("重送 redelivery", "isRedelivery", "webhook"),
    ("群組事件的 source 有什麼", "groupId", "webhook"),
    ("訊息事件的 quoteToken", "quoteToken", "webhook"),
    ("使用者傳影片來的事件欄位", "contentProvider", "webhook"),

    # ---- 訊息與 Flex ----
    ("文字訊息長度上限", "5000", "message"),
    ("一次最多送幾則訊息", "5", "message"),
    ("quick reply 最多幾個", "13", "message"),
    ("flex carousel 最多幾個 bubble", "12", "flex"),
    ("altText 上限", "1500", "message"),
    ("flex box 的 layout 可以填什麼", "baseline", "flex"),
    ("flex text 的 weight", "bold", "flex"),
    ("aspectMode 可用值", "cover", "flex"),
    ("bubble 的 size 有哪些", "giga", "flex"),
    ("flex button 的 style", "primary", "flex"),
    ("樣板輪播最多幾欄", "10", "message"),
    ("貼圖訊息要什麼欄位", "packageId", "message"),

    # ---- 圖文選單 ----
    ("圖文選單 chatBarText 上限", "14", "richmenu"),
    ("圖文選單最多幾個區域", "20", "richmenu"),
    ("圖文選單圖片尺寸", "2500", "richmenu"),
    ("richmenu alias", "richMenuAliasId", "richmenu"),
    ("圖文選單圖片上傳要打哪個主機", "api-data.line.me", "endpoint"),

    # ---- 端點與額度 ----
    ("push message 端點", "/v2/bot/message/push", "endpoint"),
    ("multicast 一次最多幾個 userId", "500", "endpoint"),
    ("narrowcast", "narrowcast", "endpoint"),
    ("怎麼查本月推播額度", "quota", "endpoint"),
    ("取得使用者 profile", "/v2/bot/profile/", "endpoint"),
    ("下載使用者傳來的圖片", "content", "endpoint"),
    ("retry key 冪等", "X-Line-Retry-Key", "endpoint"),
    ("audience 受眾", "audienceGroup", "endpoint"),

    # ---- 錯誤與疑難 ----
    ("429 是什麼意思", "rate limit", "error"),
    ("replyToken 過期", "reply", "trouble"),
    ("簽章驗證一直失敗", "body", "trouble"),

    # ---- LIFF ----
    ("liff 取得 ID token", "getIDToken", "liff"),
    ("liff 分享訊息給好友", "shareTargetPicker", "liff"),
    ("shareTargetPicker 需要哪個 LINE 版本", "10.3.0", "liff"),
    ("scanCodeV2 的版本需求", "11.7.0", "liff"),
    ("liff init 會有哪些錯誤", "INIT_FAILED", "error"),
    ("liff 外掛怎麼寫", "liff.use", "liff"),
    ("liff 取得使用者資料要什麼權限", "profile", "liff"),

    # ---- LINE Login / ID token ----
    ("驗證 ID token 的端點", "/oauth2/v2.1/verify", "endpoint"),
    ("channel access token 怎麼發", "token", "endpoint"),
    ("stateless token 效期", "15", "token"),

    # ---- MINI App ----
    ("服務訊息一次能發幾則", "5", "miniapp"),
    ("服務訊息範本上限", "20", "miniapp"),
    ("服務通知權杖效期", "31,536,000", "miniapp"),
    ("mini app 自訂路徑要驗證嗎", "Custom Path", "miniapp"),
    ("台灣的 mini app 能用站內購買嗎", "In-app purchase", "miniapp"),
    ("mini app 送審要檢查什麼", "review", "miniapp"),

    # ---- 已淘汰 ----
    ("LINE Notify 還能用嗎", "LINE Notify", "deprecation"),
    ("line:// 還能用嗎", "line://", "deprecation"),
    ("liff.scanCode 還能用嗎", "scanCodeV2", "deprecation"),
]


def answer_blob(query: str, top: int = 5) -> str:
    """把前 N 名的所有欄位串起來當作「技能給的答案」。"""
    parts = []
    for hit in core.search(query, max_results=top):
        parts.append(" ".join(str(v) for k, v in hit.items() if not k.startswith("_")))
    return " | ".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--top", type=int, default=5)
    args = ap.parse_args()

    by_cat: dict[str, list[bool]] = {}
    wrong = []
    for query, expect, cat in CASES:
        blob = answer_blob(query, args.top)
        ok = expect.lower() in blob.lower()
        by_cat.setdefault(cat, []).append(ok)
        if not ok:
            wrong.append((query, expect, blob[:150]))

    total = len(CASES)
    hit = sum(1 for v in by_cat.values() for x in v if x)
    print(f"{total} 個實戰問題，前 {args.top} 名內答對 {hit}")
    print(f"準確率 {hit / total * 100:.1f}%\n")
    print(f"{'分類':14} {'答對':>6} {'題數':>6}")
    for cat, results in sorted(by_cat.items()):
        n = len(results)
        k = sum(results)
        mark = "" if k == n else "  ←"
        print(f"  {cat:12} {k:6} {n:6}{mark}")
    if wrong:
        print(f"\n答不出來的 {len(wrong)} 題：")
        for q, e, blob in wrong:
            print(f"\n  ✗ {q!r}  找不到 {e!r}")
            if args.verbose:
                print(f"     實得：{blob}")
    return 0 if hit == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
