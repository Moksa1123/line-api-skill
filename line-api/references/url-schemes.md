# LINE URL scheme

> 官方文件：https://developers.line.biz/en/docs/messaging-api/using-line-url-scheme/
> 全部 44 個 scheme 見 `data/url-schemes.csv`。

URL scheme 是「從網頁或訊息裡的一個連結，直接叫出 LINE App 的某個畫面或功能」。
不需要 SDK、不需要 channel，貼一個 `<a href>` 就會動。

```bash
python scripts/search.py "加好友連結" --domain url_scheme
python scripts/search.py "openExternalBrowser" --domain url_scheme
```

## 1. 三個入口前綴

| 前綴 | 用途 | 沒安裝 LINE 時 |
|---|---|---|
| `https://line.me/R/` | 呼叫 LINE App 的功能 | 開瀏覽器導向 LINE 下載頁 |
| `https://liff.line.me/{liffId}` | 開啟 LIFF app | 用外部瀏覽器開啟該 LIFF app |
| `https://miniapp.line.me/{liffId}` | 開啟 LINE MINI App | 同上 |

> ⚠️ 舊的 `line://` 已淘汰 —— 它可能被非 LINE 的 App 攔截。一律用 `https://` 形式。

## 2. 三個平台層級的限制（最常踩）

1. **只支援 LINE for iOS 與 Android。** LINE for PC（macOS / Windows）完全不支援。
   如果使用者可能用電腦版，要準備一般網址的替代路徑。
2. **相機、相簿、位置這幾支只能從 LINE 聊天室觸發**（含 OpenChat）。
   從 LIFF 或外部瀏覽器呼叫沒有作用。
3. **`openExternalBrowser` 對 LIFF app 不生效。** 在 LIFF 內要開外部瀏覽器請用
   `liff.openWindow({ url, external: true })`。

## 3. 最常用的幾支

**加好友 / 分享官方帳號**

```
https://line.me/R/ti/p/%40linedevelopers          加好友畫面（LINE ID 要 percent-encode，@ 寫成 %40）
https://line.me/R/nv/recommendOA/%40linedevelopers 推薦這個官方帳號給好友
https://line.me/R/home/public/main?id=linedevelopers  官方帳號的 LINE VOOM 與商業檔案（id 不含 @）
```

**開啟聊天室並預先填好訊息**

```
https://line.me/R/oaMessage/%40linedevelopers/?Hi%20there%21
```

做「一鍵詢問」按鈕很好用：使用者點下去會進到跟你的官方帳號的聊天室，
輸入框已經填好指定文字，他只要按送出。文字要 percent-encode。

**分享一段文字給好友**

```
https://line.me/R/share?text=Hi%20there%21
```

**相機 / 相簿 / 位置**（只能從聊天室觸發）

```
https://line.me/R/nv/camera/              開相機
https://line.me/R/nv/cameraRoll/single    開相簿（單選）
https://line.me/R/nv/cameraRoll/multi     開相簿（多選）
https://line.me/R/nv/location/            傳送所在位置
```

**強制用外部瀏覽器開啟**（是 query 參數，不是 scheme）

```
https://example.com/?openExternalBrowser=1   用外部瀏覽器開
https://example.com/?openInAppBrowser=0      用 Chrome custom tab 開（僅 Android）
```

## 4. 其他分類

`data/url-schemes.csv` 另外收錄：

- **常用畫面**：聊天列表、加好友、官方帳號列表、LINE VOOM、錢包、購物
- **設定畫面**：16 支，含帳號、隱私、聊天、通話、通訊錄同步、已連結的應用程式與裝置
- **貼圖小舖**：主頁、我的貼圖、熱門 / 最新 / 活動 / 分類
- **個人檔案**：個人檔案畫面、設定 LINE ID

```bash
python scripts/search.py "設定" --domain url_scheme --max 10
```

## 5. 搭配 Messaging API 使用

URL scheme 最常出現在 **uri action** 裡 —— 圖文選單的區塊、Flex 的按鈕、
quick reply 都可以：

```json
{
  "type": "uri",
  "label": "傳送位置",
  "uri": "https://line.me/R/nv/location/"
}
```

因為 PC 版不支援，若該訊息也可能在電腦上被點到，建議加 `altUri.desktop`
指向一個網頁版的替代路徑：

```json
{
  "type": "uri",
  "label": "查看門市",
  "uri": "https://line.me/R/nv/location/",
  "altUri": { "desktop": "https://example.com/stores" }
}
```

## 相關

- [messaging-api.md](messaging-api.md) — action 物件與圖文選單
- [liff.md](liff.md) — LIFF 內開視窗要用 `liff.openWindow()`
- `data/troubleshooting.csv` 收錄了這三個限制對應的症狀與解法
