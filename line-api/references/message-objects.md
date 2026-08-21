# 訊息物件（Message objects）

> 官方文件：https://developers.line.biz/en/reference/messaging-api/#message-objects
> 全部欄位見 `data/message-objects.csv`（142 筆）與 `data/actions.csv`（34 筆）。

一次 reply / push / multicast / broadcast 最多帶 **5 個訊息物件**。
每個訊息物件都可以附加 `quickReply` 與 `sender`。

## 1. 十一種訊息型別

| `type` | 必填欄位 | 重點限制 |
|---|---|---|
| `text` | `text` | 5000 字；`emojis` 最多 20 個 |
| `textV2` | `text` | 5000 字；用 `substitution` 放 emoji / mention |
| `sticker` | `packageId`, `stickerId` | 只能送 [官方清單](https://developers.line.biz/en/docs/messaging-api/sticker-list/) 內的貼圖，見 `data/stickers.csv` |
| `image` | `originalContentUrl`, `previewImageUrl` | HTTPS(TLS1.2+)、JPEG/PNG、原圖 ≤10MB、預覽 ≤1MB |
| `video` | `originalContentUrl`, `previewImageUrl` | mp4、原檔 ≤200MB、預覽圖 JPEG/PNG ≤1MB |
| `audio` | `originalContentUrl`, `duration` | mp3 或 m4a、≤200MB；`duration` 單位是毫秒 |
| `location` | `title`, `address`, `latitude`, `longitude` | title / address 各 100 字 |
| `imagemap` | `baseUrl`, `altText`, `baseSize`, `actions` | actions 最多 50 個 |
| `template` | `altText`, `template` | 版型固定，見第 3 節 |
| `flex` | `altText`, `contents` | 見 [flex-message.md](flex-message.md) |
| `coupon` | `couponId` | 需先用 Coupon API 建立 |

### text

```json
{
  "type": "text",
  "text": "Hello $ world",
  "emojis": [
    { "index": 6, "productId": "5ac1bfd5040ab15980c9b435", "emojiId": "001" }
  ]
}
```

- `emojis[].index` 指向 `text` 中的 `$` 佔位字元位置（0-based）。
- 可用的 productId / emojiId 見 `data/emoji.csv`。

### sticker

```json
{ "type": "sticker", "packageId": "446", "stickerId": "1988" }
```

```bash
python scripts/search.py "446" --domain sticker
```

### location

```json
{
  "type": "location",
  "title": "門市",
  "address": "台北市信義區市府路45號",
  "latitude": 25.0339,
  "longitude": 121.5645
}
```

## 2. Quick Reply

附在訊息底部的快捷按鈕，**最多 13 個**，只會出現在最新一則訊息上。

```json
{
  "type": "text",
  "text": "請選擇",
  "quickReply": {
    "items": [
      { "type": "action",
        "imageUrl": "https://example.com/icon.png",
        "action": { "type": "message", "label": "我要訂位", "text": "訂位" } },
      { "type": "action",
        "action": { "type": "postback", "label": "查訂單", "data": "action=orders" } },
      { "type": "action",
        "action": { "type": "location", "label": "傳送位置" } }
    ]
  }
}
```

`camera` / `cameraRoll` / `location` 這三種 action **只能**放在 quick reply。

## 3. Template message

| `template.type` | 必填 | 說明 |
|---|---|---|
| `buttons` | `text`, `actions` | 最多 4 個 action |
| `confirm` | `text`, `actions` | 必須剛好 2 個 action |
| `carousel` | `columns` | 最多 10 欄，每欄最多 3 個 action |
| `image_carousel` | `columns` | 最多 10 欄，每欄 1 個 action |

```json
{
  "type": "template",
  "altText": "請確認",
  "template": {
    "type": "confirm",
    "text": "確定要送出嗎？",
    "actions": [
      { "type": "postback", "label": "確定", "data": "confirm=yes" },
      { "type": "postback", "label": "取消", "data": "confirm=no" }
    ]
  }
}
```

> Template 的版型固定；要自由排版請改用 Flex Message。

## 4. Action 物件（9 種）

| `type` | 必填 | 說明 | 可用位置 |
|---|---|---|---|
| `postback` | `data` | 送 postback 事件，`data` 最多 300 字 | 任何地方 |
| `message` | `text` | 代使用者送出這段文字 | 任何地方 |
| `uri` | `uri` | 開啟連結（含 `altUri.desktop`） | 任何地方 |
| `datetimepicker` | `data`, `mode` | `mode`: `date` / `time` / `datetime` | 任何地方 |
| `richmenuswitch` | `richMenuAliasId`, `data` | 切換圖文選單分頁 | 圖文選單 |
| `clipboard` | `clipboardText` | 複製文字到剪貼簿，最多 1000 字 | 任何地方 |
| `camera` | — | 開相機 | **只能** quick reply |
| `cameraRoll` | — | 開相簿 | **只能** quick reply |
| `location` | — | 開位置選擇 | **只能** quick reply |

共通選填欄位 `label`（多數情境上限 20 字）。

```json
{ "type": "postback", "label": "加入購物車", "data": "action=add&sku=A1",
  "displayText": "加入購物車", "inputOption": "closeRichMenu" }
```

- `displayText`：點下去時在聊天室顯示的文字（不設就不顯示）。
- `inputOption`：`closeRichMenu` / `openRichMenu` / `openKeyboard` / `openVoice`。

```bash
python scripts/search.py "datetimepicker" --domain action
python scripts/search.py "inputOption" --domain action
```

## 5. Sender（改寫顯示名稱與頭像）

```json
{ "type": "text", "text": "hi",
  "sender": { "name": "客服小幫手", "iconUrl": "https://example.com/icon.png" } }
```

`name` 最多 20 字，`iconUrl` 最多 2000 字元且須 HTTPS。

## 6. 送出前驗證

```bash
python scripts/validate.py message.json                 # 單則
python scripts/validate.py body.json --as push          # 整個 request body
python scripts/lineapi.py validate-push --json m.json   # LINE 官方驗證端點
```
