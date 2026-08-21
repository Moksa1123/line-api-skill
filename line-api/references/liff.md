# LIFF（LINE Front-end Framework）v2

> 官方文件：
> https://developers.line.biz/en/docs/liff/overview/
> https://developers.line.biz/en/reference/liff/
> 全部 35 個 API 見 `data/liff-api.csv`。

LIFF 是在 LINE 內建瀏覽器（LIFF browser）執行的網頁 App，
可以直接取得使用者 profile、把訊息送回聊天室、掃 QR code。

> LIFF v1 已於 **2021-10-01 停止服務**，只能用 v2。

## 1. 建立 LIFF app

1. Console 建立 **LINE Login channel**（或 LINE MINI App channel）
2. LIFF 分頁 → Add
3. 設定：
   - **Endpoint URL**：你的網頁網址（必須 HTTPS）
   - **Size**：`compact`（50%）/ `tall`（80%）/ `full`（100%）
   - **Scope**：`profile` / `openid` / `email` / `chat_message.write`
   - **Bot link feature**：登入時是否邀請加官方帳號好友
4. 取得 **LIFF ID**，網址是 `https://liff.line.me/{liffId}`

也可用 Server API 管理（需 channel access token）：

| 目的 | 端點 |
|---|---|
| 新增 LIFF app（單一 channel 最多 30 個） | `POST https://api.line.me/liff/v1/apps` |
| 更新設定 | `PUT https://api.line.me/liff/v1/apps/{liffId}` |
| 列出全部 | `GET https://api.line.me/liff/v1/apps` |
| 刪除 | `DELETE https://api.line.me/liff/v1/apps/{liffId}` |

## 2. 最小可用範例

```html
<script charset="utf-8" src="https://static.line-scdn.net/liff/edge/2/sdk.js"></script>
<script>
async function main() {
  try {
    await liff.init({ liffId: "1234567890-AbcdEfgh" });

    if (!liff.isLoggedIn()) {
      liff.login({ redirectUri: location.href });
      return;                       // login() 會導頁，後面不會執行
    }

    const profile = await liff.getProfile();
    console.log(profile.userId, profile.displayName, profile.pictureUrl);

    // ID token 給後端驗證，別直接信任前端傳來的 userId
    const idToken = liff.getIDToken();
    await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ idToken }),
    });
  } catch (err) {
    console.error("LIFF error", err.code, err.message);
  }
}
main();
</script>
```

**安全提醒**：前端拿到的 `userId` 可被竄改。後端要用
`POST https://api.line.me/oauth2/v2.1/verify`（帶 `id_token` + `client_id`）
驗證 ID token，取 `sub` 當作可信的 userId。

## 3. 常用 API

### 環境判斷

| API | 回傳 |
|---|---|
| `liff.isInClient()` | 是否在 LINE App 內（LIFF browser） |
| `liff.isLoggedIn()` | 是否已登入 |
| `liff.getOS()` | `ios` / `android` / `web` |
| `liff.getLineVersion()` | LINE App 版本（外部瀏覽器回 `null`） |
| `liff.getAppLanguage()` | LINE App 的語系（**建議用這個**） |
| `liff.getLanguage()` | ⚠️ 已淘汰，回的是瀏覽器語系 |
| `liff.getContext()` | `type`（`utou`/`group`/`room`/`external`）、`viewType`、`userId`、`liffId` 等 |
| `liff.isApiAvailable(name)` | 該 API 在目前環境是否可用 |

### 認證

`liff.login()` `liff.logout()` `liff.getAccessToken()` `liff.getIDToken()`
`liff.getDecodedIDToken()`
`liff.permission.query()` `liff.permission.requestAll()` `liff.permission.getGrantedAll()`

### Profile / 好友

`liff.getProfile()` → `{ userId, displayName, pictureUrl, statusMessage }`
`liff.getFriendship()` → `{ friendFlag: boolean }`（是否已加該官方帳號好友）
`liff.requestFriendship()`

### 視窗

```js
liff.openWindow({ url: "https://example.com", external: true });  // 用外部瀏覽器開
liff.closeWindow();                                              // 關閉 LIFF
```

### 送訊息

```js
// 送到「開啟這個 LIFF 的那個聊天室」
await liff.sendMessages([{ type: "text", text: "已完成預約 ✅" }]);

// 讓使用者挑選要分享給誰
const res = await liff.shareTargetPicker(
  [{ type: "text", text: "揪團囉" }],
  { isMultiple: true }
);
```

