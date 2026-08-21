# 官方 SDK 與開發工具

> 官方文件：https://developers.line.biz/en/docs/messaging-api/line-bot-sdk/
> LINE 的 GitHub 組織：https://github.com/orgs/line/repositories

## 1. 官方 Messaging API SDK

| 語言 | Repo |
|---|---|
| Python | https://github.com/line/line-bot-sdk-python |
| Node.js | https://github.com/line/line-bot-sdk-nodejs |
| PHP | https://github.com/line/line-bot-sdk-php |
| Java | https://github.com/line/line-bot-sdk-java |
| Go | https://github.com/line/line-bot-sdk-go |
| Ruby | https://github.com/line/line-bot-sdk-ruby |

已封存不再更新：Perl（https://github.com/line/line-bot-sdk-perl）。

其他語言可用 **LINE OpenAPI** 自行產生 client：

- https://github.com/line/line-openapi
- 搭配 [OpenAPI Generator](https://github.com/OpenAPITools/openapi-generator) 或
  Swagger Codegen。

> 本 skill 的 `data/*.csv` 就是從 `line/line-openapi` 與官方文件自動萃取的，
> 所以欄位名稱與型別與官方 SDK 完全一致。

## 2. LINE Login / LIFF SDK

| 用途 | Repo / 位址 |
|---|---|
| LIFF SDK v2 | `https://static.line-scdn.net/liff/edge/2/sdk.js` |
| LIFF CLI | https://github.com/line/liff-cli |
| 建立 LIFF 專案 | https://github.com/line/create-liff-app |
| LIFF Inspector（真機除錯） | https://github.com/line/liff-inspector |
| LIFF Mock（單元測試） | https://github.com/line/liff-mock |
| LIFF Playground | https://github.com/line/liff-playground |
| LIFF v2 Starter | https://github.com/line/line-liff-v2-starter |
| iOS（Swift） | https://github.com/line/line-sdk-ios-swift |
| Android | https://github.com/line/line-sdk-android |
| Flutter | https://github.com/line/flutter_line_sdk |

## 2.1 行動 SDK 的型別清單

iOS 與 Android SDK 的 API reference 是產生器輸出的獨立網站（jazzy / javadoc），
`data/sdk-api.csv` 收了它們的 80 個型別與連結：

```bash
python scripts/search.py "LoginManager" --domain sdk_api
python scripts/search.py "LineApiClient" --domain sdk_api
python scripts/search.py "LineSDKError" --domain sdk_api
```

| 平台 | 數量 | 常用型別 |
|---|---:|---|
| iOS (Swift) | 58 | `LoginManager`、`LoginButton`、`Session`、`LineSDKError`（含四種 ErrorReason）、`API.Auth` |
| Android | 22 | `LineApiClient`、`LineLoginApi`、`LineAuthenticationParams`（含 `Builder` / `BotPrompt`）、`LineApiError.ErrorCode` |

## 3. 線上工具

| 工具 | 位址 |
|---|---|
| LINE Developers Console | https://developers.line.biz/console/ |
| LINE Official Account Manager | https://manager.line.biz/ |
| Flex Message Simulator | https://developers.line.biz/flex-simulator/ |
| LINE API Status | https://developers.line.biz/en/docs/basics/line-api-status/ |
| Bot Designer（對話流程設計） | https://developers.line.biz/en/docs/messaging-api/using-bot-designer/ |

## 4. LINE Bot MCP Server

LINE 官方提供的 MCP server，可讓 AI 助理直接操作 Messaging API：

- https://github.com/line/line-bot-mcp-server

## 5. 本 skill 提供的工具

| 腳本 | 用途 |
|---|---|
| `scripts/search.py` | 在 2600+ 筆資料中做 BM25 搜尋（中英皆可） |
| `scripts/validate.py` | 離線驗證訊息 / Flex / request body |
| `scripts/signature.py` | webhook 簽章驗證、channel access token（含純 Python RS256 JWT） |
| `scripts/lineapi.py` | 零依賴 Messaging API client / CLI |
| `scripts/test_line.py` | 自我測試（離線 + `--live` 實打 LINE API） |

倉庫層工具（重建資料集用，不隨 skill 安裝）：

| 工具 | 用途 |
|---|---|
| `tools/fetch_sources.py` | 抓官方文件 Markdown + SDK 索引頁 + clone line-openapi 到 `.docs-cache/` |
| `tools/discover_pages.py` | 走站上 HTML 導覽，找出 llms.txt 沒列到的頁面 |
| `tools/build_dataset.py` | 由上述來源重新產生 `line-api/data/*.csv` |
| `tools/check_links.py` | 實際打過每一條 doc_url，確認沒有死連結或轉址 |
| `tools/audit_coverage.py` | 逐條比對官方文件與資料集，列出所有覆蓋缺口 |
| `tools/check_docs.py` | 確認文件寫的數字與實際資料一致（`--fix` 可自動更正） |

```bash
python tools/fetch_sources.py     # 更新來源（.docs-cache/ 不進 git）
python tools/build_dataset.py     # 重新產生資料集
python tools/check_links.py --md  # 驗證所有連結
python tools/audit_coverage.py    # 覆蓋率缺口
python tools/check_docs.py        # 文件數字是否過期
python line-api/scripts/test_line.py --live
```

## 6. 建議的執行環境

- Python 3.9+（本 skill 的腳本只用標準函式庫）
- 對外要有 HTTPS webhook：ngrok / Cloudflare Tunnel / 任何雲端 PaaS
- 正式環境務必把 channel secret 與 access token 放環境變數，不要進 repo
