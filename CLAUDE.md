# CLAUDE.md

給 Claude Code（claude.ai/code）在這個 repo 工作時的指引。

## 專案性質

`line-api-skill` 是一個 **AI skill 包**，不是應用程式。
它把 LINE Platform 的官方文件與 OpenAPI 規格萃取成可搜尋的資料集，
讓 AI 助理能查證後再回答 LINE API 問題。

**Source of truth 是 `line-api/`。** 其餘目錄都是為了產生或驗證它。

## 目錄職責

```
line-api/            ← 要發佈的技能本體（複製到 ~/.claude/skills/line-api）
  SKILL.md             技能說明；AI 進來先讀這份
  EXAMPLES.md          範例索引
  data/*.csv           產生物，不要手改「自動產生」的那幾份（見下表）
  references/*.md      人工撰寫，內容必須有官方文件佐證
  scripts/*.py         技能工具，只用標準函式庫
  examples/            可執行範例

tools/               ← 只在這個 repo 用，不隨技能安裝
  fetch_sources.py     抓來源到 .docs-cache/
  build_dataset.py     由 .docs-cache/ 產生 line-api/data/*.csv
  discover_pages.py    走站上 HTML 導覽，找出 llms.txt 漏列的頁面
  check_links.py       驗證所有 doc_url
  audit_coverage.py    逐條比對官方文件與資料集的覆蓋缺口
  check_docs.py        確認文件寫的數字與實際資料一致

.docs-cache/         ← 抓下來的官方文件與 line-openapi。git 忽略，絕不 commit
```

## 資料檔是產生的還是手寫的

| 檔案 | 來源 | 可以手改嗎 |
|---|---|---|
| `endpoints.csv` | 官方 reference + OpenAPI 交叉驗證 | ❌ 改 `tools/build_dataset.py` |
| `parameters.csv` | reference 的 `<!-- parameter -->` 區塊 | ❌ |
| `message-objects.csv` | OpenAPI `Message` / `Template` 判別聯集 | ❌ |
| `flex-components.csv` | OpenAPI `FlexComponent` / `FlexContainer` | ❌ |
| `actions.csv` / `richmenu.csv` | OpenAPI schema | ❌ |
| `webhook-events.csv` | `webhook.yml` discriminator | ❌ |
| `webhook-properties.csv` | `webhook.yml` 全部聯集與具名物件 | ❌ |
| `responses.csv` | OpenAPI 各 operation 的 2xx 回應 schema | ❌ |
| `guides.csv` | `docs/**/*.md` 的標題與各節標題 | ❌ |
| `liff-versions.csv` | LIFF release notes 的版本、日期、API | ❌ |
| `faq.csv` | `faq.md` 的題目、標籤與 HTML 錨點 | ❌ |
| `sdk-api.csv` | jazzy / javadoc 索引頁的型別清單 | ❌ |
| `url-schemes.csv` | 人工撰寫（scheme 取自官方，用途自行說明） | ✅ |
| `liff-api.csv` | LIFF reference 的 `### liff.*` 區塊 | ❌ |
| `parameters.csv` 的 liff 部分 | `liff.md` 的參數區塊 | ❌ |
| `error-codes.csv` / `limits.csv` | reference 表格 + OpenAPI 約束 | ❌ |
| `emoji.csv` / `stickers.csv` | emoji-list / sticker-list 頁面 | ❌ |
| `products.csv` | 人工撰寫 | ✅ |
| `channel-tokens.csv` | 人工撰寫 | ✅ |
| `troubleshooting.csv` | 人工撰寫 | ✅ |
| `reasoning.csv` | 人工撰寫 | ✅ |
| `deprecations.csv` | 人工撰寫 | ✅ |
| `glossary.csv` | 人工撰寫（中英術語對照） | ✅ |
| `terms.csv` | 人工撰寫（官方術語的中文定義；錨點須與官方一致） | ✅ |

改自動產生的資料要改產生器，然後重跑：

```bash
python tools/build_dataset.py
python line-api/scripts/test_line.py
```

## 開發規則

1. **不要憑記憶寫 LINE 的規格。** 任何數字、欄位名、enum 值都要能在
   `.docs-cache/raw/` 或 `line-openapi/*.yml` 找到出處。找不到就不要寫。
