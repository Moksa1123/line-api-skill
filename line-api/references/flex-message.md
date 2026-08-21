# Flex Message 完整規格

> 官方文件：
> https://developers.line.biz/en/docs/messaging-api/using-flex-messages/
> https://developers.line.biz/en/docs/messaging-api/flex-message-layout/
> 全部元件屬性見 `data/flex-components.csv`（137 筆）。
> 線上排版工具：https://developers.line.biz/flex-simulator/

## 1. 結構

```
flex message
└── contents : FlexContainer
    ├── bubble          單張卡片
    │   ├── header  : box
    │   ├── hero    : box | image | video
    │   ├── body    : box
    │   ├── footer  : box
    │   └── styles  : 各區塊背景 / 分隔線
    └── carousel        多張卡片（最多 12 個 bubble）
        └── contents : [bubble, bubble, ...]
```

```json
{
  "type": "flex",
  "altText": "在通知列與不支援的裝置顯示的文字",
  "contents": { "type": "bubble", "body": { ... } }
}
```

| 欄位 | 必填 | 限制 |
|---|---|---|
| `altText` | ✅ | 最多 1500 字 |
| `contents` | ✅ | bubble 或 carousel |

## 2. bubble

| 屬性 | 型別 | 說明 |
|---|---|---|
| `type` * | `"bubble"` | |
| `size` | `nano` \| `micro` \| `deca` \| `hecto` \| `kilo` \| `mega` \| `giga` | 卡片寬度 |
| `direction` | `ltr` \| `rtl` | 文字方向，預設 `ltr` |
| `header` / `body` / `footer` | box | |
| `hero` | box \| image \| video | 主視覺 |
| `styles` | FlexBubbleStyles | 各區塊背景色與分隔線 |
| `action` | Action | 點整張卡片的動作 |

## 3. 元件（FlexComponent）

`type` 可用值：`box` `text` `span` `image` `video` `icon` `button` `separator` `filler`

> ⚠️ `filler` 已淘汰，請改用 box 的 `margin` / `offset*` / `padding*` 排版。

### box（唯一的容器）

必填：`layout`、`contents`

| 屬性 | 可用值 / 說明 |
|---|---|
| `layout` * | `horizontal` \| `vertical` \| `baseline` |
| `contents` * | 子元件陣列 |
| `flex` | 佔比（整數） |
| `spacing` | `none` `xs` `sm` `md` `lg` `xl` `xxl` 或像素值 |
| `margin` | 同上 |
| `justifyContent` | `flex-start` `center` `flex-end` `space-between` `space-around` `space-evenly` |
| `alignItems` | `flex-start` `center` `flex-end` |
| `paddingAll` / `paddingTop` / `paddingBottom` / `paddingStart` / `paddingEnd` | |
| `backgroundColor` / `borderColor` / `borderWidth` / `cornerRadius` | |
| `width` / `maxWidth` / `height` / `maxHeight` | |
| `position` | `relative` \| `absolute` |
| `offsetTop` / `offsetBottom` / `offsetStart` / `offsetEnd` | 搭配 `position` |
| `background` | 漸層（見下） |
| `action` | 點擊整個 box 的動作 |

### text

| 屬性 | 可用值 |
|---|---|
| `text` | 文字內容（要換行請設 `wrap: true`） |
| `size` | `xxs` `xs` `sm` `md` `lg` `xl` `xxl` `3xl` `4xl` `5xl` 或像素 |
| `weight` | `regular` \| `bold` |
| `style` | `normal` \| `italic` |
| `decoration` | `none` \| `underline` \| `line-through` |
| `align` | `start` \| `end` \| `center` |
| `gravity` | `top` \| `bottom` \| `center` |
| `color` | `#RRGGBB` 或 `#RRGGBBAA` |
| `wrap` | boolean，預設 `false`（**不設就不會換行**） |
| `lineSpacing` | 行距 |
| `maxLines` | 最多顯示幾行，超過以 `...` 截斷 |
| `adjustMode` | `shrink-to-fit` |
| `contents` | span 陣列（同一段文字中混用多種樣式時使用） |

