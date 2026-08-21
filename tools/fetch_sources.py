#!/usr/bin/env python3
"""
fetch_sources.py — download every authoritative LINE Platform source into
.docs-cache/ (git-ignored). Run this before tools/build_dataset.py.

What it fetches
---------------
1. https://developers.line.biz/llms.txt        -> the official page index
2. <page>/index.html.md for every page in it   -> official docs, already Markdown
3. pages with no .md variant                   -> HTML converted to Markdown
4. https://github.com/line/line-openapi        -> OpenAPI specs (field-exact)

Nothing here is committed: .docs-cache/ is listed in .gitignore. The skill
ships the derived line-api/data/*.csv and line-api/references/*.md instead.
"""
from __future__ import annotations

import queue
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CACHE = REPO / ".docs-cache"
RAW = CACHE / "raw"
BASE = "https://developers.line.biz"
UA = {"User-Agent": "Mozilla/5.0 (+line-api-skill docs archiver)"}
WORKERS = 8

LINK_RE = re.compile(r"https://developers\.line\.biz/en/(?:docs|reference)/[A-Za-z0-9\-_/\.]*")

# Pages that exist only as HTML (no index.html.md). Kept explicit so a future
# LINE change that adds .md for them is a no-op rather than a duplicate.
HTML_ONLY = [
    "en/docs/messaging-api/emoji-list",
    "en/docs/messaging-api/sticker-list",
    "en/docs/messaging-api",
    "en/docs/line-login",
    "en/docs/line-mini-app",
    "en/docs/partner-docs",
    "en/docs/liff",
    "en/docs/basics",
    "en/docs/line-developers-console",
    "en/docs/downloads",
    "en/docs/line-social-plugins/install-guide/using-line-share-buttons",
    "en/docs/line-social-plugins/install-guide/using-like-buttons",
    "en/docs/line-social-plugins/install-guide/using-add-friend-buttons",
]


# --------------------------------------------------------------------------
def fetch(url: str, tries: int = 3) -> str | None:
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                return None
            time.sleep(1.5 * (i + 1))
        except Exception:
            time.sleep(1.5 * (i + 1))
    return None


def norm(url: str) -> str:
    url = url.split("#")[0].split("?")[0]
    if url.endswith(".md"):
        return url
    if not url.endswith("/"):
        url += "/"
    return url + "index.html.md"


def path_for(url: str) -> Path:
    rel = url[len(BASE) + 1:]
    rel = rel[: -len("index.html.md")].rstrip("/")
    return RAW / (rel + ".md")


