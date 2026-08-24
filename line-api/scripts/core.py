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


def load_dotenv(start: Path | None = None) -> int:
    """把 .env 裡的設定讀進 os.environ（只用標準函式庫）。

    repo 裡放了 .env.example 要人填憑證，腳本卻只讀 os.environ——寫進 .env
    根本不會生效。這裡從腳本位置往上找 .env，補上這一段。
    已存在的環境變數優先，不會被 .env 覆寫。
    """
    import os

    here = (start or SCRIPT_DIR).resolve()
    for folder in [here, *here.parents]:
        env = folder / ".env"
        if not env.exists():
            continue
        loaded = 0
        for raw in env.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and value and key not in os.environ:
                os.environ[key] = value
                loaded += 1
        return loaded
    return 0


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
    "webhook_field": {
        "file": "webhook-properties.csv",
        "search_cols": ["type", "schema", "property", "description", "enum", "group"],
        "output_cols": ["group", "type", "property", "value_type", "required",
                        "enum", "max_length", "default", "description", "doc_url"],
        "label": "Webhook 欄位",
    },
    "response": {
        "file": "responses.csv",
        "search_cols": ["operation_id", "path", "schema", "property", "description"],
        "output_cols": ["operation_id", "method", "path", "status", "schema",
                        "property", "value_type", "required", "enum", "max_length",
                        "description", "doc_url"],
        "label": "API 回應欄位",
    },
    "liff_availability": {
        "file": "liff-availability.csv",
        "search_cols": ["feature", "how_to_check", "min_line_version"],
        "output_cols": ["feature", "needs_permission", "min_line_version",
                        "min_os_version", "unsupported_from_version",
                        "how_to_check", "doc_url"],
        "label": "LIFF 功能需要的 LINE App 版本",
    },
    "checklist": {
        "file": "checklists.csv",
        "search_cols": ["rule", "section", "page_title", "product"],
        "output_cols": ["product", "page_title", "section", "rule", "doc_url"],
        "label": "規範與檢查清單",
    },
    "guide_spec": {
        "file": "guide-specs.csv",
        "search_cols": ["item", "attribute", "section", "page_title", "value", "product"],
        "output_cols": ["product", "page_title", "section", "item", "attribute",
                        "value", "doc_url"],
        "label": "指南頁規格（表格萃取）",
    },
    "guide": {
        "file": "guides.csv",
        "search_cols": ["title", "sections", "page", "product"],
        "output_cols": ["product", "title", "page", "sections", "doc_url"],
        "label": "官方指南頁",
    },
    "liff_version": {
        "file": "liff-versions.csv",
        "search_cols": ["version", "apis_touched", "released"],
        "output_cols": ["version", "released", "apis_touched", "doc_url"],
        "label": "LIFF 版本沿革",
    },
    "liff": {
        "file": "liff-api.csv",
        "search_cols": ["name", "category", "description", "returns", "syntax"],
        "output_cols": ["name", "kind", "category", "module", "before_init",
                        "introduced_in", "syntax", "returns", "description", "doc_url"],
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
    "sdk_api": {
        "file": "sdk-api.csv",
        "search_cols": ["name", "package", "platform", "kind"],
        "output_cols": ["platform", "kind", "name", "package", "doc_url"],
        "label": "行動 SDK 型別",
    },
    "faq": {
        "file": "faq.csv",
        "search_cols": ["question", "tags", "product"],
        "output_cols": ["question", "product", "tags", "doc_url"],
        "label": "官方 FAQ",
    },
    "url_scheme": {
        "file": "url-schemes.csv",
        "search_cols": ["scheme", "purpose", "category", "note"],
        "output_cols": ["scheme", "category", "purpose", "note", "doc_url"],
        "label": "LINE URL scheme",
    },
    "term": {
        "file": "terms.csv",
        "search_cols": ["term", "term_zh", "definition", "category"],
        "output_cols": ["term", "term_zh", "category", "definition", "doc_url"],
        "label": "官方術語",
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
    # 指南頁的規格：LIFF 與 MINI App 的規則大半寫在指南的表格裡，
    # 不在 reference 的參數區塊，所以要獨立一個域才查得到
    "liff_availability": ["isapiavailable", "is api available", "minver",
                          "line 版本", "版本需求", "支援版本", "availability",
                          "哪個版本", "沒反應", "不支援"],
    "checklist": ["送審", "審核", "review", "submission", "guideline", "規範",
                  "policy", "政策", "被退件", "requirement", "檢查清單",
                  "注意事項", "禁止"],
    "guide_spec": ["mini app", "miniapp", "mini-app", "service message", "服務訊息",
                   "icon", "圖示", "custom path", "自訂路徑", "in-app purchase",
                   "站內購買", "quick fill", "share message", "分享訊息",
                   "home screen", "桌面捷徑", "permanent link", "永久連結",
                   "verified", "已驗證", "unverified", "未驗證", "landscape",
                   "審核", "review", "consent", "同意"],
    "endpoint": ["endpoint", "api", "url", "reply", "push", "multicast", "broadcast",
                 "narrowcast", "端點", "路徑", "呼叫"],
    "parameter": ["parameter", "property", "field", "參數", "欄位", "屬性", "request body"],
    "message": ["message", "text", "sticker", "imagemap", "template", "訊息", "文字訊息",
                "圖片訊息", "影片訊息", "樣板"],
    "flex": ["flex", "bubble", "carousel", "box", "彈性訊息", "卡片"],
    "action": ["action", "postback", "datetimepicker", "uri", "動作", "按鈕"],
    "richmenu": ["richmenu", "rich menu", "圖文選單", "選單"],
    "webhook": ["webhook", "event", "follow", "unfollow", "join", "leave", "事件", "回呼"],
    "webhook_field": ["postback.params", "deliverycontext", "webhookeventid", "replytoken",
                      "quotetoken", "markasreadtoken", "source.type", "isredelivery",
                      "事件欄位", "webhook 欄位"],
    "liff": ["liff", "front-end", "前端", "liff.init", "liff.", "@line/liff",
             "模組化匯入", "tree shaking"],
    "response": ["response", "returns", "回應", "回傳", "回什麼", "response body"],
    "guide": ["guide", "how to", "tutorial", "step", "指南", "教學", "步驟",
              "怎麼做", "怎麼建", "怎麼切", "怎麼設", "哪一頁", "文件在哪", "範例流程"],
    "liff_version": ["liff version", "版本", "哪一版", "release notes", "sdk 版本"],
    "error": ["error", "400", "401", "403", "404", "409", "429", "500", "錯誤", "失敗"],
    "limit": ["limit", "max", "maximum", "限制", "上限", "最多", "長度"],
    "product": ["product", "login", "mini app", "social plugin", "beacon", "產品", "選哪個"],
    "sdk_api": ["ios sdk", "android sdk", "swift", "kotlin", "java sdk",
                "linesdk", "loginmanager", "lineapiclient", "行動 sdk", "原生 sdk"],
    "faq": ["faq", "常見問題", "官方有沒有說", "官方說明", "為什麼會", "可不可以"],
    "url_scheme": ["url scheme", "line://", "line.me/r", "openexternalbrowser",
                   "深層連結", "深連結", "開啟相機", "開啟聊天室", "加好友連結", "分享連結"],
    "term": ["glossary", "terminology", "what is", "術語", "名詞", "是什麼", "定義",
             "provider", "channel secret", "mid", "subprofile", "target reach"],
    "token": ["token", "access token", "jwt", "channel secret", "權杖", "認證", "授權"],
    "troubleshoot": ["troubleshoot", "problem", "not working", "fail", "怎麼辦",
                     "問題", "排解", "為什麼", "收不到", "驗證失敗", "沒反應", "沒收到", "無法"],
    "reasoning": ["recommend", "which", "should i", "best", "or", "vs",
                  "推薦", "建議", "適合", "比較", "還是", "哪個", "該用", "怎麼選", "選型"],
    "deprecation": ["還能用", "還可以用", "停用", "停止服務", "終止", "淘汰", "廢除", "已停", "不能用了", "deprecated", "discontinued", "notify", "停用", "淘汰", "已終止", "取代"],
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
    # 查詢字串剛好就是某個識別欄位的完整值——那一列講的就是這個東西。
    # primary 只看 search_cols[0]，而屬性型的域（message / flex /
    # webhook_field / response）的第一欄是 type 或 operation_id，
    # 於是查屬性名完全拿不到加權：查 source 會被「描述裡提到 source」
    # 的列蓋過去，查 flex 排第一的是 separator。
    # 只認「沒有空白的完整值」，避免長描述剛好等於查詢時亂加分。
    if q and " " not in q:
        for col in cfg["search_cols"]:
            if col in ("description", "note", "purpose"):
                continue          # 散文欄位剛好等於查詢是巧合，不是身分
            v = _norm(row.get(col, ""))
            if v == q:
                boost += 4.0
                break

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


def domain_scores(query: str) -> Dict[str, int]:
    """每個域的關鍵字命中分數。detect_domain 只取最高的那個，
    跨域搜尋則需要整張分佈當先驗權重。"""
    q = expand_query(query).lower()

    def weight(kw: str) -> int:
        return len(kw) * (3 if re.search(r"[一-鿿]", kw) else 1)

    return {d: sum(weight(kw) for kw in kws if kw in q)
            for d, kws in DOMAIN_KEYWORDS.items()}


def search_one(query: str, domain: str, max_results: int = 5) -> List[dict]:
    """只搜一個域。指定 --domain 時走這裡。"""
    return _search_domain(query, domain, max_results)


def search(query: str, domain: Optional[str] = None, max_results: int = 5) -> List[dict]:
    """沒指定域就跨域搜尋，不要把全部賭在一次猜測上。

    原本是 detect_domain 猜一個域、只搜那一個。實測 55 個實戰問題只有
    65% 答得出來——而且答不出來的那些，事實明明都在資料集裡：
    「altText 上限」被判到 limit 域，可是 altText 的 1500 存在
    message-objects；「webhook 簽章怎麼算」被判到 webhook 事件欄位，
    可是簽章的作法在 troubleshoot。猜錯一次，答案就再也看不到。

    改成每個域都搜，再用「域的關鍵字分數」當先驗權重合併排序。
    猜對的域仍然排前面，猜錯時其他域的答案也還在。
    """
    if not query:
        return []
    if domain:
        return _search_domain(query, domain, max_results)

    # 列舉問題不該用五列來回答「有哪些」。webhook 有 20 種事件，
    # 硬塞進五格等於挑五個給你看，而使用者要的是那張清單本身。
    # 同一種只留一列（在域內已去重），所以多回幾列不會變成雜訊。
    listing = bool(LIST_INTENT.search(query))
    if listing:
        max_results = max(max_results, 15)

    priors = domain_scores(query)
    top = max(priors.values()) or 1
    pool: List[tuple] = []
    for dom in CSV_CONFIG:
        hits = _search_domain(query, dom, max_results)
        if not hits:
            continue
        best = hits[0]["_score"] or 1.0
        # 域內先正規化（各域的 BM25 尺度不同，直接比大小沒有意義），
        # 再乘上這個域有多像是問題想問的
        prior = 1.0 + 1.5 * (priors.get(dom, 0) / top)
        for h in hits:
            pool.append((h["_score"] / best * prior, -h["_score"], h))
    pool.sort(key=lambda x: (-x[0], x[1]))

    # 一個域最多佔一半的名額。跨域搜了卻讓猜錯的那個域把五個位置全佔滿，
    # 等於白搜——實測「圖文選單圖片尺寸」前五名全是 RichMenuArea 的欄位，
    # 而答案在別的域。先照名次挑、每域設上限，不夠再回頭補滿。
    # 「這個物件有哪些欄位」本質上就是單一域的問題——問貼圖訊息的欄位，
    # 答案就該是好幾列貼圖訊息的欄位，分給別的域反而是雜訊。
    # 問「上限多少」才需要分散，因為答案常常不在猜中的那個域。
    # 問欄位時放寬到「留兩格給別的域」而不是全給——全給的話
    # 「群組事件的 source 有什麼」五格全被事件列佔滿，
    # 而答案在 webhook 逐欄位那一份的 Source 物件裡
    # 列舉與問欄位都是「答案集中在一個域」的問題，但列舉更極端：
    # 那張清單本來就住在同一份資料裡
    if listing:
        cap = max_results
    elif FIELD_INTENT.search(query):
        cap = max(2, max_results - 2)
    else:
        cap = max(1, max_results // 2)
    used: Dict[str, int] = {}
    picked, spare = [], []
    for _, _, hit in pool:
        dom = hit["_domain"]
        if used.get(dom, 0) < cap:
            used[dom] = used.get(dom, 0) + 1
            picked.append(hit)
            if len(picked) >= max_results:
                return picked
        else:
            spare.append(hit)
    return (picked + spare)[:max_results]


# 問「上限是多少」的時候，答案一定是個數字。沒有數字的那一列再怎麼
# 字面相似都不是答案——「圖文選單最多幾個區域」原本前五名全是
# RichMenuArea 的 bounds / action，而答案在 RichMenuRequest.areas = 20。
WANTS_NUMBER = re.compile(
    r"(?i)(上限|最多|幾個|幾則|幾筆|多少|多久|效期|限制|大小|長度|尺寸"
    r"|limit|max|maximum|how many|how long|size|length)")
NUMBER_FIELDS = ("max_length", "max", "value", "min_line_version")

# 「有哪些型別／種類」是列舉問題，不是查值問題。回五列同一種型別
# 等於沒有回答——問 webhook 有哪些事件，答案該是不同的事件各一列。
LIST_INTENT = re.compile(
    r"(?i)(有哪些|哪幾種|有幾種|列出|全部的|所有的|種類"
    r"|list|what types|which types|all的)")
# 每個域用哪一欄當「這是哪一種」
DISCRIMINATOR = ("event", "type", "feature", "item", "scheme", "term", "name")


def _kind_of(row: dict) -> str:
    for col in DISCRIMINATOR:
        v = str(row.get(col) or "").strip()
        if v:
            return v
    return ""


# 問「有哪些欄位／屬性」時不要分散名額
FIELD_INTENT = re.compile(
    r"(?i)(欄位|屬性|參數|有什麼|要什麼|長什麼樣|結構"
    r"|fields?|properties|params?|schema)")


def _has_number(row: dict) -> bool:
    for f in NUMBER_FIELDS:
        v = str(row.get(f) or "").strip()
        if v and any(c.isdigit() for c in v):
            return True
    return False


# 帶標點的識別字是很強的訊號：line://、liff.getIDToken、x-line-signature、
# /v2/bot/message/push —— 這些字面出現在某一列裡，那一列幾乎一定就是答案。
# BM25 會把它拆成子詞，於是「line:// 還能用嗎」變成跟一堆含 line 的列競爭，
# 真正在講 line:// 的那列排到第三，剛好被跨域合併的名額切掉。
LITERAL = re.compile(
    r"(?:/[A-Za-z0-9{}][A-Za-z0-9{}/._-]{3,}"          # /v2/bot/message/push
    r"|[A-Za-z][A-Za-z0-9]*(?:[.:/_-]+[A-Za-z0-9]*)+)"  # line:// liff.getIDToken x-line-signature
)


def _literals(query: str) -> List[str]:
    out = []
    for m in LITERAL.finditer(query):
        tok = m.group(0)
        # 要有標點才算識別字，而且長到不會誤傷（"a.b" 太短）
        if len(tok) >= 5 and re.search(r"[.:/_-]", tok):
            out.append(tok.lower())
    return out


def _search_domain(query: str, domain: str, max_results: int) -> List[dict]:
    rows, docs = load_csv(domain)
    expanded = expand_query(query)
    if not rows:
        return []
    cfg = CSV_CONFIG[domain]
    idf = compute_idf(docs)
    avg_dl = sum(len(d) for d in docs) / len(docs)
    qt = tokenize(expanded)

    wants_number = bool(WANTS_NUMBER.search(expanded))
    literals = _literals(query)
    scored = []
    for i, doc in enumerate(docs):
        s = bm25_score(qt, doc, idf, avg_dl)
        if s > 0:
            s += primary_boost(expanded, rows[i], cfg)
            if wants_number and _has_number(rows[i]):
                s += 3.0
            if literals:
                blob = " ".join(str(rows[i].get(c, "")) for c in cfg["search_cols"]).lower()
                if any(lit in blob for lit in literals):
                    s += 12.0
            scored.append((s, i))
    scored.sort(key=lambda x: (-x[0], x[1]))

    # 列舉問題：同一種只留一列，把名額讓給不同的種類
    if LIST_INTENT.search(query):
        seen_kind, deduped = set(), []
        for sc, idx in scored:
            kind = _kind_of(rows[idx])
            if kind and kind in seen_kind:
                continue
            seen_kind.add(kind)
            deduped.append((sc, idx))
        scored = deduped

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
