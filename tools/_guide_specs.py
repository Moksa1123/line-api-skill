"""把指南頁的表格攤成原子事實。

reference 頁的規格寫在 `<!-- parameter -->` 區塊裡，已經有專門的解析器；
docs/ 底下的指南頁不是那樣寫的——它們把規格放在 markdown 表格裡。
於是「服務訊息 detailed 的字數上限是多少」「MINI App 的 icon 要幾 px」
這類問題，資料集裡只有頁面標題，答不出來。

這裡把每一列表格拆成 (項目, 屬性, 值) 三元組：

    | Item     | Recommended | Soft limit | Hard limit |
    | detailed | 10          | 36         | 50         |

    → detailed / Recommended / 10
      detailed / Soft limit   / 36
      detailed / Hard limit   / 50

只取事實性的儲存格：圖片、純連結、過長的散文都丟掉，留下的是數值、
enum、是否支援之類答得出問題的東西，每一筆都帶章節名稱與官方頁連結。
"""
from __future__ import annotations

import re

# 這幾種儲存格不是事實：整格只有圖、只有連結、或空白
IMG_ONLY = re.compile(r"^!\[[^\]]*\]\([^)]*\)$")
LINK_ONLY = re.compile(r"^\[[^\]]*\]\([^)]*\)$")
MAX_CELL = 180          # 超過就是段落說明，不是欄位值


def clean_cell(cell: str) -> str:
    """去掉 markdown 修飾，留下可讀的值。"""
    s = cell.strip()
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)          # 圖片整個拿掉
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)      # 連結留文字
    s = re.sub(r"</?(ul|li|br|/?p)\s*/?>", " ", s)      # 表格裡常見的 HTML
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("`", "").replace("**", "")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def parse_tables(lines: list[str], fenced: list[bool]):
    """回傳 [(起始行, 表頭, [資料列])]。只認有分隔列的標準 markdown 表格。"""
    out = []
    i = 0
    n = len(lines)
    while i < n - 1:
        if fenced[i] or not lines[i].lstrip().startswith("|"):
            i += 1
            continue
        sep = lines[i + 1].strip()
        if not re.fullmatch(r"\|[\s:\-|]+\|", sep):
            i += 1
            continue
        header = [clean_cell(c) for c in lines[i].strip().strip("|").split("|")]
        rows = []
        j = i + 2
        while j < n and lines[j].lstrip().startswith("|") and not fenced[j]:
            rows.append([clean_cell(c) for c in lines[j].strip().strip("|").split("|")])
            j += 1
        if rows:
            out.append((i, header, rows))
        i = j
    return out


# 有些表格是「請求／回應範例的逐行說明」，第一欄放的是那一行的原文：
# 時間戳、HTTP 起始行、原始的 header 值。那是某一次呼叫的實際內容，
# 不是規格——留著只會在查「服務訊息有效期」時把日期排到第一名。
EXAMPLE_ITEM = re.compile(
    r"(?i)^("
    r".*\b(GMT|UTC)\b.*"                                  # Mon, 16 Jul 2021 10:20:10 GMT
    r"|\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}.*"                # ISO 時間戳
    r"|(GET|POST|PUT|DELETE|PATCH|HEAD) /.*"              # HTTP 起始行
    r"|HTTP/\d.*"
    r"|curl\b.*"
    r"|[A-Za-z0-9+/]{40,}={0,2}"                          # 範例裡的 token
    r")$")


def is_fact(value: str) -> bool:
    if not value or len(value) > MAX_CELL:
        return False
    if IMG_ONLY.match(value) or LINK_ONLY.match(value):
        return False
    if value in ("-", "—", "–", "N/A"):
        return False
    return True


def is_spec_item(value: str) -> bool:
    """第一欄要能當「這是在講哪一件事」，範例的原始值不算。"""
    return is_fact(value) and not EXAMPLE_ITEM.match(value)