### span（放在 text.contents 內）

`text` `size` `color` `weight` `style` `decoration`

### image

必填：`url`（HTTPS、最多 2000 字）

`size` `aspectRatio`（例：`"20:13"`）`aspectMode`（`cover` \| `fit`）
`align` `gravity` `backgroundColor` `animated` `action`

### video（只能放在 bubble.hero）

必填：`url`、`previewUrl`、`altContent`
選填：`aspectRatio`、`action`

### button

必填：`action`

`style`：`primary` \| `secondary` \| `link`
`height`：`sm` \| `md`
`color`、`gravity`、`adjustMode`、`scaling`

### icon / separator

- `icon`：必填 `url`；常搭配 `layout: baseline` 的 box 做星等、標籤。
- `separator`：`margin`、`color`。

## 4. 漸層背景

```json
{
  "type": "box",
  "layout": "vertical",
  "background": {
    "type": "linearGradient",
    "angle": "45deg",
    "startColor": "#00C300",
    "endColor": "#00A000",
    "centerColor": "#00B000",
    "centerPosition": "50%"
  },
  "contents": []
}
```

## 5. 常見版型骨架

**商品卡（image hero + 內容 + 兩顆按鈕）**

```json
{
  "type": "bubble",
  "hero": {
    "type": "image",
    "url": "https://example.com/item.jpg",
    "size": "full",
    "aspectRatio": "20:13",
    "aspectMode": "cover"
  },
  "body": {
    "type": "box", "layout": "vertical", "spacing": "sm",
    "contents": [
      { "type": "text", "text": "商品名稱", "weight": "bold", "size": "xl", "wrap": true },
      { "type": "box", "layout": "baseline", "contents": [
          { "type": "text", "text": "NT$", "size": "sm", "color": "#AAAAAA", "flex": 0 },
          { "type": "text", "text": "1,280", "size": "xl", "weight": "bold", "margin": "sm" }
      ]},
      { "type": "text", "text": "商品描述文字", "wrap": true, "color": "#666666", "size": "sm" }
    ]
  },
  "footer": {
    "type": "box", "layout": "vertical", "spacing": "sm",
    "contents": [
      { "type": "button", "style": "primary", "height": "sm",
        "action": { "type": "postback", "label": "加入購物車", "data": "action=add&sku=A1" } },
      { "type": "button", "style": "link", "height": "sm",
        "action": { "type": "uri", "label": "查看詳情", "uri": "https://example.com/item" } }
    ]
  }
}
```

**橫向兩欄（左標籤右內容）**

```json
{ "type": "box", "layout": "horizontal", "contents": [
  { "type": "text", "text": "日期", "color": "#AAAAAA", "size": "sm", "flex": 2 },
  { "type": "text", "text": "2026-08-21", "wrap": true, "size": "sm", "flex": 5 }
]}
```

## 6. 常見錯誤

| 症狀 | 原因 |
|---|---|
| 送出回 400 `The request body has N error(s)` | box 缺 `layout`、text 缺 `text`、component 缺 `type` |
| 長文字被截斷成一行 | text 沒設 `wrap: true` |
| carousel 只顯示部分 | 超過 12 個 bubble |
| 圖片破圖 | `url` 不是 HTTPS（TLS 1.2+）或不是 JPEG/PNG |
| `alignItems` 沒作用 | 只有 box 有，且要配合 `layout` |
| 通知列顯示奇怪文字 | 忘了設有意義的 `altText` |

**送出前先驗證：**

```bash
python scripts/validate.py flex.json --as flex        # 離線，含 enum / 必填 / 上限
python scripts/lineapi.py validate-push --json m.json # LINE 官方驗證端點
```

`validate.py` 會直接指出路徑，例如：

```
❌ [error] $.contents.body.layout      缺少必填屬性 layout
❌ [error] $.contents.body.contents[0].weight   值 'extra-bold' 不合法，可用值：regular, bold
```

## 7. 查任何屬性

```bash
python scripts/search.py "aspectMode" --domain flex
python scripts/search.py "justifyContent" --domain flex
python scripts/search.py "linearGradient" --domain flex
```
