# 程式碼範例

所有範例都可直接執行，且都通過 `scripts/test_line.py` 的語法與 JSON 驗證。

| 檔案 | 語言 | 內容 |
|---|---|---|
| [examples/python/flask_webhook_bot.py](examples/python/flask_webhook_bot.py) | Python | 完整 webhook server：簽章驗證、先回 200、冪等去重、reply / Flex / quick reply |
| [examples/python/push_and_flex.py](examples/python/push_and_flex.py) | Python | push / multicast / broadcast，內建離線驗證 |
| [examples/python/rich_menu_setup.py](examples/python/rich_menu_setup.py) | Python | 建立可切換的雙頁圖文選單（含 alias + richmenuswitch） |
| [examples/nodejs/express_webhook_bot.js](examples/nodejs/express_webhook_bot.js) | Node.js | Express webhook（`express.raw()` 取原始 body） |
| [examples/php/webhook_bot.php](examples/php/webhook_bot.php) | PHP | 純 PHP webhook，適合放進 WordPress / WooCommerce |
| [examples/liff/index.html](examples/liff/index.html) | HTML/JS | LIFF app：登入、profile、ID token、sendMessages、掃碼 |
| [examples/flex/*.json](examples/flex/) | JSON | 訂單明細、商品輪播、預約確認三種 Flex 版型 |

---

## 0. 先查再寫

動手前先查資料庫，不要憑印象寫 LINE 的規格。25 個搜尋域涵蓋端點、欄位、
回應、錯誤、限制、術語、FAQ 到 URL scheme。

```bash
python scripts/search.py --stats                       # 有哪些資料
python scripts/search.py "<關鍵字>"                     # 自動判斷域
python scripts/search.py "<關鍵字>" --domain all        # 不確定時全域找
```

常見問題該查哪個域：

| 想知道 | 指令 |
|---|---|
| 這支 API 怎麼呼叫 | `search.py "send push message" --domain endpoint` |
| 這個欄位有什麼限制 | `search.py "chatBarText" --domain parameter` |
| **這支 API 回什麼** | `search.py "get bot info" --domain response` |
| Flex 某屬性可用值 | `search.py "aspectMode" --domain flex` |
| webhook 事件有哪些欄位 | `search.py "postback" --domain webhook_field` |
| 這個 LIFF API 要幾版 | `search.py "scanCodeV2" --domain liff` |
| 該讀哪一頁官方指南 | `search.py "圖文選單怎麼切換" --domain guide` |
| 官方 FAQ 有沒有答過 | `search.py "429" --domain faq` |
| 加好友連結怎麼寫 | `search.py "加好友" --domain url_scheme` |
| **既有程式碼哪裡不對** | `review.py app.py` |
| 這個名詞是什麼 | `search.py "provider" --domain term` |
| 這個功能還能用嗎 | `search.py "notify" --domain deprecation` |
| iOS/Android SDK 型別 | `search.py "LoginManager" --domain sdk_api` |

中文查詢會自動補上英文術語（130 條對照），所以「圖文選單」查得到 `richmenu`。

---

## 1. 驗證 webhook 簽章

三種語言的正確寫法，關鍵都是「用原始 body」。

**Python（Flask）**

```python
import base64, hashlib, hmac
from flask import request, abort

def verify(body: bytes, signature: str) -> bool:
    expected = base64.b64encode(
        hmac.new(CHANNEL_SECRET.encode(), body, hashlib.sha256).digest()
    ).decode()
    return hmac.compare_digest(expected, signature or "")

@app.post("/callback")
def callback():
    body = request.get_data()                      # ← 原始 bytes
    if not verify(body, request.headers.get("x-line-signature", "")):
        abort(400)
    ...
```

**Node.js（Express）**

```js
app.post("/callback", express.raw({ type: "application/json" }), (req, res) => {
  const expected = crypto.createHmac("sha256", CHANNEL_SECRET)
    .update(req.body)                              // ← Buffer，不是物件
    .digest("base64");
  if (expected !== req.get("x-line-signature")) return res.status(400).end();
  ...
});
```

**PHP**

```php
$rawBody = file_get_contents('php://input');       // ← 不要用 $_POST
$expected = base64_encode(hash_hmac('sha256', $rawBody, $channelSecret, true));
if (!hash_equals($expected, $_SERVER['HTTP_X_LINE_SIGNATURE'] ?? '')) {
    http_response_code(400);
    exit;
}
```

用 skill 內建工具直接測：

```bash
python scripts/signature.py sign --secret testsecret --body '{"events":[]}'
python scripts/signature.py verify --secret testsecret --body '{"events":[]}' --signature <上一行的輸出>
```

---

## 2. 回覆訊息

```python
import json, urllib.request

def reply(reply_token, messages, token):
    req = urllib.request.Request(
        "https://api.line.me/v2/bot/message/reply",
        data=json.dumps({"replyToken": reply_token, "messages": messages},
                        ensure_ascii=False).encode(),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read()
```

`messages` 最多 5 個物件；replyToken 只能用一次、1 分鐘內。

---

## 3. Flex Message

直接套用現成版型：

```bash
python scripts/validate.py examples/flex/order-receipt.json --as flex
python scripts/lineapi.py push U1234... --json examples/flex/order-receipt.json
```

包成訊息物件：

```python
message = {
    "type": "flex",
    "altText": "訂單 A2026-0821 已出貨",     # 通知列文字，最多 1500 字
    "contents": json.load(open("examples/flex/order-receipt.json", encoding="utf-8")),
}
```

自己組的時候，最容易漏的三件事：

```jsonc
{ "type": "box", "layout": "vertical", "contents": [] }   // layout 必填
{ "type": "text", "text": "長文字", "wrap": true }         // 不設 wrap 不會換行
// carousel 最多 12 個 bubble
```

---

## 4. Quick Reply

```json
{
  "type": "text",
  "text": "請選擇",
  "quickReply": { "items": [
    { "type": "action", "action": { "type": "message", "label": "訂位", "text": "訂位" } },
    { "type": "action", "action": { "type": "postback", "label": "查訂單", "data": "action=orders" } },
    { "type": "action", "action": { "type": "datetimepicker", "label": "選日期", "data": "action=book", "mode": "date" } },
    { "type": "action", "action": { "type": "camera", "label": "拍照" } },
    { "type": "action", "action": { "type": "location", "label": "傳位置" } }
  ]}
}
```

最多 13 個；`camera` / `cameraRoll` / `location` 只能放在 quick reply。

---

## 5. 圖文選單

```bash
export LINE_CHANNEL_ACCESS_TOKEN=...
python examples/python/rich_menu_setup.py menu_a.jpg menu_b.jpg
```

手動流程：

```bash
# 1. 建立
python scripts/lineapi.py raw POST /v2/bot/richmenu --json richmenu.json
# 2. 上傳圖片（自動打 api-data.line.me，並先檢查格式與大小）
python scripts/lineapi.py richmenu-upload richmenu-abc123 menu.jpg
# 3. 設為預設
python scripts/lineapi.py raw POST /v2/bot/user/all/richmenu/richmenu-abc123
```

---

## 6. Channel access token

**Stateless（推薦，15 分鐘、不限發行數）**

```bash
python scripts/signature.py stateless --channel-id 1234567890 --channel-secret <secret>
```

```python
import json, urllib.parse, urllib.request

def stateless_token(channel_id, channel_secret):
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": channel_id,
        "client_secret": channel_secret,
    }).encode()
    req = urllib.request.Request(
        "https://api.line.me/oauth2/v3/token", data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())["access_token"]
```

**v2.1 JWT（可自訂效期、可撤銷）**

```bash
python scripts/signature.py token --jwk private.key --channel-id 1234567890 --kid <kid>
```

---

## 7. LINE Login 後端換 token

```python
import json, urllib.parse, urllib.request

def exchange_code(code, redirect_uri, channel_id, channel_secret):
    data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": channel_id,
        "client_secret": channel_secret,
    }).encode()
    req = urllib.request.Request(
        "https://api.line.me/oauth2/v2.1/token", data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())      # access_token / id_token / refresh_token
```

**驗證 ID token（拿到可信的 userId）**

```python
def verify_id_token(id_token, channel_id, nonce=None):
    form = {"id_token": id_token, "client_id": channel_id}
    if nonce:
        form["nonce"] = nonce
    req = urllib.request.Request(
        "https://api.line.me/oauth2/v2.1/verify",
        data=urllib.parse.urlencode(form).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        payload = json.loads(r.read())
    return payload["sub"]                # ← 這才是可信的 userId
```

前端 LIFF 傳來的 `userId` 可被竄改，一律用 ID token 驗證後的 `sub`。

---

## 8. 下載使用者傳來的圖片

```bash
python scripts/lineapi.py content <messageId> --out photo.jpg
```

```python
# 注意網域是 api-data.line.me
url = f"https://api-data.line.me/v2/bot/message/{message_id}/content"
req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
with urllib.request.urlopen(req, timeout=60) as r:
    open("photo.jpg", "wb").write(r.read())
```

---

## 9. 從 LINE Notify 遷移

LINE Notify 已於 **2025-03-31** 終止服務。

| Notify 的做法 | 現在的做法 |
|---|---|
| `POST https://notify-api.line.me/api/notify`，帶使用者的 Notify token | `POST https://api.line.me/v2/bot/message/push`，帶 channel access token + userId |
| 使用者到 Notify 網站授權 | 使用者必須**加官方帳號好友**，你在 `follow` webhook 事件取得 userId |
| 群組通知靠 Notify 加入群組 | 把官方帳號加入群組，用 `join` 事件取得 groupId，push 到 groupId |
| 不需要 webhook server | 要取得 userId 就需要 webhook（或用 LINE Login / LIFF 取得） |

如果對象**無法要求加好友**，唯一合規途徑是
**LINE 通知訊息（LINE notification messages）**，用手機號碼發送，
但需向 LINE 業務申請開通。

```bash
python scripts/search.py "notify" --domain deprecation
python scripts/search.py "LINE 通知訊息" --domain product
```

---

## 10. 審既有的程式碼

接手別人的 LINE 整合、或使用者問「我這樣寫對不對」時，先用資料集審一遍，
不要憑印象猜。`review.py` 會逐條比對官方規格：

```bash
python scripts/review.py ./src
python scripts/review.py app.py --min-severity error    # 只看必須修的
python scripts/review.py ./src --format json            # 給 CI 接
```

實際輸出長這樣：

```
❌ [signature-body] app.py:14
     用序列化後的 JSON 算簽章，空白或欄位順序一變就驗不過
     建議：拿原始 bytes 算（Flask: request.get_data()｜Express: express.raw()）
     依據：https://developers.line.biz/en/docs/messaging-api/verify-webhook-signature/

❌ [wrong-host] app.py:29
     /v2/bot/message/{}/content 是內容類端點，必須用 api-data.line.me
     建議：把主機改成 https://api-data.line.me

⚠️  [message-json] app.py:21
     內嵌的 訊息 $.quickreply：未知屬性 'quickreply'（可用：emojis, quickReply, ...）
```

沒問題就一筆都不報。判定不了的（例如主機放在變數裡）只會給 `info`，
不會硬說它是錯的。完整規則表在 [SKILL.md](SKILL.md#scriptsreviewpy--既有程式碼健檢)。

---

## 11. 除錯速查

```bash
python scripts/search.py "Invalid reply token" --domain error
python scripts/search.py "簽章" --domain troubleshoot
python scripts/search.py "429" --domain error --max 5
python scripts/lineapi.py info        # 確認 token 有效、看得到 bot 資訊
python scripts/lineapi.py webhook-get # 確認 webhook endpoint 設定與 active 狀態
python scripts/test_line.py --live    # 端到端檢查
```
