"""規範與檢查清單。

送審規範、開發規範、效能規範、站內購買規範——這些頁面的內容不是
「某個欄位的值是多少」，而是「你必須做到什麼」，寫成一條一條的項目符號。
表格萃取看不到，內文限制那條規則也抓不到（多數句子裡沒有數字）。

可是「送審前要檢查什麼」「哪些做法會被退件」正是做 MINI App 最常問的，
而且答錯的代價是整個審核被退。

只收規範類的頁面——用路徑與標題判斷，不是寫死清單，這樣官方新增
規範頁時會自動跟上。
"""
from __future__ import annotations

import re

# 規範類頁面的特徵。用 in 比對路徑與標題，新增頁面會自動被收進來
RULE_PAGE = re.compile(
    r"(?i)(guideline|regulation|specification|submission|submit|policy"
    r"|checklist|review|requirement)")

BULLET = re.compile(r"^\s{0,3}[-*]\s+(.+)$")
MAX_RULE = 300
MIN_RULE = 20


def clean(text: str) -> str:
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"<br\s*/?>", " ", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("`", "").replace("**", "")
    return re.sub(r"\s+", " ", s).strip()


def build(docs_dir, head_re, fence_mask) -> list[dict]:
    rows: list[dict] = []
    seen: set[tuple] = set()
    for path in sorted(docs_dir.rglob("*.md")):
        rel = path.relative_to(docs_dir).as_posix()[:-3]
        lines = path.read_text(encoding="utf-8").splitlines()
        fenced = fence_mask(lines)

        title = ""
        for i, ln in enumerate(lines):
            if fenced[i]:
                continue
            m = head_re.match(ln)
            if m and len(m.group(1)) == 1:
                title = m.group(2).strip()
                break

        if not (RULE_PAGE.search(rel) or RULE_PAGE.search(title)):
            continue

        product = rel.split("/")[0]
        url = f"https://developers.line.biz/en/docs/{rel}/"
        section = ""
        for i, ln in enumerate(lines):
            if fenced[i]:
                continue
            m = head_re.match(ln)
            if m:
                if len(m.group(1)) >= 2:
                    section = re.sub(r"^\[(.*?)\]\(#.*\)$", r"\1",
                                     m.group(2).strip()).strip()
                continue
            b = BULLET.match(ln)
            if not b:
                continue
            rule = clean(b.group(1))
            if not (MIN_RULE <= len(rule) <= MAX_RULE):
                continue
            key = (rel, rule)
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "product": product,
                "page": rel,
                "page_title": title or rel.rsplit("/", 1)[-1].replace("-", " "),
                "section": section,
                "rule": rule,
                "doc_url": url,
            })
    return rows