`sendMessages()` 的條件：
- 必須在 **LIFF browser** 內（`liff.isInClient() === true`）
- LIFF app 必須有 `chat_message.write` scope
- 必須是**從聊天室開啟**的（`liff.getContext().type` 不是 `external`）

先判斷再呼叫：

```js
if (liff.isApiAvailable("shareTargetPicker")) { ... }
```

### 掃碼

```js
const result = await liff.scanCodeV2();   // { value: "..." }
```

只在 LIFF browser 可用；`liff.scanCode()` 是舊版，已淘汰。

### 永久連結

```js
liff.permanentLink.createUrlBy("https://example.com/path?a=1");
liff.permanentLink.setExtraQueryParam("from=richmenu");
```

## 4. 環境差異（最容易踩雷）

| 開啟方式 | `isInClient()` | `sendMessages` | `scanCodeV2` | `shareTargetPicker` |
|---|---|---|---|---|
| LINE 聊天室內點連結（LIFF browser） | `true` | ✅ | ✅ | ✅ |
| LINE 內建瀏覽器（LINE IAB） | `false` | ❌ | ❌ | ❌ |
| 外部瀏覽器（Chrome / Safari） | `false` | ❌ | ❌ | ❌ |

一律用 `liff.isApiAvailable()` 判斷後再呼叫，並準備 fallback。

## 5. 常見錯誤

| 症狀 | 原因 |
|---|---|
| `liff.init()` 失敗、白畫面 | LIFF ID 錯，或目前網址不在 Endpoint URL 的路徑底下 |
| 一直重複導向登入 | `liff.login()` 後沒有 `return`，或 `redirectUri` 不在 Endpoint URL 底下 |
| 拿不到 email | Console 沒申請 Email permission，或 scope 少了 `openid email` |
| `sendMessages` 拋錯 | 不在 LIFF browser、缺 `chat_message.write`、或從外部開啟 |
| 本機開發不能用 | LIFF 需要 HTTPS；用 `ngrok` 或官方 `@line/liff-cli` |

## 6. 開發工具

```bash
npm i -g @line/liff-cli      # 本機 HTTPS 代理、切換 LIFF 設定
npx @line/create-liff-app    # 專案腳手架（React/Vue/Svelte/Next/Nuxt）
```

- LIFF Inspector：https://github.com/line/liff-inspector
- LIFF Mock（測試用）：https://github.com/line/liff-mock
- LIFF Playground：https://github.com/line/liff-playground

```bash
python scripts/search.py "shareTargetPicker" --domain liff
python scripts/search.py "getContext" --domain liff
python scripts/search.py "availability" --domain parameter   # getContext 的回傳欄位
```

## 7. 每個 API 還帶三個實用欄位

`data/liff-api.csv` 除了說明與語法，每個 API 還記了：

| 欄位 | 意義 |
|---|---|
| `introduced_in` | 最早出現在哪個 LIFF 版本（29/35 有值） |
| `before_init` | 能不能在 `liff.init()` 之前呼叫 |
| `module` | 可搖樹匯入的模組名 |

**可在 `liff.init()` 之前呼叫的只有這 8 個**：
`liff.ready`、`liff.getOS()`、`liff.getAppLanguage()`、`liff.getLanguage()`、
`liff.getVersion()`、`liff.getLineVersion()`、`liff.isInClient()`、`liff.closeWindow()`

其餘一律要等 `init()` resolve 之後才能用。

**版本需求**（完整清單見 `data/liff-versions.csv`，58 個版本）：

```bash
python scripts/search.py "scanCodeV2" --domain liff        # → introduced_in 2.15.0
python scripts/search.py "2.15.0" --domain liff_version
```

**模組化匯入**（只打包用得到的功能）：

```js
import liff from "@line/liff/core";
import getProfile from "@line/liff/get-profile";
import shareTargetPicker from "@line/liff/share-target-picker";

liff.use(new GetProfile());
```

26 個模組的對照見 `data/liff-api.csv` 的 `module` 欄位。
`liff.id`、`liff.ready`、`init()`、`getVersion()`、`use()`、`requestFriendship()`
官方沒有列出專屬模組，該欄留白。
