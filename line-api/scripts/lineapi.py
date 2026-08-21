#!/usr/bin/env python3
"""
LINE API skill — dependency-free Messaging API client + CLI.

Only the standard library, so it runs anywhere Python 3.9+ runs. Every call
routes to the right host automatically: content endpoints live on
api-data.line.me, everything else on api.line.me.

Credentials are read from the environment (or --token):
    LINE_CHANNEL_ACCESS_TOKEN   channel access token
    LINE_CHANNEL_SECRET         channel secret (webhook signature)
    LINE_CHANNEL_ID             channel ID (stateless token issuing)

CLI examples
    python scripts/lineapi.py info
    python scripts/lineapi.py quota
    python scripts/lineapi.py profile U1234...
    python scripts/lineapi.py push U1234... --text "Hello"
    python scripts/lineapi.py push U1234... --json message.json
    python scripts/lineapi.py validate-push --json message.json
    python scripts/lineapi.py richmenu-list
    python scripts/lineapi.py webhook-get
    python scripts/lineapi.py webhook-set https://example.com/callback
    python scripts/lineapi.py raw GET /v2/bot/followers/ids
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import load_dotenv, use_utf8_stdout  # noqa: E402

use_utf8_stdout()
load_dotenv()

API = "https://api.line.me"
API_DATA = "https://api-data.line.me"

# Paths that must be called on api-data.line.me instead of api.line.me.
# Source: https://developers.line.biz/en/reference/messaging-api/#domain-name
DATA_PATHS = (
    "/v2/bot/message/{messageId}/content",
    "/v2/bot/audienceGroup/upload/byFile",
    "/v2/bot/richmenu/{richMenuId}/content",
)


class LineApiError(Exception):
    def __init__(self, status: int, body: str, url: str):
        self.status, self.body, self.url = status, body, url
        detail = body
        try:
            parsed = json.loads(body)
            detail = parsed.get("message", body)
            for d in parsed.get("details") or []:
                detail += f"\n  - {d.get('property', '')}: {d.get('message', '')}"
        except Exception:
            pass
        super().__init__(f"HTTP {status} on {url}\n{detail}")


def host_for(path: str) -> str:
    """api-data.line.me for content endpoints, api.line.me otherwise."""
    if "/content" in path and ("/message/" in path or "/richmenu/" in path):
        return API_DATA
    if path.startswith("/v2/bot/audienceGroup/upload/byFile"):
        return API_DATA
    return API


class LineClient:
    def __init__(self, token: str | None = None, timeout: int = 30):
        self.token = token or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
        if not self.token:
            raise SystemExit(
                "缺少 channel access token。\n"
                "  設定環境變數：LINE_CHANNEL_ACCESS_TOKEN=...\n"
                "  或加參數：--token <token>"
            )
        self.timeout = timeout

    # ------------------------------------------------------------------ core
    def request(self, method: str, path: str, body=None, query: dict | None = None,
                content_type: str = "application/json", raw_body: bytes | None = None,
                retry_key: str | None = None):
        url = host_for(path) + path
        if query:
            url += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})

        headers = {"Authorization": "Bearer " + self.token}
        data = None
        if raw_body is not None:
            data = raw_body
            headers["Content-Type"] = content_type
        elif body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if retry_key:
            headers["X-Line-Retry-Key"] = retry_key

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                payload = r.read()
                ctype = r.headers.get("Content-Type", "")
                if "application/json" in ctype:
                    return json.loads(payload.decode("utf-8")) if payload else {}
                return payload
        except urllib.error.HTTPError as e:
            raise LineApiError(e.code, e.read().decode("utf-8", "replace"), url) from None

    # --------------------------------------------------------------- channel
    def bot_info(self):
        return self.request("GET", "/v2/bot/info")

    def quota(self):
        return self.request("GET", "/v2/bot/message/quota")

    def quota_consumption(self):
        return self.request("GET", "/v2/bot/message/quota/consumption")

    def get_webhook_endpoint(self):
        return self.request("GET", "/v2/bot/channel/webhook/endpoint")

    def set_webhook_endpoint(self, endpoint: str):
        return self.request("PUT", "/v2/bot/channel/webhook/endpoint", {"endpoint": endpoint})

    def test_webhook_endpoint(self, endpoint: str | None = None):
        return self.request("POST", "/v2/bot/channel/webhook/test",
                            {"endpoint": endpoint} if endpoint else {})

    # -------------------------------------------------------------- messages
    def reply(self, reply_token: str, messages: list, notification_disabled: bool = False):
        return self.request("POST", "/v2/bot/message/reply", {
            "replyToken": reply_token,
            "messages": messages,
            "notificationDisabled": notification_disabled,
        })

    def push(self, to: str, messages: list, retry_key: str | None = None,
             notification_disabled: bool = False):
        return self.request("POST", "/v2/bot/message/push", {
            "to": to, "messages": messages, "notificationDisabled": notification_disabled,
        }, retry_key=retry_key)

    def multicast(self, to: list, messages: list, retry_key: str | None = None):
        return self.request("POST", "/v2/bot/message/multicast",
                            {"to": to, "messages": messages}, retry_key=retry_key)

    def broadcast(self, messages: list, retry_key: str | None = None):
        return self.request("POST", "/v2/bot/message/broadcast",
                            {"messages": messages}, retry_key=retry_key)

    def validate_push(self, messages: list):
        return self.request("POST", "/v2/bot/message/validate/push", {"messages": messages})

    def validate_reply(self, messages: list):
        return self.request("POST", "/v2/bot/message/validate/reply", {"messages": messages})

    def message_content(self, message_id: str) -> bytes:
        return self.request("GET", f"/v2/bot/message/{message_id}/content")

    def show_loading(self, chat_id: str, seconds: int = 20):
        return self.request("POST", "/v2/bot/chat/loading/start",
                            {"chatId": chat_id, "loadingSeconds": seconds})

    # --------------------------------------------------------------- profile
    def profile(self, user_id: str):
        return self.request("GET", f"/v2/bot/profile/{user_id}")

    def followers(self, limit: int = 300, start: str | None = None):
        return self.request("GET", "/v2/bot/followers/ids", query={"limit": limit, "start": start})

    def group_summary(self, group_id: str):
        return self.request("GET", f"/v2/bot/group/{group_id}/summary")

    # -------------------------------------------------------------- richmenu
    def richmenu_list(self):
        return self.request("GET", "/v2/bot/richmenu/list")

    def richmenu_create(self, richmenu: dict):
        return self.request("POST", "/v2/bot/richmenu", richmenu)

    def richmenu_delete(self, rich_menu_id: str):
        return self.request("DELETE", f"/v2/bot/richmenu/{rich_menu_id}")

    def richmenu_upload(self, rich_menu_id: str, image_path: str):
        """Upload the menu image. Goes to api-data.line.me, not api.line.me."""
        path = Path(image_path)
        suffix = path.suffix.lower()
        if suffix not in (".jpg", ".jpeg", ".png"):
            raise SystemExit("圖文選單圖片必須是 JPEG 或 PNG")
        size = path.stat().st_size
        if size > 1024 * 1024:
            raise SystemExit(f"圖片 {size/1024/1024:.2f} MB 超過 1 MB 上限")
        ctype = "image/png" if suffix == ".png" else "image/jpeg"
        return self.request("POST", f"/v2/bot/richmenu/{rich_menu_id}/content",
                            raw_body=path.read_bytes(), content_type=ctype)

    def richmenu_set_default(self, rich_menu_id: str):
        return self.request("POST", f"/v2/bot/user/all/richmenu/{rich_menu_id}")

    def richmenu_link_user(self, user_id: str, rich_menu_id: str):
        return self.request("POST", f"/v2/bot/user/{user_id}/richmenu/{rich_menu_id}")

    # --------------------------------------------------------------- insight
    def insight_followers(self, date: str):
        return self.request("GET", "/v2/bot/insight/followers", query={"date": date})

    def insight_demographic(self):
        return self.request("GET", "/v2/bot/insight/demographic")


# --------------------------------------------------------------------------
def _load_messages(args) -> list:
    if args.text:
        return [{"type": "text", "text": args.text}]
    if args.json:
        raw = sys.stdin.read() if args.json == "-" else Path(args.json).read_text(encoding="utf-8")
        data = json.loads(raw)
        return data if isinstance(data, list) else [data]
    raise SystemExit("請提供 --text 或 --json")


def _print(value) -> None:
    if isinstance(value, (bytes, bytearray)):
        sys.stdout.buffer.write(value)
        return
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main() -> int:
    ap = argparse.ArgumentParser(description="LINE Messaging API 無依賴用戶端")
    ap.add_argument("--token", help="channel access token（預設讀 LINE_CHANNEL_ACCESS_TOKEN）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", help="GET /v2/bot/info")
    sub.add_parser("quota", help="GET /v2/bot/message/quota")
    sub.add_parser("consumption", help="GET /v2/bot/message/quota/consumption")
    sub.add_parser("webhook-get", help="GET webhook endpoint")
    sub.add_parser("richmenu-list", help="GET /v2/bot/richmenu/list")
    sub.add_parser("followers", help="GET /v2/bot/followers/ids")

    p = sub.add_parser("webhook-set")
    p.add_argument("endpoint")
    p = sub.add_parser("webhook-test")
    p.add_argument("endpoint", nargs="?")

    p = sub.add_parser("profile")
    p.add_argument("user_id")

    for name in ("push", "validate-push", "validate-reply"):
        p = sub.add_parser(name)
        if name == "push":
            p.add_argument("to")
            p.add_argument("--retry-key")
        p.add_argument("--text")
        p.add_argument("--json")

    p = sub.add_parser("multicast")
    p.add_argument("user_ids", help="逗號分隔，最多 500 個")
    p.add_argument("--text")
    p.add_argument("--json")

    p = sub.add_parser("broadcast")
    p.add_argument("--text")
    p.add_argument("--json")

    p = sub.add_parser("content", help="下載使用者傳來的圖片/影片/音訊")
    p.add_argument("message_id")
    p.add_argument("--out", required=True)

    p = sub.add_parser("richmenu-upload")
    p.add_argument("rich_menu_id")
    p.add_argument("image")

    p = sub.add_parser("raw", help="呼叫任意端點")
    p.add_argument("method", choices=["GET", "POST", "PUT", "DELETE"])
    p.add_argument("path")
    p.add_argument("--json")

    args = ap.parse_args()
    client = LineClient(args.token)

    try:
        if args.cmd == "info":
            _print(client.bot_info())
        elif args.cmd == "quota":
            _print(client.quota())
        elif args.cmd == "consumption":
            _print(client.quota_consumption())
        elif args.cmd == "webhook-get":
            _print(client.get_webhook_endpoint())
        elif args.cmd == "webhook-set":
            _print(client.set_webhook_endpoint(args.endpoint))
        elif args.cmd == "webhook-test":
            _print(client.test_webhook_endpoint(args.endpoint))
        elif args.cmd == "profile":
            _print(client.profile(args.user_id))
        elif args.cmd == "followers":
            _print(client.followers())
        elif args.cmd == "push":
            _print(client.push(args.to, _load_messages(args), retry_key=args.retry_key))
        elif args.cmd == "multicast":
            ids = [u.strip() for u in args.user_ids.split(",") if u.strip()]
            _print(client.multicast(ids, _load_messages(args)))
        elif args.cmd == "broadcast":
            _print(client.broadcast(_load_messages(args)))
        elif args.cmd == "validate-push":
            _print(client.validate_push(_load_messages(args)) or {"result": "valid"})
        elif args.cmd == "validate-reply":
            _print(client.validate_reply(_load_messages(args)) or {"result": "valid"})
        elif args.cmd == "content":
            data = client.message_content(args.message_id)
            Path(args.out).write_bytes(data)
            print(f"已寫入 {args.out}（{len(data)} bytes）")
        elif args.cmd == "richmenu-list":
            _print(client.richmenu_list())
        elif args.cmd == "richmenu-upload":
            _print(client.richmenu_upload(args.rich_menu_id, args.image))
        elif args.cmd == "raw":
            body = json.loads(Path(args.json).read_text(encoding="utf-8")) if args.json else None
            _print(client.request(args.method, args.path, body))
    except LineApiError as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
