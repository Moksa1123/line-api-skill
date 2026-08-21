/**
 * LINE Bot webhook server（Express，零第三方 SDK）
 *
 * 重點：
 *   1. 用 express.raw() 取得原始 body 來驗簽章 —— 用 express.json() 會驗不過
 *   2. 先回 200，再非同步處理
 *   3. webhookEventId 去重（LINE 未收到 200 會重送）
 *
 * 執行：
 *   npm init -y && npm i express
 *   LINE_CHANNEL_SECRET=... LINE_CHANNEL_ACCESS_TOKEN=... node express_webhook_bot.js
 *   ngrok http 3000
 *
 * 文件：https://developers.line.biz/en/docs/messaging-api/verify-webhook-signature/
 */
const crypto = require("node:crypto");
const express = require("express");

const CHANNEL_SECRET = process.env.LINE_CHANNEL_SECRET;
const CHANNEL_ACCESS_TOKEN = process.env.LINE_CHANNEL_ACCESS_TOKEN;
const API = "https://api.line.me";

if (!CHANNEL_SECRET || !CHANNEL_ACCESS_TOKEN) {
  console.error("請設定 LINE_CHANNEL_SECRET 與 LINE_CHANNEL_ACCESS_TOKEN");
  process.exit(1);
}

const app = express();
const seen = new Set(); // 正式環境請換成 Redis / DB unique index

function verifySignature(rawBody, signature) {
  const expected = crypto
    .createHmac("sha256", CHANNEL_SECRET)
    .update(rawBody)
    .digest("base64");
  const a = Buffer.from(expected);
  const b = Buffer.from(signature || "");
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

async function callLine(method, path, body) {
  const res = await fetch(API + path, {
    method,
    headers: {
      Authorization: `Bearer ${CHANNEL_ACCESS_TOKEN}`,
      "Content-Type": "application/json",
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    console.error(`LINE API ${method} ${path} -> ${res.status}`, await res.text());
    return null;
  }
  const text = await res.text();
  return text ? JSON.parse(text) : {};
}

const reply = (replyToken, messages) =>
  callLine("POST", "/v2/bot/message/reply", { replyToken, messages });

const push = (to, messages) =>
  callLine("POST", "/v2/bot/message/push", { to, messages });

async function handleEvent(event) {
  switch (event.type) {
    case "follow":
      return reply(event.replyToken, [
        { type: "text", text: "感謝加入好友！" },
      ]);

    case "message":
      if (event.message.type === "text") {
        return reply(event.replyToken, [
          {
            type: "text",
            text: `你說了：${event.message.text}`,
            quickReply: {
              items: [
                { type: "action", action: { type: "message", label: "選單", text: "選單" } },
                { type: "action", action: { type: "postback", label: "查訂單", data: "action=orders" } },
              ],
            },
          },
        ]);
      }
      if (event.message.type === "image") {
        // 圖片內容要到 api-data.line.me 下載
        console.log("收到圖片，messageId =", event.message.id);
        return reply(event.replyToken, [{ type: "text", text: "收到圖片了" }]);
      }
      return;

    case "postback":
      return reply(event.replyToken, [
        { type: "text", text: `postback: ${event.postback.data}` },
      ]);

    default:
      console.log("未處理的事件型別：", event.type);
  }
}

// express.raw 讓 req.body 保持 Buffer —— 簽章驗證的前提
app.post("/callback", express.raw({ type: "application/json" }), (req, res) => {
  const signature = req.get("x-line-signature");
  if (!verifySignature(req.body, signature)) {
    return res.status(400).send("invalid signature");
  }

  const payload = JSON.parse(req.body.toString("utf8"));
  res.status(200).send("OK"); // 先回 200

  for (const event of payload.events || []) {
    if (seen.has(event.webhookEventId)) continue; // 重送
    seen.add(event.webhookEventId);
    if (event.mode === "standby") continue;
    handleEvent(event).catch((err) => console.error("處理事件失敗", err));
  }
});

app.get("/health", (_req, res) => res.json({ ok: true }));

const port = process.env.PORT || 3000;
app.listen(port, () => console.log(`listening on :${port}`));
