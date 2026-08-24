#!/usr/bin/env python3
"""
LINE API skill — 檢查既有程式碼是否正確、是否照官方做法寫。

不是 linter，也不執行你的程式。它拿資料集當標準答案，逐條比對程式碼裡的
LINE 用法：呼叫的端點存不存在、主機對不對、有沒有用到已停止服務的東西、
webhook 簽章驗得對不對、憑證有沒有寫死、內嵌的訊息 JSON 送得出去嗎。

    python scripts/review.py app.py
    python scripts/review.py ./src --format json
    python scripts/review.py ./src --min-severity error

規則來自資料，不是寫死的清單：
    deprecations.csv  → 12 項已淘汰功能與替代方案
    endpoints.csv     → 121 支合法端點、7 支必須走 api-data.line.me
    message-objects   → 內嵌訊息 JSON 交給 validate.py 逐欄位檢查
所以官方文件變了、資料集重建後，這支工具的判準也跟著更新。
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import _limits  # noqa: E402
import validate as val  # noqa: E402
from core import use_utf8_stdout  # noqa: E402

use_utf8_stdout()

DATA = HERE.parent / "data"

CODE_EXT = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".php",
            ".java", ".kt", ".go", ".rb", ".cs", ".swift", ".html", ".vue"}
SKIP_DIRS = {"node_modules", ".git", "vendor", "dist", "build", "__pycache__",
             ".venv", "venv", ".next", "target",
             # 產生物。coverage 報告會把整份 .ts 內嵌進 .ts.html，
             # 掃到就等於把同一份程式碼審兩次，而且第二次沒有上下文
             "coverage", "htmlcov", ".turbo", ".nuxt", ".output", "out",
             "storybook-static", ".svelte-kit", ".pytest_cache", ".mypy_cache"}

TEST_FILE = re.compile(
    r"(?i)"
    r"(^|[/\\.])(tests?|__tests__|spec|specs|e2e|fixtures?)([/\\.]|$)"  # tests/ __tests__/
    r"|\.(test|spec)\.[a-z]+$"                                          # foo.test.ts
    r"|(^|[/\\])test_[^/\\]*$"                                          # pytest: test_foo.py
    r"|_test\.[a-z]+$")                                                 # Go: foo_test.go


def is_test_file(path: Path) -> bool:
    """測試檔會刻意寫進假憑證與已淘汰的值來斷言行為，判準要放寬。"""
    return bool(TEST_FILE.search(str(path).replace("\\", "/")))


HASH_COMMENT_EXT = {".py", ".rb", ".php", ".sh", ".yml", ".yaml"}


def code_mask(text: str, suffix: str) -> str:
    """把註解換成等長空白，字串內容保留。

    寫得最用心的程式碼最容易被誤判：解釋「為什麼不能拿 JSON.stringify 算簽章」
    的那段 docblock，本身就含有 `JSON.stringify` 與 `x-line-signature`。
    用原文比對等於在罰寫註解的人。長度與換行都保持不變，行號才不會跑掉。

    字串留著 —— 端點、訊息 JSON、寫死的憑證本來就住在字串裡。
    """
    out = list(text)
    n = len(text)
    i = 0
    hash_ok = suffix in HASH_COMMENT_EXT
    html_ok = suffix in (".html", ".vue")

    def blank(start: int, end: int) -> None:
        for j in range(start, min(end, n)):
            if out[j] != "\n":
                out[j] = " "

    while i < n:
        c = text[i]
        # 跳脫序列整組跳過。JS 的 regex literal 結尾長這樣：/^line:\/\//
        # 一個字元一個字元走的話，最後的 \/ 加收尾的 / 會被讀成 `//` 行註解，
        # 從那裡到行尾全部被清掉——包含後面真正該檢查的程式碼
        if c == "\\":
            i += 2
            continue
        # --- 字串：整段跳過，不做任何處理 ---
        if c in "\"'`":
            if suffix == ".py" and text[i:i + 3] in ('"""', "'''"):
                # docstring 當註解看：它多半是散文，而散文最會提到反例
                quote, j = text[i:i + 3], i + 3
                while j < n and text[j:j + 3] != quote:
                    j += 2 if text[j] == "\\" else 1
                blank(i, j + 3)
                i = j + 3
                continue
            quote, j = c, i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == quote:
                    break
                if text[j] == "\n" and quote != "`":
                    break        # 一般字串不跨行，八成是引號沒配對，別吃掉整份檔案
                j += 1
            i = j + 1
            continue
        # --- 註解 ---
        if c == "/" and i + 1 < n:
            if text[i + 1] == "/":
                j = text.find("\n", i)
                j = n if j < 0 else j
                blank(i, j)
                i = j
                continue
            if text[i + 1] == "*":
                j = text.find("*/", i + 2)
                j = n if j < 0 else j + 2
                blank(i, j)
                i = j
                continue
        if hash_ok and c == "#":
            j = text.find("\n", i)
            j = n if j < 0 else j
            blank(i, j)
            i = j
            continue
        if html_ok and text.startswith("<!--", i):
            j = text.find("-->", i)
            j = n if j < 0 else j + 3
            blank(i, j)
            i = j
            continue
        i += 1
    return "".join(out)

SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}

# 這兩條講的是「專案有沒有做這件事」，不是「這一行寫錯了」，所以只報一次
PROJECT_RULES = {"signature-missing", "idempotency"}

# 測試檔本來就會寫進「壞的」值來斷言它們會被擋下來：已淘汰的 scheme、
# 少一個必填欄位的訊息 JSON、假的 channel secret。那不是在用它們。
# 其餘規則照常——測試裡把端點拼錯，那還是拼錯
TEST_EXEMPT_RULES = {"deprecated", "message-json", "hardcoded-secret"}


def rows(name: str) -> list[dict]:
    path = DATA / name
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


# 概念 → 官方值。來源是資料集，這裡不存任何數字——
# 抄一份數字進來就等於多一份會過期的真相
LIMIT_VALUES = _limits.official_values(rows)


class Finding:
    __slots__ = ("severity", "rule", "file", "line", "message", "fix", "doc")

    def __init__(self, severity, rule, file, line, message, fix="", doc=""):
        self.severity, self.rule, self.file, self.line = severity, rule, file, line
        self.message, self.fix, self.doc = message, fix, doc

    def as_dict(self) -> dict:
        return {"severity": self.severity, "rule": self.rule, "file": self.file,
                "line": self.line, "message": self.message,
                "fix": self.fix, "doc": self.doc}


# --------------------------------------------------------------------------
# 規則資料
# --------------------------------------------------------------------------
def normalise_path(path: str) -> str:
    """把各語言的路徑參數寫法統一成 {}，才能跟端點清單比對。"""
    path = re.sub(r"\$\{[^}]*\}", "{}", path)      # JS/TS 樣板字串
    path = re.sub(r"\{[^}]*\}", "{}", path)        # f-string / URI template
    path = re.sub(r"'\s*\+\s*[\w.]+\s*\+\s*'", "{}", path)
    path = re.sub(r'"\s*\+\s*[\w.]+\s*\+\s*"', "{}", path)
    path = re.sub(r"%[sd]", "{}", path)
    return path.rstrip("/") or "/"


def endpoint_index():
    """回傳 (端點樣板清單, 必須走 api-data 的樣板集合)。

    樣板以路徑分段保存，比對時把樣板裡的 {} 當萬用字元。程式碼裡的路徑參數
    可能是 f-string、樣板字串、字串相接，也可能就是一個字面值 ID——
    逐段比對才三種都吃得下。
    """
    templates, data_host = [], set()
    for r in rows("endpoints.csv"):
        norm = normalise_path(r["path"])
        segs = tuple(norm.strip("/").split("/"))
        templates.append(segs)
        if r["host"] == "https://api-data.line.me":
            data_host.add(segs)
    return templates, data_host


