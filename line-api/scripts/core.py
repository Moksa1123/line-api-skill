#!/usr/bin/env python3
"""
LINE API skill — BM25 search engine over the generated dataset.

Pure standard library. Mirrors the search architecture used by the
taiwan-payment / taiwan-invoice skills so the CLI feels identical.

    from core import search, search_all, detect_domain

    search("push message", domain="endpoint")
    search("2000010")                 # domain auto-detected
    search_all("rich menu")
"""
from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR.parent / "data"


def use_utf8_stdout() -> None:
    """Windows consoles default to cp950/cp1252 and mangle the Chinese output."""
    import sys as _sys
    for stream in (_sys.stdout, _sys.stderr):
        enc = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if enc != "utf8" and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

# --------------------------------------------------------------------------
# domain configuration: which CSV, which columns are searched, which are shown
# --------------------------------------------------------------------------
CSV_CONFIG: Dict[str, dict] = {
    "endpoint": {
        "file": "endpoints.csv",
        "search_cols": ["title", "path", "operation_id", "description", "category", "api"],
        "output_cols": ["api", "title", "method", "host", "path", "query_params",
                        "auth", "rate_limit", "operation_id", "description", "doc_url"],
        "label": "API 端點",
    },
    "parameter": {
        "file": "parameters.csv",
        "search_cols": ["parameter", "endpoint", "block", "description", "value_type", "section"],
        "output_cols": ["api", "endpoint", "block", "parameter", "value_type",
                        "required", "max", "description", "doc_url"],
        "label": "請求/回應欄位",
    },
    "message": {
        "file": "message-objects.csv",
        "search_cols": ["type", "schema", "property", "description", "enum", "group"],
        "output_cols": ["group", "type", "property", "value_type", "required",
                        "enum", "max_length", "default", "description", "doc_url"],
        "label": "訊息物件",
    },
    "flex": {
        "file": "flex-components.csv",
        "search_cols": ["type", "schema", "property", "description", "enum", "group"],
        "output_cols": ["group", "type", "property", "value_type", "required",
                        "enum", "max_length", "default", "description", "doc_url"],
        "label": "Flex Message 元件",
    },
    "action": {
        "file": "actions.csv",
        "search_cols": ["type", "schema", "property", "description", "enum"],
        "output_cols": ["type", "property", "value_type", "required", "enum",
                        "max_length", "default", "description", "doc_url"],
        "label": "Action 物件",
    },
    "richmenu": {
        "file": "richmenu.csv",
        "search_cols": ["type", "schema", "property", "description", "enum"],
        "output_cols": ["type", "property", "value_type", "required", "enum",
                        "max_length", "default", "description", "doc_url"],
        "label": "圖文選單",
    },
    "webhook": {
        "file": "webhook-events.csv",
        "search_cols": ["event", "schema", "properties", "description"],
        "output_cols": ["event", "schema", "required", "properties", "description", "doc_url"],
        "label": "Webhook 事件",
    },
    "liff": {
        "file": "liff-api.csv",
        "search_cols": ["name", "category", "description", "returns", "syntax"],
        "output_cols": ["name", "kind", "category", "syntax", "returns", "description", "doc_url"],
        "label": "LIFF SDK",
    },
    "error": {
        "file": "error-codes.csv",
        "search_cols": ["code_or_message", "description", "scope", "api", "kind"],
        "output_cols": ["api", "kind", "scope", "code_or_message", "description", "doc_url"],
        "label": "錯誤碼 / 錯誤訊息",
    },
    "limit": {
        "file": "limits.csv",
        "search_cols": ["field", "schema", "constraint", "description"],
        "output_cols": ["schema", "field", "constraint", "value", "description"],
        "label": "數值限制",
    },
    "product": {
        "file": "products.csv",
        "search_cols": ["product", "product_zh", "what_it_is", "use_when", "key_apis", "channel_type"],
        "output_cols": ["product", "product_zh", "channel_type", "what_it_is",
                        "use_when", "key_apis", "auth", "doc_url"],
        "label": "LINE 產品",
    },
    "token": {
        "file": "channel-tokens.csv",
        "search_cols": ["token_type", "token_type_zh", "use_when", "how_to_issue", "endpoint"],
        "output_cols": ["token_type_zh", "token_type", "validity", "max_per_channel",
                        "endpoint", "use_when", "doc_url"],
        "label": "存取權杖",
    },
    "troubleshoot": {
        "file": "troubleshooting.csv",
        "search_cols": ["issue", "symptom", "cause", "solution", "area"],
        "output_cols": ["issue", "symptom", "cause", "solution", "area", "severity", "doc_url"],
        "label": "疑難排解",
    },
    "reasoning": {
        "file": "reasoning.csv",
        "search_cols": ["scenario", "recommendation", "reason", "key_apis", "anti_patterns"],
        "output_cols": ["scenario", "recommendation", "confidence", "reason",
                        "anti_patterns", "key_apis", "doc_url"],
        "label": "選型建議",
    },
    "deprecation": {
        "file": "deprecations.csv",
        "search_cols": ["item", "status", "replacement", "note"],
        "output_cols": ["item", "status", "effective_date", "replacement", "note", "doc_url"],
        "label": "已停用 / 已淘汰",
    },
    "emoji": {
        "file": "emoji.csv",
        "search_cols": ["product_id"],
        "output_cols": ["product_id", "emoji_id_from", "emoji_id_to", "count"],
        "label": "LINE emoji",
    },
    "sticker": {
        "file": "stickers.csv",
        "search_cols": ["package_id", "title_en", "sticker_ids"],
        "output_cols": ["package_id", "title_en", "sticker_id_from", "sticker_id_to", "count"],
        "label": "貼圖",
    },
}

