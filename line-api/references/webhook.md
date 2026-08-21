# Webhook 接收與簽章驗證

> 官方文件：
> https://developers.line.biz/en/docs/messaging-api/receiving-messages/
> https://developers.line.biz/en/docs/messaging-api/verify-webhook-signature/
> 事件型別完整清單見 `data/webhook-events.csv`（20 種事件 + 7 種訊息子型別）。

## 1. 開通順序（收不到事件幾乎都是這裡沒設好）

1. **LINE Developers Console** → 你的 Messaging API channel → Messaging API 分頁
   - 填入 **Webhook URL**（必須 HTTPS、憑證鏈完整、不接受自簽）
   - 打開 **Use webhook**
2. **LINE Official Account Manager** → 回應設定
   - **關閉**「自動回應訊息」（開著會把訊息吃掉，你的 webhook 收不到）
   - **開啟**「Webhook」

兩個後台都要設，只設一邊是最常見的「webhook 沒反應」原因。

## 2. Request 格式

```
POST /your/callback HTTP/1.1
Content-Type: application/json
x-line-signature: {base64 signature}
User-Agent: LineBotWebhook/2.0

{
  "destination": "U0123456789abcdef...",
  "events": [ { ... }, { ... } ]
}
```

- `destination`：收到這個 webhook 的 bot 自己的 userId。
- `events`：可能一次多筆，也可能是**空陣列**（Console 按 Verify 時就是空的）。

## 3. 簽章驗證（必做）

```
signature = Base64( HMAC-SHA256( channel_secret, raw_request_body ) )
比對 signature 與 x-line-signature 標頭（用 constant-time 比較）
```

**關鍵：一定要用原始 body bytes。** 用框架 parse 過的 JSON 再 `json.dumps()`
會改變空白與鍵順序，簽章永遠對不上。

| 框架 | 取得原始 body |
|---|---|
| Flask | `request.get_data()` |
| FastAPI | `await request.body()` |
| Django | `request.body` |
| Express | `express.raw({type: 'application/json'})`，用 `req.body`（Buffer） |
| Laravel | `$request->getContent()` |
| PHP 原生 | `file_get_contents('php://input')` |

本 skill 附的實作與 CLI：

```bash
python scripts/signature.py sign   --secret <channel secret> --body '{"events":[]}'
python scripts/signature.py verify --secret <channel secret> --body-file body.json --signature <sig>
```

```python
from signature import verify_signature
if not verify_signature(CHANNEL_SECRET, raw_body, request.headers["x-line-signature"]):
    return "", 400
```

LINE **不公開 webhook 來源 IP**，所以不要用 IP 白名單，簽章驗證就是唯一的驗證手段。

## 4. 回應與重送

- 收到後**先回 200**，處理放到背景（queue / thread / task）。
- 沒有及時回 200，LINE 會**重送**同一個 webhook。
- 重送的事件 `webhookEventId` 與原本相同 → 用它做冪等去重
  （寫進 Redis SET NX 或資料庫 unique index）。
- `deliveryContext.isRedelivery = true` 代表這是重送。

```python
if event["deliveryContext"]["isRedelivery"]:
    ...  # 可能已處理過
if not seen.add_if_absent(event["webhookEventId"]):
    return  # 重複，直接略過
```

## 5. 每個事件都有的共同屬性

| 屬性 | 說明 |
|---|---|
| `type` | 事件型別，見下表 |
| `mode` | `active`（正常）/ `standby`（module 待命中，不要回覆） |
| `timestamp` | 事件發生時間（毫秒 UNIX time） |
| `source` | `{ "type": "user"\|"group"\|"room", "userId"/"groupId"/"roomId": ... }` |
| `webhookEventId` | 事件唯一 ID → 冪等去重用 |
| `deliveryContext.isRedelivery` | 是否為重送 |
| `replyToken` | 只有可回覆的事件才有 |

## 6. 事件型別

| type | 何時發生 | 可 reply |
|---|---|---|
| `message` | 使用者傳訊息 | ✅ |
| `messageEdited` | 使用者編輯訊息 | ✅ |
| `unsend` | 使用者收回訊息 | ❌ |
| `follow` | 加好友 / 解除封鎖 | ✅ |
| `unfollow` | 封鎖官方帳號 | ❌ |
| `join` | bot 被加入群組 / 多人聊天室 | ✅ |
| `leave` | bot 被踢出或群組解散 | ❌ |
| `memberJoined` | 有人加入該群組 | ✅ |
| `memberLeft` | 有人離開該群組 | ❌ |
| `postback` | 使用者點了 postback action | ✅ |
| `videoPlayComplete` | 影片訊息播完 | ✅ |
| `beacon` | 進入 LINE Beacon 範圍 | ✅ |
| `accountLink` | 帳號連結完成 | ✅ |
| `membership` | 會員方案訂閱/取消 | ✅ |
| `activated` / `deactivated` | module channel 取得/交還控制權 | ❌ |
| `botSuspended` / `botResumed` | 官方帳號被停權 / 恢復 | ❌ |
| `module` | module channel 掛載/卸載 | ❌ |
| `delivery` | LINE 通知訊息送達回report | ❌ |

`message` 事件的 `message.type` 子型別：
`text` / `image` / `video` / `audio` / `file` / `location` / `sticker`

```bash
python scripts/search.py "postback" --domain webhook
python scripts/search.py "message.image" --domain webhook
```

## 7. 各事件的重點欄位

```jsonc
// message + text
{"type":"message","replyToken":"...","source":{"type":"user","userId":"U..."},
 "message":{"id":"325708","type":"text","text":"Hello",
            "quoteToken":"q...","mention":{"mentionees":[...]}}}

// postback
{"type":"postback","replyToken":"...","postback":{"data":"action=buy&id=1",
 "params":{"date":"2026-08-21"}}}

// follow
{"type":"follow","replyToken":"...","follow":{"isUnblocked":false}}

// beacon
{"type":"beacon","beacon":{"hwid":"d41d8cd98f","type":"enter"}}
```

`postback.params` 在兩種情況會有值：
- **datetimepicker action** → `date` / `time` / `datetime`
- **richmenuswitch action** → `newRichMenuAliasId` / `status`

## 8. 下載使用者傳來的媒體

```
GET https://api-data.line.me/v2/bot/message/{messageId}/content
```

注意是 **api-data.line.me**。影片/音訊可能還在轉檔，先查：

```
GET https://api-data.line.me/v2/bot/message/{messageId}/content/transcoding
```

```bash
python scripts/lineapi.py content 325708 --out photo.jpg
```

## 9. 本機開發

LINE 只接受公開 HTTPS URL，localhost 不行。用 ngrok 或 Cloudflare Tunnel：

```bash
ngrok http 3000
# 把 https://xxxx.ngrok-free.app/callback 貼進 Console 的 Webhook URL
```

設定完可用 API 直接測試，不必手動點 Console：

```bash
python scripts/lineapi.py webhook-set https://xxxx.ngrok-free.app/callback
python scripts/lineapi.py webhook-test
```
