# 錯誤碼、限制與計費

> 官方文件：
> https://developers.line.biz/en/reference/messaging-api/#status-codes
> https://developers.line.biz/en/docs/messaging-api/pricing/
> 全部 226 筆錯誤見 `data/error-codes.csv`；114 條數值限制見 `data/limits.csv`。

## 1. HTTP 狀態碼（Messaging API）

| 狀態碼 | 意義 | 怎麼處理 |
|---|---|---|
| `200` | 成功 | |
| `400` | request 有問題 | 讀 `details[].property` 找出錯欄位 |
| `401` | 沒有有效的 channel access token | 檢查 token 是否過期 / 屬於這個 channel |
| `403` | 無權限使用此資源 | 帳號方案或申請狀態不足 |
| `404` | 找不到（多半是取 profile 時使用者未加好友/未同意） | 視為正常情境，要能 fallback |
| `409` | 同一個 retry key 已被受理 | 冪等生效，讀 `X-Line-Accepted-Request-Id` |
| `410` | 資源已不存在 | |
| `413` | request 超過 2MB | 縮小 payload |
| `415` | 上傳的媒體型別不支援 | |
| `429` | 超過 rate limit **或** 訊息額度用完 | 兩者要分開判斷（見下） |
| `500` | LINE 端錯誤 | 退避重試 |

## 2. 錯誤 body 與常見 message

```json
{
  "message": "The request body has 2 error(s)",
  "details": [
    { "message": "May not be empty", "property": "messages[0].text" }
  ]
}
```

| `message` | 意義 |
|---|---|
| `The request body has X error(s)` | JSON 欄位錯，看 `details` |
| `Invalid reply token` | replyToken 過期或已用過 |
| `The property, XXX, in the request body is invalid` | 指定欄位不合法 |
| `The request body could not be parsed as JSON` | JSON 格式錯 |
| `Authentication failed due to the following reason: XXX` | token 問題 |
| `Access to this API is not available for your account` | 帳號無此 API 權限 |
| `Failed to send messages` | 例如指定的 userId 不存在 |
| `You have reached your monthly limit.` | **額度用完**（不是 rate limit） |
| `The API rate limit has been exceeded. Try again later.` | **rate limit** |
| `Not found` | 取不到 profile（未加好友 / 未同意 / 已封鎖） |

分辨 429 的兩種情況：

```python
if resp.status == 429:
    if "monthly limit" in body.get("message", ""):
        ...   # 額度用完 → 升級方案或改用 reply
    else:
        ...   # rate limit → 退避重試
```

```bash
python scripts/search.py "Invalid reply token" --domain error
python scripts/search.py "429" --domain error --max 5
```

## 3. Rate limit

- 多數送訊端點：**2,000 requests/second**
- 查詢類端點較低，逐支不同
- 另有「同時併發操作數」上限

每支端點的實際值：

```bash
python scripts/search.py "get profile" --domain endpoint --max 1
python scripts/search.py "narrowcast" --domain endpoint --max 1
```

## 4. 常用數值限制速查

| 項目 | 上限 |
|---|---|
| 一次 API 送出的訊息物件數 | 5 |
| multicast 收訊者 | 500 |
| Quick reply 按鈕 | 13 |
| Flex carousel bubble | 12 |
| Flex `altText` | 1500 字 |
| 文字訊息 `text` | 5000 字 |
| 文字訊息 `emojis` | 20 個 |
| Imagemap `actions` | 50 |
| Rich menu `areas` | 20 |
| Rich menu `chatBarText` | 14 字 |
| Rich menu `name` | 300 字 |
| Rich menu 圖片 | JPEG/PNG、寬 800–2500、高 ≥250、比例 ≥1.45、≤1MB |
| Rich menu alias（每個官方帳號） | 1000 |
| Rich menu bulk link 一次人數 | 500 |
| Rich menu batch operations | 1000 |
| postback / datetimepicker `data` | 300 字 |
| `clipboardText` | 1000 字 |
| Sender `name` | 20 字 |
| Loading animation 秒數 | 5–60 |
| Webhook URL 長度 | 500 字 |
| Request body 總大小 | 2 MB |
| 圖片訊息原圖 / 預覽圖 | 10 MB / 1 MB |
| 影片、音訊檔 | 200 MB |
| LIFF app（每個 channel） | 30 |
| Reply token 有效期 | 1 分鐘，且只能用一次 |
| Channel access token v2.1 效期 | 最長 30 天；JWT assertion 最長 30 分鐘 |
| Stateless channel access token 效期 | 15 分鐘 |

```bash
python scripts/search.py "maxItems" --domain limit --max 20
python scripts/search.py "richmenu" --domain limit --max 10
```

## 5. 計費（Messaging API）

- **reply message 不計入額度**，push / multicast / broadcast / narrowcast 會計入。
- 一次送 3 個訊息物件給 1 人 = 3 則計費訊息。
- 免費額度與加購上限依方案與地區而異，見
  https://developers.line.biz/en/docs/messaging-api/pricing/

查目前額度：

```bash
python scripts/lineapi.py quota          # 本月上限
python scripts/lineapi.py consumption    # 已使用
```

**省額度的設計原則**

1. 能用 reply 就不要用 push。
2. 多則訊息合併成一則 Flex Message。
3. 分眾用 narrowcast，不要 broadcast 全體。
4. 對已知名單用 multicast（500 人一批），不要迴圈 push。

## 6. 疑難排解

```bash
python scripts/search.py "收不到" --domain troubleshoot
python scripts/search.py "簽章" --domain troubleshoot
python scripts/search.py --domain troubleshoot "圖片" --max 5
```

21 個常見問題的症狀 / 原因 / 解法在 `data/troubleshooting.csv`。
