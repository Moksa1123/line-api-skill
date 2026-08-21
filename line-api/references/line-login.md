# LINE Login v2.1

> 官方文件：
> https://developers.line.biz/en/docs/line-login/integrate-line-login/
> https://developers.line.biz/en/reference/line-login/
> 端點見 `data/endpoints.csv`（`api = line-login`）。

LINE Login 是標準的 **OAuth 2.0 授權碼流程 + OpenID Connect**。

## 1. 完整流程

```
1. 導使用者到  https://access.line.me/oauth2/v2.1/authorize?...
2. 使用者同意後，LINE 導回你的 redirect_uri?code=...&state=...
3. 後端用 code 換 access token + ID token  (POST https://api.line.me/oauth2/v2.1/token)
4. 驗證 ID token，取得 userId / displayName / picture / email
```

### 步驟 1：授權 URL

```
https://access.line.me/oauth2/v2.1/authorize
  ?response_type=code
  &client_id={channel ID}
  &redirect_uri={URL encoded callback}
  &state={CSRF 隨機字串}
  &scope=profile%20openid%20email
  &nonce={replay 防護隨機字串}
```

| 參數 | 必填 | 說明 |
|---|---|---|
| `response_type` | ✅ | 固定 `code` |
| `client_id` | ✅ | LINE Login channel 的 **Channel ID** |
| `redirect_uri` | ✅ | 必須與 Console 上登錄的完全一致（要 URL encode） |
| `state` | ✅ | 每次登入產生新的隨機值，回來時比對 → 防 CSRF |
| `scope` | ✅ | 見下表 |
| `nonce` | 選填 | 會原樣放進 ID token → 防 replay |
| `prompt` | 選填 | `consent` 強制再次顯示同意畫面 |
| `bot_prompt` | 選填 | `normal` / `aggressive`，登入時一併邀請加官方帳號好友 |

### Scope 對照

| scope | 拿得到 |
|---|---|
| `profile` | userId、displayName、pictureUrl、statusMessage（呼叫 `/v2/profile`） |
| `openid` | ID token（內含 userId） |
| `profile openid` | ID token 額外含 displayName、picture |
| `profile openid email` | 再加上 email（**需先申請 Email permission**） |

Email 權限要在 Console → LINE Login → OpenID Connect → **Email address permission**
送出申請文件後才會開通。沒申請就給 `email` scope 會拿不到 email。

### 步驟 3：用 code 換 token

```
POST https://api.line.me/oauth2/v2.1/token
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code
&code={授權碼}
&redirect_uri={與步驟 1 完全相同}
&client_id={channel ID}
&client_secret={channel secret}
```

```json
{
  "access_token": "bNl4YEFPI/hjFWhTqexp4...",
  "expires_in": 2592000,
  "id_token": "eyJhbGciOiJIUzI1NiJ9...",
  "refresh_token": "Aa1FdeggRhTnPNNpxr8p",
  "scope": "profile openid email",
  "token_type": "Bearer"
}
```

- access token 效期 30 天。
- refresh token 效期 90 天（自 access token 發行起算）。過期就要重新登入。

> 注意：`POST /oauth2/v2.1/token` 這支端點同時服務兩件事——
> `grant_type=authorization_code` 是 LINE Login 換 user access token，
> `grant_type=client_credentials` + JWT assertion 是 Messaging API 換 channel access token。

## 2. ID token（OpenID Connect）

ID token 是 JWT，**必須驗證後才能信任**。最安全的做法是交給 LINE 驗：

```
POST https://api.line.me/oauth2/v2.1/verify
Content-Type: application/x-www-form-urlencoded

id_token={id_token}
&client_id={channel ID}
&nonce={步驟 1 送出的 nonce}
&user_id={預期的 userId，選填}
```

回傳 payload：

```json
{
  "iss": "https://access.line.me",
  "sub": "U1234567890abcdef...",
  "aud": "1234567890",
  "exp": 1504169092,
  "iat": 1504263657,
  "nonce": "0987654asdf",
  "amr": ["pwd"],
  "name": "Taro Line",
  "picture": "https://sample_line.me/aBcdefg123456",
  "email": "taro.line@example.com"
}
```

- `sub` 就是 **userId**——這是你要存進資料庫綁定會員的值。
- 自行驗證時：`iss` 必須是 `https://access.line.me`、`aud` 必須是你的 channel ID、
  `exp` 未過期、`nonce` 相符，簽章用 channel secret（HS256）或 LINE 的公鑰（ES256）。

## 3. 其他端點

| 目的 | 端點 | 需要 |
|---|---|---|
| 取得使用者 profile | `GET https://api.line.me/v2/profile` | user access token（`profile` scope） |
| OIDC userinfo | `GET https://api.line.me/oauth2/v2.1/userinfo` | user access token |
| 驗證 access token | `GET https://api.line.me/oauth2/v2.1/verify?access_token=...` | — |
| 刷新 access token | `POST https://api.line.me/oauth2/v2.1/token`（`grant_type=refresh_token`） | refresh token |
| 撤銷 access token | `POST https://api.line.me/oauth2/v2.1/revoke` | — |
| 解除授權 | `POST https://api.line.me/user/v1/deauthorize` | user access token |
| 查是否已加官方帳號好友 | `GET https://api.line.me/friendship/v1/status` | user access token（`profile` scope） |

## 4. 常見問題

| 症狀 | 原因 |
|---|---|
| `400 invalid_request` redirect_uri mismatch | callback URL 與 Console 登錄的不完全一致（含結尾斜線、query） |
| 拿不到 email | 沒申請 Email permission，或 scope 沒帶 `email` |
| userId 與 Messaging API 拿到的不同 | 兩個 channel 不在同一個 provider 底下 |
| ID token 驗證失敗 | `aud` 要放 channel ID 不是 channel secret；`nonce` 要與授權時一致 |
| 登入後想自動加好友 | 授權 URL 加 `bot_prompt=aggressive`，並在 Console 綁定官方帳號 |

## 5. 與 LIFF 的關係

在 LINE App 內開啟的網頁，用 **LIFF** 比自己實作 LINE Login 流程簡單得多：
`liff.init()` 之後直接 `liff.getProfile()` / `liff.getIDToken()`。
LIFF app 掛在 LINE Login channel（或 LINE MINI App channel）底下。
見 [liff.md](liff.md)。
