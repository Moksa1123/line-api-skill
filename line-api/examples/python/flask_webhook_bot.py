#!/usr/bin/env python3
"""
最小但正確的 LINE Bot webhook server（Flask）

示範四件最容易做錯的事：
  1. 用「原始 request body」驗證 x-line-signature
  2. 先回 200，再非同步處理
  3. 用 webhookEventId 做冪等去重（LINE 會重送）
  4. replyToken 只能用一次、1 分鐘內有效

執行：
    pip install flask
    export LINE_CHANNEL_SECRET=...
    export LINE_CHANNEL_ACCESS_TOKEN=...
    python flask_webhook_bot.py
    ngrok http 3000     # 把 https://xxx.ngrok-free.app/callback 設進 Console

文件：https://developers.line.biz/en/docs/messaging-api/building-bot/
"""
import base64
import hashlib
import hmac
import json
import os
import queue
import threading
import urllib.error
import urllib.request

from flask import Flask, abort, request

CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]
CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
API = "https://api.line.me"

app = Flask(__name__)

# 正式環境請換成 Redis / 資料庫的 unique index
_seen_lock = threading.Lock()
_seen_events: set[str] = set()
_work: "queue.Queue[dict]" = queue.Queue()


# --------------------------------------------------------------------------
def verify_signature(body: bytes, signature: str) -> bool:
    """Base64(HMAC-SHA256(channel secret, raw body)) == x-line-signature"""
    expected = base64.b64encode(
        hmac.new(CHANNEL_SECRET.encode("utf-8"), body, hashlib.sha256).digest()
    ).decode("ascii")
    return hmac.compare_digest(expected, signature or "")


def call(method: str, path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload else None
    req = urllib.request.Request(
        API + path,
        data=data,
        headers={
            "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        # 400 Invalid reply token 等錯誤要記下來，不要讓 worker 掛掉
        app.logger.error("LINE API %s %s -> %s %s",
                         method, path, e.code, e.read().decode("utf-8", "replace"))
        return {}


def reply(reply_token: str, messages: list) -> None:
    call("POST", "/v2/bot/message/reply",
         {"replyToken": reply_token, "messages": messages})


def push(to: str, messages: list) -> None:
    call("POST", "/v2/bot/message/push", {"to": to, "messages": messages})


# --------------------------------------------------------------------------
def handle_event(event: dict) -> None:
    etype = event.get("type")
    source = event.get("source", {})
    reply_token = event.get("replyToken")

    if etype == "follow":
        reply(reply_token, [{
            "type": "text",
            "text": "感謝加入好友！輸入「選單」看看可以做什麼。",
            "quickReply": {"items": [
                {"type": "action", "action": {"type": "message", "label": "選單", "text": "選單"}},
            ]},
        }])
        return

    if etype == "message" and event["message"]["type"] == "text":
        text = event["message"]["text"].strip()

        if text == "選單":
            reply(reply_token, [_menu_flex()])
        else:
            reply(reply_token, [{"type": "text", "text": f"你說了：{text}"}])
        return

    if etype == "postback":
        data = event["postback"]["data"]
        reply(reply_token, [{"type": "text", "text": f"收到 postback：{data}"}])
        return

    if etype == "join":
        reply(reply_token, [{"type": "text", "text": "大家好，我來了！"}])
        return

    # unfollow / leave 沒有 replyToken，只能記錄
    if etype in ("unfollow", "leave"):
        app.logger.info("%s from %s", etype, source)


def _menu_flex() -> dict:
    return {
        "type": "flex",
        "altText": "服務選單",
        "contents": {
            "type": "bubble",
            "body": {
                "type": "box", "layout": "vertical", "spacing": "md",
                "contents": [
                    {"type": "text", "text": "服務選單", "weight": "bold", "size": "xl"},
                    {"type": "separator"},
                    {"type": "text", "text": "請選擇要辦理的項目", "wrap": True,
                     "color": "#666666", "size": "sm"},
                ],
            },
            "footer": {
                "type": "box", "layout": "vertical", "spacing": "sm",
                "contents": [
                    {"type": "button", "style": "primary", "height": "sm",
                     "action": {"type": "postback", "label": "查詢訂單",
                                "data": "action=orders", "displayText": "查詢訂單"}},
                    {"type": "button", "style": "secondary", "height": "sm",
                     "action": {"type": "postback", "label": "聯絡客服",
                                "data": "action=support", "displayText": "聯絡客服"}},
                ],
            },
        },
    }


def worker() -> None:
    while True:
        event = _work.get()
        try:
            handle_event(event)
        except Exception:
            app.logger.exception("處理 webhook 事件失敗")
        finally:
            _work.task_done()


threading.Thread(target=worker, daemon=True).start()


# --------------------------------------------------------------------------
@app.post("/callback")
def callback():
    body = request.get_data()                      # ← 必須是原始 bytes
    signature = request.headers.get("x-line-signature", "")

    if not verify_signature(body, signature):
        abort(400, "invalid signature")

    payload = json.loads(body.decode("utf-8"))

    for event in payload.get("events", []):
        event_id = event.get("webhookEventId")
        with _seen_lock:
            if event_id in _seen_events:
                continue                            # 重送，略過
            _seen_events.add(event_id)
        if event.get("mode") == "standby":
            continue                                # module 待命中，不要回覆
        _work.put(event)

    return "OK", 200                                # 先回 200，處理在背景


@app.get("/health")
def health():
    return {"ok": True}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 3000)))
