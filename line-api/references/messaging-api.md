# Messaging API 參考

> 官方文件：https://developers.line.biz/en/docs/messaging-api/overview/
> API reference：https://developers.line.biz/en/reference/messaging-api/
> 全部 121 個端點見 `data/endpoints.csv`；1492 個欄位見 `data/parameters.csv`。

## 1. 架構

```
使用者 ──訊息──▶ LINE Platform ──webhook(POST, JSON)──▶ 你的 bot server
                      ▲                                      │
                      └────── reply / push (HTTPS) ──────────┘
```

- Webhook 一定是 `POST`，body 是 JSON，帶 `x-line-signature` 標頭。
- 你的伺服器**必須先回 200**，再非同步處理，否則 LINE 會重送。

## 2. 網域（最常見的踩雷點）

| 網域 | 用途 |
|---|---|
| `https://api.line.me` | 絕大多數端點 |
| `https://api-data.line.me` | **只有**內容類端點：<br>`GET /v2/bot/message/{messageId}/content`<br>`POST/GET /v2/bot/richmenu/{richMenuId}/content`<br>`POST/PUT /v2/bot/audienceGroup/upload/byFile` |

打錯網域會拿到 404 或連線錯誤。`scripts/lineapi.py` 的 `host_for()` 已自動處理。

## 3. 認證

所有 Messaging API 端點都用：

```
Authorization: Bearer {channel access token}
```

四種 channel access token 的差異、效期與取得方式見
[channel-access-token.md](channel-access-token.md) 與 `data/channel-tokens.csv`。

## 4. 送訊息的五種方式

| 方式 | 端點 | 對象 | 計費 | 上限 |
|---|---|---|---|---|
| reply | `POST /v2/bot/message/reply` | 觸發 webhook 的對話 | **不計費** | 1 個 replyToken、5 則訊息 |
| push | `POST /v2/bot/message/push` | 單一 userId / groupId / roomId | 計費 | 5 則訊息 |
| multicast | `POST /v2/bot/message/multicast` | 多個 userId | 計費 | **500 個 userId**、5 則訊息 |
| broadcast | `POST /v2/bot/message/broadcast` | 全部好友 | 計費 | 5 則訊息 |
| narrowcast | `POST /v2/bot/message/narrowcast` | 依屬性 / audience 分眾 | 計費 | 5 則訊息，非同步執行 |

**replyToken 規則**

- 只能用一次。
- 必須在收到 webhook 後 **1 分鐘內**使用。
- webhook 重送時附帶的 replyToken，也只有從收到重送起算 1 分鐘。
- 逾時或要送第二批 → 改用 push。

**request body 範例（reply）**

```json
{
  "replyToken": "nHuyWiB7yP5Zw52FIkcQobQuGDXCTA",
  "messages": [
    { "type": "text", "text": "Hello!" }
  ],
  "notificationDisabled": false
}
```

送出前先驗：

```bash
python scripts/validate.py body.json --as reply     # 離線，零成本
python scripts/lineapi.py validate-push --json m.json   # 呼叫 LINE 官方驗證端點
```

## 5. 常用端點速查

| 目的 | 端點 |
|---|---|
| 查 bot 資訊 | `GET /v2/bot/info` |
| 查本月訊息額度 | `GET /v2/bot/message/quota` |
| 查已用量 | `GET /v2/bot/message/quota/consumption` |
| 取得使用者 profile | `GET /v2/bot/profile/{userId}` |
| 取得好友 userId 清單 | `GET /v2/bot/followers/ids` |
| 下載使用者傳的圖片/影片 | `GET /v2/bot/message/{messageId}/content`（api-data） |
| 顯示「輸入中」動畫 | `POST /v2/bot/chat/loading/start`（5–60 秒，僅一對一） |
| 標記已讀 | `POST /v2/bot/message/markAsRead` |
| 設定 webhook URL | `PUT /v2/bot/channel/webhook/endpoint` |
| 測試 webhook URL | `POST /v2/bot/channel/webhook/test` |
| 查群組摘要 | `GET /v2/bot/group/{groupId}/summary` |
| 離開群組 | `POST /v2/bot/group/{groupId}/leave` |

完整清單：

```bash
python scripts/search.py "insight" --domain endpoint --max 10
python scripts/search.py "audience" --domain endpoint --max 10
```

## 6. Rate limit

- 多數送訊端點：**2,000 requests/second**。
- 查詢類（profile、insight、audience）較低，逐支不同。
- 每支端點的實際值在 `data/endpoints.csv` 的 `rate_limit` 欄位。
- 超過會拿到 `429`。`429` 也可能代表**訊息額度用完**（訊息內容為
  `You have reached your monthly limit.`），兩者要分開處理。

```bash
python scripts/search.py "get profile" --domain endpoint --max 1   # 看該端點的 rate limit
```

## 7. 冪等：X-Line-Retry-Key

重試時帶同一個 UUID，LINE 不會重複執行：

```
X-Line-Retry-Key: 123e4567-e89b-12d3-a456-426614174000
```

已被接受過的請求會回 `409 Conflict`，並在
`X-Line-Accepted-Request-Id` 標頭回傳原本的 request id。

支援的端點與細節：https://developers.line.biz/en/docs/messaging-api/retrying-api-request/

## 8. 錯誤處理

```json
{
  "message": "The request body has 2 error(s)",
  "details": [
    { "message": "May not be empty", "property": "messages[0].text" },
    { "message": "Must be one of the following values: [text, image, ...]",
      "property": "messages[1].type" }
  ]
}
```

`details[].property` 直接指出出錯欄位——先讀它再 debug。
狀態碼與錯誤訊息對照見 [errors-and-limits.md](errors-and-limits.md)
與 `data/error-codes.csv`（226 筆）。

## 9. 群組 / 多人聊天室

- `source.type` 會是 `user` / `group` / `room`。
- 群組要拿成員名稱需 `GET /v2/bot/group/{groupId}/member/{userId}`，
  且該使用者需已同意；拿不到是正常情況，程式要能 fallback。
- 只有加入群組後才能取得 `groupId`（來自 `join` 事件或群組內訊息事件）。

## 10. 相關文件

- [webhook.md](webhook.md) — 接收事件與簽章驗證
- [message-objects.md](message-objects.md) — 9 種訊息型別欄位
- [flex-message.md](flex-message.md) — Flex Message 完整規格
- [rich-menu.md](rich-menu.md) — 圖文選單
- [errors-and-limits.md](errors-and-limits.md) — 錯誤與限制
