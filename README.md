<h1 align="center">line-api-skill</h1>

<h3 align="center">LINE Platform AI 開發技能包</h3>

<p align="center">
  Messaging API · LINE Login · LIFF · LINE MINI App · Social Plugins · 通知訊息
</p>

<p align="center">
  <img src="https://img.shields.io/badge/endpoints-121-success?style=flat-square" alt="121 endpoints">
  <img src="https://img.shields.io/badge/fields-1584-blue?style=flat-square" alt="1584 fields">
  <img src="https://img.shields.io/badge/dataset-3595%20rows-orange?style=flat-square" alt="3595 rows">
  <img src="https://img.shields.io/badge/python-3.9%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/dependencies-0-brightgreen?style=flat-square" alt="zero dependencies">
</p>

---

## 這是什麼

一個給 AI 編碼助理（Claude Code、Cursor、Windsurf、Codex CLI…）使用的 LINE 開發技能包。

它把 **https://developers.line.biz 的全部文件**與
**[`line/line-openapi`](https://github.com/line/line-openapi) 官方 OpenAPI 規格**
萃取成一份 3,595 筆的可搜尋資料庫，並附上能實際執行的驗證與 API 工具。

AI 助理因此不必憑記憶回答 LINE API 問題——欄位名稱、字數上限、
enum 可用值、rate limit、錯誤碼全部查得到，而且每一筆都附官方文件連結。

## 內容

```
line-api/
├── SKILL.md                 技能說明（AI 讀這份）
├── EXAMPLES.md              程式碼範例集
├── data/                    25 個 CSV，共 3,595 筆
│   ├── endpoints.csv            121 個端點（method / host / path / rate limit / auth）
│   ├── parameters.csv          1584 個請求/回應欄位（8 份官方 reference，含 LIFF SDK）
│   ├── message-objects.csv      142 訊息物件 / template / imagemap action
│   ├── flex-components.csv      136 Flex 容器、元件、樣式
│   ├── actions.csv               34 action 物件
│   ├── richmenu.csv              23 圖文選單欄位
│   ├── webhook-events.csv        27 webhook 事件與訊息子型別
│   ├── webhook-properties.csv   247 webhook 事件的逐欄位型別與說明
│   ├── responses.csv            218 每支端點回應主體的逐欄位型別
│   ├── guides.csv               221 官方指南頁索引（標題 + 各節）
│   ├── liff-versions.csv         58 LIFF 版本沿革
│   ├── faq.csv                   92 官方 FAQ 題目與錨點連結
│   ├── url-schemes.csv           44 LINE URL scheme
│   ├── liff-api.csv              35 LIFF SDK v2 API
│   ├── error-codes.csv          226 狀態碼與錯誤訊息
│   ├── limits.csv               114 數值限制
│   ├── products.csv               8 LINE 產品選型
│   ├── channel-tokens.csv         5 存取權杖型別
│   ├── troubleshooting.csv       21 疑難排解
│   ├── reasoning.csv             23 情境建議
│   ├── deprecations.csv          12 已停用功能與替代方案
│   ├── terms.csv                 57 官方術語表，附中文定義
│   ├── glossary.csv             130 中英術語對照（讓中文查詢命中英文資料）
│   ├── emoji.csv / stickers.csv  可用的 emoji 與貼圖 ID
├── references/              11 份主題參考文件
├── scripts/                 5 支工具（純標準函式庫）
└── examples/                Python / Node.js / PHP / LIFF / Flex 範例

tools/                       重建資料集用（不隨技能安裝）
├── fetch_sources.py         抓官方文件 + clone line-openapi → .docs-cache/
├── build_dataset.py         由來源重新產生 line-api/data/*.csv
├── discover_pages.py        走遍站上 HTML 導覽，找出 llms.txt 沒列到的頁面
├── check_links.py           實際打過每一條 doc_url，確認無死連結或轉址
└── audit_coverage.py        逐條比對官方文件與資料集，列出所有覆蓋缺口
```

## 安裝

**Claude Code**

```bash
git clone https://github.com/<you>/line-api-skill.git
cp -r line-api-skill/line-api ~/.claude/skills/line-api
```

之後在 Claude Code 裡輸入 `/line-api`，或直接問「幫我做一個 LINE bot」即可觸發。

**其他 AI 助理**：把 `line-api/` 整個複製進該工具的 skill / rules 目錄即可，
內容是純 Markdown + CSV + Python，沒有任何平台相依。

## 快速試用

```bash
cd line-api

python scripts/search.py --stats
python scripts/search.py "push message"
python scripts/search.py "圖文選單"
python scripts/search.py "429" --domain error

python scripts/validate.py examples/flex/order-receipt.json --as flex
python scripts/test_line.py
```

實際打 LINE API：

```bash
export LINE_CHANNEL_ACCESS_TOKEN=...
python scripts/lineapi.py info
python scripts/lineapi.py quota
python scripts/test_line.py --live
```

## 五支工具

| 工具 | 做什麼 |
|---|---|
| `search.py` | BM25 搜尋 24 個資料域；中文查詢會自動補上英文術語 |
| `validate.py` | 離線驗證訊息 / Flex / request body：型別、必填、typo、enum、上限、已淘汰元件 |
| `signature.py` | webhook 簽章驗證；channel access token（含純 Python 實作的 RS256 JWT） |
| `lineapi.py` | 零依賴 Messaging API client，自動切換 `api.line.me` / `api-data.line.me` |
| `test_line.py` | 42 項離線測試 + 4 項線上測試 |

## 資料怎麼來的

```
https://developers.line.biz/llms.txt
        ↓  tools/fetch_sources.py
231 頁官方文件（多數有 index.html.md；其餘由 HTML 轉換）+ github.com/line/line-openapi
        ↓  tools/build_dataset.py
line-api/data/*.csv  ← 交叉驗證：文件端點 ⊇ OpenAPI 端點
        ↓  tools/check_links.py
每一條 doc_url 實際 HTTP 驗證過（含偵測 SPA 假 200 與轉址）
        ↓  tools/audit_coverage.py
1492 個官方參數區塊逐條回查，確認沒有漏收的欄位、上限、enum 或預設值
```

抓下來的原始文件放在 `.docs-cache/`，**已在 `.gitignore` 中，不會進入版本控制**——
那是 LY Corporation 的內容，本倉庫只發佈萃取後的資料集與自撰的參考文件。

要更新到最新版文件：

```bash
python tools/fetch_sources.py
python tools/build_dataset.py
python tools/check_links.py --md
python tools/audit_coverage.py
python line-api/scripts/test_line.py
```

## 授權

本倉庫程式碼採 MIT。
LINE、LINE Messaging API、LIFF、LINE MINI App 為 LY Corporation 的商標；
本專案與 LY Corporation 無隸屬關係，資料集是對其公開文件與公開 OpenAPI 規格的整理。
