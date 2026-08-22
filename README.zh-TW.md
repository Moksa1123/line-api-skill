# line-api-skill

**別再猜 LINE 的 API，查就對了。**

一個 [Agent Skill](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)，
把整份 LINE Platform 官方文件變成可查詢的資料庫，讓 AI 助理照規格回答，而不是憑記憶。

<p>
  <img src="https://img.shields.io/badge/endpoints-121-success?style=flat-square" alt="121 endpoints">
  <img src="https://img.shields.io/badge/fields-1584-blue?style=flat-square" alt="1584 fields">
  <img src="https://img.shields.io/badge/dataset-3675%20rows-orange?style=flat-square" alt="3675 rows">
  <img src="https://img.shields.io/badge/platforms-8-9cf?style=flat-square" alt="8 platforms">
  <img src="https://img.shields.io/badge/python-3.9%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/dependencies-0-brightgreen?style=flat-square" alt="zero dependencies">
</p>

```
121 個端點 · 1,584 個請求/回應欄位 · 295 個回應欄位
233 筆錯誤碼 · 247 個 webhook 欄位 · 136 個 Flex 元件 · 44 個 URL scheme
35 個 LIFF API 橫跨 58 個版本 · 80 個行動 SDK 型別 · 92 題官方 FAQ
```

[English](README.md) · 繁體中文 · [日本語](README.ja.md) · [한국어](README.ko.md)

---

## 這個技能要解決的問題

LINE 的 API 對小錯誤的懲罰，往往很難追。

`chatBarText` 上限是 14 個字。輪播每一欄的 `text` 可以放 120 字 —— 但只要加了縮圖或標題就縮到 60 字。
圖文選單的圖片要上傳到 `api-data.line.me`，不是 `api.line.me`。replyToken 只能用一次、逾一分鐘失效。
同一個輪播裡的 bubble 寬度必須全部相同。

這些都不是猜得出來的，而憑記憶回答的助理會很有自信地給你錯的。這個技能讓它先查再答。

## 快速開始

```bash
git clone https://github.com/Moksa1123/line-api-skill
cd line-api-skill
python tools/install-skill.py claude-code --global
```

然後用你自己的話問就好：

```
你：   幫我做一個 LINE bot，收到訂單查詢就回一張 Flex 卡片

助理： （查端點、查 Flex 結構、查欄位上限，
        寫出程式，送出前先離線驗證 JSON）
```

## 安裝

```bash
python tools/install-skill.py --list                   # 看支援哪些平台
python tools/install-skill.py claude-code --global
python tools/install-skill.py cursor                   # 裝到目前專案
python tools/install-skill.py claude-ai --to ./build    # 產生可上傳的 zip
```

支援 8 個平台 —— Claude Code、Claude.ai、Cursor、Codex CLI、Gemini CLI、
Devin Desktop（原 Windsurf）、GitHub Copilot、Continue。依各平台載入技能的方式，
分成三種安裝型態：完整目錄、壓成單一份規則檔、或打包成 zip 供網頁上傳。
升級時會清掉上一版留下的檔案 —— 讓去年的錯資料留在今年的對的資料旁邊，比不裝還糟。

## 怎麼用

正常情況你不需要自己執行任何工具，技能會教助理走這個循環：

```
1. 先查        search.py     端點、欄位、上限、enum、錯誤、FAQ
2. 寫 JSON     （助理）       照剛查到的結構寫，不臆測
3. 離線驗證    validate.py   型別、必填、錯字、enum、上限、已淘汰元件
4. 才送出      lineapi.py    正確的主機、正確的標頭
```

想自己下指令也可以：

```bash
python scripts/search.py "輪播"                       # 自動判斷搜尋域
python scripts/search.py "get bot info" --domain response
python scripts/search.py "圖文選單" --domain all
python scripts/validate.py message.json --as push
python scripts/signature.py verify --secret <s> --body-file b.json --signature <sig>
python scripts/lineapi.py info
```

驗證器會直接指到出錯的路徑：

```
❌ $.contents.body.layout               缺少必填屬性 layout
❌ $.contents.body.contents[0].weight   值 'extra-bold' 不合法，可用值：regular, bold
⚠️  $.template.columns                  各欄的 action 數量不一致
```

### 審既有的程式碼

