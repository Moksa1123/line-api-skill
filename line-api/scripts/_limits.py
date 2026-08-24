"""程式碼裡寫死的 LINE 限制值，跟官方對不對得起來。

## 為什麼要有這一條

這一類 bug 不會壞、不會被 LINE 退、驗證器也看不出來：

    export const MAX_ALT_TEXT = 400      // 官方是 1500

400 比 1500 小，送出去 LINE 照收，測試全綠，客人也不會抱怨——
只是通知列上的文字被白白砍掉四分之三，而沒有人會發現。反過來寫得比官方
大則會在正式環境被退件，而且多半是在某個剛好超長的真實資料上才第一次爆。

## 這裡不寫死任何數字

每一個概念只記「它對應資料集的哪一列」，值一律當場查。官方改了限制、
重跑 build_dataset.py 之後，這條規則自動跟著更新——把數字抄進來就會有
第二份會過期的真相，而這整個專案存在的理由就是不要有那種東西。

## 同名不同義的處理

`MAX_CARDS = 10` 可能指樣板輪播的 10 欄，也可能指 Flex 輪播的 12 個 bubble。
所以一個概念可以有多個候選值，**只有在程式碼裡的數字跟每一個候選都不同時**
才報。寧可漏掉一個模稜兩可的，也不要對著寫對的人喊錯。
"""
from __future__ import annotations

import re

# 概念 → 這個概念在資料集裡的出處（可以有多個，代表同名不同義）
#   (檔案, type 或 schema, 屬性)
CONCEPTS: dict[str, list[tuple[str, str, str]]] = {
    "alttext": [("message-objects.csv", "flex", "altText")],
    "text": [("message-objects.csv", "text", "text")],
    "messagetext": [("message-objects.csv", "text", "text")],
    "chatbartext": [("richmenu.csv", "RichMenuRequest", "chatBarText")],
    "richmenuname": [("richmenu.csv", "RichMenuRequest", "name")],
    "richmenuareas": [("richmenu.csv", "RichMenuRequest", "areas")],
    "areas": [("richmenu.csv", "RichMenuRequest", "areas")],
    "bubbles": [("flex-components.csv", "carousel", "contents")],
    "flexbubbles": [("flex-components.csv", "carousel", "contents")],
    "carouselbubbles": [("flex-components.csv", "carousel", "contents")],
    "quickreplies": [("message-objects.csv", "QuickReply", "items")],
    "quickreplyitems": [("message-objects.csv", "QuickReply", "items")],
    "postbackdata": [("actions.csv", "postback", "data")],
    "sendername": [("message-objects.csv", "Sender", "name")],
    # 同名不同義：卡片可能是樣板輪播的欄，也可能是 Flex 輪播的 bubble
    "cards": [("message-objects.csv", "CarouselTemplate", "columns"),
              ("flex-components.csv", "carousel", "contents")],
    "carouselcards": [("message-objects.csv", "CarouselTemplate", "columns"),
                      ("flex-components.csv", "carousel", "contents")],
    "columns": [("message-objects.csv", "CarouselTemplate", "columns")],
    # action 的 label 上限依「放在哪」而不同，三個都是合法答案
    "actionlabel": [("actions.csv", "message", "label")],
}

# 這幾個概念的名字太通用：CSS 有 columns、報表有 text、UI 有 cards、
# 地圖有 areas。實測掃一個 1165 檔的專案，label-print-css.ts 的
# `columns = 1` 與 stat-card.tsx 的 `columns = 4` 都被當成樣板輪播的欄數。
# 所以這幾個要檔案本身有夠強的 LINE 味道才算——只靠檔案裡有 "line"
# 是不夠的，line-height 也是 line。
GENERIC = {"text", "cards", "columns", "areas"}

LINE_CONTEXT = re.compile(
    r"(?i)(@line/|liff\.|line\.me|x-line-signature|richmenu|rich_menu"
    r"|flexmessage|flex_message|quickreply|quick_reply|replytoken"
    r"|channelaccesstoken|channel_access_token|messagingapi|messaging_api)")


# 這些字拿掉之後才是概念本身
STRIP_PREFIX = ("max", "min", "limit", "line", "the")
STRIP_SUFFIX = ("length", "limit", "max", "count", "chars", "characters",
                "size", "len", "num", "total")


def normalise(identifier: str) -> str:
    """MAX_ALT_TEXT / maxAltTextLength / MAX_ALT_TEXT_CHARS → alttext"""
    parts = re.split(r"[_\-\s]+|(?<=[a-z0-9])(?=[A-Z])", identifier)
    words = [p.lower() for p in parts if p]
    while words and words[0] in STRIP_PREFIX:
        words.pop(0)
    while words and words[-1] in STRIP_SUFFIX:
        words.pop()
    return "".join(words)


def official_values(rows_fn) -> dict[str, list[tuple[int, str, str]]]:
    """概念 → [(官方值, 出處說明, doc_url)]。查不到出處的概念直接略過。"""
    cache: dict[str, list[dict]] = {}
    out: dict[str, list[tuple[int, str, str]]] = {}
    for concept, sources in CONCEPTS.items():
        found = []
        for fname, owner, prop in sources:
            if fname not in cache:
                cache[fname] = rows_fn(fname)
            for r in cache[fname]:
                if r.get("property") != prop:
                    continue
                if r.get("type") != owner and r.get("schema") != owner:
                    continue
                raw = (r.get("max_length") or "").strip()
                if raw.isdigit():
                    found.append((int(raw), f"{owner}.{prop}", r.get("doc_url", "")))
                break
        if found:
            out[concept] = found
    return out


# 只看「識別字 = 數字」這種形式。底線分隔的數字（5_000）也要吃得下
ASSIGN = re.compile(
    r"\b(?P<name>[A-Za-z_][A-Za-z0-9_]{2,40})\s*[:=]\s*(?P<value>\d[\d_]*)\b")


def scan(text: str, values: dict[str, list[tuple[int, str, str]]]):
    """回傳 [(行號, 識別字, 程式裡的值, 官方候選)]。"""
    hits = []
    strong = bool(LINE_CONTEXT.search(text))
    for m in ASSIGN.finditer(text):
        concept = normalise(m.group("name"))
        candidates = values.get(concept)
        if not candidates:
            continue
        if concept in GENERIC and not strong:
            continue
        value = int(m.group("value").replace("_", ""))
        if any(value == official for official, _, _ in candidates):
            continue
        hits.append((text[:m.start()].count("\n") + 1,
                     m.group("name"), value, candidates))
    return hits
