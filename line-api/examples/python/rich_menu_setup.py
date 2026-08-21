#!/usr/bin/env python3
"""
建立一組可切換的雙頁圖文選單（rich menu A ⇄ B）

流程：
  1. 建立 rich menu A / B
  2. 上傳圖片（注意：api-data.line.me）
  3. 建立 alias（menu-a / menu-b）
  4. 把 A 設為預設選單
之後使用者點「切換」區塊會觸發 richmenuswitch action，即時換頁。

執行：
    export LINE_CHANNEL_ACCESS_TOKEN=...
    python rich_menu_setup.py menu_a.jpg menu_b.jpg

圖片規格：JPEG/PNG、寬 800–2500、高 ≥250、寬高比 ≥1.45、≤1MB
文件：https://developers.line.biz/en/docs/messaging-api/switch-rich-menus/
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
API = "https://api.line.me"
API_DATA = "https://api-data.line.me"          # 內容類端點在不同網域

WIDTH, HEIGHT = 2500, 843                      # 小型選單；請與實際圖片一致


def call(method, url, payload=None, raw=None, content_type="application/json"):
    if raw is not None:
        data, ctype = raw, content_type
    elif payload is not None:
        data, ctype = json.dumps(payload).encode(), "application/json"
    else:
        data, ctype = None, "application/json"
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": ctype},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{method} {url}\nHTTP {e.code}: {e.read().decode('utf-8', 'replace')}")


def menu_object(name: str, chat_bar_text: str, switch_to_alias: str) -> dict:
    """三個功能區塊 + 一個切換區塊。"""
    quarter = WIDTH // 4
    return {
        "size": {"width": WIDTH, "height": HEIGHT},
        "selected": True,
        "name": name,                       # 後台辨識用，最多 300 字
        "chatBarText": chat_bar_text,       # 使用者看得到，最多 14 字
        "areas": [
            {"bounds": {"x": 0, "y": 0, "width": quarter, "height": HEIGHT},
             "action": {"type": "postback", "label": "查訂單",
                        "data": "action=orders", "displayText": "查詢訂單"}},
            {"bounds": {"x": quarter, "y": 0, "width": quarter, "height": HEIGHT},
             "action": {"type": "postback", "label": "會員卡", "data": "action=card"}},
            {"bounds": {"x": quarter * 2, "y": 0, "width": quarter, "height": HEIGHT},
             "action": {"type": "uri", "label": "線上訂購",
                        "uri": "https://example.com/shop"}},
            # 切換到另一頁：richmenuswitch 只能用在圖文選單裡
            {"bounds": {"x": quarter * 3, "y": 0, "width": quarter, "height": HEIGHT},
             "action": {"type": "richmenuswitch", "label": "更多",
                        "richMenuAliasId": switch_to_alias, "data": "switch=" + switch_to_alias}},
        ],
    }


def upload_image(rich_menu_id: str, path: Path) -> None:
    suffix = path.suffix.lower()
    if suffix not in (".jpg", ".jpeg", ".png"):
        raise SystemExit(f"{path} 必須是 JPEG 或 PNG")
    size = path.stat().st_size
    if size > 1024 * 1024:
        raise SystemExit(f"{path} 為 {size/1024/1024:.2f} MB，超過 1 MB 上限")
    call("POST", f"{API_DATA}/v2/bot/richmenu/{rich_menu_id}/content",
         raw=path.read_bytes(),
         content_type="image/png" if suffix == ".png" else "image/jpeg")


def upsert_alias(alias_id: str, rich_menu_id: str) -> None:
    """alias 已存在就更新，不存在就建立。"""
    try:
        call("POST", f"{API}/v2/bot/richmenu/alias",
             {"richMenuAliasId": alias_id, "richMenuId": rich_menu_id})
    except SystemExit as e:
        if "richMenuAliasId is already used" not in str(e) and "409" not in str(e):
            raise
        call("POST", f"{API}/v2/bot/richmenu/alias/{alias_id}",
             {"richMenuId": rich_menu_id})


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("用法：python rich_menu_setup.py menu_a.jpg menu_b.jpg")
    image_a, image_b = Path(sys.argv[1]), Path(sys.argv[2])

    print("1) 建立 rich menu ...")
    menu_a = call("POST", f"{API}/v2/bot/richmenu",
                  menu_object("主選單 A", "開啟選單", "menu-b"))["richMenuId"]
    menu_b = call("POST", f"{API}/v2/bot/richmenu",
                  menu_object("主選單 B", "開啟選單", "menu-a"))["richMenuId"]
    print("   A:", menu_a, "\n   B:", menu_b)

    print("2) 上傳圖片（api-data.line.me）...")
    upload_image(menu_a, image_a)
    upload_image(menu_b, image_b)

    print("3) 建立 alias ...")
    upsert_alias("menu-a", menu_a)
    upsert_alias("menu-b", menu_b)

    print("4) 設為預設選單 ...")
    call("POST", f"{API}/v2/bot/user/all/richmenu/{menu_a}")

    print("\n完成。目前的選單清單：")
    for m in call("GET", f"{API}/v2/bot/richmenu/list").get("richmenus", []):
        print(f"   {m['richMenuId']}  {m['name']}")


if __name__ == "__main__":
    main()