把 reviewer 指向已經寫好的整合，它會拿同一份資料集去比對：端點存不存在、
主機對不對、簽章是不是用原始 body 且常數時間比對、訊息 JSON 有沒有錯字、
用到的 API 是不是已經停服。

```bash
python scripts/review.py ./src
python scripts/review.py app.py --min-severity error   # 只看必須修的
python scripts/review.py ./src --format json           # 給 CI 接
```

```
❌ [signature-body] app.py:14   用序列化後的 JSON 算簽章，空白一變就驗不過
   → 拿原始 bytes 算（Flask: request.get_data()｜Express: express.raw()）
❌ [wrong-host]      app.py:29   /v2/bot/message/{}/content 必須用 api-data.line.me
⚠️  [message-json]    app.py:21   未知屬性 'quickreply'（是不是想寫 quickReply？）
```

九條規則，每一條都附修法與官方出處。程式碼沒問題就一筆都不報 ——
本倉庫自家範例的期望輸出是零筆，這件事有測試守著。

## 涵蓋範圍

| 領域 | 查得到什麼 |
|---|---|
| Messaging API | 97 個端點、rate limit、retry key、訊息額度、成效統計 |
| 訊息物件 | 11 種型別、quick reply、4 種樣板、9 種 action |
| Flex Message | 容器、9 種元件、每個屬性、體積上限 |
| 圖文選單 | 物件結構、圖片規格、alias、個別使用者綁定 |
| Webhook | 20 種事件、247 個帶型別的欄位、簽章驗證 |
| LINE Login | OAuth 2.0 + OIDC、scope、ID token 驗證 |
| LIFF | 35 個 API、引進版本、可搖樹匯入模組 |
| LINE MINI App | 已驗證與未驗證的差異、服務訊息、站內購買 |
| URL scheme | 44 個 scheme，以及三個最常踩的平台限制 |
| 行動 SDK | 80 個 iOS / Android 型別，附官方 reference 連結 |

另外還有 LINE 官方術語 57 條、FAQ 92 題、人工整理的疑難排解，以及已停止服務的清單
（LINE Notify 已於 2025-03-31 終止），確保助理不會推薦已經死掉的 API。

## 工具

| 工具 | 做什麼 |
|---|---|
| `search.py` | BM25 搜尋 25 個資料域；中文查詢會自動補上英文術語 |
| `validate.py` | 離線驗證訊息 / Flex：型別、必填、錯字、enum、上限、已淘汰元件 |
| `signature.py` | webhook 簽章；channel access token（含純 Python 實作的 RS256 JWT） |
| `lineapi.py` | 零依賴 Messaging API client，自動判斷該打哪個主機 |
| `review.py` | 審既有程式碼：已停服 API、主機打錯、簽章寫法、端點拼錯、訊息 JSON 錯字 |
| `test_line.py` | 45 項離線測試 + 6 項線上測試 |

## 資料怎麼來的

```
https://developers.line.biz/llms.txt        github.com/line/line-openapi
        ↓ tools/fetch_sources.py                    ↓
231 頁官方文件（多數有 .md 版）               10 份 OpenAPI 規格
        ↓ tools/build_dataset.py
line-api/data/*.csv    ← 交叉驗證：文件端點 ⊇ OpenAPI 端點
```

四道獨立把關，每一道都實際抓到過真的錯誤：

| 把關 | 檢查什麼 |
|---|---|
| `test_line.py` | 資料完整性、搜尋、驗證器、簽章、JWT |
| `audit_coverage.py` | 文件寫過的欄位是否都進了資料集 |
| `check_links.py` | 每條文件連結是否有效（會識破 SPA 的假 200） |
| `check_docs.py` | README 裡的數字是否與實際資料一致 |

抓下來的頁面放在 `.docs-cache/`，**已 git 忽略、絕不發佈** —— 那是 LY Corporation 的內容。
本倉庫只發佈萃取後的資料集與自撰的說明。

要更新到最新版文件：

```bash
python tools/fetch_sources.py
python tools/build_dataset.py
python tools/audit_coverage.py
python tools/check_links.py --md
python tools/check_docs.py
python line-api/scripts/test_line.py
```

## 授權

本倉庫程式碼採 MIT。

LINE、LINE Messaging API、LIFF、LINE MINI App 為 LY Corporation 的商標。
本專案與 LY Corporation 無隸屬關係，資料集是對其公開文件與公開 OpenAPI 規格的整理。
