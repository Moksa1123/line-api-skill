# 圖文選單（Rich Menu）

> 官方文件：
> https://developers.line.biz/en/docs/messaging-api/using-rich-menus/
> https://developers.line.biz/en/docs/messaging-api/switch-rich-menus/
> 欄位見 `data/richmenu.csv`；端點見 `data/endpoints.csv`。

## 1. 建立流程（四步）

```
1. POST   /v2/bot/richmenu                       建立選單物件 → 拿到 richMenuId
2. POST   api-data /v2/bot/richmenu/{id}/content 上傳圖片   ← 注意是 api-data.line.me
3. POST   /v2/bot/user/all/richmenu/{id}         設為預設選單
   或 POST /v2/bot/user/{userId}/richmenu/{id}   綁給特定使用者
4. （選用）POST /v2/bot/richmenu/alias           建立 alias 供切換用
```

圖片**上傳後不能替換**。要換圖就重建一個 rich menu。

## 2. 圖片規格（不符會 400）

- 格式：JPEG 或 PNG
- 寬：800 ～ 2500 px
- 高：250 px 以上
- 寬高比（width / height）：**1.45 以上**
- 檔案大小：**1 MB 以內**

常用尺寸：`2500 × 1686`（大型）、`2500 × 843`（小型）。

`scripts/lineapi.py richmenu-upload` 會在上傳前先擋掉格式與大小錯誤。

## 3. Rich menu 物件

```json
{
  "size": { "width": 2500, "height": 1686 },
  "selected": false,
  "name": "主選單 v1",
  "chatBarText": "開啟選單",
  "areas": [
    {
      "bounds": { "x": 0, "y": 0, "width": 1250, "height": 843 },
      "action": { "type": "postback", "label": "查訂單", "data": "action=orders" }
    },
    {
      "bounds": { "x": 1250, "y": 0, "width": 1250, "height": 843 },
      "action": { "type": "uri", "label": "官網", "uri": "https://example.com" }
    }
  ]
}
```

| 欄位 | 說明 | 限制 |
|---|---|---|
| `size` | 必須與圖片尺寸一致 | |
| `selected` | 預設是否展開 | |
| `name` | 後台辨識用，使用者看不到 | 300 字 |
| `chatBarText` | 聊天室下方的按鈕文字 | **14 字** |
| `areas` | 可點擊區塊 | **最多 20 個** |
| `areas[].bounds` | 以圖片左上角為原點的像素座標 | |
| `areas[].action` | 任何 action 物件 | |

建立前可先驗證：

```
POST /v2/bot/richmenu/validate
```

## 4. 綁定

| 目的 | 端點 |
|---|---|
| 設為全體預設 | `POST /v2/bot/user/all/richmenu/{richMenuId}` |
| 取消全體預設 | `DELETE /v2/bot/user/all/richmenu` |
| 綁給單一使用者 | `POST /v2/bot/user/{userId}/richmenu/{richMenuId}` |
| 解除單一使用者 | `DELETE /v2/bot/user/{userId}/richmenu` |
| 批次綁定（≤500 人） | `POST /v2/bot/richmenu/bulk/link` |
| 批次解除（≤500 人） | `POST /v2/bot/richmenu/bulk/unlink` |
| 大量替換 / 解除 | `POST /v2/bot/richmenu/batch`（最多 1000 個 operation，非同步） |
| 查批次進度 | `GET /v2/bot/richmenu/progress/batch` |

優先序：**個人選單 > 預設選單**。

## 5. 分頁切換（alias + richmenuswitch）

要做「選單 A ⇄ 選單 B」的分頁效果：

```
1. 建立 rich menu A、B（各自上傳圖片）
2. POST /v2/bot/richmenu/alias  { "richMenuAliasId": "menu-a", "richMenuId": "richmenu-A..." }
3. POST /v2/bot/richmenu/alias  { "richMenuAliasId": "menu-b", "richMenuId": "richmenu-B..." }
4. 在 A 的某個 area 放：
   { "type": "richmenuswitch", "richMenuAliasId": "menu-b", "data": "switch-to-b" }
5. 把 A 綁給使用者
```

- alias 每個官方帳號最多 **1000 個**。
- 切換時會送出 `postback` 事件，`postback.params` 帶
  `newRichMenuAliasId` 與 `status`。
- 切換不需重新呼叫 link API，體感即時。

## 6. 成效

```
GET /v2/bot/insight/richmenu/{richMenuId}/summary?from=20260801&to=20260821
GET /v2/bot/insight/richmenu/{richMenuId}/daily?from=20260801&to=20260821
```

## 7. 常見錯誤

| 症狀 | 原因 |
|---|---|
| 上傳圖片 404 / 連線失敗 | 打到 `api.line.me`，應該是 `api-data.line.me` |
| 上傳回 400 | 圖片格式、尺寸、比例或大小不符（見第 2 節） |
| 選單建立成功但看不到 | 沒有上傳圖片，或沒有 link 給使用者 |
| `chatBarText` 被拒 | 超過 14 字 |
| 點了沒反應 | `bounds` 座標超出圖片範圍，或 `areas` 超過 20 個 |
| 換圖沒生效 | 圖片不可替換，必須重建 rich menu |

```bash
python scripts/lineapi.py richmenu-list
python scripts/search.py "rich menu" --domain endpoint --max 10
python scripts/search.py "richmenuswitch" --domain action
```