# --------------------------------------------------------------------------
# domain auto-detection
# --------------------------------------------------------------------------
DOMAIN_KEYWORDS: Dict[str, List[str]] = {
    "endpoint": ["endpoint", "api", "url", "reply", "push", "multicast", "broadcast",
                 "narrowcast", "端點", "路徑", "呼叫"],
    "parameter": ["parameter", "property", "field", "參數", "欄位", "屬性", "request body"],
    "message": ["message", "text", "sticker", "imagemap", "template", "訊息", "文字訊息",
                "圖片訊息", "影片訊息", "樣板"],
    "flex": ["flex", "bubble", "carousel", "box", "彈性訊息", "卡片"],
    "action": ["action", "postback", "datetimepicker", "uri", "動作", "按鈕"],
    "richmenu": ["richmenu", "rich menu", "圖文選單", "選單"],
    "webhook": ["webhook", "event", "follow", "unfollow", "join", "leave", "事件", "回呼"],
    "liff": ["liff", "front-end", "前端", "liff.init", "liff."],
    "error": ["error", "400", "401", "403", "404", "409", "429", "500", "錯誤", "失敗"],
    "limit": ["limit", "max", "maximum", "限制", "上限", "最多", "長度"],
    "product": ["product", "login", "mini app", "social plugin", "beacon", "產品", "選哪個"],
    "token": ["token", "access token", "jwt", "channel secret", "權杖", "認證", "授權"],
    "troubleshoot": ["troubleshoot", "problem", "not working", "fail", "怎麼辦",
                     "問題", "排解", "為什麼", "收不到", "驗證失敗", "沒反應", "沒收到", "無法"],
    "reasoning": ["recommend", "which", "should i", "best", "or", "vs",
                  "推薦", "建議", "適合", "比較", "還是", "哪個", "該用", "怎麼選", "選型"],
    "deprecation": ["deprecated", "discontinued", "notify", "停用", "淘汰", "已終止", "取代"],
    "emoji": ["emoji", "表情"],
    "sticker": ["sticker", "貼圖", "package id"],
}

_CACHE: Dict[str, Tuple[List[dict], List[List[str]]]] = {}
_GLOSSARY: Optional[List[Tuple[str, str]]] = None


def load_glossary() -> List[Tuple[str, str]]:
    """zh -> en term pairs, longest Chinese term first so 圖文選單 beats 選單."""
    global _GLOSSARY
    if _GLOSSARY is not None:
        return _GLOSSARY
    pairs: List[Tuple[str, str]] = []
    path = DATA_DIR / "glossary.csv"
    if path.exists():
        with open(path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                zh, en = (row.get("zh") or "").strip(), (row.get("en") or "").strip()
                if zh and en:
                    pairs.append((zh, en))
    pairs.sort(key=lambda p: -len(p[0]))
    _GLOSSARY = pairs
    return pairs


def expand_query(query: str) -> str:
    """Append the English equivalents of any Chinese terms found in the query.

    The generated dataset is English (it comes from LINE's own specs), so a
    Chinese query would otherwise never match it.
    """
    extra: List[str] = []
    for zh, en in load_glossary():
        if zh in query:
            for token in en.split():
                if token.lower() not in query.lower() and token not in extra:
                    extra.append(token)
    return (query + " " + " ".join(extra)).strip() if extra else query


# --------------------------------------------------------------------------
CAMEL_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+")


def tokenize(text: str) -> List[str]:
    """Mixed CJK / latin tokenizer.

    Latin runs are emitted whole *and* split on camelCase / dotted paths, so a
    query for "multicast" still finds `MulticastRequest.to` and "chat bar"
    finds `chatBarText`. CJK is indexed as unigrams plus bigrams.
    """
    if not text:
        return []
    tokens: List[str] = []
    for m in re.finditer(r"[A-Za-z0-9_.]+", text):
        run = m.group()
        tokens.append(run.lower())
        parts = [p for chunk in run.replace("_", ".").split(".") if chunk
                 for p in CAMEL_RE.findall(chunk)]
        if len(parts) > 1 or parts and parts[0].lower() != run.lower():
            tokens.extend(p.lower() for p in parts)
    cjk = re.findall(r"[一-鿿]", text)
    tokens.extend(cjk)
    tokens.extend(cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1))
    return tokens


