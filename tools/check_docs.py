#!/usr/bin/env python3
"""
check_docs.py — 確認文件寫的數字與實際資料一致。

資料集這半年會一直長，SKILL.md 與 README 裡的「3675 筆」「25 個搜尋域」
「43 項測試」很容易默默過期。這支工具把文件宣稱的數字跟實際算出來的比對，
對不上就 exit 1，讓它跟測試一樣是硬性把關而不是靠記得。

用法：
    python tools/check_docs.py
    python tools/check_docs.py --fix    # 直接把數字改成正確值
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "line-api"
sys.path.insert(0, str(SKILL / "scripts"))

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

import core  # noqa: E402


def facts() -> dict:
    stats = core.dataset_stats()
    tests = (SKILL / "scripts" / "test_line.py").read_text(encoding="utf-8")
    checks = re.findall(r'@check\("([^"]+)"', tests)
    return {
        "rows": sum(v for v in stats.values() if v > 0),
        "csvs": len(list((SKILL / "data").glob("*.csv"))),
        "domains": len(core.CSV_CONFIG),
        "offline_tests": sum(1 for c in checks if not c.startswith("live:")),
        "live_tests": sum(1 for c in checks if c.startswith("live:")),
        "references": len(list((SKILL / "references").glob("*.md"))),
        "platforms": len(list((REPO / "assets" / "templates" / "platforms").glob("*.json"))),
        "endpoints": stats.get("endpoint", 0),
        "parameters": stats.get("parameter", 0),
    }


READMES = ("README.md", "README.zh-TW.md", "README.ja.md", "README.ko.md")


def rules(f: dict) -> list[tuple[Path, str, str, str]]:
    """(檔案, 說明, 正規式, 應有的值)。正規式第 1 組是要比對的數字。"""
    skill, claude = (SKILL / "SKILL.md"), (REPO / "CLAUDE.md")
    out = [
        (skill, "資料集總筆數", r"共 \*\*(\d+) 筆\*\*", str(f["rows"])),
        (skill, "搜尋域數量", r"## (\d+) 個搜尋域", str(f["domains"])),
        (claude, "離線測試數", r"test_line\.py +# 離線 (\d+) 項", str(f["offline_tests"])),
    ]
    # 四份 README 的 badge 與統計數字必須一致——翻譯版最容易被漏掉
    for name in READMES:
        path = REPO / name
        out += [
            (path, "badge 端點數", r"endpoints-(\d+)-success", str(f["endpoints"])),
            (path, "badge 欄位數", r"fields-(\d+)-blue", str(f["parameters"])),
            (path, "badge 筆數", r"dataset-(\d+)%20rows", str(f["rows"])),
            (path, "badge alt", r'alt="(\d+) rows"', str(f["rows"])),
            (path, "badge 平台數", r"platforms-(\d+)-9cf", str(f["platforms"])),
            # 各語言的量詞寫法不同，韓文的「121개」中間沒有空格
            (path, "統計區端點數",
             r"^(\d+) ?(?:endpoints|個端點|エンドポイント|개 엔드포인트)",
             str(f["endpoints"])),
            (path, "離線測試數", r"`test_line\.py` \|[^|]*?(\d+)", str(f["offline_tests"])),
        ]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true", help="直接把文件裡的數字改成正確值")
    args = ap.parse_args()

    f = facts()
    print("實際數據：")
    for k, v in f.items():
        print(f"   {k:16} {v}")
    print()

    problems, fixed = [], 0
    edits: dict[Path, str] = {}
    for path, label, pattern, want in rules(f):
        text = edits.get(path) or path.read_text(encoding="utf-8")
        m = re.search(pattern, text, re.M)
        if not m:
            problems.append(f"{path.name}｜{label}：找不到對應寫法（{pattern}）")
            continue
        if m.group(1) == want:
            continue
        problems.append(f"{path.name}｜{label}：文件寫 {m.group(1)}，實際 {want}")
        if args.fix:
            start, end = m.span(1)
            edits[path] = text[:start] + want + text[end:]
            fixed += 1

    for path, text in edits.items():
        path.write_text(text, encoding="utf-8")

    # 搜尋域是否都在 SKILL.md 的表格裡（emoji / sticker 允許合併成一列）
    skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    listed = set(re.findall(r"`([a-z_]+)`", skill_text))
    missing_domains = sorted(d for d in core.CSV_CONFIG if d not in listed)
    if missing_domains:
        problems.append(f"SKILL.md｜搜尋域表格沒提到：{missing_domains}")

    # 每個資料檔都該在 CLAUDE.md 的來源表裡有一行
    claude_text = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    undocumented = sorted(p.name for p in (SKILL / "data").glob("*.csv")
                          if p.name not in claude_text)
    if undocumented:
        problems.append(f"CLAUDE.md｜資料來源表沒列到：{undocumented}")

    if problems:
        print("需要修正：")
        for p in problems:
            print("   ✗", p)
        if args.fix and fixed:
            print(f"\n已自動修正 {fixed} 處數字（其餘需人工處理）")
    else:
        print("文件與實際資料一致。")
    remaining = [p for p in problems if not args.fix or "文件寫" not in p]
    return 1 if remaining else 0


if __name__ == "__main__":
    raise SystemExit(main())
