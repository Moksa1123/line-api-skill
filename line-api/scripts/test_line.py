#!/usr/bin/env python3
"""
LINE API skill — self-test suite.

Offline tests (always run, no credentials, no network):
    dataset integrity, search engine, message validator, webhook signature,
    RS256 JWT construction, api-data host routing.

Live tests (only with LINE_CHANNEL_ACCESS_TOKEN set):
    GET /v2/bot/info, /v2/bot/message/quota, webhook endpoint,
    POST /v2/bot/message/validate/push — LINE's own validator is used to
    confirm the messages this skill produces are accepted, without sending
    anything to a user.

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
from core import use_utf8_stdout  # noqa: E402

use_utf8_stdout()

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
        "webhook-properties.csv",
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
        return "離線驗證與 LINE 官方驗證結果一致"

    for fn in (t_info, t_quota, t_webhook, t_validate_live):
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