def match_endpoint(path: str, templates):
    """把程式碼裡的路徑對到官方端點樣板；對不到回 None。"""
    segs = tuple(path.strip("/").split("/"))
    for tpl in templates:
        if len(tpl) != len(segs):
            continue
        if all(t == "{}" or t == s for t, s in zip(tpl, segs)):
            return tpl
    return None


DEPRECATED_TOKENS = [
    # (在程式碼裡長什麼樣, deprecations.csv 的 item, 等級, 補充說明)
    (r"notify-api\.line\.me", "LINE Notify", "error", ""),
    (r"\bliff\.scanCode\s*\(", "liff.scanCode()", "error", ""),
    (r"\bliff\.getLanguage\s*\(", "liff.getLanguage()", "error", ""),
    # 兩種寫法要分開看待，而且都不能連「叫別人不要用 line://」的訊息一起抓
    # （那種句子後面接的是標點或空白，所以底下兩條都要求後面有東西）。
    #
    # `line://ti/p/...`：真的在指一個網址，明確是在用它
    (r"line://[A-Za-z0-9]", "line:// URL scheme", "error", ""),
    # `/^line:\/\//` 或 `/^(https:|tel:|line:|mailto:)/`：一個「關於 line: 的
    # 樣式」。放進白名單是接受它、放進 if 是擋掉它，兩者長得一模一樣，
    # 正規式分不出來——所以只提醒，不斷定。用 error 講一件分不出對錯的事，
    # 下次真的錯了也沒人看。
    # 前面必須是 ^ ( 或 |，才確定是在比對 scheme：散文裡的「不要用 line://」
    # 前面是空白或標點，而 scheme 白名單一定長在這三個字元後面
    (r"[|^(]line:", "line:// URL scheme", "warning",
     "這是一個比對 line:// 的樣式；請確認是在擋它，而不是把它放進白名單"),
    (r'"type"\s*:\s*"filler"', "Flex filler component", "error", ""),
    (r"'type'\s*:\s*'filler'", "Flex filler component", "error", ""),
    (r"liff/edge/1/sdk\.js", "LIFF v1", "error", ""),
]

SECRET_PATTERNS = [
    (r'["\'][A-Za-z0-9+/]{100,}=*["\']', "看起來像寫死的 channel access token"),
    (r'(?i)channel[_-]?secret\s*[:=]\s*["\'][0-9a-f]{32}["\']', "寫死的 channel secret"),
    # 變數名不一定叫 access_token，常見的就是 TOKEN
    (r'(?i)\b(token|secret|credential)\b\s*[:=]\s*["\'][A-Za-z0-9+/]{40,}=*["\']',
     "寫死的憑證（token / secret）"),
]

MESSAGE_TYPES = ("text", "flex", "template", "image", "video", "audio",
                 "location", "sticker", "imagemap")

HMAC_CALL = (r"(?i)\b(hmac\.new|createHmac|hash_hmac|HmacSHA256"
             r"|Mac\.getInstance|hmac\.New|HMACSHA256)\b")

# 「算了 HMAC」還不等於「在驗簽」——測試檔算 HMAC 是為了產生要送出去的
# 標頭，那裡面根本沒有比對。要看到真的拿它去比，才輪得到比對方式這件事
SIG_COMPARE = (r"(?i)(\b\w*(?:sig|signature|expected|digest)\w*\s*[!=]==?"
               r"|[!=]==?\s*\w*(?:sig|signature|expected|digest)\w*)")

# 收 webhook 的入口：既要有 HTTP handler，也要有 LINE 的事件特徵。
# 只看檔名或「有 webhook 這個字」的話，行銷首頁和清 log 的排程都會被當成接收端。
HTTP_HANDLER = (r"(?i)(@app\.(?:route|post)|app\.post|router\.post|fastify\.post"
                r"|\.post\s*\(|def\s+callback|http\.HandleFunc|@PostMapping"
                r"|func\s+\w*[Ww]ebhook|serve_?http|addEventListener\s*\(\s*['\"]fetch)")
