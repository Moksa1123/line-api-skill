#!/usr/bin/env python3
"""跑一次 LINE Login，把 ID token 取回來寫進 .env。

## 為什麼需要這支

技能裡其他東西都有外部真值可以對照：訊息與圖文選單送 LINE 官方的驗證
端點、端點路徑用錯的 method 探、LIFF API 對照實際發佈的 SDK。只有
LINE Login 的 ID token 驗證沒有——因為要有一個真的 ID token，而 ID token
只能由使用者實際登入一次才會產生。

這支把 OAuth 2.0 授權碼流程整段跑完：起一個 localhost 伺服器、開瀏覽器、
接住轉回來的 code、換成 token，最後把 id_token 寫進 .env。

## 你要先在 Console 做兩件事

在 LINE Developers Console 選你的 **LINE Login channel**（LIFF app 所屬
的那個，不是 Messaging API channel）：

  1. Basic settings → OpenID Connect → Apply
     沒有這個就不會回 id_token，只會回 access_token。
  2. LINE Login → Callback URL → 加一行 http://localhost:8765/callback
     那個 port 被別的程式佔住的話，用 --port 換一個，
     Console 那邊也多加一行對應的（一個 channel 可以設多個 callback）。

然後把那個 channel 的 ID 與 secret 放進 .env：

    LINE_LOGIN_CHANNEL_ID=...
    LINE_LOGIN_CHANNEL_SECRET=...

## 安全

id_token 是一個代表「某個使用者是誰」的憑證，效期很短。這支不會把它
印在畫面上，只寫進 .env（已在 .gitignore）並顯示解出來的欄位。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import socket
import sys
import time
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "line-api" / "scripts"))

import core  # noqa: E402

core.load_dotenv()
core.use_utf8_stdout()

AUTHORIZE = "https://access.line.me/oauth2/v2.1/authorize"
TOKEN = "https://api.line.me/oauth2/v2.1/token"
VERIFY = "https://api.line.me/oauth2/v2.1/verify"

_result: dict = {}


class Catch(BaseHTTPRequestHandler):
    """只收 LINE 轉回來的那一次。

    localhost 上什麼都可能來敲門——瀏覽器要 favicon、別的程式在輪詢
    （測試機上就有東西一直送 ?v=4.1 過來）。只要是帶參數的請求就收下的話，
    會把那些當成授權回呼，然後說「沒有拿到授權碼」。
    所以路徑要對，而且必須帶 code 或 error。
    """

    def do_GET(self):                                   # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(parsed.query)
        mine = parsed.path.rstrip("/") == "/callback" and ("code" in q or "error" in q)
        if mine:
            _result.update({k: v[0] for k, v in q.items()})
            body = ("完成，可以關掉這個分頁了。" if "code" in q
                    else f"授權沒有成功：{q.get('error_description', q)}")
        else:
            body = "這不是授權回呼，忽略。"
        self.send_response(200 if mine else 404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(f"<meta charset=utf-8><h2>{body}</h2>".encode())

    def log_message(self, *a):                          # 別把 code 印進終端機
        pass


def claims_of(id_token: str) -> dict:
    payload = id_token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--print-token", action="store_true",
                    help="把 id_token 印出來（預設只寫進 .env）")
    args = ap.parse_args()

    cid = os.environ.get("LINE_LOGIN_CHANNEL_ID")
    secret = os.environ.get("LINE_LOGIN_CHANNEL_SECRET")
    if not (cid and secret):
        print(__doc__)
        raise SystemExit("缺少 LINE_LOGIN_CHANNEL_ID 或 LINE_LOGIN_CHANNEL_SECRET")

    redirect = f"http://localhost:{args.port}/callback"
    state = secrets.token_urlsafe(16)
    url = AUTHORIZE + "?" + urllib.parse.urlencode({
        "response_type": "code",
        "client_id": cid,
        "redirect_uri": redirect,
        "state": state,
        # 沒有 openid 就不會回 id_token
        "scope": "openid profile",
    })

    # 先把 port 綁起來再開瀏覽器。反過來的話，使用者已經登入完了才發現
    # 沒人接得住轉回來的授權碼——而授權碼只能用一次。
    try:
        server = HTTPServer(("localhost", args.port), Catch)
    except OSError as e:
        free = []
        for cand in (8080, 8088, 9090, 12345, 23456, 3456, 4567):
            probe = socket.socket()
            try:
                probe.bind(("localhost", cand))
                free.append(cand)
            except OSError:
                pass
            finally:
                probe.close()
        hint = "".join(
            f"  python tools/get_id_token.py --port {c}\n"
            f"      → Callback URL 加 http://localhost:{c}/callback\n"
            for c in free[:3])
        raise SystemExit(
            f"綁不上 localhost:{args.port}（{e}）。\n"
            f"這個 port 被別的程式佔著。改用別的，並在 Console 的 Callback URL\n"
            f"多加一行（LINE 允許一個 channel 設多個 callback）：\n\n" + hint)

    print("在瀏覽器完成登入。沒有自動開啟的話手動貼上：\n")
    print(f"  {url}\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    server.timeout = 20
    # 瀏覽器可能先來要 favicon，所以要收到帶參數的那一次才停。
    # handle_request() 逾時會直接返回，沒有這個上限就會空轉到天荒地老
    deadline = time.time() + 300
    while not _result and time.time() < deadline:
        server.handle_request()
    if not _result:
        raise SystemExit("等了 5 分鐘沒有等到瀏覽器轉回來。"
                         "確認 Callback URL 有加 " + redirect)

    if "code" not in _result:
        raise SystemExit(f"沒有拿到授權碼：{_result}")
    if _result.get("state") != state:
        raise SystemExit("state 對不上，可能不是這次的請求，中止")

    data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": _result["code"],
        "redirect_uri": redirect,
        "client_id": cid,
        "client_secret": secret,
    }).encode()
    req = urllib.request.Request(
        TOKEN, data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        tok = json.loads(r.read())

    idt = tok.get("id_token")
    if not idt:
        raise SystemExit(
            "回應裡沒有 id_token。多半是那個 channel 還沒開 OpenID Connect："
            "Console → Basic settings → OpenID Connect → Apply")

    c = claims_of(idt)
    print("\n拿到了。ID token 的內容：")
    print(f"  iss  {c.get('iss')}")
    print(f"  aud  {c.get('aud')}        （= channel ID）")
    print(f"  sub  {str(c.get('sub'))[:6]}…      （使用者 ID，不完整顯示）")
    print(f"  exp  {c.get('exp')}         （效期 {c.get('exp', 0) - c.get('iat', 0)} 秒）")
    print(f"  name {c.get('name', '(沒有 profile scope)')}")

    env = REPO / ".env"
    lines = env.read_text(encoding="utf-8").splitlines() if env.exists() else []
    lines = [l for l in lines if not l.startswith("LINE_ID_TOKEN=")]
    lines.append(f"LINE_ID_TOKEN={idt}")
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n已寫進 {env}（.gitignore 有擋）。")
    print("接著跑：python line-api/scripts/test_line.py --live")
    if args.print_token:
        print(f"\n{idt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
