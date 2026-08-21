# LINE MINI App

> 官方文件：https://developers.line.biz/en/docs/line-mini-app/discover/introduction/
> API reference：https://developers.line.biz/en/reference/line-mini-app/

LINE MINI App 是跑在 LINE 裡的網頁 App，使用者不用安裝任何東西。
技術上就是掛在 **LINE MINI App channel** 底下的 LIFF app，
所有 LIFF API 都能用（見 [liff.md](liff.md)），另外多了 MINI App 專屬功能。

## 1. 未驗證 vs 已驗證

| | 未驗證 MINI App | 已驗證 MINI App |
|---|---|---|
| 建立門檻 | 任何人建 channel 即可 | 需通過 LINE 審查 |
| Header 顯示 | 標題 + endpoint 網域名稱 | 服務名稱 |
| 服務訊息（Service Messages） | 只能在 Developing channel 測試 | ✅ 可用 |
| 出現在 LINE 服務列表 / 搜尋 | ❌ | ✅ |
| 自訂路徑、永久連結等進階功能 | 受限 | ✅ |

送審：https://developers.line.biz/en/docs/line-mini-app/submit/submission-guide/

## 2. Channel 結構

一個 LINE MINI App channel 底下有兩個內部 channel：

- **Developing**：開發測試用
- **Published**：正式對外

兩者的 LIFF ID 不同，佈署時要切換。

## 3. 服務訊息（Service Messages）

在使用者於 MINI App 做完某個動作後，發送**確認或通知**訊息。

- 訊息會出現在各地區固定的官方通知聊天室
  （台灣：「LINE MINI App 通知」）。
- 一次使用者動作最多送 **5 則**服務訊息。
- **只能是動作的確認 / 回覆**：禁止廣告、優惠、活動、新品通知。
- 必須使用 Console 上建立並通過審查的 **範本（template）**。

流程：

```
1. POST https://api.line.me/message/v3/notifier/token   取得 notification token
   （前端 LIFF 取得後傳給後端，token 有使用期限）
2. POST https://api.line.me/message/v3/notifier/send     用 token + 範本送出
```

## 4. 站內購買（In-App Purchase）

僅特定情境開放，需另外送審。

| 目的 | 端點 |
|---|---|
| 預約購買 | `POST https://api.line.me/iap/v1/product/reserve` |
| 查詢 webhook 事件紀錄 | `GET https://api.line.me/iap/v1/webhook/events` |

文件：https://developers.line.biz/en/docs/line-mini-app/in-app-purchase/overview/

## 5. 其他內建功能

| 功能 | 說明 |
|---|---|
| 分享 | 內建分享鈕，把 MINI App 分享給好友 / 群組 |
| Add to Home Screen | `liff.createShortcutOnHomeScreen()` 建立桌面捷徑 |
| 永久連結 | `https://miniapp.line.me/{liffId}/path`，可直達內頁 |
| 自訂路徑 | 已驗證 MINI App 可申請自訂路徑取代 LIFF ID |
| Channel 同意簡化 | 已驗證 MINI App 使用者不需每次同意 |
| 自訂動作鈕 | Header 右側可放自訂按鈕 |
| Quick Fill | 讓使用者用 LINE 已存資料快速填表 |

## 6. 開發要點

- 就是一般的 HTML5 網頁；LINE MINI App 瀏覽器支援多數 HTML5 規格。
- 一定要處理**外部瀏覽器**開啟的情況（`liff.isInClient() === false`）。
- 效能指南：https://developers.line.biz/en/docs/line-mini-app/develop/performance-guidelines/
- 設計規範（icon、loading、橫向）：`docs/line-mini-app/design/`
- Playground（可實測）：https://miniapp.line.me/lineminiapp_playground

## 7. LIFF vs LINE MINI App 怎麼選

| 需求 | 選 |
|---|---|
| 只是在自己的官方帳號聊天室內開表單 / 預約頁 | **LIFF**（LINE Login channel） |
| 要出現在 LINE 服務列表、要用服務訊息、要品牌化 header | **LINE MINI App**（需審查） |

> LINE 已宣布未來 LIFF 會整併進 LINE MINI App 品牌，
> 新專案建議直接以 LINE MINI App channel 建立。
> 參考：https://developers.line.biz/en/news/2025/?month=02&day=12&article=line-mini-app
