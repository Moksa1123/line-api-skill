#!/usr/bin/env python3
"""
主動發訊：push / multicast / broadcast，以及組 Flex Message 與 quick reply。

執行：
    export LINE_CHANNEL_ACCESS_TOKEN=...
    python push_and_flex.py --to U1234567890abcdef... --demo order
    python push_and_flex.py --dry-run --demo picker      # 只印出 JSON，不送出

送出前一律先跑 scripts/validate.py 檢查，避免浪費訊息額度。
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

# 讓範例可以直接用 skill 內建的離線驗證器
SKILL = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILL / "scripts"))
import validate as val  # noqa: E402

API = "https://api.line.me"


def call(path: str, payload: dict) -> dict:
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    if not token:
        raise SystemExit("請設定 LINE_CHANNEL_ACCESS_TOKEN")
    req = urllib.request.Request(
        API + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')}")


# --------------------------------------------------------------------------
# 訊息建構
# --------------------------------------------------------------------------
def order_card(order_no: str, total: str, status: str) -> dict:
    """訂單狀態卡片。"""
    def row(label: str, value: str) -> dict:
        return {"type": "box", "layout": "baseline", "spacing": "sm", "contents": [
            {"type": "text", "text": label, "color": "#AAAAAA", "size": "sm", "flex": 2},
            {"type": "text", "text": value, "wrap": True, "size": "sm", "flex": 5},
        ]}

    return {
        "type": "flex",
        "altText": f"訂單 {order_no}：{status}",
        "contents": {
            "type": "bubble",
            "body": {"type": "box", "layout": "vertical", "spacing": "md", "contents": [
                {"type": "text", "text": "訂單通知", "weight": "bold", "size": "xl"},
                {"type": "separator"},
                row("訂單編號", order_no),
                row("金額", total),
                row("狀態", status),
            ]},
            "footer": {"type": "box", "layout": "vertical", "contents": [
                {"type": "button", "style": "primary", "height": "sm", "action": {
                    "type": "uri", "label": "查看訂單",
                    "uri": f"https://example.com/orders/{order_no}"}},
            ]},
        },
    }


def picker() -> dict:
    """帶 quick reply 的文字訊息（最多 13 個按鈕）。"""
    return {
        "type": "text",
        "text": "請選擇要辦理的項目：",
        "quickReply": {"items": [
            {"type": "action", "action": {
                "type": "postback", "label": "查訂單", "data": "action=orders",
                "displayText": "查訂單"}},
            {"type": "action", "action": {
                "type": "datetimepicker", "label": "選日期", "data": "action=book",
                "mode": "date"}},
            {"type": "action", "action": {
                "type": "location", "label": "傳送位置"}},
            {"type": "action", "action": {
                "type": "message", "label": "聯絡客服", "text": "客服"}},
        ]},
    }


def coupon_text() -> dict:
    """文字訊息 + LINE emoji（emojis[].index 指向 text 裡的 $）。"""
    return {
        "type": "text",
        "text": "$ 本週會員日 全館 9 折 $",
        "emojis": [
            {"index": 0, "productId": "5ac1bfd5040ab15980c9b435", "emojiId": "001"},
            {"index": 15, "productId": "5ac1bfd5040ab15980c9b435", "emojiId": "002"},
        ],
    }


DEMOS = {
    "order": lambda: [order_card("A2026-0821-0007", "NT$1,280", "已出貨")],
    "picker": lambda: [picker()],
    "coupon": lambda: [coupon_text()],
    "all": lambda: [order_card("A2026-0821-0007", "NT$1,280", "已出貨"), picker()],
}


# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="LINE push / multicast / broadcast 範例")
    ap.add_argument("--demo", choices=list(DEMOS), default="order")
    ap.add_argument("--to", help="單一 userId（push）")
    ap.add_argument("--multicast", help="逗號分隔的 userId，最多 500 個")
    ap.add_argument("--broadcast", action="store_true", help="發給所有好友")
    ap.add_argument("--dry-run", action="store_true", help="只印 JSON 與驗證結果")
    args = ap.parse_args()

    messages = DEMOS[args.demo]()

    # 1. 一律先離線驗證
    result = val.run(messages, "messages")
    errors = [p for p in result.problems if p.level == "error"]
    for p in result.problems:
        print(f"[{p.level}] {p.path}: {p.message}")
    if errors:
        return 1
    print(f"驗證通過：{len(messages)} 則訊息\n")

    print(json.dumps(messages, ensure_ascii=False, indent=2))
    if args.dry_run:
        return 0

    # 2. 送出
    if args.to:
        print("\npush ->", call("/v2/bot/message/push",
                                {"to": args.to, "messages": messages}))
    elif args.multicast:
        ids = [u.strip() for u in args.multicast.split(",") if u.strip()]
        if len(ids) > 500:
            raise SystemExit(f"multicast 一次最多 500 個 userId，目前 {len(ids)} 個")
        print("\nmulticast ->", call("/v2/bot/message/multicast",
                                     {"to": ids, "messages": messages}))
    elif args.broadcast:
        print("\nbroadcast ->", call("/v2/bot/message/broadcast",
                                     {"messages": messages}))
    else:
        print("\n（未指定 --to / --multicast / --broadcast，只做驗證與輸出）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