LINE_EVENT = r"(replyToken|webhookEventId|destination)"


def looks_like_receiver(text: str) -> bool:
    return bool(re.search(HTTP_HANDLER, text) and re.search(LINE_EVENT, text))


def project_facts(files: dict) -> dict:
    """整個專案層級的事實。

    驗簽與去重是「專案有沒有做」，不是「這個檔案有沒有做」。分層寫的專案
    會把驗簽放進 signature.ts、去重放進 webhook.ts，逐檔判斷就會對著
    每一個沒寫的檔案各報一次 —— 包含正在做這件事的那一支。
    """
    verifies = dedups = False
    for masked in files.values():
        if re.search(HMAC_CALL, masked) and re.search(r"(?i)x[-_]line[-_]signature", masked):
            verifies = True
        # 官方 SDK 的 middleware 自己驗簽，看不到 createHmac
        if re.search(r"(?i)(line\.middleware|WebhookParser|linebot\.WebhookHandler"
                     r"|SignatureValidator|@line/bot-sdk)", masked):
            verifies = True
        if re.search(r"webhookEventId", masked):
            dedups = True
    return {"verifies": verifies, "dedups": dedups}


# --------------------------------------------------------------------------
def review_text(path: Path, text: str, known, data_host, project=None) -> list[Finding]:
    out: list[Finding] = []
    lines = text.splitlines()          # 顯示用，保留原文
    text = code_mask(text, path.suffix)  # 判斷用，註解已清空且長度不變
    # 單檔模式沒有專案視野，只能拿這一份檔案當全部
    project = project if project is not None else project_facts({str(path): text})
    is_test = is_test_file(path)
    rel = str(path)
    dep_rows = {d["item"]: d for d in rows("deprecations.csv")}

    def add(sev, rule, ln, msg, fix="", doc=""):
        if is_test and rule in TEST_EXEMPT_RULES:
            return
        out.append(Finding(sev, rule, rel, ln, msg, fix, doc))

    # ---- 1. 已停用 / 已淘汰 -------------------------------------------
    for pattern, item, sev, note in DEPRECATED_TOKENS:
        for m in re.finditer(pattern, text):
            ln = text[:m.start()].count("\n") + 1
            info = dep_rows.get(item, {})
            add(sev, "deprecated", ln,
                (f"{note}：{item}" if note else
                 f"用到已{'停止服務' if info.get('status') == 'discontinued' else '淘汰'}的"
                 f" {item}")
                + (f"（{info['effective_date']} 起）" if info.get("effective_date") else ""),
                f"改用 {info.get('replacement')}" if info.get("replacement") else "",
                info.get("doc_url", ""))

    # ---- 2. 端點與主機 -------------------------------------------------
    # `${encodeURIComponent(id)}` 裡有括號，字元集吃不下就會在 `(` 斷掉，
    # 斷出來的殘骸既對不上任何端點（假警報），也讓後面的 /content 消失（真漏報）
    for m in re.finditer(r"""(?P<host>https://api(?:-data)?\.line\.me)?"""
                         r"""(?P<path>/v2/bot/(?:\$\{[^{}]*(?:\([^()]*\))?[^{}]*\}"""
                         r"""|[A-Za-z0-9{}$/._+'"\-])*)""", text):
        raw = m.group("path")
        # 去掉字串結尾殘留的引號
        raw = raw.rstrip("\"'")
        norm = normalise_path(raw)
        ln = text[:m.start()].count("\n") + 1
        host = m.group("host")

        tpl = match_endpoint(norm, known)
        shown = ("/" + "/".join(tpl)) if tpl else norm
        if tpl and tpl in data_host:
            if host == "https://api.line.me":
                add("error", "wrong-host", ln,
                    f"{shown} 是內容類端點，必須用 api-data.line.me",
                    "把主機改成 https://api-data.line.me",
                    "https://developers.line.biz/en/reference/messaging-api/#domain-name")
            elif host is None and "api-data.line.me" not in text:
                # 主機是變數時看不出來；但整個檔案都沒提到 api-data，才值得提醒
                add("info", "wrong-host", ln,
                    f"{shown} 是內容類端點，請確認呼叫時用的是 api-data.line.me",
                    doc="https://developers.line.biz/en/reference/messaging-api/#domain-name")
        # 原本會跳過「最後一段是參數」的路徑，結果連中間段拼錯（profiel）也一起放過
        elif tpl is None and norm.count("/") >= 3:
            add("warning", "unknown-endpoint", ln,
                f"官方端點清單裡沒有 {norm}，可能是路徑拼錯",
                "用 scripts/search.py \"<關鍵字>\" --domain endpoint 查正確路徑")

    # ---- 3. webhook 簽章 -----------------------------------------------
    # PHP 讀標頭時會變成 HTTP_X_LINE_SIGNATURE，用連字號比對會漏掉
    has_sig = re.search(r"(?i)x[-_]line[-_]signature", text)
    computes_hmac = re.search(HMAC_CALL, text)
    if has_sig:
        # 用 parse 過的 JSON 再序列化來算簽章 —— 永遠對不上
        # 序列化必須出現在 hmac 這一次呼叫的「參數裡面」才算數。
        # 只看附近有沒有出現會誤報：正確的程式碼常常在同一個檔案的別處用
        # json.dumps 組 API request body。
        bad_body = None
        for _m in re.finditer(r"(?i)\b(hmac\.new|createHmac|hash_hmac)\b", text):
            depth, end = 0, None
            for i in range(_m.end(), min(len(text), _m.end() + 600)):
                if text[i] == "(":
                    depth += 1
                elif text[i] == ")":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            args = text[_m.end(): end if end else _m.end() + 300]
            if re.search(r"(?i)(json\.dumps|JSON\.stringify|json_encode|toJson)", args):
                bad_body = _m
                break
        if bad_body:
            ln = text[:bad_body.start()].count("\n") + 1
            add("error", "signature-body", ln,
                "簽章似乎是用序列化過的 JSON 算的；必須用原始 request body bytes",
                "Flask: request.get_data()｜Express: express.raw()｜PHP: php://input",
                "https://developers.line.biz/en/docs/messaging-api/verify-webhook-signature/")
        # 只有「真的在算 HMAC」的檔案才談得上比對方式。
        # 原本只要檔案提到 x-line-signature 就報，於是 pino 的遮蔽欄位清單
        # 和把驗簽委派出去的路由檔全中招，真正驗簽的那一支反而沒事。
        if computes_hmac and re.search(SIG_COMPARE, text) and not re.search(
                r"(?i)(compare_digest|timingSafeEqual|hash_equals|MessageDigest\.isEqual)", text):
            ln = text[:computes_hmac.start()].count("\n") + 1
            add("warning", "signature-compare", ln,
                "簽章比對似乎沒有用常數時間比較，容易被時間差攻擊",
                "Python: hmac.compare_digest｜Node: crypto.timingSafeEqual｜PHP: hash_equals",
                "https://developers.line.biz/en/docs/messaging-api/verify-webhook-signature/")
    elif not project.get("verifies") and looks_like_receiver(text):
        add("error", "signature-missing", 1,
            "看起來是 webhook 接收端，但整個專案都沒有驗證 x-line-signature",
            "LINE 不公開來源 IP，簽章是唯一的驗證手段",
            "https://developers.line.biz/en/docs/messaging-api/verify-webhook-signature/")

    # ---- 4. 冪等與先回 200 ---------------------------------------------
    # 去重通常寫在獨立的一支（events 表、Redis），跟收 webhook 的路由不同檔。
    # 逐檔判斷會對著每一個碰到 replyToken 的檔案各喊一次，包含正在做去重的那支。
    if not project.get("dedups") and re.search(r"replyToken", text) \
            and looks_like_receiver(text):
        add("info", "idempotency", 1,
            "整個專案都沒看到用 webhookEventId 去重；LINE 沒收到 200 會重送同一筆事件",
            "把 webhookEventId 寫進 Redis/DB 的 unique index 做冪等",
            "https://developers.line.biz/en/docs/messaging-api/receiving-messages/")

    # ---- 4.5 寫死的限制值與官方對不上 ----------------------------------
    for ln, name, value, candidates in _limits.scan(text, LIMIT_VALUES):
        official = candidates[0][0]
        where = "、".join(f"{src} = {v}" for v, src, _ in candidates)
        doc = candidates[0][2]
        if value > official:
            add("error", "wrong-limit", ln,
                f"{name} = {value}，超過官方的上限（{where}）；"
                f"超過的內容會被 LINE 退件",
                "把常數改成官方值，或在送出前先截斷", doc)
        else:
            # 比官方小不會壞，但多半是抄錯——而且沒有人會發現。
            # MAX_ALT_TEXT 寫成 400（官方 1500）就是這樣：通知列的文字
            # 被砍掉四分之三，測試全綠、LINE 照收、客人也不會抱怨。
            add("warning", "wrong-limit", ln,
                f"{name} = {value}，比官方的上限小（{where}）；"
                f"如果不是刻意保守，等於白白少用了額度",
                "確認是刻意的，否則改成官方值", doc)

    # ---- 5. 憑證寫死 ---------------------------------------------------
    for pattern, label in SECRET_PATTERNS:
        for m in re.finditer(pattern, text):
            ln = text[:m.start()].count("\n") + 1
            snippet = lines[ln - 1] if ln <= len(lines) else ""
            if re.search(r"(?i)(example|dummy|test|xxx|your[_-]?token|<|\.\.\.)", snippet):
                continue
            add("error", "hardcoded-secret", ln, label,
                "改從環境變數讀取，並確認該檔案沒有被 commit")

    # ---- 6. 內嵌的訊息 JSON --------------------------------------------
    for obj, ln in json_literals(text):
        problems, kind = best_interpretation(obj)
        if kind is None:
            continue
        for p in problems:
            add("error" if p.level == "error" else "warning", "message-json", ln,
                f"內嵌的 {kind} {p.path}：{p.message}",
                "送出前先跑 scripts/validate.py", p.doc)

    return out


