# 工具詳細說明

SKILL.md 只放流程與路由；每支工具的完整用法、判斷依據與已知分寸放這裡。
官方依據：[Messaging API reference](https://developers.line.biz/en/reference/messaging-api/)、
[驗證訊息物件](https://developers.line.biz/en/reference/messaging-api/#validate-message-objects-of-a-push-message)。

## `scripts/search.py` — 資料庫搜尋

```bash
python scripts/search.py "push message"                  # 找端點
python scripts/search.py "429" --domain error            # 找錯誤
python scripts/search.py "aspectMode" --domain flex      # 找 Flex 屬性
python scripts/search.py "shareTargetPicker" --domain liff
python scripts/search.py "webhook 收不到" --domain troubleshoot
python scripts/search.py "rich menu" --domain all --format json
```

## `scripts/validate.py` — 離線訊息驗證器

檢查型別、必填、未知屬性（typo）、enum、字數/陣列上限、已淘汰元件，
以及兩類只寫在文件散文、OpenAPI 沒有的規則：

- **網址**：標明「Protocol: HTTPS」的欄位必須是 `https://`；`uri` 與 `linkUri`
  只收 http / https / line / tel 四種 scheme。
- **label**：規格由「action 放在哪」決定，不是由 action 型別決定 ——
  quick reply 必填上限 20、Flex button 必填上限 40、image carousel 選填上限 12。

**`--as webhook` 是唯一方向相反的模式**：驗的是收到的東西，用途是確認
handler 對欄位的假設站不站得住。收訊端的「必填」意思不一樣——規格說 LINE 會送，
不代表你一定收得到（官方自己的 follow 與 message 範例就沒有 `follow` 與 `quoteToken`），
所以那裡只提醒「讀取前先判斷」，不報錯。

```bash
python scripts/validate.py event.json --as webhook
```

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

## `scripts/signature.py` — 簽章與權杖

```bash
# webhook 簽章
python scripts/signature.py verify --secret <channel secret> --body-file body.json --signature <sig>
python scripts/signature.py sign   --secret <channel secret> --body '{"events":[]}'

# channel access token
python scripts/signature.py stateless --channel-id 1234 --channel-secret <secret>   # 15 分鐘
python scripts/signature.py token --jwk private.key --channel-id 1234 --kid <kid>   # v2.1，最長 30 天
```

驗 LINE Login / LIFF 的 ID token（純標準函式庫，兩種簽法都做）：

```python
from signature import verify_id_token
claims = verify_id_token(id_token, channel_id, channel_secret=secret)
```

LINE 的 ID token 有兩種簽法：web 登入流程是 **HS256**（用 channel secret），
LIFF 與原生 App 是 **ES256**（用 JWKS 公鑰、ECDSA P-256）。最常見的錯誤是
「只 base64 解開就相信裡面的 `sub`」—— 那等於沒有驗證，任何人都能自己編一個。
這裡把驗簽與 `iss` / `aud` / `exp` / `nonce` 全部做完，不過就丟例外。

`HS256` 那條已經拿真的 ID token 跟 LINE 的 `/oauth2/v2.1/verify` 對照過，
兩邊判斷一致。`ES256` 的簽章數學過 RFC 6979 的官方向量、金鑰解析拿 LINE
真實 JWKS 的 20 把公鑰驗算過，但**端到端沒有實測**（需要 LIFF 發出來的
token）—— 用在正式環境前請自己測一次。
```

RS256 JWT 以純標準函式庫實作（不需要 PyJWT / cryptography），
並會擋掉超過 30 分鐘的 assertion 與超過 30 天的 token_exp。

## `scripts/lineapi.py` — 零依賴 API client / CLI

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

## `scripts/review.py` — 既有程式碼健檢

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

## `scripts/test_line.py` — 自我測試

```bash
python scripts/test_line.py           # 離線：資料完整性、搜尋、驗證器、簽章、JWT
python scripts/test_line.py --live    # 加上實際呼叫 LINE API（需 access token）
```
