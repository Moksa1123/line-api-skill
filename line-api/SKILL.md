---
name: line-api
description: LINE Platform 開發專家 — Messaging API（bot、webhook、Flex Message、圖文選單、推播/分眾）、LINE Login v2.1（OAuth 2.0 + OIDC）、LIFF v2、LINE MINI App、LINE Social Plugins、LINE 通知訊息。當使用者要做 LINE 聊天機器人、LINE 登入、LIFF 網頁、圖文選單、Flex Message、webhook 簽章驗證、channel access token（含 JWT v2.1）、或從已停止服務的 LINE Notify 遷移時使用。內建 121 個官方端點、1584 個欄位、261 筆錯誤碼的可搜尋資料庫，以及離線訊息驗證器、簽章/JWT 工具與零依賴 API client。Use for LINE bot, LINE Messaging API, LINE Login, LIFF, rich menu, Flex Message, webhook signature.
user-invocable: true
---

# LINE Platform 開發技能

## 資料出處

| 項目 | 內容 |
|---|---|
| 來源 | [`line/line-openapi`](https://github.com/line/line-openapi) 官方 OpenAPI 規格（commit `de8bd9e`，2026-07-28）＋ https://developers.line.biz 官方文件（2026-08-21 抓取） |
| 筆數 | 共 **7096 筆**，分 28 個搜尋域；各域筆數用 `python scripts/search.py --stats` 看，不在這裡手寫 |
| 出處欄 | 每筆都有 `doc_url`（官方頁面或釘 commit 的規格檔）與 `trust`（實測／官方文件／推論） |
| 對應版本 | Messaging API、LINE Login v2.1、LIFF v2（資料內最新 LIFF 版本 2.30.0） |
| 驗證 | 2026-11-15：自我測試全過、`tools/check_links.py` 實際打過全部連結；已知落差記在 `data/pending.csv` |

`trust` 是「推論」的資料（選型建議、疑難排解的診斷、中文術語對照）是依官方文件歸納的，
轉述給使用者時要說「建議」，不可以說成官方規定。

## 用法

**何時用**

- 做 LINE 官方帳號聊天機器人（收 webhook、回訊息、推播）
- 設計 Flex Message／圖文選單／Quick Reply
- 實作 LINE Login 第三方登入、綁定會員
- 開發 LIFF 網頁或 LINE MINI App
- 處理 channel access token、webhook 簽章、JWT
- 除錯：400／401／429、簽章驗不過、webhook 收不到、圖片破圖
- 從 **LINE Notify（已終止服務）** 遷移

**何時不用**

| 情況 | 改用 |
|---|---|
| LINE Pay 金流串接 | `taiwan-payment` skill |
| LINE 官方帳號後台的操作、行銷文案 | 不是 API 問題，這個資料集沒有 |
| LINE WORKS、LINE 廣告 API | 不在資料集內；直接說查不到，不要拿 Messaging API 硬套 |

**唯一入口：`scripts/search.py`。** 任何問題先用它查，其他工具都是查完之後的下一步。

| 使用者會跑的 | 用途 |
|---|---|
| `scripts/search.py` | 入口：查資料庫 |
| `scripts/validate.py` | 產出訊息 JSON 後驗證 |
| `scripts/review.py` | 審既有程式碼 |
| `scripts/signature.py` | webhook 簽章、channel access token、ID token |
| `scripts/lineapi.py` | 零依賴 API client（需 access token） |
| `scripts/test_line.py` | 自我測試 |

維護者用的工具在 repo 的 `tools/`，見最後一段「維護」。每支工具的完整說明在
[references/tools.md](references/tools.md)。

## 路由

**鐵則：先查再答，不憑記憶。查不到就說查不到，標「待補」並記進 `data/pending.csv`，不猜。**

```bash
python scripts/search.py "<關鍵字>"                 # 不指定 --domain：搜遍所有域再合併排序
python scripts/search.py "<關鍵字>" --domain <域>   # 只搜那一個域
python scripts/search.py --stats                    # 每個域有幾筆
```

中文、口語說法可以直接查：`data/glossary.csv` 會自動補上英文術語
（「圖文選單」→ rich menu、「彈性訊息」→ Flex）。不確定是哪個域時**不要指定** `--domain`——
只猜一個域的做法實測只答得出 65% 的實戰問題（2026-08-25），答不出來的事實其實都在別的域裡。

| 使用者會怎麼說 | 查哪個域 | 指令 |
|---|---|---|
| 「推播要打哪支 API」「怎麼取得使用者資料」 | `endpoint` | `search.py "push message"` |
| 「這個欄位必填嗎」「字數上限多少」 | `parameter`、`limit` | `search.py "altText 上限"` |
| 「API 會回什麼欄位」 | `response` | `search.py "get profile response" --domain response` |
| 「文字／圖片／貼圖訊息怎麼寫」 | `message` | `search.py "貼圖訊息"` |
| 「卡片版面」「Flex 的 bubble 有哪些大小」 | `flex` | `search.py "bubble size" --domain flex` |
| 「按鈕按了要做什麼」 | `action` | `search.py "postback action"` |
| 「下方選單」「圖文選單尺寸」 | `richmenu` | `search.py "圖文選單圖片尺寸"` |
| 「收到什麼事件」「webhook 欄位」 | `webhook`、`webhook_field` | `search.py "postback 事件欄位"` |
| 「回 400／401／429 是什麼意思」 | `error` | `search.py "429" --domain error` |
| 「webhook 收不到」「簽章一直失敗」 | `troubleshoot` | `search.py "簽章驗證失敗"` |
| 「該用 reply 還是 push」「要選哪個產品」 | `reasoning`、`product` | `search.py "<情境>" --domain reasoning` |
| 「token 要用哪一種」「效期多久」 | `token` | `search.py "stateless token 效期"` |
| 「LIFF 怎麼取得 ID token」「LIFF 要哪個 LINE 版本」 | `liff`、`liff_availability`、`liff_version` | `search.py "shareTargetPicker 版本"` |
| 「MINI App 送審要檢查什麼」「服務訊息規格」 | `checklist`、`guide_spec` | `search.py "mini app 送審"` |
| 「LINE Notify／舊 API 還能用嗎」 | `deprecation` | `search.py "notify" --domain deprecation` |
| 「官方文件哪一頁在講」「FAQ」 | `guide`、`faq` | `search.py "<主題>" --domain guide` |
| 「加好友連結」「開相機的網址」 | `url_scheme` | `search.py "加好友" --domain url_scheme` |
| 「這個名詞是什麼意思」 | `term` | `search.py "channel 是什麼"` |
| 「iOS／Android SDK 有哪些類別」 | `sdk_api` | `search.py "LoginManager" --domain sdk_api` |
| 「可以送哪些貼圖／emoji」 | `sticker`、`emoji` | `search.py "sticker" --domain sticker` |

搜尋結果每筆都附 `doc_url` 與 `trust`。回答時附上 `doc_url`；結果裡沒有的事實不要補。

## 使用

| 任務 | 步驟 | 查的資料 | 產出與完成的證據 |
|---|---|---|---|
| 選送訊方式 | 1. 查 `reasoning` 2. 對照下表 | `reasoning`、`endpoint` | 選定的端點＋`doc_url` |
| 寫 webhook handler | 1. 查事件與欄位 2. 用原始 body 驗簽 3. 先回 200 再處理 4. 用 `webhookEventId` 去重 | `webhook`、`webhook_field`、`troubleshoot` | 程式碼；`review.py` 0 error |
| 組訊息／Flex JSON | 1. 查元件屬性與上限 2. 寫 JSON 3. 驗證 | `message`、`flex`、`action`、`limit` | JSON；`validate.py` 0 error |
| 圖文選單 | 1. 查尺寸與區域規則 2. 建立 3. 上傳圖片（`api-data.line.me`）4. 綁定／alias | `richmenu`、`endpoint` | JSON；`validate.py --as richmenu` 0 error |
| LINE Login／綁定會員 | 1. 確認 channel 在同一個 provider 2. 走 OAuth 2.0 授權碼流程 3. 驗 ID token | `endpoint`、`token`、`guide` | 程式碼；`signature.py` 的 `verify_id_token` 通過 |
| LIFF 網頁 | 1. 查 API 與引進版本 2. 查 LINE App 版本需求 3. 寫程式 | `liff`、`liff_availability`、`liff_version` | 程式碼；用到的 API 都查得到版本需求 |
| channel access token | 1. 選 token 型別 2. 需要時產生 JWT | `token` | `signature.py stateless`／`token` 成功取得 |
| 除錯錯誤碼 | 1. 查錯誤碼 2. 查疑難排解 3. 對照使用者程式碼 | `error`、`troubleshoot` | 原因＋`doc_url`；改完 `review.py` 0 error |
| 審既有程式碼 | 1. `review.py` 2. 依報告改 3. 再跑一次 | 由 `review.py` 自動查 | `review.py --min-severity error` exit 0 |
| LINE Notify 遷移 | 1. 查 `deprecation` 2. 改用 push／LINE 通知訊息 | `deprecation`、`product` | 程式碼不再呼叫 notify-api；`review.py` 0 error |

**選送訊方式**

| 情境 | 做法 |
|---|---|
| 使用者傳訊息後回覆 | `reply`（不計費） |
| 通知單一使用者 | `push` |
| 通知多位已知 userId | `multicast`（上限 500） |
| 通知全部好友 | `broadcast` |
| 依性別／年齡／地區分眾 | `narrowcast` + audience |
| 對方沒加好友但要通知 | LINE 通知訊息（需向 LINE 業務申請） |
| 官網放「加好友」按鈕 | LINE Social Plugins（純前端，不需 channel） |
| 網站用 LINE 帳號登入 | LINE Login v2.1 |
| 聊天室內開表單／預約 | LIFF |
| 要出現在 LINE 服務列表 | LINE MINI App（需審查） |

**寫程式時務必遵守**

1. **Webhook 簽章一定用原始 body**：`Base64(HMAC-SHA256(channel secret, raw_body)) == x-line-signature`。
   parse 再 serialize 會改變空白與鍵順序，永遠驗不過。LINE 不公開來源 IP，簽章是唯一的驗證手段。
2. **先回 200 再處理**，用 `webhookEventId` 去重；否則 LINE 重送會重複處理。
3. **replyToken 只能用一次、要在 1 分鐘內用**；第二批或逾時改用 push（會計費）。
4. **內容類端點在 `api-data.line.me`**：下載使用者傳的內容、圖文選單圖片、audience by file。打錯網域會 404。
5. **userId 是每個 provider 一組**：綁定會員前先確認 Messaging API 與 LINE Login channel 在同一個 provider。
6. **憑證不進 repo／前端／log**。正式環境優先用 stateless token（15 分鐘）或 v2.1 JWT token（效期可自訂、可撤銷）。
7. **已停用的東西不要再用**：LINE Notify、LIFF v1、`liff.scanCode()`、`liff.getLanguage()`、`line://` scheme、Flex `filler`。
   替代方案與停用日期查 `search.py "<名稱>" --domain deprecation`。

## 驗證

產出後一定要跑。全部驗證器有錯都回非 0 的 exit code，可以直接當關卡。

| 產出 | 驗證器 | 通過標準 |
|---|---|---|
| 訊息／Flex／request body JSON | `python scripts/validate.py <file> [--as flex\|push\|reply\|…]` | 0 error（exit 0）；要連 warning 一起擋就加 `--strict` |
| 圖文選單 JSON | `python scripts/validate.py <file> --as richmenu` | 0 error |
| 要確認 LINE 端判斷（需 token） | `python scripts/lineapi.py validate-push --json <file>` | 印出 `{"result": "valid"}`（exit 0） |
| 寫好或改過的 LINE 程式碼 | `python scripts/review.py <file-or-dir> --min-severity error` | exit 0（沒有 error） |
| webhook 簽章 | `python scripts/signature.py verify --secret <s> --body-file b.json --signature <sig>` | 印出 VALID（exit 0） |
| skill 本身 | `python scripts/test_line.py` | 0 failed；加 `--live` 會實打 LINE API |

`validate.py` 的 `error` 代表 LINE 會退件（400），`warning` 代表 LINE 會收但不會照你想的運作。
這個分級是拿生成語料逐筆送進 LINE 官方驗證端點對照校準的，細節見 [references/tools.md](references/tools.md)。

## 參考文件

| 檔案 | 內容 |
|---|---|
| [references/tools.md](references/tools.md) | 每支工具的完整用法、驗證器的判斷依據、review 規則表 |
| [references/messaging-api.md](references/messaging-api.md) | 架構、網域、五種送訊方式、rate limit、冪等、錯誤處理 |
| [references/webhook.md](references/webhook.md) | 開通順序、簽章驗證、事件、重送與冪等 |
| [references/message-objects.md](references/message-objects.md) | 訊息型別、quick reply、template、action |
| [references/flex-message.md](references/flex-message.md) | Flex 完整結構、元件屬性、常見版型、除錯 |
| [references/rich-menu.md](references/rich-menu.md) | 建立、上傳、綁定、alias 分頁切換、圖片規格 |
| [references/channel-access-token.md](references/channel-access-token.md) | token 型別、JWT v2.1、安全守則 |
| [references/line-login.md](references/line-login.md) | OAuth 2.0 + OIDC 流程、scope、ID token 驗證 |
| [references/liff.md](references/liff.md) | LIFF v2 設定、SDK API、環境差異 |
| [references/line-mini-app.md](references/line-mini-app.md) | 驗證／未驗證差異、服務訊息、IAP |
| [references/url-schemes.md](references/url-schemes.md) | LINE URL scheme 與限制 |
| [references/errors-and-limits.md](references/errors-and-limits.md) | 狀態碼、錯誤訊息、限制速查、計費 |
| [references/sdk-and-tools.md](references/sdk-and-tools.md) | 官方 SDK、LIFF 工具、線上工具 |
| [EXAMPLES.md](EXAMPLES.md) | 可直接執行的程式碼範例 |
| [evals/RESULTS.md](evals/RESULTS.md) | 最近一次 evals 答對率（有 skill／沒有 skill） |

## 維護

維護者在 repo 根目錄跑（`tools/` 不隨 skill 安裝，可用第三方套件，例如 `build_dataset.py` 需要 PyYAML）。

```bash
python tools/fetch_sources.py          # 重抓官方文件與 OpenAPI 到 .docs-cache/（不進 git）
python tools/build_dataset.py          # 重新產生 line-api/data/*.csv
python tools/check_links.py --md       # 實際打過每一條連結
python tools/check_docs.py             # SKILL.md 與 README 的每個數字都要對得上資料；--fix 自動改
python tools/benchmark.py              # 實戰問題的搜尋準確率
python line-api/scripts/test_line.py --live
python tools/install-skill.py claude-code --global   # 同步到安裝版
```

LINE 改版（OpenAPI 新 commit 或文件更新）後：重抓 → 重建 → 跑測試 → `check_docs.py` →
重跑 evals 並更新 `evals/RESULTS.md` → 同步安裝版。`data/pending.csv` 裡 `open` 的項目每次改版都要再查一次。