# --------------------------------------------------------------------------
# HTML -> Markdown (only for the handful of pages with no .md variant)
# --------------------------------------------------------------------------
class MDConv(HTMLParser):
    SKIP = {"script", "style", "svg", "button", "nav"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip_depth = 0
        self.list_stack: list[str] = []
        self.in_pre = 0
        self.row: list[str] = []
        self.cell: list[str] = []
        self.in_cell = 0
        self.rows: list[list[str]] = []
        self.href = ""
        self.link_text: list[str] = []
        self.in_link = 0

    def w(self, s: str) -> None:
        if self.in_link:
            self.link_text.append(s)
        elif self.in_cell:
            self.cell.append(s)
        else:
            self.out.append(s)

    def nl(self, n: int = 1) -> None:
        if self.in_cell or self.in_link:
            return
        self.out.append("\n" * n)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self.SKIP:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.nl(2)
            self.w("#" * int(tag[1]) + " ")
        elif tag == "p":
            self.nl(2)
        elif tag == "br":
            self.w("  \n")
        elif tag == "hr":
            self.nl(2)
            self.w("---")
            self.nl(2)
        elif tag in ("strong", "b"):
            self.w("**")
        elif tag in ("em", "i"):
            self.w("*")
        elif tag == "code" and not self.in_pre:
            self.w("`")
        elif tag == "pre":
            self.in_pre += 1
            self.nl(2)
            self.w("```\n")
        elif tag == "a":
            self.in_link = 1
            self.link_text = []
            self.href = a.get("href") or ""
        elif tag == "img":
            src = a.get("src") or ""
            if src.startswith("/"):
                src = BASE + src
            self.w("![" + (a.get("alt") or "") + "](" + src + ")")
        elif tag in ("ul", "ol"):
            self.list_stack.append(tag)
            self.nl(1)
        elif tag == "li":
            self.nl(1)
            depth = max(0, len(self.list_stack) - 1)
            marker = "- " if (self.list_stack or ["ul"])[-1] == "ul" else "1. "
            self.w("  " * depth + marker)
        elif tag == "table":
            self.rows = []
        elif tag == "tr":
            self.row = []
        elif tag in ("td", "th"):
            self.in_cell = 1
            self.cell = []

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth:
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6", "p"):
            self.nl(2)
        elif tag in ("strong", "b"):
            self.w("**")
        elif tag in ("em", "i"):
            self.w("*")
        elif tag == "code" and not self.in_pre:
            self.w("`")
        elif tag == "pre":
            self.w("\n```")
            self.in_pre = max(0, self.in_pre - 1)
            self.nl(2)
        elif tag == "a":
            self.in_link = 0
            txt = "".join(self.link_text).strip()
            href = self.href
            if href.startswith("/"):
                href = BASE + href
            if txt:
                self.w("[" + txt + "](" + href + ")" if href else txt)
        elif tag in ("ul", "ol"):
            if self.list_stack:
                self.list_stack.pop()
            self.nl(1)
        elif tag in ("td", "th"):
            self.in_cell = 0
            self.row.append(" ".join("".join(self.cell).split()).replace("|", "\\|"))
        elif tag == "tr":
            if self.row:
                self.rows.append(self.row)
            self.row = []
        elif tag == "table":
            if self.rows:
                width = max(len(r) for r in self.rows)
                self.nl(2)
                head = self.rows[0] + [""] * (width - len(self.rows[0]))
                self.out.append("| " + " | ".join(head) + " |\n")
                self.out.append("| " + " | ".join(["---"] * width) + " |\n")
                for r in self.rows[1:]:
                    r = r + [""] * (width - len(r))
                    self.out.append("| " + " | ".join(r) + " |\n")
                self.nl(2)
            self.rows = []

    def handle_data(self, d):
        if self.skip_depth:
            return
        if self.in_pre:
            self.w(d)
            return
        if not d.strip():
            if self.out and not self.out[-1].endswith((" ", "\n")):
                self.w(" ")
            return
        self.w(re.sub(r"\s+", " ", d))

    def result(self) -> str:
        s = "".join(self.out)
        s = re.sub(r"[ \t]+\n", "\n", s)
        s = re.sub(r"\n{3,}", "\n\n", s)
        return s.strip() + "\n"


def extract_main(html: str) -> str | None:
    m = re.search(r'<main class="markdown-content">', html)
    if not m:
        return None
    i, depth, end = m.end(), 1, len(html)
    for mm in re.finditer(r"</?main\b", html[i:]):
        if mm.group().startswith("</"):
            depth -= 1
            if depth == 0:
                end = i + mm.start()
                break
        else:
            depth += 1
    return html[i:end]


# --------------------------------------------------------------------------
def crawl_markdown(seeds: list[str]) -> tuple[int, int]:
    lock = threading.Lock()
    seen: set[str] = set()
    q: queue.Queue[str] = queue.Queue()
    saved: list[str] = []
    failed: list[str] = []

    for s in seeds:
        n = norm(s)
        if n not in seen:
            seen.add(n)
            q.put(n)

    def worker():
        while True:
            try:
                url = q.get(timeout=5)
            except queue.Empty:
                return
            try:
                body = fetch(url)
                if body is None or body.lstrip().startswith("<!DOCTYPE"):
                    with lock:
                        failed.append(url)
                    continue
                p = path_for(url)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(body, encoding="utf-8")
                with lock:
                    saved.append(url)
                for link in LINK_RE.findall(body):
                    n = norm(link)
                    if not n.startswith(BASE + "/en/"):
                        continue
                    with lock:
                        if n in seen:
                            continue
                        seen.add(n)
                    q.put(n)
            finally:
                q.task_done()

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(WORKERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return len(saved), len(failed)


def crawl_html(paths: list[str]) -> int:
    ok = 0
    for rel in paths:
        html = fetch(BASE + "/" + rel + "/")
        if not html:
            print("  ! no html:", rel)
            continue
        inner = extract_main(html)
        if not inner:
            print("  ! no main:", rel)
            continue
        conv = MDConv()
        conv.feed(inner)
        out = RAW / (rel + ".md")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(conv.result(), encoding="utf-8")
        ok += 1
    return ok


def clone_openapi() -> None:
    dest = CACHE / "line-openapi"
    if dest.exists():
        print("  refreshing line-openapi ...")
        subprocess.run(["git", "-C", str(dest), "pull", "--quiet"], check=False)
        return
    print("  cloning line/line-openapi ...")
    subprocess.run(
        ["git", "clone", "--depth", "1", "--quiet",
         "https://github.com/line/line-openapi.git", str(dest)],
        check=True,
    )


def main() -> int:
    CACHE.mkdir(parents=True, exist_ok=True)
    print("1/3  llms.txt page index")
    llms = fetch(BASE + "/llms.txt")
    if not llms:
        sys.exit("could not fetch https://developers.line.biz/llms.txt")
    (CACHE / "llms.txt").write_text(llms, encoding="utf-8")
    seeds = sorted(set(re.findall(r"\((https://developers\.line\.biz/[^)]+\.md)\)", llms)))
    print(f"     {len(seeds)} seed pages")

    print("2/3  crawling Markdown docs")
    ok, bad = crawl_markdown(seeds)
    print(f"     saved {ok}, no-markdown {bad}")
    extra = crawl_html(HTML_ONLY)
    print(f"     converted {extra} HTML-only pages")

    print("3/3  OpenAPI specs")
    clone_openapi()

    total = len(list(RAW.rglob("*.md")))
    print(f"\nDone. {total} pages in {RAW}")
    print("Next: python tools/build_dataset.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