def compute_idf(documents: List[List[str]]) -> Dict[str, float]:
    n = len(documents)
    df: Dict[str, int] = {}
    for doc in documents:
        for term in set(doc):
            df[term] = df.get(term, 0) + 1
    return {t: math.log((n - f + 0.5) / (f + 0.5) + 1.0) for t, f in df.items()}


def bm25_score(query_tokens, doc_tokens, idf, avg_dl, k1: float = 1.5, b: float = 0.75) -> float:
    dl = len(doc_tokens) or 1
    tf: Dict[str, int] = {}
    for term in doc_tokens:
        tf[term] = tf.get(term, 0) + 1
    score = 0.0
    for term in query_tokens:
        f = tf.get(term)
        if not f:
            continue
        score += idf.get(term, 0.0) * (f * (k1 + 1)) / (f + k1 * (1 - b + b * (dl / avg_dl)))
    return score


def _norm(s: str) -> str:
    return re.sub(r"[\s_\-/]+", " ", str(s).lower()).strip()


def primary_boost(query: str, row: dict, cfg: dict) -> float:
    """Reward rows whose *primary* field actually names what was asked for.

    Pure BM25 over concatenated columns ranks "Validate message objects of a
    push message" above "Send push message" for the query "push message";
    this boost restores the intuitive ordering.
    """
    primary = _norm(row.get(cfg["search_cols"][0], ""))
    if not primary:
        return 0.0
    q = _norm(query)
    boost = 0.0
    if q and q in primary:
        # coverage: how much of the primary field the query accounts for
        boost += 3.0 + 6.0 * (len(q) / len(primary))
        if primary == q:
            boost += 3.0
    else:
        qt = [t for t in q.split() if t]
        if qt and all(t in primary for t in qt):
            boost += 1.5
    # prefer the more specific (shorter) primary field among equals
    boost += max(0.0, 1.0 - len(primary) / 120.0)
    return boost


def load_csv(domain: str) -> Tuple[List[dict], List[List[str]]]:
    if domain in _CACHE:
        return _CACHE[domain]
    cfg = CSV_CONFIG.get(domain)
    if not cfg:
        return [], []
    path = DATA_DIR / cfg["file"]
    if not path.exists():
        return [], []
    rows, docs = [], []
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            rows.append(row)
            docs.append(tokenize(" ".join(str(row.get(c, "")) for c in cfg["search_cols"])))
    _CACHE[domain] = (rows, docs)
    return rows, docs


def detect_domain(query: str) -> str:
    q = expand_query(query).lower()
    # weight by keyword length: "驗證失敗" (troubleshoot) should beat "失敗" (error)
    def weight(kw: str) -> int:
        # a CJK keyword carries far more meaning per character than a latin one
        return len(kw) * (3 if re.search(r"[一-鿿]", kw) else 1)

    scores = {d: sum(weight(kw) for kw in kws if kw in q) for d, kws in DOMAIN_KEYWORDS.items()}
    # a bare HTTP status code is almost always an error lookup
    if re.fullmatch(r"[1-5]\d\d", query.strip()):
        return "error"
    if query.strip().startswith("liff."):
        return "liff"
    if query.strip().startswith("/") or query.strip().startswith("http"):
        return "endpoint"
    best = max(scores.values())
    if best == 0:
        return "endpoint"
    return max(scores, key=lambda d: scores[d])


def search(query: str, domain: Optional[str] = None, max_results: int = 5) -> List[dict]:
    if not query:
        return []
    domain = domain or detect_domain(query)
    rows, docs = load_csv(domain)
    expanded = expand_query(query)
    if not rows:
        return []
    cfg = CSV_CONFIG[domain]
    idf = compute_idf(docs)
    avg_dl = sum(len(d) for d in docs) / len(docs)
    qt = tokenize(expanded)

    scored = []
    for i, doc in enumerate(docs):
        s = bm25_score(qt, doc, idf, avg_dl)
        if s > 0:
            scored.append((s + primary_boost(expanded, rows[i], cfg), i))
    scored.sort(key=lambda x: (-x[0], x[1]))

    out = []
    for score, idx in scored[:max_results]:
        row = rows[idx]
        item = {c: row.get(c, "") for c in cfg["output_cols"]}
        item["_score"] = round(score, 2)
        item["_domain"] = domain
        out.append(item)
    return out


def search_all(query: str, max_per_domain: int = 3) -> Dict[str, List[dict]]:
    result = {}
    for domain in CSV_CONFIG:
        hits = search(query, domain=domain, max_results=max_per_domain)
        if hits:
            result[domain] = hits
    return result


def dataset_stats() -> Dict[str, int]:
    stats = {}
    for domain, cfg in CSV_CONFIG.items():
        path = DATA_DIR / cfg["file"]
        stats[domain] = (len(load_csv(domain)[0]) if path.exists() else -1)
    return stats


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("usage: python core.py <query> [domain]")
        print("domains:", ", ".join(CSV_CONFIG))
        raise SystemExit(1)
    q = sys.argv[1]
    d = sys.argv[2] if len(sys.argv) > 2 else None
    res = search_all(q) if d == "all" else search(q, domain=d)
    print(json.dumps(res, ensure_ascii=False, indent=2))
