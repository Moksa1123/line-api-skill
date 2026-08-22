---
name: line-api
description: LINE Platform 開發專家 — Messaging API（bot、webhook、Flex Message、圖文選單、推播/分眾）、LINE Login v2.1（OAuth 2.0 + OIDC）、LIFF v2、LINE MINI App、LINE Social Plugins、LINE 通知訊息。當使用者要做 LINE 聊天機器人、LINE 登入、LIFF 網頁、圖文選單、Flex Message、webhook 簽章驗證、channel access token（含 JWT v2.1）、或從已停止服務的 LINE Notify 遷移時使用。內建 121 個官方端點、1492 個欄位、226 筆錯誤碼的可搜尋資料庫，以及離線訊息驗證器、簽章/JWT 工具與零依賴 API client。
user-invocable: true
---

# LINE Platform 開發技能

> 資料全部由 [`line/line-openapi`](https://github.com/line/line-openapi) 官方 OpenAPI 規格
> 與 https://developers.line.biz 官方文件自動萃取，共 **3675 筆**。
> 每一筆都附官方文件連結，且連結經 `tools/check_links.py` 實際驗證過。

## 何時使用

- 做 LINE 官方帳號聊天機器人（收 webhook、回訊息、推播）
- 設計 Flex Message / 圖文選單 / Quick Reply
- 實作 LINE Login 第三方登入、綁定會員
- 開發 LIFF 網頁或 LINE MINI App
- 處理 channel access token、webhook 簽章、JWT
- 除錯：400 / 401 / 429、簽章驗不過、webhook 收不到、圖片破圖
- 從 **LINE Notify（已於 2025-03-31 終止服務）** 遷移

---

## 使用流程（重要）

**回答任何 LINE API 問題前，先查資料庫，不要憑記憶回答。**

```bash
python scripts/search.py "<關鍵字>"                 # 自動判斷搜尋域
python scripts/search.py "<關鍵字>" --domain all    # 不確定時全域搜尋
python scripts/search.py --stats                    # 看資料集有什麼
```

中文查詢也可以（內建 130+ 條術語對照，會自動補上英文詞）：

```bash
python scripts/search.py "圖文選單"        # → richmenu
python scripts/search.py "簽章驗證失敗"    # → troubleshoot
python scripts/search.py "彈性訊息"        # → flex
```

**產生任何訊息 JSON 後，一律先驗證再送出：**

```bash
python scripts/validate.py message.json              # 離線、零成本、零 API 呼叫
python scripts/validate.py body.json --as push
python scripts/lineapi.py validate-push --json m.json  # LINE 官方驗證端點
```

**要改既有的 LINE 程式碼、或使用者問「我這樣寫對不對」時，先審一次：**

```bash
python scripts/review.py app.py            # 單一檔案
python scripts/review.py ./src             # 整個目錄
```

它會照資料集比對這份程式碼：端點是否存在、內容類端點有沒有打錯主機、
簽章是不是用原始 body 且常數時間比對、內嵌的訊息 JSON 有沒有錯字、
有沒有用到已停止服務的 API。**動手改之前先看它報什麼**，
不要憑印象斷定使用者的程式碼哪裡有問題。

---

## 25 個搜尋域

| 域 | 內容 | 筆數 |
|---|---|---|
| `endpoint` | 全部 API 端點（method / host / path / rate limit / auth） | 121 |
| `parameter` | 每支端點與 LIFF SDK 的請求/回應欄位（含字數上限） | 1584 |
| `message` | 11 種訊息物件 + template + imagemap action | 142 |
| `flex` | Flex Message 容器、元件、樣式 | 136 |
| `action` | 9 種 action 物件 | 34 |
| `richmenu` | 圖文選單物件 | 23 |
| `webhook` | 20 種 webhook 事件 + 7 種訊息子型別 | 27 |
| `webhook_field` | 每個 webhook 事件的逐欄位型別與說明 | 247 |
| `response` | 每支端點回應主體的逐欄位型別 | 218 |
| `guide` | 221 頁官方指南的標題與各節索引 | 221 |
| `faq` | 官方 FAQ 92 題（題目、標籤、錨點連結） | 92 |
| `sdk_api` | iOS Swift / Android SDK 的型別清單 | 80 |
| `url_scheme` | LINE URL scheme（加好友、相機、設定畫面…） | 44 |
| `liff_version` | LIFF 版本沿革（哪一版引進哪個 API） | 58 |
| `liff` | LIFF SDK v2 全部 API（含引進版本、模組化匯入、可否在 init 前呼叫） | 35 |
| `error` | 狀態碼、錯誤訊息、每支端點的錯誤表 | 226 |
| `limit` | OpenAPI 明訂的數值限制 | 114 |
| `term` | 官方術語表（57 條，附中文定義） | 57 |
| `product` | LINE 各產品比較與選型 | 8 |
| `token` | 四種 channel access token + user access token | 5 |
| `troubleshoot` | 常見問題的症狀 / 原因 / 解法 | 21 |
| `reasoning` | 情境 → 建議做法 | 23 |
| `deprecation` | 已停用 / 已淘汰功能與替代方案 | 12 |
| `emoji` / `sticker` | 可用的 LINE emoji 與貼圖 ID | 60 |

---

## 工具

### `scripts/search.py` — 資料庫搜尋

```bash
python scripts/search.py "push message"                  # 找端點
python scripts/search.py "429" --domain error            # 找錯誤
python scripts/search.py "aspectMode" --domain flex      # 找 Flex 屬性
python scripts/search.py "shareTargetPicker" --domain liff
python scripts/search.py "webhook 收不到" --domain troubleshoot
python scripts/search.py "rich menu" --domain all --format json
```

### `scripts/validate.py` — 離線訊息驗證器

檢查型別、必填、未知屬性（typo）、enum、字數/陣列上限、已淘汰元件，
以及兩類只寫在文件散文、OpenAPI 沒有的規則：

- **網址**：標明「Protocol: HTTPS」的欄位必須是 `https://`；`uri` 與 `linkUri`
  只收 http / https / line / tel 四種 scheme。
- **label**：規格由「action 放在哪」決定，不是由 action 型別決定 ——
  quick reply 必填上限 20、Flex button 必填上限 40、image carousel 選填上限 12。

也驗圖文選單（`--as richmenu`，走 `/v2/bot/richmenu/validate` 的規則）：
寬 800–2500、高 ≥250、長寬比 ≥1.45 —— 官方寫的是範圍，不是 Console 上那六種預設尺寸。

**兩個等級的意思是明確的：**

| 等級 | 意思 |
|---|---|
| `error` | LINE 會退件（400） |
| `warning` | LINE 會收，但不會照你想的運作 |

這不是憑感覺分的。從資料集生出 659 則訊息與 41 個圖文選單，逐筆送進 LINE 官方的
兩支驗證端點對照，700 筆判斷全部一致。幾個反直覺的地方就是這樣挖出來的：

- `text` 的 5000 上限數的是 **UTF-16 單位不是字元** —— 一個 emoji 佔兩個，
  所以 2501 個 emoji 會被退，用 `len()` 數則會放行。
- 多出來的屬性在 **Flex 裡是致命的**（400），在訊息物件、樣板、action 上則是收下但沒作用。
- 字串欄位給數字，訊息層級 LINE 自動轉型，Flex 與圖文選單直接退。
- `camera` / `location` 放進樣板，LINE 收單但按了不會有反應 —— 所以是 warning 不是 error。

`test_line.py --live` 會重跑這個對照。

```bash
python scripts/validate.py flex.json --as flex
echo '{"type":"text","text":"hi"}' | python scripts/validate.py -
python scripts/validate.py body.json --as multicast --format json
```

錯誤會直接指到路徑：

```
❌ [error] $.contents.body.layout            缺少必填屬性 layout
❌ [error] $.contents.body.contents[0].weight 值 'extra-bold' 不合法，可用值：regular, bold
```

### `scripts/signature.py` — 簽章與權杖

```bash
# webhook 簽章
python scripts/signature.py verify --secret <channel secret> --body-file body.json --signature <sig>
python scripts/signature.py sign   --secret <channel secret> --body '{"events":[]}'

# channel access token
python scripts/signature.py stateless --channel-id 1234 --channel-secret <secret>   # 15 分鐘
python scripts/signature.py token --jwk private.key --channel-id 1234 --kid <kid>   # v2.1，最長 30 天
```

RS256 JWT 以純標準函式庫實作（不需要 PyJWT / cryptography），
並會擋掉超過 30 分鐘的 assertion 與超過 30 天的 token_exp。

### `scripts/lineapi.py` — 零依賴 API client / CLI

會自動判斷該打 `api.line.me` 還是 `api-data.line.me`。

```bash
export LINE_CHANNEL_ACCESS_TOKEN=...
python scripts/lineapi.py info
python scripts/lineapi.py quota
python scripts/lineapi.py profile U1234...
python scripts/lineapi.py push U1234... --text "Hello"
python scripts/lineapi.py push U1234... --json message.json
python scripts/lineapi.py richmenu-list
python scripts/lineapi.py content 325708 --out photo.jpg
python scripts/lineapi.py raw GET /v2/bot/followers/ids
```

### `scripts/review.py` — 既有程式碼健檢

拿資料集去審別人（或自己）寫好的 LINE 程式碼，判斷是不是官方做法。
支援 `.py` / `.js` / `.ts` / `.php` / `.rb` / `.go` / `.java` / `.kt` / `.cs` / `.swift`。

```bash
python scripts/review.py app.py
python scripts/review.py ./src --format json     # 給程式接的輸出
python scripts/review.py ./src --min-severity error   # 只看必須修的
```

檢查項目：

| rule | 等級 | 抓什麼 |
|---|---|---|
| `deprecated` | error / warning | 用到已停止服務的 API（LINE Notify…）。分不出是在用它還是在擋它的寫法（`/^line:\/\//` 這種樣式）只給 warning |
| `wrong-host` | error | 內容類端點打到 `api.line.me` 而不是 `api-data.line.me` |
| `hardcoded-secret` | error | channel secret / access token 寫死在原始碼 |
| `signature-body` | error | 拿反序列化後再 dump 的 JSON 算簽章（空白一差就驗不過） |
| `signature-compare` | warning | 真的在驗簽，卻用 `==` 比而不是常數時間比較 |
| `signature-missing` | error | 有 webhook 端點，但整個專案都沒驗簽章 |
| `unknown-endpoint` | warning | 路徑不在官方端點清單裡（多半是拼錯） |
| `message-json` | warning | 內嵌的訊息 / Flex JSON 直接丟給 validate.py 驗 |
| `idempotency` | info | 沒用 `webhookEventId` 去重，LINE 重送會重複處理 |

每一筆都附建議與官方文件連結。找不到問題就什麼都不報。

判斷時的三個分寸，都是拿真實專案掃出來才調對的：

- **註解不算程式碼。** 解釋「為什麼不能用 JSON.stringify 算簽章」的那段 docblock，
  本身就含有 `JSON.stringify` 與 `x-line-signature`。用原文比對等於在罰寫註解的人。
- **`signature-missing` 與 `idempotency` 是專案層級的。** 分層寫的專案會把驗簽放進
  `signature.ts`、去重放進 `webhook.ts`；逐檔判斷會對著每一個沒寫的檔案各報一次，
  包含正在做這件事的那一支。這兩條只報一次，而且全專案都沒做才報。
- **測試檔不套 `deprecated` / `message-json` / `hardcoded-secret`。** 測試會刻意寫進
  已淘汰的值、少一個必填欄位的 JSON、假的 channel secret，來斷言它們會被擋下來，
  那不是在用它們。認得四種命名慣例：`foo.test.ts`、`tests/`、`test_foo.py`、`foo_test.go`。
  其餘規則照常 —— 測試裡把端點拼錯，那還是拼錯。

零誤報這件事有兩個測試守著：自家 `examples/` 6 個檔要零筆，
以及上面三種寫法都不得觸發。

### `scripts/test_line.py` — 自我測試

```bash
python scripts/test_line.py           # 離線：資料完整性、搜尋、驗證器、簽章、JWT
python scripts/test_line.py --live    # 加上實際呼叫 LINE API（需 access token）
```

---

## 參考文件

| 檔案 | 內容 |
|---|---|
| [references/messaging-api.md](references/messaging-api.md) | 架構、網域、五種送訊方式、rate limit、冪等、錯誤處理 |
| [references/webhook.md](references/webhook.md) | 開通順序、簽章驗證、20 種事件、重送與冪等 |
| [references/message-objects.md](references/message-objects.md) | 11 種訊息型別、quick reply、template、9 種 action |
| [references/flex-message.md](references/flex-message.md) | Flex 完整結構、元件屬性、常見版型、除錯 |
| [references/rich-menu.md](references/rich-menu.md) | 建立、上傳、綁定、alias 分頁切換、圖片規格 |
| [references/channel-access-token.md](references/channel-access-token.md) | 四種 token、JWT v2.1、安全守則 |
| [references/line-login.md](references/line-login.md) | OAuth 2.0 + OIDC 流程、scope、ID token 驗證 |
| [references/liff.md](references/liff.md) | LIFF v2 設定、SDK API、環境差異 |
| [references/line-mini-app.md](references/line-mini-app.md) | 驗證/未驗證差異、服務訊息、IAP |
| [references/url-schemes.md](references/url-schemes.md) | LINE URL scheme：加好友、相機、設定畫面、外部瀏覽器與三大限制 |
| [references/errors-and-limits.md](references/errors-and-limits.md) | 狀態碼、錯誤訊息、限制速查、計費 |
| [references/sdk-and-tools.md](references/sdk-and-tools.md) | 官方 SDK、LIFF 工具、線上工具 |
| [EXAMPLES.md](EXAMPLES.md) | 可直接執行的程式碼範例 |

---

## 開發時務必遵守

### 1. Webhook 簽章一定要用「原始 body」

```
Base64( HMAC-SHA256( channel secret, raw_request_body ) ) == x-line-signature
```

用框架 parse 過的 JSON 再 serialize 會改變空白與鍵順序，永遠驗不過。
LINE 不公開來源 IP，簽章是唯一的驗證手段。

### 2. 先回 200，再處理

沒有及時回 200 → LINE 重送 → 同一筆訂單被處理兩次。
用 `webhookEventId` 做冪等去重。

### 3. replyToken 只能用一次、1 分鐘內

超過或要送第二批 → 改用 push（會計費）。

### 4. 內容類端點在 `api-data.line.me`

`GET /v2/bot/message/{id}/content`、rich menu 圖片上傳/下載、
audience by file — 打錯網域會 404。

### 5. userId 是「每個 provider 一組」

同 provider 下的 Messaging API channel 與 LINE Login channel 拿到的 userId 相同；
跨 provider 就不同。綁定會員前先確認 channel 在同一個 provider 底下。

### 6. 憑證絕不進 repo / 前端 / log

```
LINE_CHANNEL_ID=
LINE_CHANNEL_SECRET=
LINE_CHANNEL_ACCESS_TOKEN=
```

正式環境優先用 **stateless token**（15 分鐘、不限發行數）或
**v2.1 JWT token**（可自訂效期、可撤銷）；long-lived token 只用於本機測試。

### 7. 已停用的東西不要再用

```bash
python scripts/search.py "notify" --domain deprecation
```

| 已停用 | 替代 |
|---|---|
| LINE Notify（2025-03-31 終止） | Messaging API push；對方未加好友則用 LINE 通知訊息 |
| LIFF v1（2021-10-01 終止） | LIFF v2 SDK |
| `liff.scanCode()` | `liff.scanCodeV2()` |
| `liff.getLanguage()` | `liff.getAppLanguage()` |
| `line://` scheme | `https://line.me/R/...` / `https://liff.line.me/...` |
| Flex `filler` | box 的 `margin` / `offset*` / `padding*` |

---

## 常見任務的正確做法

| 任務 | 做法 |
|---|---|
| 使用者傳訊息後回覆 | `reply`（不計費） |
| 通知單一使用者 | `push` |
| 通知 2–500 位已知 userId | `multicast`（一次最多 500） |
| 通知全部好友 | `broadcast` |
| 依性別/年齡/地區分眾 | `narrowcast` + audience |
| 對方沒加好友但要通知 | LINE 通知訊息（需向 LINE 業務申請） |
| 官網放「加好友」按鈕 | LINE Social Plugins（純前端，不需 channel） |
| 網站用 LINE 帳號登入 | LINE Login v2.1 |
| 聊天室內開表單/預約 | LIFF |
| 要出現在 LINE 服務列表 | LINE MINI App（需審查） |

```bash
python scripts/search.py "<你的情境>" --domain reasoning
```

---

## 重建資料集（維護者用）

```bash
python tools/fetch_sources.py     # 抓官方文件與 OpenAPI 到 .docs-cache/（不進 git）
python tools/build_dataset.py     # 重新產生 line-api/data/*.csv
python tools/check_links.py --md  # 實際打過每一條連結
python line-api/scripts/test_line.py --live
```