# 有些關鍵限制根本不在表格裡。服務訊息最重要的兩個數字就寫在句子中間：
# 「A service notification token expires 1 year (31,536,000 seconds) after
#  being issued... up to 5 service messages can be sent」
# 表格萃取看不到這種，可是問「服務訊息有效期多久」的人要的正是它。
# 只收「同時有數字與限制字眼」的句子，並且限制長度——這是在抽事實，
# 不是在轉載頁面。
LIMIT_WORDS = re.compile(
    r"(?i)\b(up to|at most|maximum|max\.|no more than|can't exceed|cannot exceed"
    r"|expires?|valid for|limited to|at least|minimum|per (?:day|month|user|request))\b")
NUMBER = re.compile(r"\d")
SENTENCE = re.compile(r"(?<=[.!?])\s+")
MAX_SENTENCE = 200


def prose_limits(lines: list[str], fenced: list[bool], section_at: list[str]):
    """回傳 [(章節, 句子)]。"""
    out = []
    for i, ln in enumerate(lines):
        s = ln.strip()
        if fenced[i] or not s or s.startswith(("|", "#", ">", "<!--", "-", "*", "```")):
            continue
        for sent in SENTENCE.split(clean_cell(s)):
            sent = sent.strip()
            if not (10 < len(sent) <= MAX_SENTENCE):
                continue
            if NUMBER.search(sent) and LIMIT_WORDS.search(sent):
                out.append((section_at[i] if i < len(section_at) else "", sent))
    return out


def build(docs_dir, head_re, fence_mask, anchor=None) -> list[dict]:
    rows: list[dict] = []
    seen: set[tuple] = set()
    for path in sorted(docs_dir.rglob("*.md")):
        rel = path.relative_to(docs_dir).as_posix()[:-3]
        product = rel.split("/")[0]
        lines = path.read_text(encoding="utf-8").splitlines()
        fenced = fence_mask(lines)

        # 每一行落在哪個章節底下，之後用來組錨點
        section_at: list[str] = []
        cur = ""
        title = ""
        for i, ln in enumerate(lines):
            if not fenced[i]:
                m = head_re.match(ln)
                if m:
                    level, name = len(m.group(1)), m.group(2).strip()
                    name = re.sub(r"^\[(.*?)\]\(#.*\)$", r"\1", name).strip()
                    if level == 1 and not title:
                        title = name
                    elif level >= 2:
                        cur = name
            section_at.append(cur)

        # 不加錨點。實測這些指南頁裡真正被連到的 686 個錨點，只有 125 個
        # 等於標題的 slug——「Maximum number of characters for each element」
        # 的真實錨點是 #maximum-number-of-characters，猜出來的 slug 會多一截。
        # 猜錯的錨點會把人送到頁面上錯的位置，而且看起來很權威；
        # section 欄位本來就寫著該看哪一節，連到頁面就夠了。
        url = f"https://developers.line.biz/en/docs/{rel}/"
        for start, header, table in parse_tables(lines, fenced):
            section = section_at[start] if start < len(section_at) else ""
            if len(header) < 2:
                continue
            for r in table:
                if not r or not is_spec_item(r[0]):
                    continue
                item = r[0]
                for col, cell in zip(header[1:], r[1:]):
                    if not is_fact(cell) or not col:
                        continue
                    key = (rel, section, item, col, cell)
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append({
                        "product": product,
                        "page": rel,
                        "page_title": title or rel.rsplit("/", 1)[-1].replace("-", " "),
                        "section": section,
                        "item": item,
                        "attribute": col,
                        "value": cell,
                        "doc_url": url,
                    })

        for section, sent in prose_limits(lines, fenced, section_at):
            key = (rel, section, sent, "limit", "")
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "product": product,
                "page": rel,
                "page_title": title or rel.rsplit("/", 1)[-1].replace("-", " "),
                "section": section,
                "item": section or (title or rel),
                "attribute": "限制（寫在內文）",
                "value": sent,
                "doc_url": url,
            })
    return rows
