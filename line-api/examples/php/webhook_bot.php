<?php
/**
 * LINE Bot webhook（純 PHP，無需 SDK）
 *
 * 適合放進 WordPress / WooCommerce 或任何 PHP 專案。
 * 重點：
 *   1. 用 php://input 取原始 body 驗簽章（不要用 $_POST 或 json_decode 後再 encode）
 *   2. 先回 200 再處理（PHP 可用 fastcgi_finish_request()）
 *   3. 用 webhookEventId 去重
 *
 * 環境變數：
 *   LINE_CHANNEL_SECRET
 *   LINE_CHANNEL_ACCESS_TOKEN
 *
 * 文件：https://developers.line.biz/en/docs/messaging-api/verify-webhook-signature/
 */

declare(strict_types=1);

const LINE_API = 'https://api.line.me';

$channelSecret = getenv('LINE_CHANNEL_SECRET') ?: '';
$accessToken   = getenv('LINE_CHANNEL_ACCESS_TOKEN') ?: '';

if ($channelSecret === '' || $accessToken === '') {
    http_response_code(500);
    exit('missing LINE credentials');
}

// ---------------------------------------------------------------- 1. 驗簽章
$rawBody   = file_get_contents('php://input');
$signature = $_SERVER['HTTP_X_LINE_SIGNATURE'] ?? '';

$expected = base64_encode(hash_hmac('sha256', $rawBody, $channelSecret, true));
if (!hash_equals($expected, $signature)) {
    http_response_code(400);
    exit('invalid signature');
}

// ------------------------------------------------------- 2. 先回 200 再處理
http_response_code(200);
echo 'OK';
if (function_exists('fastcgi_finish_request')) {
    fastcgi_finish_request();
}

$payload = json_decode($rawBody, true);
foreach (($payload['events'] ?? []) as $event) {
    if (!line_claim_event($event['webhookEventId'] ?? '')) {
        continue;                       // 重送，已處理過
    }
    if (($event['mode'] ?? 'active') === 'standby') {
        continue;
    }
    line_handle_event($event, $accessToken);
}

// --------------------------------------------------------------- 事件處理
function line_handle_event(array $event, string $token): void
{
    $type       = $event['type'] ?? '';
    $replyToken = $event['replyToken'] ?? null;

    if ($type === 'follow' && $replyToken) {
        line_reply($token, $replyToken, [
            ['type' => 'text', 'text' => '感謝加入好友！'],
        ]);
        return;
    }

    if ($type === 'message' && ($event['message']['type'] ?? '') === 'text' && $replyToken) {
        $text = trim($event['message']['text']);

        if ($text === '訂單') {
            line_reply($token, $replyToken, [line_order_flex('A2026-0821', 'NT$1,280', '已出貨')]);
            return;
        }

        line_reply($token, $replyToken, [
            ['type' => 'text', 'text' => '你說了：' . $text],
        ]);
        return;
    }

    if ($type === 'postback' && $replyToken) {
        line_reply($token, $replyToken, [
            ['type' => 'text', 'text' => 'postback: ' . ($event['postback']['data'] ?? '')],
        ]);
    }
}

/** 訂單狀態卡片 */
function line_order_flex(string $orderNo, string $total, string $status): array
{
    return [
        'type'     => 'flex',
        'altText'  => "訂單 {$orderNo} — {$status}",
        'contents' => [
            'type' => 'bubble',
            'body' => [
                'type'     => 'box',
                'layout'   => 'vertical',
                'spacing'  => 'md',
                'contents' => [
                    ['type' => 'text', 'text' => '訂單狀態', 'weight' => 'bold', 'size' => 'xl'],
                    ['type' => 'separator'],
                    line_kv('訂單編號', $orderNo),
                    line_kv('金額', $total),
                    line_kv('狀態', $status),
                ],
            ],
            'footer' => [
                'type'     => 'box',
                'layout'   => 'vertical',
                'contents' => [[
                    'type'   => 'button',
                    'style'  => 'primary',
                    'height' => 'sm',
                    'action' => [
                        'type'  => 'uri',
                        'label' => '查看明細',
                        'uri'   => 'https://example.com/orders/' . rawurlencode($orderNo),
                    ],
                ]],
            ],
        ],
    ];
}

function line_kv(string $label, string $value): array
{
    return [
        'type'     => 'box',
        'layout'   => 'baseline',
        'spacing'  => 'sm',
        'contents' => [
            ['type' => 'text', 'text' => $label, 'color' => '#AAAAAA', 'size' => 'sm', 'flex' => 2],
            ['type' => 'text', 'text' => $value, 'wrap' => true, 'size' => 'sm', 'flex' => 5],
        ],
    ];
}

// ------------------------------------------------------------------ API 呼叫
function line_reply(string $token, string $replyToken, array $messages): void
{
    line_call($token, 'POST', '/v2/bot/message/reply', [
        'replyToken' => $replyToken,
        'messages'   => $messages,
    ]);
}

function line_push(string $token, string $to, array $messages): void
{
    line_call($token, 'POST', '/v2/bot/message/push', [
        'to'       => $to,
        'messages' => $messages,
    ]);
}

function line_call(string $token, string $method, string $path, ?array $body = null): ?array
{
    $ch = curl_init(LINE_API . $path);
    curl_setopt_array($ch, [
        CURLOPT_CUSTOMREQUEST  => $method,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT        => 15,
        CURLOPT_HTTPHEADER     => [
            'Authorization: Bearer ' . $token,
            'Content-Type: application/json',
        ],
        CURLOPT_POSTFIELDS => $body === null
            ? null
            : json_encode($body, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES),
    ]);
    $response = curl_exec($ch);
    $status   = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    curl_close($ch);

    if ($status < 200 || $status >= 300) {
        error_log("LINE API {$method} {$path} -> {$status} {$response}");
        return null;
    }
    return $response ? json_decode($response, true) : [];
}

// ------------------------------------------------------------------ 冪等
/**
 * 回傳 true 代表這個事件是第一次看到。
 * 這裡用檔案示範；正式環境請改用 Redis SETNX 或資料庫 unique index。
 */
function line_claim_event(string $eventId): bool
{
    if ($eventId === '') {
        return true;
    }
    $dir = sys_get_temp_dir() . '/line-events';
    if (!is_dir($dir)) {
        mkdir($dir, 0700, true);
    }
    $file = $dir . '/' . preg_replace('/[^A-Za-z0-9_-]/', '', $eventId);
    $fh   = @fopen($file, 'x');       // 'x' = 已存在就失敗
    if ($fh === false) {
        return false;
    }
    fclose($fh);
    return true;
}
