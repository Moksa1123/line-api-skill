#!/usr/bin/env python3
"""
LINE API skill — self-test suite.

Offline tests (always run, no credentials, no network):
    dataset integrity, search engine, message validator, webhook signature,
    RS256 JWT construction, api-data host routing.

Live tests (--live). 憑證從環境變數或 .env 讀，缺哪個就跳過哪幾項：
    LINE_CHANNEL_ACCESS_TOKEN
        GET /v2/bot/info、/v2/bot/message/quota、webhook endpoint，
        以及 POST /v2/bot/message/validate/push——用 LINE 官方驗證器確認
        本技能產出的訊息會被接受，且不會發訊息給任何使用者。
    LINE_CHANNEL_ID + LINE_CHANNEL_SECRET
        POST /oauth2/v3/token，驗證 stateless token 與 15 分鐘效期。
    LINE_CHANNEL_ID + LINE_ASSERTION_PRIVATE_KEY (+ LINE_ASSERTION_KID)
        POST /oauth2/v2.1/token，驗證本專案純標準函式庫實作的 RS256 JWT
        能被 LINE 伺服器接受——這是唯一能證明簽章實作相容的檢查。

    測試不會印出任何憑證。

Usage
    python scripts/test_line.py
    python scripts/test_line.py --live
    python scripts/test_line.py --verbose
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import hmac
import json
import os
import re
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import core  # noqa: E402
import signature as sig  # noqa: E402
import validate as val  # noqa: E402
from core import load_dotenv, use_utf8_stdout  # noqa: E402

use_utf8_stdout()
load_dotenv()

DATA = HERE.parent / "data"
REFS = HERE.parent / "references"

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
results: list[tuple[str, str, str]] = []
VERBOSE = False


def check(name: str):
    def wrap(fn):
        def run():
            try:
                detail = fn() or ""
                results.append((PASS, name, detail))
            except AssertionError as e:
                results.append((FAIL, name, str(e)))
            except _Skip as e:
                results.append((SKIP, name, str(e)))
            except Exception:
                results.append((FAIL, name, traceback.format_exc(limit=2).strip().splitlines()[-1]))
        run.__name__ = fn.__name__
        return run
    return wrap


class _Skip(Exception):
    pass


def rows(name: str) -> list[dict]:
    with open(DATA / name, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


# ==========================================================================
# 1. dataset integrity
# ==========================================================================
@check("dataset: every expected CSV exists and is non-empty")
def t_dataset_present():
    expected = [
        "endpoints.csv", "parameters.csv", "message-objects.csv", "flex-components.csv",
        "actions.csv", "richmenu.csv", "webhook-events.csv", "liff-api.csv",
        "webhook-properties.csv", "responses.csv", "guides.csv",
        "liff-versions.csv", "terms.csv", "url-schemes.csv", "faq.csv", "sdk-api.csv",
        "error-codes.csv", "limits.csv", "products.csv", "channel-tokens.csv",
        "troubleshooting.csv", "reasoning.csv", "deprecations.csv", "glossary.csv",
        "emoji.csv", "stickers.csv",
    ]
    missing = [n for n in expected if not (DATA / n).exists()]
    assert not missing, f"缺少資料檔：{missing}"
    empty = [n for n in expected if len(rows(n)) == 0]
    assert not empty, f"資料檔是空的：{empty}"
    return f"{len(expected)} 個資料檔，共 {sum(len(rows(n)) for n in expected)} 筆"


@check("dataset: every CSV row has exactly as many fields as the header")
def t_csv_wellformed():
    problems = []
    for path in sorted(DATA.glob("*.csv")):
        with open(path, encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
            for lineno, row in enumerate(reader, start=2):
                if len(row) != len(header):
                    problems.append(f"{path.name}:{lineno} 有 {len(row)} 欄，表頭是 {len(header)} 欄")
    assert not problems, "; ".join(problems[:5])
    return f"{len(list(DATA.glob('*.csv')))} 個 CSV 欄位數一致"


@check("dataset: endpoints have method, host, path and a doc URL")
def t_endpoints_shape():
    data = rows("endpoints.csv")
    assert len(data) >= 110, f"端點只有 {len(data)} 筆，預期至少 110"
    for r in data:
        assert r["method"] in ("GET", "POST", "PUT", "DELETE", "PATCH"), r
        assert r["host"].startswith("https://"), r
        assert r["path"].startswith("/"), r
        assert r["doc_url"].startswith("https://developers.line.biz/"), r
    return f"{len(data)} endpoints"


@check("dataset: content endpoints are routed to api-data.line.me")
def t_data_host():
    data = rows("endpoints.csv")
    content = [r for r in data
               if r["path"].endswith("/content") and "/richmenu/" in r["path"]]
    assert content, "找不到 rich menu content 端點"
    for r in content:
        assert r["host"] == "https://api-data.line.me", \
            f"{r['method']} {r['path']} 應該用 api-data.line.me，實際 {r['host']}"
    return f"{len(content)} 個 content 端點主機正確"


@check("dataset: no duplicate (method, path) endpoints")
def t_no_dup_endpoints():
    seen = {}
    for r in rows("endpoints.csv"):
        key = (r["method"], re.sub(r"\{[^}]+\}", "{}", r["host"] + r["path"]))
        assert key not in seen, f"重複端點 {key}"
        seen[key] = r
    return f"{len(seen)} unique"


@check("dataset: all 20 webhook event types are present")
def t_webhook_events():
    events = {r["event"] for r in rows("webhook-events.csv")}
    required = {
        "message", "unsend", "follow", "unfollow", "join", "leave",
        "memberJoined", "memberLeft", "postback", "videoPlayComplete",
        "beacon", "accountLink", "membership", "module", "activated",
        "deactivated", "botSuspended", "botResumed", "delivery", "messageEdited",
    }
    missing = required - events
    assert not missing, f"缺少 webhook 事件：{sorted(missing)}"
    return f"{len(events)} 種事件（含 message 子型別）"


@check("dataset: 端點回應欄位有進資料集")
def t_responses():
    resp = rows("responses.csv")
    assert len(resp) >= 180, f"回應欄位只有 {len(resp)} 筆"

    def fields(op):
        return {r["property"] for r in resp if r["operation_id"] == op}

    # 這些先前完全查不到——只攤平了請求 schema，回應沒有
    assert {"userId", "basicId", "displayName", "chatMode"} <= fields("getBotInfo")
    assert "type" in fields("getMessageQuota")
    assert fields("getProfile"), "getProfile 沒有回應欄位"

    # 每一支端點都要有回應資料。沒有欄位的（回空物件、二進位、無主體）
    # 也必須說明是哪一種，不能留白讓人以為是漏抓。
    eps = rows("endpoints.csv")
    ops = {r["operation_id"] for r in resp}
    uncovered = [e for e in eps if (e["operation_id"] or e["title"]) not in ops]
    assert not uncovered, f"這些端點沒有任何回應資料：{[e['path'] for e in uncovered][:5]}"

    blank = [r for r in resp if not r["property"] and not r["description"]]
    assert not blank, f"有 {len(blank)} 列既沒欄位也沒說明"

    # 不在 OpenAPI 裡的 API，回應欄位要從官方文件補進來
    login = {r["property"] for r in resp if "Verify ID token" in r["operation_id"]}
    assert {"iss", "sub", "aud", "exp"} <= login, f"LINE Login 的 ID token 欄位不全：{login}"

    from_docs = sum(1 for r in resp if r["source"] == "docs")
    assert from_docs >= 50, f"只有 {from_docs} 筆來自文件"
    return (f"{len(resp)} 筆、{len(eps)}/{len(eps)} 支端點全覆蓋"
            f"（OpenAPI {len(resp) - from_docs} + 文件 {from_docs}）")


@check("dataset: 221 頁官方指南都有索引")
def t_guides():
    guides = rows("guides.csv")
    assert len(guides) >= 200, f"指南只有 {len(guides)} 頁"
    assert all(g["title"] for g in guides), "有指南頁沒有標題"
    assert all(g["doc_url"].startswith("https://developers.line.biz/en/docs/")
               for g in guides), "指南頁的 doc_url 格式錯誤"

    products = {g["product"] for g in guides}
    for want in ("messaging-api", "liff", "line-login", "line-mini-app"):
        assert want in products, f"指南索引缺少 {want}"

    titles = " ".join(g["title"] for g in guides)
    assert "Switch between tabs on rich menus" in titles, "缺少圖文選單切換指南"
    return f"{len(guides)} 頁、{len(products)} 個產品線"


@check("dataset: LIFF 版本沿革能回答『這個 API 要幾版』")
def t_liff_versions():
    versions = rows("liff-versions.csv")
    assert len(versions) >= 50, f"版本只有 {len(versions)} 個"
    dated = [v for v in versions if v["released"]]
    assert len(dated) >= 30, f"只有 {len(dated)} 個版本有日期"

    api = rows("liff-api.csv")

    def intro(name):
        return next((r["introduced_in"] for r in api if r["name"] == name), None)

    # release notes 明確公告過的，一定要算得出來
    assert intro("liff.shareTargetPicker()") == "2.3.0"
    assert intro("liff.scanCodeV2()") == "2.15.0"

    # 可在 init() 之前呼叫的方法，是文件用提示框標註的事實
    before = [r["name"] for r in api if r["before_init"] == "true"]
    assert "liff.getOS()" in before and "liff.isInClient()" in before, before
    assert "liff.getProfile()" not in before, "getProfile 需要先 init，不該被標記"

    # 可搖樹匯入的模組名。連續大寫要當一個字，否則 getOS 會變成 get-o-s
    def module(name):
        return next((r["module"] for r in api if r["name"] == name), None)

    assert module("liff.getOS()") == "@line/liff/get-os"
    assert module("liff.getIDToken()") == "@line/liff/get-id-token"
    assert module("liff.getDecodedIDToken()") == "@line/liff/get-decoded-id-token"
    assert module("liff.shareTargetPicker()") == "@line/liff/share-target-picker"
    # 文件沒有列出專屬模組的就留白，不臆測
    assert module("liff.init()") == "", "init 文件未列模組，不該自行填入"
    with_module = sum(1 for r in api if r["module"])
    assert with_module >= 28, f"只有 {with_module} 個 API 對到模組"
    return (f"{len(versions)} 版、{len(dated)} 個有日期；"
            f"{sum(1 for r in api if r['introduced_in'])} 個 API 標出引進版本；"
            f"{len(before)} 個可在 init 前呼叫")


@check("validate: 六個曾經放行、但 LINE 會退件的寫法")
def t_validate_false_accepts():
    """每一條都是拿 POST /v2/bot/message/validate/push 打出來的差異。

    離線驗證器原本放行、LINE 實際回 400 的六種寫法。上限值也都對著官方
    驗證器逐一試過邊界（40 過 41 退、20 過 21 退、12 過 13 退），
    所以這裡的數字不是抄來的，是量出來的。
    """
    img = "https://example.com/a.jpg"

    def errs(msg):
        return [p for p in val.run([msg], "messages").problems if p.level == "error"]

    def fbtn(action):
        return {"type": "flex", "altText": "a", "contents": {
            "type": "bubble", "body": {"type": "box", "layout": "vertical",
                                       "contents": [{"type": "button", "action": action}]}}}

    def qr(action):
        return {"type": "text", "text": "h", "quickReply": {
            "items": [{"type": "action", "action": action}]}}

    cases = [
        # (說明, 訊息, 應該要被擋嗎)
        ("postback 缺 data", qr({"type": "postback", "label": "a"}), True),
        ("postback 有 data", qr({"type": "postback", "label": "a", "data": "k=v"}), False),

        ("內容 URL 用 http", {"type": "image", "originalContentUrl": "http://x.com/a.jpg",
                              "previewImageUrl": "http://x.com/a.jpg"}, True),
        ("sender iconUrl 用 http",
         {"type": "text", "text": "h", "sender": {"name": "B", "iconUrl": "http://x.com/a.jpg"}}, True),
        ("內容 URL 用 https", {"type": "image", "originalContentUrl": img,
                               "previewImageUrl": img}, False),

        ("uri action 用 ftp", fbtn({"type": "uri", "label": "a", "uri": "ftp://x"}), True),
        ("uri action 用 tel", fbtn({"type": "uri", "label": "a", "uri": "tel:0212345678"}), False),
        ("uri action 用 line://", fbtn({"type": "uri", "label": "a", "uri": "line://ti/p/@x"}), False),

        # label 的上限與必填由「放在哪」決定，不是由 action 型別決定
        ("quickReply label 21", qr({"type": "message", "label": "x" * 21, "text": "a"}), True),
        ("quickReply label 20", qr({"type": "message", "label": "x" * 20, "text": "a"}), False),
        ("flex button label 41", fbtn({"type": "message", "label": "x" * 41, "text": "a"}), True),
        ("flex button label 40", fbtn({"type": "message", "label": "x" * 40, "text": "a"}), False),
        ("flex button 缺 label",
         fbtn({"type": "richmenuswitch", "richMenuAliasId": "a1", "data": "k=v"}), True),
        ("flex 非 button 的 action 不必有 label", {"type": "flex", "altText": "a", "contents": {
            "type": "bubble", "body": {"type": "box", "layout": "vertical", "contents": [
                {"type": "image", "url": img,
                 "action": {"type": "uri", "uri": "https://x.com"}}]}}}, False),
        ("image_carousel label 13", {"type": "template", "altText": "a", "template": {
            "type": "image_carousel", "columns": [
                {"imageUrl": img,
                 "action": {"type": "message", "label": "x" * 13, "text": "a"}}]}}, True),
        ("image_carousel label 12", {"type": "template", "altText": "a", "template": {
            "type": "image_carousel", "columns": [
                {"imageUrl": img,
                 "action": {"type": "message", "label": "x" * 12, "text": "a"}}]}}, False),

        # 輪播各欄不一致 LINE 是回 400，不是提醒
        ("輪播各欄動作數不一致", {"type": "template", "altText": "a", "template": {
            "type": "carousel", "columns": [
                {"text": "a", "actions": [{"type": "message", "label": "a", "text": "a"}]},
                {"text": "b", "actions": [{"type": "message", "label": "b", "text": "b"},
                                          {"type": "message", "label": "c", "text": "c"}]}]}}, True),
    ]
    wrong = []
    for name, msg, should_fail in cases:
        got = bool(errs(msg))
        if got != should_fail:
            wrong.append(f"{name}：預期{'擋' if should_fail else '放行'}，實際{'擋' if got else '放行'}")
    assert not wrong, "; ".join(wrong)
    return f"{len(cases)} 個與 LINE 官方驗證器對照過的案例全部一致"


# 官方文件 reference/messaging-api.md 的 webhook 事件範例，逐字照抄。
# 技能會被複製到別人的環境，測試不能依賴 .docs-cache，所以嵌在這裡。
OFFICIAL_WEBHOOK_SAMPLES = {
        "message/text": {
            "type": "message",
            "message": {
                "type": "text",
                "id": "14353798921116",
                "text": "Hello, world"
            },
            "timestamp": 1625665242211,
            "source": {
                "type": "user",
                "userId": "U80696558e1aa831..."
            },
            "replyToken": "757913772c4646b784d4b7ce46d12671",
            "mode": "active",
            "webhookEventId": "01FZ74A0TDDPYRVKNK77XKC3ZR",
            "deliveryContext": {
                "isRedelivery": False
            }
        },
        "follow": {
            "type": "follow",
            "timestamp": 1625665242214,
            "source": {
                "type": "user",
                "userId": "Ufc729a925b3abef..."
            },
            "replyToken": "bb173f4d9cf64aed9d408ab4e36339ad",
            "mode": "active",
            "webhookEventId": "01FZ74ASS536FW97EX38NKCZQK",
            "deliveryContext": {
                "isRedelivery": False
            }
        },
        "unfollow": {
            "type": "unfollow",
            "timestamp": 1625665242215,
            "source": {
                "type": "user",
                "userId": "Ubbd4f124aee5113..."
            },
            "mode": "active",
            "webhookEventId": "01FZ74B5Y0F4TNKA5SCAVKPEDM",
            "deliveryContext": {
                "isRedelivery": False
            }
        },
        "join": {
            "replyToken": "nHuyWiB7yP5Zw52FIkcQobQuGDXCTA",
            "type": "join",
            "mode": "active",
            "timestamp": 1462629479859,
            "source": {
                "type": "group",
                "groupId": "C4af4980629..."
            },
            "webhookEventId": "01FZ74A0TDDPYRVKNK77XKC3ZR",
            "deliveryContext": {
                "isRedelivery": False
            }
        },
        "memberJoined": {
            "replyToken": "0f3779fba3b349968c5d07db31eabf65",
            "type": "memberJoined",
            "mode": "active",
            "timestamp": 1462629479859,
            "source": {
                "type": "group",
                "groupId": "C4af4980629..."
            },
            "webhookEventId": "01FZ74A0TDDPYRVKNK77XKC3ZR",
            "deliveryContext": {
                "isRedelivery": False
            },
            "joined": {
                "members": [
                    {
                        "type": "user",
                        "userId": "U4af4980629..."
                    },
                    {
                        "type": "user",
                        "userId": "U91eeaf62d9..."
                    }
                ]
            }
        },
        "unsend": {
            "type": "unsend",
            "mode": "active",
            "timestamp": 1462629479859,
            "source": {
                "type": "group",
                "groupId": "Ca56f94637c...",
                "userId": "U4af4980629..."
            },
            "webhookEventId": "01FZ74A0TDDPYRVKNK77XKC3ZR",
            "deliveryContext": {
                "isRedelivery": False
            },
            "unsend": {
                "messageId": "325708"
            }
        },
        "videoPlayComplete": {
            "replyToken": "nHuyWiB7yP5Zw52FIkcQobQuGDXCTA",
            "type": "videoPlayComplete",
            "mode": "active",
            "timestamp": 1462629479859,
            "source": {
                "type": "user",
                "userId": "U4af4980629..."
            },
            "webhookEventId": "01FZ74A0TDDPYRVKNK77XKC3ZR",
            "deliveryContext": {
                "isRedelivery": False
            },
            "videoPlayComplete": {
                "trackingId": "track-id"
            }
        },
        "beacon": {
            "replyToken": "nHuyWiB7yP5Zw52FIkcQobQuGDXCTA",
            "type": "beacon",
            "mode": "active",
            "timestamp": 1462629479859,
            "source": {
                "type": "user",
                "userId": "U4af4980629..."
            },
            "webhookEventId": "01FZ74A0TDDPYRVKNK77XKC3ZR",
            "deliveryContext": {
                "isRedelivery": False
            },
            "beacon": {
                "hwid": "d41d8cd98f",
                "type": "enter"
            }
        },
        "accountLink": {
            "replyToken": "b60d432864f44d079f6d8efe86cf404b",
            "type": "accountLink",
            "mode": "active",
            "source": {
                "userId": "U91eeaf62d...",
                "type": "user"
            },
            "timestamp": 1513669370317,
            "webhookEventId": "01FZ74A0TDDPYRVKNK77XKC3ZR",
            "deliveryContext": {
                "isRedelivery": False
            },
            "link": {
                "result": "ok",
                "nonce": "xxxxxxxxxxxxxxx"
            }
        },
        "membership": {
            "type": "membership",
            "source": {
                "type": "user",
                "userId": "U4af4980629..."
            },
            "replyToken": "nHuyWiB7yP5Zw52FIkcQobQuGDXCTA",
            "membership": {
                "type": "joined",
                "membershipId": 3189
            },
            "timestamp": 1462629479859,
            "mode": "active",
            "webhookEventId": "01FZ74A0TDDPYRVKNK77XKC3ZR",
            "deliveryContext": {
                "isRedelivery": False
            }
        },
        "messageEdited": {
            "type": "messageEdited",
            "replyToken": "950e63e8f46542ab89f645b4c2a1180a",
            "message": {
                "type": "text",
                "id": "610830548529053697",
                "quoteToken": "XyiyoB3R1BA...",
                "text": "Edited message"
            },
            "webhookEventId": "01KPW6071XGPXPAF4XCN96XEAN",
            "deliveryContext": {
                "isRedelivery": False
            },
            "timestamp": 1776914799524,
            "source": {
                "type": "group",
                "groupId": "Ca56f94637c...",
                "userId": "U4af4980629..."
            },
            "mode": "active"
        },
        "leave": {
            "type": "leave",
            "mode": "active",
            "timestamp": 1462629479859,
            "source": {
                "type": "group",
                "groupId": "C4af4980629..."
            },
            "webhookEventId": "01FZ74A0TDDPYRVKNK77XKC3ZR",
            "deliveryContext": {
                "isRedelivery": False
            }
        },
        "memberLeft": {
            "type": "memberLeft",
            "mode": "active",
            "timestamp": 1462629479960,
            "source": {
                "type": "group",
                "groupId": "C4af4980629..."
            },
            "webhookEventId": "01FZ74A0TDDPYRVKNK77XKC3ZR",
            "deliveryContext": {
                "isRedelivery": False
            },
            "left": {
                "members": [
                    {
                        "type": "user",
                        "userId": "U4af4980629..."
                    },
                    {
                        "type": "user",
                        "userId": "U91eeaf62d9..."
                    }
                ]
            }
        }
    }


@check("search: 資料集裡的東西查得回來（抽樣召回率）")
def t_search_recall():
    """拿每一列自己的識別欄位當查詢，看它回不回得來。

    手寫幾十組期望值只會固化寫的人的假設，而且查不回來的資料等於不存在，
    是最容易默默壞掉又沒人發現的一種。全資料集 3500 列跑過一次是
    99.03% 召回、96.83% 第一名命中；這裡抽樣跑，門檻設在 97%，
    掉下去就是搜尋或資料出了事。

    剩下那不到 1% 是「同一個字串本來就有多個合理答案」——查 source
    回傳 Source 物件的欄位、查 video 回傳影片訊息的欄位，都是對的。
    """
    probes = {
        "endpoint": ("title", ["method", "path"]),
        "parameter": ("parameter", ["endpoint", "parameter"]),
        "message": ("property", ["type", "property"]),
        "flex": ("property", ["type", "property"]),
        "action": ("property", ["type", "property"]),
        "webhook": ("event", ["event"]),
        "response": ("property", ["operation_id", "property"]),
        "guide": ("title", ["doc_url"]),
        "faq": ("question", ["question"]),
        "term": ("term", ["term"]),
        "url_scheme": ("scheme", ["scheme"]),
        "sdk_api": ("name", ["platform", "name"]),
        "limit": ("field", ["schema", "field"]),
    }
    hit = total = 0
    weak = []
    for domain, (qcol, idcols) in probes.items():
        rows, _ = core.load_csv(domain)
        if not rows:
            continue
        out_cols = core.CSV_CONFIG[domain]["output_cols"]
        idcols = [c for c in idcols if c in out_cols] or [qcol]
        counts = {}
        for r in rows:
            counts[(r.get(qcol) or "").strip()] = counts.get((r.get(qcol) or "").strip(), 0) + 1
        step = max(1, len(rows) // 12)
        for row in rows[::step]:
            q = (row.get(qcol) or "").strip()
            if not q:
                continue
            total += 1
            hits = core.search(q, domain=domain, max_results=5)
            if counts[q] == 1:
                want = tuple((row.get(c) or "") for c in idcols)
                ok = want in [tuple((h.get(c) or "") for c in idcols) for h in hits]
            else:
                # 同名多列：回傳任一個同名的都算對，因為查詢本身沒有唯一解
                ok = q in [(h.get(qcol) or "").strip() for h in hits]
            if ok:
                hit += 1
            else:
                weak.append(f"[{domain}] {q[:40]!r}")
    rate = hit / total * 100
    assert rate >= 97.0, f"召回率掉到 {rate:.1f}%（{total} 次查詢）：" + "; ".join(weak[:5])
    return f"{total} 次查詢，召回率 {rate:.1f}%"


@check("search: LIFF 與 MINI App 的規格查得到（規格寫在指南的表格裡，不在 reference）")
def t_guide_specs():
    """LIFF 與 LINE MINI App 的規則大半不在 reference 的參數區塊裡，
    而在指南頁的表格：服務訊息的字數上限、未驗證 MINI App 不能用哪些功能、
    站內購買的商品編號格式。以前整個資料集只有這些頁面的標題，
    問「自訂路徑」會完全查不到東西。

    每一條都指名一個具體事實，而不是「有回傳結果就算過」——
    回錯答案跟沒有答案一樣糟。
    """
    def find(query, want, domain="guide_spec"):
        hits = core.search(query, domain=domain, max_results=8)
        blob = " | ".join(
            f"{h.get('item','')} {h.get('attribute','')} {h.get('value','')}"
            for h in hits)
        return want.lower() in blob.lower(), blob[:110]

    cases = [
        # (查詢, 前八名裡必須出現的字串)
        ("service message maximum characters detailed", "50"),
        ("服務訊息 字數上限", "soft limit"),
        ("custom path unverified", "custom path"),
        ("自訂路徑", "custom path"),
        ("share target picker LIFF browser", "share target picker"),
        ("in-app purchase product id", "iap_"),
        ("站內購買", "iap"),
        ("add to home screen", "shortcut"),
        # 有些關鍵數字只寫在內文句子裡，表格萃取看不到
        ("service notification token expires", "31,536,000"),
        ("service message templates per channel", "20"),
    ]
    bad = []
    for query, want in cases:
        ok, blob = find(query, want)
        if not ok:
            bad.append(f"{query!r} 前八名沒有 {want!r}（得到 {blob}）")
    assert not bad, "; ".join(bad)

    # 這個域本身要有足夠的量，不然是解析器壞了而不是查詢寫錯
    rows, _ = core.load_csv("guide_spec")
    assert len(rows) >= 2000, f"指南規格只有 {len(rows)} 筆"
    mini = [r for r in rows if r.get("product") == "line-mini-app"]
    liff = [r for r in rows if r.get("product") == "liff"]
    assert len(mini) >= 800, f"MINI App 只有 {len(mini)} 筆"
    assert len(liff) >= 150, f"LIFF 只有 {len(liff)} 筆"
    return f"{len(rows)} 筆（MINI App {len(mini)}、LIFF {len(liff)}），{len(cases)} 個查詢全命中"


@check("signature: ID token 驗簽（HS256 與 ES256 兩種 LINE 都會用）")
def t_id_token():
    """LINE 的 ID token 有兩種簽法，取決於 token 怎麼來的：
    web 登入流程是 HS256（channel secret），LIFF 與原生 App 是 ES256
    （JWKS 公鑰、ECDSA P-256）。

    最常見的錯誤是「只 base64 解開就相信裡面的 sub」——那等於沒有驗證，
    任何人都能自己編一個 payload。所以兩種都要能真的驗。

    ES256 的數學用 RFC 6979 A.2.5 的官方測試向量檢查，不是拿自己的實作
    跟自己比對——那樣兩邊一起錯也看不出來。
    """
    # --- ES256：權威測試向量 ---
    def b64u_int(i):
        return base64.urlsafe_b64encode(i.to_bytes(32, "big")).rstrip(b"=").decode()

    ux = 0x60FED4BA255A9D31C961EB74C6356D68C049B8923B61FA6CE669622E60F29FB6
    uy = 0x7903FE1008B8BC99A41AE9E95628BC64F2F1B20C2D7E9F5177A3C294D4462299
    r = 0xEFD48B2AACB6A8FD1140DD9CD45E81D69D2C877B56AAF991C34D0EA84EAF3716
    s_ = 0xF7CB1C942D657C41D436C7A1B6E29F65F3E900DBB9AFF4064DC4AB2F843ACDA8
    jwk = {"kty": "EC", "crv": "P-256", "x": b64u_int(ux), "y": b64u_int(uy)}
    good = r.to_bytes(32, "big") + s_.to_bytes(32, "big")
    assert sig.es256_verify(b"sample", good, jwk), "RFC 6979 的向量應該要通過"
    flipped = bytearray(good)
    flipped[0] ^= 1
    assert not sig.es256_verify(b"sample", bytes(flipped), jwk), "竄改簽章要失敗"
    assert not sig.es256_verify(b"sampld", good, jwk), "換訊息要失敗"
    assert not sig.es256_verify(b"sample", good[:63], jwk), "長度不對要失敗"

    # --- HS256：自己組一個 ID token 走完整條驗證 ---
    secret = "test-channel-secret"
    cid = "1234567890"
    now = 1_700_000_000

    def make(payload, key=secret):
        head = sig.b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        body = sig.b64url(json.dumps(payload).encode())
        mac = hmac.new(key.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
        return f"{head}.{body}.{sig.b64url(mac)}"

    base = {"iss": "https://access.line.me", "sub": "U1", "aud": cid,
            "exp": now + 3600, "iat": now, "name": "Tester"}
    ok = sig.verify_id_token(make(base), cid, channel_secret=secret, now=now)
    assert ok["sub"] == "U1"

    def rejects(token, **kw):
        try:
            sig.verify_id_token(token, kw.pop("cid", cid),
                                channel_secret=kw.pop("secret", secret),
                                now=now, **kw)
        except ValueError:
            return True
        return False

    assert rejects(make(base, key="wrong-secret")), "簽章錯要擋"
    assert rejects(make({**base, "iss": "https://evil.example"})), "iss 不對要擋"
    assert rejects(make({**base, "aud": "9999999999"})), "aud 不是這個 channel 要擋"
    assert rejects(make({**base, "exp": now - 1})), "過期要擋"
    assert rejects(make({**base, "nonce": "aaa"}), nonce="bbb"), "nonce 對不上要擋"
    # 沒帶 secret 就驗不了 HS256，不能默默放行
    assert rejects(make(base), secret=None), "缺 channel secret 不該通過"
    # 「alg: none」這種經典攻擊
    none_head = sig.b64url(json.dumps({"alg": "none"}).encode())
    none_body = sig.b64url(json.dumps(base).encode())
    assert rejects(f"{none_head}.{none_body}."), "alg=none 要擋"
    return "ES256 過 RFC 6979 向量；HS256 七種偽造全部擋下"


@check("dataset: LIFF 功能需要的 LINE App 版本（跟 SDK 版本是兩回事）")
def t_liff_availability():
    """liff-api.csv 的 introduced_in 是「這個 API 從哪一版 LIFF SDK 開始有」，
    但線上最常見的問題是「我用最新 SDK，為什麼使用者按了沒反應」——
    答案通常是使用者的 LINE App 太舊。兩個版本混在一起講會害人，
    所以另開一份表，欄位名稱直接寫明是 LINE App 版本。
    """
    data = rows("liff-availability.csv")
    assert len(data) >= 10, f"只有 {len(data)} 個功能"
    by = {r["feature"]: r for r in data}
    # 抽查幾個實際會踩到的
    assert by["shareTargetPicker"]["min_line_version"] == "10.3.0"
    assert by["scanCodeV2"]["min_line_version"] == "11.7.0"
    assert by["scanCodeV2"]["min_os_version"] == "14.3.0", "scanCodeV2 還有 iOS 版本要求"
    # scanCode 是被淘汰的那個：有「從哪一版起不再支援」
    assert by["scanCode"]["unsupported_from_version"] == "9.19.0"
    for r in data:
        assert r["how_to_check"].startswith("liff.isApiAvailable("), r
        assert re.fullmatch(r"\d+\.\d+\.\d+", r["min_line_version"]), r
    hits = core.search("shareTargetPicker 需要哪個 LINE 版本", max_results=3)
    assert any(h.get("feature") == "shareTargetPicker" for h in hits), \
        "版本需求要查得到"
    return f"{len(data)} 個功能，含 minVer / minOsVer / 停止支援版本"


@check("dataset: 送審與開發規範查得到（條列式的規則，表格萃取抓不到）")
def t_checklists():
    """送審規範、開發規範、效能規範這些頁面寫的是「你必須做到什麼」，
    一條一條的項目符號。表格萃取看不到，內文限制那條也抓不到
    （多數規則裡沒有數字）。而「送審前要檢查什麼」正是做 MINI App
    最常問的，答錯的代價是整個審核被退。
    """
    data = rows("checklists.csv")
    assert len(data) >= 150, f"規範只有 {len(data)} 條"
    mini = [r for r in data if r["product"] == "line-mini-app"]
    assert len(mini) >= 50, f"MINI App 的規範只有 {len(mini)} 條"
    assert all(r["rule"] and r["doc_url"].startswith("https://") for r in data)
    # 收進來的必須是規範類的頁面，不能把整站的項目符號都掃進來
    pages = {r["page"] for r in data}
    assert any("submission" in p or "submit" in p for p in pages), "送審指南沒收到"
    assert any("guidelines" in p for p in pages), "開發規範沒收到"
    assert not any("/demo/" in p or "/technicalcase/" in p for p in pages), \
        "案例介紹頁不該被當成規範"
    for q in ("送審前要檢查什麼", "mini app 送審 規範", "效能規範"):
        assert core.search(q, domain="checklist", max_results=3), f"{q!r} 查不到"
    return f"{len(data)} 條（MINI App {len(mini)}），來自 {len(pages)} 個規範頁"


@check("search: 自然說法要問得到對的東西")
def t_search_intent():
    """人不會用欄位名稱發問。這些是逐一人工確認過答案正確的查詢——
    中文、英文、口語都有，每一條都對應到一個具體的錯誤答案風險。"""
    cases = [
        # (查詢, 域, 命中判斷函式的說明, 檢查)
        ("send push message", "endpoint", lambda h: h["path"] == "/v2/bot/message/push"),
        ("圖文選單", "richmenu", lambda h: True),
        ("輪播", "message", lambda h: "carousel" in (h.get("type") or "")),
        ("chatBarText", "richmenu", lambda h: h["property"] == "chatBarText"),
        ("quick reply", "message", lambda h: "uick" in str(h)),
        ("aspectMode", "flex", lambda h: h["property"] == "aspectMode"),
        ("postback", "webhook", lambda h: h["event"] == "postback"),
        ("scanCodeV2", "liff", lambda h: "scanCodeV2" in (h.get("name") or "")),
        ("加好友", "url_scheme", lambda h: True),
        ("簽章驗證失敗", "troubleshoot", lambda h: True),
        ("429", "error", lambda h: "429" in (h.get("code_or_message") or "")),
        ("get bot info", "response", lambda h: h["operation_id"] == "getBotInfo"),
    ]
    bad = []
    for query, domain, ok in cases:
        hits = core.search(query, domain=domain, max_results=5)
        if not hits:
            bad.append(f"{query!r} 在 {domain} 查不到任何東西")
        elif not any(ok(h) for h in hits):
            bad.append(f"{query!r} 前五名沒有對的答案（得到 {hits[0]}）")
    assert not bad, "; ".join(bad)
    return f"{len(cases)} 個自然查詢都命中"


@check("validate: 官方文件裡的 webhook 事件範例一個都不能被誤判")
def t_validate_webhook():
    """13 個事件的官方範例逐字照抄，加上四種壞掉的 payload。

    webhook 是唯一「方向相反」的驗證：驗的是收到的東西。這裡最容易錯的
    假設是「規格說必填就一定收得到」——官方自己的 follow 與 message 範例
    就沒有 follow 和 quoteToken，所以收訊端的必填只給 warning，
    寫成「讀取前先判斷」，不是報錯。

    範例取自 reference/messaging-api.md 的 JSON 區塊，一字未改。
    """
    official = OFFICIAL_WEBHOOK_SAMPLES
    noisy = []
    for name, ev in official.items():
        errs = [p for p in val.run(ev, "webhook").problems if p.level == "error"]
        if errs:
            noisy.append(f"{name}: {errs[0].path} {errs[0].message[:50]}")
    assert not noisy, "官方範例被誤判：" + "; ".join(noisy)

    def base(**kw):
        ev = {"type": "message", "timestamp": 1, "mode": "active",
              "webhookEventId": "01F", "deliveryContext": {"isRedelivery": False},
              "source": {"type": "user", "userId": "U1"}, "replyToken": "r",
              "message": {"id": "1", "type": "text", "text": "h"}}
        ev.update(kw)
        return ev

    def errs(ev):
        return [p for p in val.run(ev, "webhook").problems if p.level == "error"]

    assert errs(base(type="nope")), "不存在的事件型別要抓到"
    assert errs(base(source={"type": "zzz"})), "不存在的 source 型別要抓到"
    assert errs(base(message={"id": "1", "type": "zzz"})), "不存在的訊息型別要抓到"
    # 拼錯的屬性在 webhook 上是警告：LINE 之後加新欄位時不該讓人整批變紅
    typo = val.run(base(replytoken="r"), "webhook").problems
    assert any(p.level == "warning" and "replytoken" in p.message for p in typo),         "拼錯的屬性至少要提醒"

    # 收訊端的必填只提醒不報錯——這正是官方範例會缺的那些
    lean = val.run({"type": "follow", "timestamp": 1, "mode": "active",
                    "webhookEventId": "01F",
                    "deliveryContext": {"isRedelivery": False},
                    "source": {"type": "user", "userId": "U1"},
                    "replyToken": "r"}, "webhook").problems
    assert not [p for p in lean if p.level == "error"], "缺 follow 不該是錯誤"
    assert any(p.level == "warning" for p in lean), "缺 follow 要提醒"
    return f"{len(official)} 個官方範例零誤判，4 種壞 payload 全抓到"


@check("validate: 對照 LINE 官方驗證器量出來的 13 條規則")
def t_validate_measured_rules():
    """這些規則的數字與等級全部是實測的，不是從文件抄的。

    做法是拿資料集生出 659 個訊息與 41 個圖文選單，逐筆送
    POST /v2/bot/message/validate/push 與 /v2/bot/richmenu/validate，
    比對兩邊的判斷。文件沒寫、或寫了但與實際行為不同的地方，
    只有這樣才問得出來——例如 text 的 5000 是 UTF-16 單位不是字元。
    """
    E = "\U0001F600"          # 一個 emoji＝1 字元＝2 個 UTF-16 單位
    img = "https://example.com/a.jpg"

    def bad(msg, kind="messages"):
        return [p for p in val.run(msg if kind == "messages" else msg, kind).problems
                if p.level == "error"]

    def m(msg):
        return bool(bad([msg]))

    def flexc(contents):
        return {"type": "flex", "altText": "a", "contents": contents}

    def box(layout, *children):
        return flexc({"type": "bubble", "body": {"type": "box", "layout": layout,
                                                 "contents": list(children)}})

    cases = [
        # (說明, 是否該被擋)
        # 1. text 的 5000 是 UTF-16 單位。4999 個 a 加一個 emoji 只有 5000 個
        #    字元，卻是 5001 個單位——用 len() 數會放行，LINE 會退
        ("text 5000 單位", m({"type": "text", "text": "a" * 4998 + E}), False),
        ("text 5001 單位", m({"type": "text", "text": "a" * 4999 + E}), True),
        ("emoji 2500 個", m({"type": "text", "text": E * 2500}), False),
        ("emoji 2501 個", m({"type": "text", "text": E * 2501}), True),
        # 2. 其他欄位是數字元，不是數單位
        ("quickReply label 20 個 emoji",
         m({"type": "text", "text": "h", "quickReply": {"items": [
             {"type": "action", "action": {"type": "message", "label": E * 20,
                                           "text": "a"}}]}}), False),
        # 3. bubble 至少要有一個區塊
        ("空的 bubble", m(flexc({"type": "bubble"})), True),
        ("bubble 只有 footer", m(flexc({"type": "bubble", "footer": {
            "type": "box", "layout": "vertical",
            "contents": [{"type": "text", "text": "h"}]}})), False),
        # 4. hero 只收 box / image / video
        ("hero 放 text", m(flexc({"type": "bubble", "hero": {"type": "text", "text": "h"},
                                  "body": {"type": "box", "layout": "vertical",
                                           "contents": []}})), True),
        # 5. box 能放什麼由 layout 決定
        ("vertical box 放 icon", m(box("vertical", {"type": "icon", "url": img})), True),
        ("baseline box 放 icon", m(box("baseline", {"type": "icon", "url": img})), False),
        ("baseline box 放 button",
         m(box("baseline", {"type": "button",
                            "action": {"type": "message", "label": "a", "text": "a"}})), True),
        ("box 放 span", m(box("vertical", {"type": "span", "text": "h"})), True),
        # 6. text 要有 text 或 contents
        ("flex text 兩個都沒有", m(box("vertical", {"type": "text"})), True),
        ("flex text 用 contents",
         m(box("vertical", {"type": "text", "contents": [{"type": "span", "text": "h"}]})), False),
        # 7. action 放錯位置：Flex 是退件，樣板是收單但不會動
        ("camera 放 Flex button",
         m(box("vertical", {"type": "button", "action": {"type": "camera", "label": "c"}})), True),
        ("camera 放樣板（只警告）", m({"type": "template", "altText": "a", "template": {
            "type": "buttons", "text": "t",
            "actions": [{"type": "camera", "label": "c"}]}}), False),
        ("richmenuswitch 放 Flex button",
         m(box("vertical", {"type": "button", "action": {
             "type": "richmenuswitch", "label": "a",
             "richMenuAliasId": "x", "data": "k=v"}})), True),
        # 8. 色碼：Flex 收 8 碼，樣板的 imageBackgroundColor 只收 6 碼
        ("flex color #RRGGBBAA",
         m(box("vertical", {"type": "text", "text": "h", "color": "#FF0000AA"})), False),
        ("flex color 寫成 red",
         m(box("vertical", {"type": "text", "text": "h", "color": "red"})), True),
        ("imageBackgroundColor 8 碼", m({"type": "template", "altText": "a", "template": {
            "type": "buttons", "text": "t", "imageBackgroundColor": "#FF0000AA",
            "actions": [{"type": "message", "label": "a", "text": "a"}]}}), True),
        # 9. 尺寸：offset/padding 收 %，margin/spacing/cornerRadius 不收
        ("margin 10px", m(box("vertical", {"type": "text", "text": "h", "margin": "10px"})), False),
        ("margin 10%", m(box("vertical", {"type": "text", "text": "h", "margin": "10%"})), True),
        ("offsetTop 10%",
         m(box("vertical", {"type": "text", "text": "h", "offsetTop": "10%"})), False),
        # 10. 未知屬性：Flex 退件，其他地方只是沒作用
        ("Flex 多一個屬性",
         m(box("vertical", {"type": "text", "text": "h", "zzz": 1})), True),
        ("訊息多一個屬性", m({"type": "text", "text": "h", "zzz": 1}), False),
        # 11. null：必填給 null 等於沒給；Flex 連選填給 null 都退
        ("必填給 null", m({"type": "text", "text": None}), True),
        ("選填給 null", m({"type": "text", "text": "h", "sender": None}), False),
        ("Flex 選填給 null",
         m(box("vertical", {"type": "text", "text": "h", "margin": None})), True),
        # 12. 型別轉換：訊息層級雙向都收，Flex 兩邊都不收
        ("訊息 text 給數字", m({"type": "text", "text": 123}), False),
        ("Flex text 給數字", m(box("vertical", {"type": "text", "text": 123})), True),
        ("URL 欄位給數字", m({"type": "image", "originalContentUrl": 123,
                              "previewImageUrl": img}), True),
        # 13. imagemap 設了 video，它底下就變必填
        ("imagemap video 空的", m({"type": "imagemap", "baseUrl": "https://e.com/b",
                                   "altText": "a", "video": {},
                                   "baseSize": {"width": 1040, "height": 1040},
                                   "actions": []}), True),
    ]
    wrong = [f"{n}：預期{'擋' if e else '放行'}" for n, got, e in cases if got != e]
    assert not wrong, "; ".join(wrong)
    return f"{len(cases)} 條實測規則全部一致"


@check("validate: 圖文選單的尺寸規則是範圍不是固定清單")
def t_validate_richmenu():
    """官方寫的是寬 800–2500、高 ≥250、比例 ≥1.45，不是六種固定尺寸。
    邊界逐一對照過 POST /v2/bot/richmenu/validate：799 退、2501 退、
    249 退、比例 1.4493 退、1.4514 收。"""
    def rm(**kw):
        base = {"size": {"width": 2500, "height": 1686}, "selected": False,
                "name": "m", "chatBarText": "選單",
                "areas": [{"bounds": {"x": 0, "y": 0, "width": 100, "height": 100},
                           "action": {"type": "message", "label": "a", "text": "a"}}]}
        base.update(kw)
        return base

    def bad(obj):
        return bool([p for p in val.run(obj, "richmenu").problems if p.level == "error"])

    cases = [
        ("2500x1686", bad(rm()), False),
        ("800x250 下界", bad(rm(size={"width": 800, "height": 250})), False),
        ("799 寬", bad(rm(size={"width": 799, "height": 250})), True),
        ("2501 寬", bad(rm(size={"width": 2501, "height": 250})), True),
        ("800x249", bad(rm(size={"width": 800, "height": 249})), True),
        ("比例 1.4493", bad(rm(size={"width": 1000, "height": 690})), True),
        ("比例 1.4514", bad(rm(size={"width": 1000, "height": 689})), False),
        ("正方形", bad(rm(size={"width": 1000, "height": 1000})), True),
        ("chatBarText 14", bad(rm(chatBarText="x" * 14)), False),
        ("chatBarText 15", bad(rm(chatBarText="x" * 15)), True),
        ("size 給 null", bad(rm(size=None)), True),
        ("chatBarText 給數字", bad(rm(chatBarText=123)), True),
        ("size.width 給字串", bad(rm(size={"width": "2500", "height": 1686})), False),
        ("area 缺 action",
         bad(rm(areas=[{"bounds": {"x": 0, "y": 0, "width": 10, "height": 10}}])), True),
        ("0 個 area", bad(rm(areas=[])), False),
    ]
    wrong = [f"{n}：預期{'擋' if e else '放行'}" for n, got, e in cases if got != e]
    assert not wrong, "; ".join(wrong)
    # 超出圖片範圍 LINE 收下，所以是警告不是錯誤
    over = val.run(rm(areas=[{"bounds": {"x": 0, "y": 0, "width": 3000, "height": 1686},
                              "action": {"type": "message", "label": "a", "text": "a"}}]),
                   "richmenu").problems
    assert any(p.level == "warning" for p in over), "超出範圍的區塊應該給警告"
    assert not any(p.level == "error" for p in over), "LINE 收下這種，不該報 error"
    return f"{len(cases)} 條邊界規則與官方驗證端點一致"


@check("review: 對自家正確範例不得有任何誤報")
def t_review_clean():
    import review
    known, data_host = review.endpoint_index()
    ex = HERE.parent / "examples"
    noisy = []
    for f in sorted(ex.rglob("*")):
        if f.suffix not in review.CODE_EXT:
            continue
        found = review.review_text(f, f.read_text(encoding="utf-8"), known, data_host)
        noisy += [f"{f.name}:{x.line} [{x.rule}] {x.message[:50]}" for x in found]
    assert not noisy, "自家範例被誤報：" + "; ".join(noisy[:4])
    return "6 個範例檔零誤報"


@check("review: 該抓的問題一個都不能漏")
def t_review_catches():
    import review
    known, data_host = review.endpoint_index()
    bad = '''
import hmac, hashlib, base64, json, requests
from flask import request
CHANNEL_SECRET = "0123456789abcdef0123456789abcdef"
def cb():
    body = request.get_json()
    sig = base64.b64encode(hmac.new(CHANNEL_SECRET.encode(),
          json.dumps(body).encode(), hashlib.sha256).digest()).decode()
    if sig != request.headers.get("x-line-signature"):
        return "", 400
    for e in body["events"]:
        msg = {"type": "text", "text": "hi", "quickreply": {}}
        requests.post("https://api.line.me/v2/bot/message/reply",
                      json={"replyToken": e["replyToken"], "messages": [msg]})
    requests.get("https://api.line.me/v2/bot/message/1/content")
    requests.get("https://api.line.me/v2/bot/profiel/U1")
    requests.post("https://notify-api.line.me/api/notify")
'''
    rules = {f.rule for f in review.review_text(Path("bad.py"), bad, known, data_host)}
    for want in ("hardcoded-secret",      # 寫死的 channel secret
                 "signature-body",        # 用序列化過的 JSON 算簽章
                 "signature-compare",     # 沒有常數時間比較
                 "wrong-host",            # content 端點打到 api.line.me
                 "unknown-endpoint",      # profiel 拼錯
                 "deprecated",            # LINE Notify 已終止
                 "message-json"):         # quickreply 拼錯
        assert want in rules, f"沒抓到 {want}（實際抓到 {sorted(rules)}）"
    return f"{len(rules)} 類問題全部抓到"


@check("review: 寫得好的程式碼不該被罵（真實專案驗出來的誤報）")
def t_review_precision():
    """這五種寫法都出現在實際的正式專案裡，每一種都曾被誤報。

    第一次拿 review.py 掃一個 249 檔的 LINE SaaS，23 筆發現全是假的：
    註解、pino 遮蔽清單、coverage 產物、分層寫的驗簽與去重、樣板字串裡的
    函式呼叫。真正該報的那一筆反而漏掉。以下逐條釘住。
    """
    import review
    known, data_host = review.endpoint_index()

    def rules_for(name, src, project=None):
        return {f.rule for f in
                review.review_text(Path(name), src, known, data_host, project)}

    # 1. 解釋「不可以這樣做」的註解，不是在這樣做
    doc = '''
/**
 * 轉發的是原始位元組，不是重新序列化的 JSON。
 * 用 JSON.stringify 重算 x-line-signature 會因為空白差異對不上。
 */
export async function forward(raw: Buffer) { return raw }
'''
    assert not rules_for("forward.ts", doc), "註解被當成程式碼了"

    # 2. 只是把標頭列進遮蔽清單，沒有在驗簽
    redact = '''
export const logger = pino({
  redact: { paths: ['authorization', 'req.headers["x-line-signature"]'] },
})
'''
    assert "signature-compare" not in rules_for("logger.ts", redact), \
        "沒算 HMAC 的檔案不該被要求常數時間比較"

    # 3. 產生簽章送出去的測試，裡面沒有任何比對
    signer = '''
import { createHmac } from 'node:crypto'
const sig = createHmac('sha256', SECRET).update(raw).digest('base64')
await app.inject({ headers: { 'x-line-signature': sig }, payload: raw })
'''
    assert "signature-compare" not in rules_for("fwd.test.ts", signer), \
        "只簽章不比對的程式碼不該被要求常數時間比較"

    # 4. 樣板字串裡有函式呼叫，路徑不可以在括號處被截斷
    tpl = ('const res = await fetch(`https://api-data.line.me'
           '/v2/bot/message/${encodeURIComponent(messageId)}/content`)\n')
    assert not rules_for("client.ts", tpl), \
        "巢狀 ${...(...)} 讓路徑解析斷掉了"

    # 5. 驗簽在 signature.ts、去重在 webhook.ts，收 webhook 的路由兩者都沒寫
    route = '''
app.post('/webhook/:key', async (req, reply) => {
  const ok = await verifySignature(req.rawBody, req.headers['x-line-signature'])
  if (!ok) return reply.code(400).send()
  for (const e of req.body.events) await handle(e.replyToken, e)
})
'''
    layered = {"sig.ts": "createHmac('sha256', s); if (a === b) {} // x-line-signature",
               "hook.ts": "const id = event.webhookEventId"}
    assert not (rules_for("routes.ts", route, review.project_facts(layered))
                & review.PROJECT_RULES), "分層寫的專案被逐檔重複指責"

    # 6. coverage 報告會把整份 .ts 內嵌進 .ts.html，掃到等於重複審查
    assert "coverage" in review.SKIP_DIRS and "htmlcov" in review.SKIP_DIRS

    # 7. 為了叫別人不要用而提到 line://，不是在用它
    reject = ("if (/^line:\\/\\//.test(uri)) "
              "issues.push({ message: '用了已淘汰的 line://，請改成 https://line.me/R/ 開頭' })\n")
    deps = [f for f in review.review_text(Path("check.ts"), reject, known, data_host)
            if f.rule == "deprecated"]
    assert len(deps) == 1 and deps[0].line == 1, \
        f"應該只認出 regex 裡那一個 line://，實際 {[(f.line) for f in deps]}"

    # 反面：真的在驗簽卻用 == 比，還是要抓
    weak = '''
const expected = createHmac('sha256', SECRET).update(raw).digest('base64')
if (expected !== req.headers['x-line-signature']) return reply.code(400).send()
'''
    assert "signature-compare" in rules_for("weak.ts", weak), "真的用 == 比卻沒抓到"
    return "7 類誤報都不再發生，真問題照樣抓得到"


@check("dataset: 行動 SDK（iOS / Android）的型別清單有進資料集")
def t_sdk_api():
    sdk = rows("sdk-api.csv")
    assert len(sdk) >= 70, f"SDK 型別只有 {len(sdk)} 個"

    platforms = {r["platform"] for r in sdk}
    assert platforms == {"ios-swift", "android"}, platforms

    # jazzy 目錄名是複數，早期用 rstrip("s") 會產出 classe / typealiase
    kinds = {r["kind"] for r in sdk}
    assert not any(k.endswith("e") and k not in ("typealias",) and k[:-1] in kinds
                   for k in kinds), f"型別分類看起來被截錯字：{sorted(kinds)}"
    for bad in ("classe", "typealiase", "struct s"):
        assert bad not in kinds, f"型別分類有誤：{bad}"

    names = {r["name"] for r in sdk}
    for want in ("LoginManager", "LineSDKError", "LineApiClient", "LineLoginApi"):
        assert want in names, f"缺少 SDK 型別 {want}"

    assert all(r["doc_url"].startswith("https://developers.line.biz/en/reference/")
               for r in sdk), "SDK 型別的連結格式錯誤"
    ios = sum(1 for r in sdk if r["platform"] == "ios-swift")
    android = sum(1 for r in sdk if r["platform"] == "android")
    return f"{len(sdk)} 個型別（iOS {ios} / Android {android}）"


@check("dataset: 官方 FAQ 題目與錨點都正確")
def t_faq():
    faq = rows("faq.csv")
    assert len(faq) >= 85, f"FAQ 只有 {len(faq)} 題"
    assert all(f["question"] for f in faq), "有題目是空的"

    # 錨點是 LINE 人工命名的，推導不出來，只能從頁面原始碼取。
    # 少一個都代表轉換器又把錨點丟了。
    anchored = [f for f in faq if "#" in f["doc_url"]]
    assert len(anchored) == len(faq), f"只有 {len(anchored)}/{len(faq)} 題有錨點"

    urls = " ".join(f["doc_url"] for f in faq)
    for want in ("#why-do-i-get-429-error-during-message-delivery",
                 "#what-are-userid-groupid-and-roomid"):
        assert want in urls, f"缺少被官方文件引用的 FAQ 錨點 {want}"

    products = {f["product"] for f in faq if f["product"]}
    assert len(products) >= 5, f"標籤分類只有 {products}"
    return f"{len(faq)} 題全部有錨點，涵蓋 {len(products)} 個產品線"


@check("dataset: LINE URL scheme 有收錄且分類正確")
def t_url_schemes():
    schemes = rows("url-schemes.csv")
    assert len(schemes) >= 40, f"URL scheme 只有 {len(schemes)} 筆"
    assert all(s["purpose"] for s in schemes), "有 scheme 沒寫用途"

    by_cat = {}
    for s in schemes:
        by_cat.setdefault(s["category"], []).append(s["scheme"])
    for want in ("camera", "official-account", "settings", "sticker-shop", "browser"):
        assert want in by_cat, f"缺少分類 {want}"

    all_schemes = " ".join(s["scheme"] for s in schemes)
    for want in ("line.me/R/ti/p/", "line.me/R/nv/camera/",
                 "openExternalBrowser=1", "liff.line.me/"):
        assert want in all_schemes, f"缺少 {want}"

    # 相機類只能從聊天室觸發，是最常踩的雷，必須有註記
    camera = [s for s in schemes if s["category"] == "camera"]
    assert all("聊天室" in s["note"] for s in camera), "相機類 scheme 沒有註明使用限制"
    return f"{len(schemes)} 個 scheme、{len(by_cat)} 種分類"


@check("dataset: 官方術語表 57 條全部收錄且錨點正確")
def t_glossary_terms():
    terms = rows("terms.csv")
    assert len(terms) >= 50, f"術語只有 {len(terms)} 條"
    for r in terms:
        assert r["definition"], f"{r['term']} 沒有定義"
        assert r["doc_url"].startswith("https://developers.line.biz/en/glossary/#"), r["term"]

    # 常被 reference 連到的錨點必須查得到
    anchors = {r["doc_url"].split("#")[-1] for r in terms}
    for want in ("liff-browser", "line-iab", "external-browser", "provider",
                 "channel-access-token", "user-id", "rich-menu-alias"):
        assert want in anchors, f"術語表缺少 #{want}"

    # 有 .docs-cache 時，逐條比對官方術語表有沒有新增詞條
    cache = HERE.parent.parent / ".docs-cache" / "raw" / "en" / "glossary.md"
    if cache.exists():
        text = cache.read_text(encoding="utf-8")
        official = set(re.findall(r"^#{2,3}\s*\[[^\]]+\]\(#([a-z0-9\-]+)\)\s*$",
                                  text, re.M))
        missing = official - anchors
        assert not missing, f"官方新增了這些術語但資料集沒收：{sorted(missing)}"
        return f"{len(terms)} 條，與官方 {len(official)} 條完全對上"
    return f"{len(terms)} 條術語"


@check("dataset: 每一份官方 reference 都真的被處理過")
def t_every_reference_processed():
    """擋住最難察覺的疏漏：整份文件沒被列入處理清單。

    liff.md（LIFF 客戶端 SDK、92 個參數區塊）就曾經這樣被漏掉——所有測試
    都是綠的，但整個 LIFF 的欄位資料根本不存在。
    """
    cache = HERE.parent.parent / ".docs-cache" / "raw" / "en" / "reference"
    if not cache.exists():
        raise _Skip("沒有 .docs-cache（只有維護者跑得到）")
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "bd", HERE.parent.parent / "tools" / "build_dataset.py")
    bd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bd)

    params = rows("parameters.csv")
    got = {}
    for r in params:
        got[r["api"]] = got.get(r["api"], 0) + 1

    problems = []
    for path in sorted(cache.glob("*.md")):
        blocks = path.read_text(encoding="utf-8").count("<!-- parameter start")
        entry = bd.REF_FILES.get(path.name)
        if entry is None:
            problems.append(f"{path.name} 有 {blocks} 個參數區塊卻沒列入 REF_FILES")
        elif blocks and not got.get(entry[0]):
            problems.append(f"{path.name} 已列入卻萃取到 0 筆")
    assert not problems, "; ".join(problems)
    return f"{len(list(cache.glob('*.md')))} 份 reference 全部處理完畢"


@check("dataset: 五大產品線都有實際資料（Flex / bot / LIFF / MINI App / Login）")
def t_product_coverage():
    params = rows("parameters.csv")
    eps = rows("endpoints.csv")
    per_api = {}
    for r in params:
        per_api[r["api"]] = per_api.get(r["api"], 0) + 1

    # 每個產品線的參數數量下限。liff 曾經是 0——整份 liff.md 沒被列入
    # REF_FILES，所有測試卻都是綠的，所以這裡直接把門檻釘死。
    floors = {
        "messaging-api": 1000,   # Flex / bot / 圖文選單 / 推播都在這裡
        "liff": 80,              # LIFF 客戶端 SDK
        "liff-server": 30,
        "line-login": 50,
        "line-login-v2": 25,
        "line-mini-app": 60,
        "line-notification-messages": 20,
        "partner-docs": 50,
    }
    for api, floor in floors.items():
        got = per_api.get(api, 0)
        assert got >= floor, f"{api} 只有 {got} 個參數，預期至少 {floor}"

    # LIFF 客戶端的關鍵欄位必須查得到
    liff_params = {r["parameter"] for r in params if r["api"] == "liff"}
    for want in ("config.liffId", "availability", "menuColorSetting"):
        assert want in liff_params, f"LIFF 參數缺少 {want}"

    # 端點若被多份文件記載，also_in 要保留另一邊的產品線
    multi = [r for r in eps if r["also_in"]]
    assert multi, "沒有任何端點標記 also_in，跨文件端點的來源資訊掉了"
    return (f"{len(floors)} 個產品線都達標；LIFF {per_api.get('liff', 0)} 個參數；"
            f"{len(multi)} 支跨文件端點有標記")


@check("dataset: webhook 事件有逐欄位的型別與說明")
def t_webhook_properties():
    rows_ = rows("webhook-properties.csv")
    assert len(rows_) >= 200, f"webhook 欄位只有 {len(rows_)} 筆"

    def get(schema, prop, col="value_type"):
        return next((r[col] for r in rows_ if r["schema"] == schema and r["property"] == prop), None)

    # 每個事件都該有的共同屬性，型別要正確
    assert get("PostbackEvent", "postback") == "PostbackContent"
    assert get("PostbackEvent", "webhookEventId") == "string"
    assert get("MessageEvent", "message") == "MessageContent"
    assert get("FollowEvent", "follow") == "FollowDetail"
    assert get("DeliveryContext", "isRedelivery") == "boolean"
    assert get("TextMessageContent", "quoteToken") == "string"

    # source 的三種型別要齊
    sources = {r["type"] for r in rows_ if r["group"] == "source"}
    for want in ("user", "group", "room"):
        assert want in sources, f"source 缺少 {want}（目前 {sorted(sources)}）"

    # 事件屬性表要涵蓋 webhook-events.csv 列出的每一種事件
    events = {r["event"] for r in rows("webhook-events.csv") if "." not in r["event"]}
    covered = {r["type"] for r in rows_ if r["group"] == "event"}
    missing = events - covered
    assert not missing, f"這些事件沒有欄位表：{sorted(missing)}"

    described = sum(1 for r in rows_ if r["description"])
    return f"{len(rows_)} 個欄位、{len(covered)} 種事件，{described} 個有說明"


@check("dataset: every message / flex / action discriminator is covered")
def t_discriminators():
    msg = {r["type"] for r in rows("message-objects.csv") if r["group"] == "message"}
    for t in ("text", "sticker", "image", "video", "audio", "location",
              "imagemap", "template", "flex"):
        assert t in msg, f"缺少訊息型別 {t}"
    flex = {r["type"] for r in rows("flex-components.csv") if r["group"] == "flex-component"}
    for t in ("box", "button", "image", "video", "icon", "text", "span",
              "separator", "filler"):
        assert t in flex, f"缺少 Flex 元件 {t}"
    act = {r["type"] for r in rows("actions.csv")}
    for t in ("postback", "message", "uri", "datetimepicker", "camera",
              "cameraRoll", "location", "richmenuswitch", "clipboard"):
        assert t in act, f"缺少 action {t}"
    return f"{len(msg)} 訊息型別 / {len(flex)} Flex 元件 / {len(act)} action"


@check("dataset: documented limits match LINE's published values")
def t_known_limits():
    limits = {(r["field"], r["constraint"]): r["value"] for r in rows("limits.csv")}
    expected = {
        ("PushMessageRequest.messages", "maxItems"): "5",
        ("MulticastRequest.to", "maxItems"): "500",
        ("QuickReply.items", "maxItems"): "13",
        ("RichMenuRequest.chatBarText", "maxLength"): "14",
        ("PostbackAction.data", "maxLength"): "300",
        ("ShowLoadingAnimationRequest.loadingSeconds", "maximum"): "60",
    }
    for key, want in expected.items():
        got = limits.get(key)
        assert got == want, f"{key} 應為 {want}，實際 {got}"
    return f"{len(limits)} 條限制，6 條抽查全部相符"


@check("dataset: text message max length is 5000")
def t_text_limit():
    hit = [r for r in rows("parameters.csv")
           if r["endpoint"] == "Text message" and r["parameter"] == "text"]
    assert hit, "找不到 Text message 的 text 參數"
    assert hit[0]["max"].startswith("5000"), f"text 上限應為 5000，實際 {hit[0]['max']}"
    return "text max 5000"


@check("dataset: every doc_url points at developers.line.biz (or a stated exception)")
def t_doc_urls():
    allowed_other = {"https://notify-bot.line.me/en/"}
    bad = []
    for path in sorted(DATA.glob("*.csv")):
        for r in rows(path.name):
            for k, v in r.items():
                if not isinstance(k, str) or not isinstance(v, str):
                    continue
                if k.endswith("url") and v and not v.startswith("https://developers.line.biz/"):
                    if v not in allowed_other:
                        bad.append((path.name, v))
    assert not bad, f"非官方網域的連結：{bad[:5]}"
    return "全部連結指向官方文件"


# ==========================================================================
# 2. search engine
# ==========================================================================
@check("search: english query returns the exact endpoint first")
def t_search_en():
    cases = {
        "send push message": "/v2/bot/message/push",
        "send reply message": "/v2/bot/message/reply",
        "get bot info": "/v2/bot/info",
        "issue channel access token": None,
    }
    for query, want_path in cases.items():
        hits = core.search(query, domain="endpoint", max_results=3)
        assert hits, f"{query!r} 查無結果"
        if want_path:
            assert hits[0]["path"] == want_path, \
                f"{query!r} 第一名是 {hits[0]['path']}，預期 {want_path}"
    return f"{len(cases)} 個查詢全部命中"


@check("search: chinese query reaches the english dataset via the glossary")
def t_search_zh():
    cases = [
        ("圖文選單", "richmenu", "rich"),
        ("簽章驗證失敗", "troubleshoot", "簽章"),
        ("彈性訊息", "flex", "flex"),
        ("推播", "endpoint", "push"),
    ]
    for query, want_domain, needle in cases:
        domain = core.detect_domain(query)
        assert domain == want_domain, f"{query!r} 判定為 {domain}，預期 {want_domain}"
        hits = core.search(query, max_results=3)
        assert hits, f"{query!r} 查無結果"
        blob = json.dumps(hits, ensure_ascii=False).lower()
        assert needle.lower() in blob, f"{query!r} 結果裡找不到 {needle!r}"

    # an ambiguous question may land in more than one domain — what matters is
    # that the answer surfaces, so search every domain for it
    notify = core.search_all("LINE Notify 停了怎麼辦")
    blob = json.dumps(notify, ensure_ascii=False)
    assert "Notify" in blob, "LINE Notify 的答案沒有出現在任何域"
    return f"{len(cases)} 個中文查詢域判定正確，LINE Notify 也查得到"


@check("search: camelCase / dotted identifiers are reachable by their parts")
def t_tokenizer():
    parts = core.tokenize("MulticastRequest.to")
    for want in ("multicast", "request", "to"):
        assert want in parts, f"{want!r} 不在 {parts}"
    assert "chat" in core.tokenize("chatBarText")
    assert core.tokenize("push") == ["push"], "純小寫查詢不該被拆開"

    # 這正是修正前查不到的案例
    hits = core.search("multicast", domain="limit", max_results=8)
    assert any(h["field"] == "MulticastRequest.to" for h in hits),         "查 multicast 找不到 MulticastRequest.to"
    hits = core.search("chatBarText", domain="richmenu", max_results=5)
    assert any(h["max_length"] == "14" for h in hits), "查 chatBarText 找不到 14 字上限"
    return "camelCase 與點號路徑都可被子詞命中"


@check("search: 資料裡有的 max_length，輸出欄位就不能漏掉")
def t_output_cols_expose_limits():
    import csv as _csv
    missing = []
    for domain, cfg in core.CSV_CONFIG.items():
        path = DATA / cfg["file"]
        with open(path, encoding="utf-8", newline="") as f:
            reader = _csv.DictReader(f)
            fields = reader.fieldnames or []
            has_values = any(r.get("max_length") for r in reader)
        if "max_length" in fields and has_values and "max_length" not in cfg["output_cols"]:
            missing.append(domain)
    assert not missing, f"這些域藏起了 max_length：{missing}"
    # 輪播上限 12 是最常被問到的一條，直接釘住
    hits = core.search("carousel", domain="flex", max_results=5)
    assert any(h.get("max_length") == "12" for h in hits), "查 carousel 看不到 12 的上限"
    return "有限制值的域都會顯示 max_length"


@check("search: query expansion adds the english term")
def t_expand():
    out = core.expand_query("圖文選單怎麼建立")
    assert "rich" in out and "menu" in out, out
    assert core.expand_query("push message") == "push message", "英文查詢不應被改寫"
    return out


@check("search: every domain is searchable and returns well-formed rows")
def t_all_domains():
    for domain, cfg in core.CSV_CONFIG.items():
        data, _ = core.load_csv(domain)
        assert data, f"{domain} 沒有資料"
        probe = str(data[0].get(cfg["search_cols"][0], "")) or "a"
        hits = core.search(probe, domain=domain, max_results=1)
        assert hits, f"{domain} 用 {probe!r} 查不到東西"
        for col in cfg["output_cols"]:
            assert col in hits[0], f"{domain} 輸出缺少欄位 {col}"
    return f"{len(core.CSV_CONFIG)} 個搜尋域全部正常"


# ==========================================================================
# 3. message validator
# ==========================================================================
@check("validate: accepts correct messages")
def t_validate_good():
    good = [
        {"type": "text", "text": "hello"},
        {"type": "sticker", "packageId": "446", "stickerId": "1988"},
        {"type": "image", "originalContentUrl": "https://e.com/a.jpg",
         "previewImageUrl": "https://e.com/p.jpg"},
        {"type": "template", "altText": "t",
         "template": {"type": "confirm", "text": "ok?", "actions": [
             {"type": "message", "label": "yes", "text": "yes"},
             {"type": "message", "label": "no", "text": "no"}]}},
        {"type": "flex", "altText": "f", "contents": {
            "type": "bubble",
            "body": {"type": "box", "layout": "vertical",
                     "contents": [{"type": "text", "text": "hi", "weight": "bold"}]}}},
    ]
    for m in good:
        v = val.run(m, "message")
        errs = [p for p in v.problems if p.level == "error"]
        assert not errs, f"{m['type']} 應該通過，卻報錯：{[e.message for e in errs]}"
    return f"{len(good)} 種訊息全部通過"


@check("validate: catches each class of mistake")
def t_validate_bad():
    cases = [
        ({"type": "txt", "text": "x"}, "type"),
        ({"type": "text"}, "text"),
        ({"type": "text", "text": "x" * 5001}, "5000"),
        ({"type": "text", "text": "x", "quickreply": {}}, "quickreply"),
        ({"type": "flex", "altText": "a", "contents": {
            "type": "bubble", "body": {"type": "box", "contents": []}}}, "layout"),
        ({"type": "flex", "altText": "a", "contents": {
            "type": "bubble", "body": {"type": "box", "layout": "sideways",
                                       "contents": []}}}, "sideways"),
        ({"type": "text", "text": "x", "quickReply": {"items": [
            {"type": "action", "action": {"type": "nope", "label": "l"}}]}}, "nope"),
        ({"type": "text", "text": "x", "quickReply": {"items": [
            {"type": "action", "action": {"type": "message", "label": "l", "text": "t"}}
        ] * 14}}, "13"),
        ({"type": "flex", "altText": "a", "contents": {
            "type": "carousel", "contents": [
                {"type": "bubble", "body": {"type": "box", "layout": "vertical",
                                            "contents": []}}] * 13}}, "12"),
    ]
    for payload, needle in cases:
        v = val.run(payload, "message")
        blob = " ".join(p.message + p.path for p in v.problems)
        assert needle in blob, f"沒抓到 {needle!r}：{blob or '(no problems)'}"
    return f"{len(cases)} 種錯誤全部被抓到"


@check("validate: enforces request-level limits")
def t_validate_request():
    v = val.run({"to": ["U" + str(i) for i in range(501)],
                 "messages": [{"type": "text", "text": "hi"}]}, "multicast")
    assert any("500" in p.message for p in v.problems), "沒抓到 multicast 500 上限"

    v = val.run({"to": "U1", "messages": [{"type": "text", "text": "x"}] * 6}, "push")
    assert any("5 則" in p.message for p in v.problems), "沒抓到一次最多 5 則訊息"

    v = val.run({"messages": []}, "broadcast")
    assert any("空陣列" in p.message for p in v.problems), "沒抓到空 messages"
    return "multicast 500 / messages 5 / 空陣列 都抓到"


@check("validate: 輪播的欄數、動作數與條件式 text 上限都會擋")
def t_validate_carousel():
    def msg(template):
        return {"type": "template", "altText": "a", "template": template}

    col = {"text": "t", "actions": [{"type": "message", "label": "a", "text": "a"}]}

    # template carousel：最多 10 欄
    v = val.run(msg({"type": "carousel", "columns": [col] * 11}), "message")
    assert any("10" in p.message for p in v.problems), "沒抓到 carousel 10 欄上限"

    # 每欄最多 3 個 action
    over = {"text": "t", "actions": [{"type": "message", "label": "a", "text": "a"}] * 4}
    v = val.run(msg({"type": "carousel", "columns": [over]}), "message")
    assert any("3" in p.message for p in v.problems), "沒抓到每欄 3 個 action 上限"

    # 條件式 text：沒有圖也沒有標題 → 120 字以內合法
    v = val.run(msg({"type": "carousel",
                     "columns": [{"text": "x" * 110,
                                  "actions": col["actions"]}]}), "message")
    assert not [p for p in v.problems if p.level == "error"],         f"無圖無標題的 110 字不該報錯：{[p.message for p in v.problems]}"

    # 有標題 → 上限縮到 60
    v = val.run(msg({"type": "carousel",
                     "columns": [{"title": "標題", "text": "x" * 110,
                                  "actions": col["actions"]}]}), "message")
    assert any("60" in p.message for p in v.problems), "有標題時沒有套用 60 字上限"

    # Flex carousel：最多 12 個 bubble
    bubble = {"type": "bubble", "body": {"type": "box", "layout": "vertical", "contents": []}}
    v = val.run({"type": "carousel", "contents": [bubble] * 13}, "flex")
    assert any("12" in p.message for p in v.problems), "沒抓到 Flex carousel 12 bubble 上限"

    # 正常的兩欄輪播不該有任何抱怨
    v = val.run(msg({"type": "carousel", "columns": [col, col]}), "message")
    assert not v.problems, f"正常輪播被誤報：{[p.message for p in v.problems]}"
    return "template 10 欄 / 每欄 3 動作 / 條件式 text / Flex 12 bubble 全部生效"


@check("dataset: 只寫在文件散文裡的 enum 與預設值也要進資料集")
def t_prose_enums_and_defaults():
    msg = rows("message-objects.csv")

    def find(schema, prop, col):
        return next((r[col] for r in msg if r["schema"] == schema and r["property"] == prop), None)

    # OpenAPI 只說這兩個是 string，enum 只寫在文件正文裡
    assert find("CarouselTemplate", "imageAspectRatio", "enum") == "rectangle|square"
    assert find("CarouselTemplate", "imageSize", "enum") == "cover|contain"
    assert find("CarouselTemplate", "imageAspectRatio", "default") == "rectangle"
    assert find("CarouselColumn", "imageBackgroundColor", "default") == "#FFFFFF"

    enums = sum(1 for r in msg if r["enum"])
    defaults = sum(1 for r in msg if r["default"])
    assert enums >= 8, f"訊息物件的 enum 只有 {enums} 筆"
    assert defaults >= 10, f"訊息物件的預設值只有 {defaults} 筆"
    return f"訊息物件：{enums} 個 enum、{defaults} 個預設值"


@check("dataset: 輪播各層的欄位上限都齊全")
def t_carousel_limits_complete():
    msg = rows("message-objects.csv")
    flex = rows("flex-components.csv")

    def mx(rowset, schema, prop):
        return next((r["max_length"] for r in rowset
                     if r["schema"] == schema and r["property"] == prop), None)

    expected = [
        (msg, "CarouselTemplate", "columns", "10"),
        (msg, "CarouselColumn", "actions", "3"),
        (msg, "CarouselColumn", "title", "40"),
        (msg, "CarouselColumn", "text", "120"),
        (msg, "CarouselColumn", "thumbnailImageUrl", "2000"),
        (msg, "ImageCarouselTemplate", "columns", "10"),
        (msg, "ImageCarouselColumn", "imageUrl", "2000"),
        (msg, "ButtonsTemplate", "actions", "4"),
        (flex, "FlexCarousel", "contents", "12"),
    ]
    for rowset, schema, prop, want in expected:
        got = mx(rowset, schema, prop)
        assert got == want, f"{schema}.{prop} 應為 {want}，實際 {got!r}"
    # confirm template 的官方寫法是「剛好 2 個」而非上限，規則在驗證器裡
    exact = val.run({"type": "template", "altText": "a", "template": {
        "type": "confirm", "text": "ok?",
        "actions": [{"type": "message", "label": "a", "text": "a"}]}}, "message")
    assert any("剛好 2 個" in p.message for p in exact.problems),         "confirm template 只給 1 個 action 應該要報錯"
    return f"{len(expected)} 個輪播上限正確，confirm 的『剛好 2 個』也生效"


@check("validate: 輪播各欄不一致時會提醒")
def t_carousel_consistency():
    action = [{"type": "message", "label": "a", "text": "a"}]

    def run(columns):
        return val.run({"type": "template", "altText": "a",
                        "template": {"type": "carousel", "columns": columns}}, "message")

    v = run([{"text": "a", "actions": action},
             {"text": "b", "actions": action * 2}])
    assert any("action 數量不一致" in p.message for p in v.problems), "沒抓到 action 數不一致"

    v = run([{"text": "a", "thumbnailImageUrl": "https://e.com/1.jpg", "actions": action},
             {"text": "b", "actions": action}])
    assert any("thumbnailImageUrl" in p.message for p in v.problems), "沒抓到有些欄缺圖"

    v = run([{"text": "a", "thumbnailImageUrl": "https://e.com/1.jpg", "actions": action},
             {"text": "b", "thumbnailImageUrl": "https://e.com/2.jpg", "actions": action}])
    assert not v.problems, f"一致的輪播被誤報：{[p.message for p in v.problems]}"
    return "action 數與圖片/標題一致性都會檢查"


@check("validate: Flex 容器的 JSON 體積與 bubble 寬度規則")
def t_flex_container_rules():
    def bubble(size=None, filler="x"):
        b = {"type": "bubble", "body": {"type": "box", "layout": "vertical",
                                        "contents": [{"type": "text", "text": filler}]}}
        if size:
            b["size"] = size
        return b

    # 同一個 carousel 內不能混用不同寬度
    v = val.run({"type": "carousel", "contents": [bubble("kilo"), bubble("mega")]}, "flex")
    assert any("寬度必須相同" in p.message for p in v.problems), "沒抓到 bubble 寬度混用"

    v = val.run({"type": "carousel", "contents": [bubble("kilo"), bubble("kilo")]}, "flex")
    assert not v.problems, f"寬度一致卻被誤報：{[p.message for p in v.problems]}"

    v = val.run({"type": "carousel", "contents": [bubble(), bubble()]}, "flex")
    assert not v.problems, "都用預設寬度卻被誤報"

    # JSON 體積：bubble 30 KB、carousel 50 KB
    v = val.run(bubble(filler="x" * 31000), "flex")
    assert any("30 KB" in p.message for p in v.problems), "沒抓到 bubble 超過 30 KB"

    big = {"type": "carousel", "contents": [bubble(filler="x" * 9000) for _ in range(6)]}
    v = val.run(big, "flex")
    assert any("50 KB" in p.message for p in v.problems), "沒抓到 carousel 超過 50 KB"
    return "bubble 30KB / carousel 50KB / 寬度一致 全部生效"


@check("validate: flags the deprecated filler component")
def t_validate_deprecated():
    v = val.run({"type": "bubble", "body": {
        "type": "box", "layout": "vertical",
        "contents": [{"type": "filler"}]}}, "flex")
    assert any(p.level == "warning" and "filler" in p.message for p in v.problems), \
        "filler 沒有被標記為淘汰"
    return "filler warning"


# ==========================================================================
# 4. signature and JWT
# ==========================================================================
@check("signature: matches an independent HMAC-SHA256 implementation")
def t_signature():
    secret, body = "channel-secret", b'{"destination":"U1","events":[]}'
    got = sig.sign_body(secret, body)
    want = base64.b64encode(
        hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
    assert got == want, f"{got} != {want}"
    assert sig.verify_signature(secret, body, got)
    assert not sig.verify_signature(secret, body + b" ", got), "改動 body 仍通過驗證"
    assert not sig.verify_signature("wrong", body, got), "錯誤密鑰仍通過驗證"
    assert not sig.verify_signature(secret, body, ""), "空簽章仍通過驗證"
    return got[:16] + "..."


@check("signature: verifies LINE's own documented example vector")
def t_signature_vector():
    # Independently reproducible: any HMAC-SHA256 tool gives the same answer.
    secret = "testsecret"
    body = '{"events":[{"type":"message"}]}'
    expected = base64.b64encode(
        hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()).decode()
    assert sig.sign_body(secret, body) == expected
    return expected


@check("jwt: RS256 signature verifies against the public key")
def t_jwt():
    jwk = _test_jwk()
    token = sig.make_jwt(jwk, "1234567890", kid="test-kid", token_exp=86400, now=1_700_000_000)
    header_b64, payload_b64, sig_b64 = token.split(".")
    header = json.loads(sig.b64url_decode(header_b64))
    payload = json.loads(sig.b64url_decode(payload_b64))
    assert header == {"alg": "RS256", "typ": "JWT", "kid": "test-kid"}, header
    assert payload["iss"] == payload["sub"] == "1234567890"
    assert payload["aud"] == "https://api.line.me/"
    assert payload["exp"] == 1_700_000_000 + 1800, "exp 必須是發行後 30 分鐘內"
    assert payload["token_exp"] == 86400
    assert sig.rs256_verify(f"{header_b64}.{payload_b64}".encode(),
                            sig.b64url_decode(sig_b64), jwk), "RS256 簽章驗不過"
    return "header/payload/signature 全部正確"


@check("jwt: rejects out-of-spec lifetimes")
def t_jwt_limits():
    jwk = _test_jwk()
    for kwargs, needle in (
        ({"token_exp": 60 * 60 * 24 * 31}, "30 days"),
        ({"jwt_lifetime": 60 * 60}, "30 minutes"),
    ):
        try:
            sig.make_jwt(jwk, "1", kid="k", **kwargs)
        except ValueError as e:
            assert needle in str(e), str(e)
        else:
            raise AssertionError(f"{kwargs} 應該要被拒絕")
    return "token_exp 30 天 / assertion 30 分鐘 上限有生效"


_JWK_CACHE: dict | None = None


def _test_jwk() -> dict:
    """A throwaway RSA key for the round-trip tests."""
    global _JWK_CACHE
    if _JWK_CACHE:
        return _JWK_CACHE
    try:
        from cryptography.hazmat.primitives.asymmetric import rsa
    except ImportError:
        raise _Skip("需要 cryptography 套件才能產生測試金鑰（pip install cryptography）")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = key.private_numbers()

    def enc(i: int) -> str:
        raw = i.to_bytes((i.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    _JWK_CACHE = {
        "kty": "RSA", "alg": "RS256", "use": "sig", "kid": "test-kid",
        "n": enc(numbers.public_numbers.n),
        "e": enc(numbers.public_numbers.e),
        "d": enc(numbers.d),
    }
    return _JWK_CACHE


# ==========================================================================
# 5. client wiring
# ==========================================================================
@check("client: picks api-data.line.me only for content endpoints")
def t_host_routing():
    import lineapi
    cases = {
        "/v2/bot/message/abc/content": lineapi.API_DATA,
        "/v2/bot/richmenu/rich-1/content": lineapi.API_DATA,
        "/v2/bot/audienceGroup/upload/byFile": lineapi.API_DATA,
        "/v2/bot/message/push": lineapi.API,
        "/v2/bot/info": lineapi.API,
        "/v2/bot/richmenu/list": lineapi.API,
    }
    for path, want in cases.items():
        got = lineapi.host_for(path)
        assert got == want, f"{path} -> {got}，預期 {want}"
    return f"{len(cases)} 條路徑主機判斷正確"


@check("examples: every shipped Flex/message JSON validates clean")
def t_examples_valid():
    ex = HERE.parent / "examples"
    if not ex.exists():
        raise _Skip("examples/ 尚未建立")
    files = sorted(ex.rglob("*.json"))
    assert files, "examples/ 裡沒有 JSON 範例"
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        kind = "flex" if data.get("type") in ("bubble", "carousel") else "auto"
        v = val.run(data, val.detect_kind(data) if kind == "auto" else kind)
        problems = [f"{p.level} {p.path}: {p.message}" for p in v.problems]
        assert not problems, f"{f.name} -> {problems[:3]}"
    return f"{len(files)} 個範例 JSON 全部通過（含 warning）"


@check("examples: python examples are syntactically valid")
def t_examples_python():
    import ast
    ex = HERE.parent / "examples"
    if not ex.exists():
        raise _Skip("examples/ 尚未建立")
    files = sorted(ex.rglob("*.py"))
    for f in files:
        try:
            ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        except SyntaxError as e:
            raise AssertionError(f"{f.name}:{e.lineno} {e.msg}")
    return f"{len(files)} 個 Python 範例語法正確"


@check("references: every reference doc exists and links to official docs")
def t_references():
    if not REFS.exists():
        raise _Skip("references/ 尚未建立")
    files = sorted(REFS.glob("*.md"))
    assert files, "references/ 是空的"
    for f in files:
        text = f.read_text(encoding="utf-8")
        assert "developers.line.biz" in text, f"{f.name} 沒有官方文件連結"
        assert len(text) > 500, f"{f.name} 內容過短"
    return f"{len(files)} 份參考文件"


# ==========================================================================
# 6. live tests
# ==========================================================================
def live_tests() -> None:
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")

    @check("live: GET /v2/bot/info")
    def t_info():
        if not token:
            raise _Skip("未設定 LINE_CHANNEL_ACCESS_TOKEN")
        import lineapi
        info = lineapi.LineClient(token).bot_info()
        assert "basicId" in info or "userId" in info, info
        return f"{info.get('displayName', '?')} ({info.get('basicId', '?')})"

    @check("live: GET /v2/bot/message/quota")
    def t_quota():
        if not token:
            raise _Skip("未設定 LINE_CHANNEL_ACCESS_TOKEN")
        import lineapi
        q = lineapi.LineClient(token).quota()
        assert "type" in q, q
        return json.dumps(q, ensure_ascii=False)

    @check("live: GET webhook endpoint")
    def t_webhook():
        if not token:
            raise _Skip("未設定 LINE_CHANNEL_ACCESS_TOKEN")
        import lineapi
        try:
            info = lineapi.LineClient(token).get_webhook_endpoint()
        except lineapi.LineApiError as e:
            if e.status == 404:
                raise _Skip("尚未設定 webhook endpoint")
            raise
        return f"{info.get('endpoint')} active={info.get('active')}"

    @check("live: LINE accepts the messages this skill builds (validate/push)")
    def t_validate_live():
        if not token:
            raise _Skip("未設定 LINE_CHANNEL_ACCESS_TOKEN")
        import lineapi
        client = lineapi.LineClient(token)
        messages = [
            {"type": "text", "text": "skill self-test"},
            {"type": "flex", "altText": "self-test", "contents": {
                "type": "bubble",
                "body": {"type": "box", "layout": "vertical", "contents": [
                    {"type": "text", "text": "OK", "weight": "bold", "size": "lg"},
                    {"type": "separator", "margin": "md"},
                    {"type": "button", "style": "primary", "action": {
                        "type": "uri", "label": "docs",
                        "uri": "https://developers.line.biz/"}}]}}},
        ]
        offline = val.run(messages, "messages")
        assert not [p for p in offline.problems if p.level == "error"], \
            "離線驗證就沒過，先修好訊息"
        client.validate_push(messages)   # raises on rejection

        # 兩邊逐筆對照。只證明「我們說可以的 LINE 收」還不夠——
        # 「我們說不行的 LINE 也真的退」才代表規則沒有寫過頭。
        # 六個 FALSE-ACCEPT 就是這樣挖出來的（見 t_validate_false_accepts）。
        img = "https://example.com/a.jpg"

        def fbtn(action):
            return {"type": "flex", "altText": "a", "contents": {
                "type": "bubble", "body": {"type": "box", "layout": "vertical",
                                           "contents": [{"type": "button", "action": action}]}}}

        def qr(action):
            return {"type": "text", "text": "h", "quickReply": {
                "items": [{"type": "action", "action": action}]}}

        corpus = [
            ("postback 缺 data", qr({"type": "postback", "label": "a"})),
            ("postback 完整", qr({"type": "postback", "label": "a", "data": "k=v"})),
            ("內容 URL 用 http", {"type": "image", "originalContentUrl": "http://x.com/a.jpg",
                                  "previewImageUrl": "http://x.com/a.jpg"}),
            ("內容 URL 用 https", {"type": "image", "originalContentUrl": img,
                                   "previewImageUrl": img}),
            ("uri 用 ftp", fbtn({"type": "uri", "label": "a", "uri": "ftp://x"})),
            ("uri 用 tel", fbtn({"type": "uri", "label": "a", "uri": "tel:0212345678"})),
            ("quickReply label 21", qr({"type": "message", "label": "x" * 21, "text": "a"})),
            ("quickReply label 20", qr({"type": "message", "label": "x" * 20, "text": "a"})),
            ("flex button label 41", fbtn({"type": "message", "label": "x" * 41, "text": "a"})),
            ("flex button label 40", fbtn({"type": "message", "label": "x" * 40, "text": "a"})),
            ("flex button 缺 label",
             fbtn({"type": "richmenuswitch", "richMenuAliasId": "a1", "data": "k=v"})),
            ("輪播各欄不一致", {"type": "template", "altText": "a", "template": {
                "type": "carousel", "columns": [
                    {"text": "a", "actions": [{"type": "message", "label": "a", "text": "a"}]},
                    {"text": "b", "actions": [
                        {"type": "message", "label": "b", "text": "b"},
                        {"type": "message", "label": "c", "text": "c"}]}]}}),
            ("sticker", {"type": "sticker", "packageId": "446", "stickerId": "1988"}),
        ]
        disagree = []
        for name, msg in corpus:
            ours_ok = not [p for p in val.run([msg], "messages").problems
                           if p.level == "error"]
            try:
                client.validate_push([msg])
                line_ok = True
            except lineapi.LineApiError:
                line_ok = False
            if ours_ok != line_ok:
                side = "我們放行但 LINE 退件" if ours_ok else "我們擋了但 LINE 收"
                disagree.append(f"{name}（{side}）")
        assert not disagree, "與 LINE 官方驗證器判斷不一致：" + "; ".join(disagree)
        return f"{len(corpus)} 個案例與 LINE 官方驗證器逐筆一致"

    channel_id = os.environ.get("LINE_CHANNEL_ID")
    channel_secret = os.environ.get("LINE_CHANNEL_SECRET")
    jwk_path = os.environ.get("LINE_ASSERTION_PRIVATE_KEY")
    kid = os.environ.get("LINE_ASSERTION_KID")

    @check("live: 用 channel ID + secret 換 stateless channel access token")
    def t_stateless():
        if not (channel_id and channel_secret):
            raise _Skip("需要 LINE_CHANNEL_ID 與 LINE_CHANNEL_SECRET")
        result = sig.issue_stateless_token(channel_id, channel_secret)
        assert result.get("access_token"), result
        assert result.get("token_type") == "Bearer", result
        # 官方文件說 stateless token 效期 15 分鐘
        assert int(result.get("expires_in", 0)) == 900,             f"expires_in 應為 900 秒，實際 {result.get('expires_in')}"
        return "取得成功，效期 900 秒（不印出 token）"

    @check("live: 純 Python RS256 JWT 能被 LINE 接受並換到 v2.1 token")
    def t_jwt_live():
        if not (channel_id and jwk_path):
            raise _Skip("需要 LINE_CHANNEL_ID 與 LINE_ASSERTION_PRIVATE_KEY")
        jwk = json.loads(Path(jwk_path).read_text(encoding="utf-8"))
        if "keys" in jwk:
            jwk = jwk["keys"][0]
        assertion = sig.make_jwt(jwk, channel_id, kid=kid or jwk.get("kid"),
                                 token_exp=86400)
        result = sig.issue_token_v21(assertion)
        assert result.get("access_token"), result
        # 這是唯一能證明本專案自己實作的 RS256 簽章與 LINE 伺服器相容的檢查
        return f"LINE 接受了本專案簽出的 JWT，token 效期 {result.get('expires_in')} 秒"

    @check("live: 自己驗一個真的 ID token，並與 LINE 的 verify 端點對答案")
    def t_id_token_live():
        """ID token 是唯一沒辦法單方面取得的東西——它得由使用者實際登入
        一次才會產生。用 tools/get_id_token.py 跑完 LINE Login 之後，
        這一項才會啟用。

        驗兩件事：
          1. 我們純標準函式庫的驗簽，判斷跟 LINE 官方的 verify 端點一致
          2. responses.csv 記的 ID token 欄位，跟實際回傳的一致
        """
        idt = os.environ.get("LINE_ID_TOKEN")
        login_id = os.environ.get("LINE_LOGIN_CHANNEL_ID")
        login_secret = os.environ.get("LINE_LOGIN_CHANNEL_SECRET")
        if not (idt and login_id):
            raise _Skip("需要 LINE_ID_TOKEN 與 LINE_LOGIN_CHANNEL_ID"
                        "（跑 python tools/get_id_token.py）")

        header = json.loads(sig.b64url_decode(idt.split(".")[0]))
        alg = header.get("alg")

        # 1. 我們自己驗
        try:
            mine = sig.verify_id_token(idt, login_id, channel_secret=login_secret)
            mine_ok, mine_err = True, ""
        except ValueError as e:
            mine_ok, mine_err, mine = False, str(e), {}

        # 2. LINE 官方驗
        body = urllib.parse.urlencode({"id_token": idt, "client_id": login_id}).encode()
        req = urllib.request.Request(
            "https://api.line.me/oauth2/v2.1/verify", data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                theirs = json.loads(r.read())
            line_ok = True
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:120]
            theirs, line_ok = {}, False
            if "expired" in detail.lower():
                raise _Skip("這個 ID token 已過期，重跑 tools/get_id_token.py")

        assert mine_ok == line_ok, (
            f"跟 LINE 的判斷不一致：我們{'通過' if mine_ok else '擋下'}"
            f"（{mine_err}），LINE {'通過' if line_ok else '擋下'}")
        assert line_ok, "LINE 說這個 token 無效"

        # 兩邊解出來的身分必須是同一個人
        for field in ("sub", "aud", "iss", "exp"):
            assert str(mine.get(field)) == str(theirs.get(field)),                 f"{field} 解出來不一樣"

        # 3. responses.csv 記的欄位對不對
        claimed = {r["property"] for r in rows("responses.csv")
                   if "Verify ID token" in r["operation_id"]}
        missing = sorted(set(theirs) - claimed)
        assert not missing, f"實際回傳有、資料集沒記的欄位：{missing}"
        return (f"alg={alg}，我們的驗簽與 LINE 一致，"
                f"回傳 {len(theirs)} 個欄位資料集全都有記")

    for fn in (t_info, t_quota, t_webhook, t_validate_live, t_stateless, t_jwt_live,
               t_id_token_live):
        fn()


# ==========================================================================
def main() -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description="LINE API skill 自我測試")
    ap.add_argument("--live", action="store_true", help="加測需要 channel access token 的線上項目")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()
    VERBOSE = args.verbose

    offline = [v for k, v in sorted(globals().items()) if k.startswith("t_") and callable(v)]
    for fn in offline:
        fn()
    if args.live:
        live_tests()

    print()
    print("LINE API skill — 測試結果")
    print("=" * 96)
    icon = {PASS: "PASS", FAIL: "FAIL", SKIP: "SKIP"}
    for status, name, detail in results:
        print(f"[{icon[status]}] {name}")
        if detail and (status != PASS or VERBOSE):
            for line in str(detail).splitlines():
                print(f"        {line}")
        elif detail and status == PASS:
            print(f"        {detail}")
    print("-" * 96)
    counts = {s: sum(1 for r in results if r[0] == s) for s in (PASS, FAIL, SKIP)}
    print(f"{counts[PASS]} passed, {counts[FAIL]} failed, {counts[SKIP]} skipped")
    if not args.live:
        print("提示：設定 LINE_CHANNEL_ACCESS_TOKEN 後加上 --live 可實際打 LINE API 驗證。")
    return 1 if counts[FAIL] else 0


if __name__ == "__main__":
    raise SystemExit(main())
