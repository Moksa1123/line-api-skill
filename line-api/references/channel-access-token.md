# Channel access token（四種）

> 官方文件：
> https://developers.line.biz/en/docs/basics/channel-access-token/
> https://developers.line.biz/en/docs/messaging-api/generate-json-web-token/
> 對照表見 `data/channel-tokens.csv`。

## 1. Channel 與 Provider

- **Provider**：提供服務的個人或組織。
- **Channel**：使用 LINE Platform 功能的通道，分成
  `Messaging API channel`、`LINE Login channel`、`LINE MINI App channel`。
- **同一個 LINE 使用者在同一個 provider 底下的所有 channel，`userId` 相同；
  跨 provider 則不同。** 這是綁定會員時最容易踩的雷。

## 2. 四種 channel access token

| 型別 | 效期 | 每個 channel 可同時存在 | 取得方式 |
|---|---|---|---|
| **可指定效期（v2.1）** | 最長 30 天（自訂） | 30 | JWT assertion → `POST /oauth2/v2.1/token` |
| **Stateless** | 15 分鐘 | 不限 | channel ID + secret → `POST /oauth2/v3/token` |
| Short-lived | 30 天 | 30 | channel ID + secret → `POST /v2/oauth/accessToken` |
| Long-lived | 永不過期 | 1 | LINE Developers Console 手動發行 |

發行數量是**分型別各自計算**的；過期的不計入。

### 怎麼選

- **多實例 / serverless / 不想管理 token** → **stateless**（15 分鐘，隨用隨取，不佔額度）。
- **要能主動撤銷、要自訂效期** → **v2.1（JWT）**。
- **只是本機測試** → long-lived（但絕不要用在正式環境）。

## 3. Stateless token（最省事）

```
POST https://api.line.me/oauth2/v3/token
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials
&client_id={channel ID}
&client_secret={channel secret}
```

```json
{ "access_token": "eyJhbGciOi...", "token_type": "Bearer", "expires_in": 900 }
```

```bash
python scripts/signature.py stateless --channel-id 1234567890 --channel-secret <secret>
```

## 4. Channel access token v2.1（JWT）

### 步驟 1：產生 assertion signing key

規格（RFC 7517 JWK）：

- `kty` = `RSA`，2048 bits
- `alg` = `RS256`
- `use` = `sig`（或 `key_ops` = `["verify"]`）
- 上傳到 Console 的**公鑰不可含 `kid`**（`kid` 是 Console 發給你的）

### 步驟 2：到 Console 上傳公鑰，取得 `kid`

LINE Developers Console → channel → Basic settings → Assertion Signing Key。

### 步驟 3：組出 JWT

```jsonc
// header
{ "alg": "RS256", "typ": "JWT", "kid": "536e453c-aa93-4449-8e90-add2608783c6" }

// payload
{
  "iss": "1234567890",            // channel ID
  "sub": "1234567890",            // 必須與 iss 相同
  "aud": "https://api.line.me/",  // 結尾有斜線
  "exp": 1787286638,              // 最多發行後 30 分鐘
  "token_exp": 2592000            // token 效期，最多 30 天
}
```

```bash
python scripts/signature.py jwt   --jwk private.key --channel-id 1234567890 --kid <kid>
python scripts/signature.py token --jwk private.key --channel-id 1234567890 --kid <kid>
```

`scripts/signature.py` 用純標準函式庫實作 RS256（不需要 PyJWT / cryptography），
並會擋掉超過 30 分鐘 / 30 天的設定。

### 步驟 4：換 token

```
POST https://api.line.me/oauth2/v2.1/token
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials
&client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-bearer
&client_assertion={JWT}
```

```json
{ "access_token": "eyJhbGciOi...", "token_type": "Bearer",
  "expires_in": 2592000, "key_id": "sDTOzw5wIfWx..." }
```

### 管理

| 目的 | 端點 |
|---|---|
| 列出所有有效 token 的 key ID | `GET /oauth2/v2.1/tokens/kid` |
| 驗證 token | `GET /oauth2/v2.1/verify` |
| 撤銷 token | `POST /oauth2/v2.1/revoke` |

## 5. User access token（LINE Login）

代表「使用者」而非「channel」，由 LINE Login 授權碼流程取得。

- access token 效期 **30 天**（`expires_in: 2592000`）
- refresh token 效期 **90 天**（自 access token 發行起算）
- 用來呼叫 `GET /v2/profile`、`GET /oauth2/v2.1/userinfo`、`GET /friendship/v1/status`

細節見 [line-login.md](line-login.md)。

## 6. 安全守則

- channel secret 與 access token **絕不能出現在前端 / repo / log**。
- 懷疑外洩就立刻撤銷（long-lived token 只能在 Console 重新發行）。
- 重新發行 channel secret 會使舊的立即失效，包含 webhook 簽章驗證。
- 環境變數命名建議（本 skill 的腳本預設讀這些）：

```
LINE_CHANNEL_ID=
LINE_CHANNEL_SECRET=
LINE_CHANNEL_ACCESS_TOKEN=
```