# 同一個 type 值在不同位置代表不同東西：`type: text` 可能是文字訊息，也可能是
# Flex 的 text 元件；`type: location` 可能是位置訊息，也可能是 quick reply 動作。
# 光看 type 判斷會大量誤報，所以每一種可能的解讀都驗一次，全部都不合法才報。
INTERPRETATIONS = [
    ("Message", "訊息"),
    ("FlexComponent", "Flex 元件"),
    ("FlexContainer", "Flex 容器"),
    ("Action", "action"),
    ("Template", "樣板"),
    ("ImagemapAction", "imagemap action"),
]


def best_interpretation(obj):
    """回傳 (問題清單, 這是什麼)。看得懂但沒問題就回 ([], kind)；完全不認得回 (None 版本)。"""
    if not isinstance(obj, dict) or not isinstance(obj.get("type"), str):
        return [], None
    tag = obj["type"]
    best = None
    for union, label in INTERPRETATIONS:
        if tag not in val.REG.union_types(union):
            continue
        v = val.Validator()
        v.check_typed("$", obj, union)
        if not v.problems:
            return [], None          # 有一種解讀完全乾淨，就不是問題
        errors = [p for p in v.problems if p.level == "error"]
        # 先比 error 數，再比總問題數：屬性拼錯只算 warning，但那正是最該抓的
        rank = (len(errors), len(v.problems))
        if best is None or rank < best[0]:
            best = (rank, v.problems, label)
    return (best[1], best[2]) if best else ([], None)