2. **腳本只用 Python 標準函式庫。** 技能會被複製到別人的環境，不能要求裝套件。
   （`tools/build_dataset.py` 例外，它需要 PyYAML，但只有維護者會跑。）
3. **新增 reference 檔一定要同時加進 `REF_FILES`。**
   `liff.md` 曾經被抓下來卻沒列入處理清單，結果整個 LIFF 客戶端 SDK 的
   92 個參數區塊都不存在，而所有測試依然是綠的。
   `tools/audit_coverage.py` 的 [S] 區塊與 `test_line.py` 現在都會擋這種情況。
4. **解析文件時要略過 ``` 程式碼區塊。**
   官方 shell 範例裡有 `# Example of ...` 這種註解，長得跟 h1 標題一樣，
   會讓解析器誤判章節結束。統一走 `fence_mask()`。
5. **每筆資料都要有 `doc_url`**，且必須通過 `tools/check_links.py`。
   developers.line.biz 是 Nuxt SPA，不存在的路徑也會回 200，
   所以檢查器會看 `data-ssr` 與 redirect meta，不要簡化成只看狀態碼。
6. **`.docs-cache/` 永遠不 commit。** 那是 LY Corporation 的內容。
7. **改任何東西後跑測試**：`python line-api/scripts/test_line.py`。
   有 channel access token 時再跑一次 `--live`。
8. **憑證不進 repo**：`.env`、`*.key`、`*.jwk` 都已在 `.gitignore`。
   範例一律用 `os.environ[...]` 讀。

## 常用指令

```bash
# 重建整條資料管線
python tools/fetch_sources.py          # 需要網路，約 231 頁 + git clone
python tools/build_dataset.py
python tools/check_links.py --md
python tools/audit_coverage.py      # A/B/C/E 應為 0（Template 基底除外）
python tools/check_docs.py          # 文件數字過期會 exit 1，--fix 可自動更正

# 測試
python line-api/scripts/test_line.py            # 離線 45 項
python line-api/scripts/test_line.py --live     # 加 6 項實打 LINE API

# 技能本身的工具
python line-api/scripts/search.py "<query>" [--domain <domain>]
python line-api/scripts/validate.py <file.json> [--as flex|push|reply|...]
python line-api/scripts/review.py <file-or-dir> [--min-severity error]
python line-api/scripts/signature.py verify --secret <s> --body-file b.json --signature <sig>
python line-api/scripts/lineapi.py info
```

## 測試涵蓋什麼

`line-api/scripts/test_line.py` 的離線部分會擋住這些回歸：

- 資料檔缺漏、空檔、CSV 欄位數不一致
- 端點少於 110 筆、重複端點、host/path/doc_url 格式錯誤
- 內容類端點沒有指向 `api-data.line.me`
- 20 種 webhook 事件、訊息/Flex/action 判別值缺漏
- 抽查的限制值（push 5 則、multicast 500、quick reply 13、chatBarText 14…）
- 搜尋引擎：英文查詢命中正確端點、中文查詢經術語表命中英文資料
- 驗證器：9 類錯誤（type 錯、缺必填、超長、typo、enum 錯、巢狀 action 錯、陣列超量…）
- 簽章與 RS256 JWT 與獨立實作結果一致
- 所有範例 JSON 驗證零 error 零 warning、Python 範例語法正確
- 輪播三層限制（template 10 欄 / 每欄 3 動作 / Flex 12 bubble）與條件式 text 上限
- Flex 容器體積（bubble 30KB、carousel 50KB）與同一輪播內 bubble 寬度一致
- 只寫在文件散文裡的 enum 與預設值（imageAspectRatio、imageSize…）有進資料集
- camelCase 與點號識別字可用子詞查到（查 multicast 要找得到 MulticastRequest.to）
- webhook 逐欄位表涵蓋所有事件，且共同屬性型別正確
- review.py 對自家 `examples/` 零誤報，且七類問題（拼錯的端點、錯的主機、
  寫死的憑證、簽章三種寫法、已停服 API、訊息 JSON 錯字）一個都不漏

新增功能請一併補測試。

## Git

- 不要直接 push 到 `main`；開 `feat/...` 或 `fix/...` 分支後開 PR。
- commit 前確認 `git status` 沒有 `.docs-cache/` 或憑證檔。