def json_literals(text: str):
    """抓出程式碼裡可以被 json.loads 解析的物件字面值。

    只處理解析得動的，解析不動就跳過——寧可少報，也不要對著自己誤讀的東西亂建議。
    """
    for m in re.finditer(r'\{\s*["\']type["\']\s*:', text):
        start = m.start()
        depth, end = 0, None
        for i in range(start, min(len(text), start + 20000)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end is None:
            continue
        blob = text[start:end]
        # Python 的 True/False/None 轉成 JSON 的寫法
        blob = re.sub(r"\bTrue\b", "true", blob)
        blob = re.sub(r"\bFalse\b", "false", blob)
        blob = re.sub(r"\bNone\b", "null", blob)
        blob = re.sub(r"'([^'\\]*)'", r'"\1"', blob)
        blob = re.sub(r",\s*([}\]])", r"\1", blob)
        try:
            yield json.loads(blob), text[:start].count("\n") + 1
        except Exception:
            continue


# --------------------------------------------------------------------------
def collect(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    out = []
    for p in sorted(target.rglob("*")):
        if p.is_file() and p.suffix in CODE_EXT and not (SKIP_DIRS & set(p.parts)):
            out.append(p)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="檢查程式碼的 LINE API 用法是否正確")
    ap.add_argument("target", help="要檢查的檔案或目錄")
    ap.add_argument("--format", choices=["text", "json"], default="text")
    ap.add_argument("--min-severity", choices=["error", "warning", "info"],
                    default="info")
    args = ap.parse_args()

    target = Path(args.target)
    if not target.exists():
        raise SystemExit(f"找不到 {target}")

    known, data_host = endpoint_index()
    files = collect(target)

    # 第一趟：讀檔並遮掉註解，順便算出專案層級的事實（有沒有驗簽、有沒有去重）
    sources: dict[Path, str] = {}
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if "line" not in text.lower():
            continue
        sources[path] = text
    project = project_facts({str(p): code_mask(t, p.suffix) for p, t in sources.items()})

    # 第二趟：逐檔套規則
    findings: list[Finding] = []
    for path, text in sources.items():
        findings.extend(review_text(path, text, known, data_host, project))

    # 專案層級的問題只講一次。同一件事在 40 個檔案各喊一遍，等於沒講
    seen_once = set()
    kept = []
    for f in findings:
        if f.rule in PROJECT_RULES:
            if f.rule in seen_once:
                continue
            seen_once.add(f.rule)
        kept.append(f)
    findings = kept

    cap = SEVERITY_ORDER[args.min_severity]
    findings = [f for f in findings if SEVERITY_ORDER[f.severity] <= cap]
    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.file, f.line))

    if args.format == "json":
        print(json.dumps({"files_scanned": len(files),
                          "findings": [f.as_dict() for f in findings]},
                         ensure_ascii=False, indent=2))
    else:
        icon = {"error": "❌", "warning": "⚠️ ", "info": "ℹ️ "}
        print(f"\n掃描 {len(files)} 個檔案")
        print("=" * 92)
        if not findings:
            print("沒有發現問題。")
        for f in findings:
            print(f"\n{icon[f.severity]} [{f.rule}] {f.file}:{f.line}")
            print(f"     {f.message}")
            if f.fix:
                print(f"     建議：{f.fix}")
            if f.doc:
                print(f"     依據：{f.doc}")
        print("\n" + "-" * 92)
        counts = {s: sum(1 for f in findings if f.severity == s)
                  for s in ("error", "warning", "info")}
        print(f"{counts['error']} error, {counts['warning']} warning, {counts['info']} info")

    return 1 if any(f.severity == "error" for f in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
