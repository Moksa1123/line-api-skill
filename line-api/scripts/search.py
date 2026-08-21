#!/usr/bin/env python3
"""
LINE API skill — search CLI.

    python scripts/search.py "push message"
    python scripts/search.py "429" --domain error
    python scripts/search.py "flex bubble" --domain flex --max 10
    python scripts/search.py "rich menu" --domain all
    python scripts/search.py "webhook signature" --format json
    python scripts/search.py --stats
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import CSV_CONFIG, dataset_stats, search, search_all, use_utf8_stdout  # noqa: E402

use_utf8_stdout()

WIDTH = 100


def _wrap(text: str, width: int) -> list[str]:
    out, line = [], ""
    for word in str(text).split():
        if len(line) + len(word) + 1 > width:
            out.append(line)
            line = word
        else:
            line = (line + " " + word).strip()
    if line:
        out.append(line)
    return out or [""]


def fmt_results(results: list[dict], domain: str) -> str:
    if not results:
        return f"查無結果（域：{domain}）\n提示：用 --domain all 做全域搜尋，或換個關鍵字。"
    label = CSV_CONFIG.get(domain, {}).get("label", domain)
    out = ["", f"搜尋域：{domain}（{label}）  結果 {len(results)} 筆", "=" * WIDTH]
    for i, item in enumerate(results, 1):
        item = dict(item)
        score = item.pop("_score", 0)
        item.pop("_domain", None)
        out.append(f"\n[#{i}]  score {score}")
        out.append("-" * WIDTH)
        for key, value in item.items():
            if not value:
                continue
            key_label = key.replace("_", " ")
            lines = _wrap(value, WIDTH - 24)
            out.append(f"  {key_label:<20}: {lines[0]}")
            for extra in lines[1:]:
                out.append(f"  {'':<20}  {extra}")
    return "\n".join(out)


def fmt_all(all_results: dict[str, list[dict]]) -> str:
    if not all_results:
        return "查無結果"
    out = ["", f"全域搜尋 — {len(all_results)} 個域有命中", "=" * WIDTH]
    for domain, results in all_results.items():
        label = CSV_CONFIG[domain]["label"]
        out.append(f"\n【{domain}】{label}  ({len(results)} 筆)")
        out.append("-" * WIDTH)
        for i, item in enumerate(results, 1):
            item = dict(item)
            score = item.pop("_score", 0)
            item.pop("_domain", None)
            head = [f"{k}={v}" for k, v in list(item.items())[:3] if v]
            out.append(f"  [{i}] score {score}  " + "  ".join(head)[: WIDTH - 20])
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="LINE Platform 開發資料庫搜尋",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="可用域：" + ", ".join(list(CSV_CONFIG) + ["all"]),
    )
    ap.add_argument("query", nargs="?", help="搜尋關鍵字")
    ap.add_argument("--domain", "-d", choices=list(CSV_CONFIG) + ["all"], help="搜尋域（不指定則自動偵測）")
    ap.add_argument("--format", "-f", choices=["text", "json"], default="text")
    ap.add_argument("--max", "-m", type=int, default=5, help="每個域最多幾筆")
    ap.add_argument("--stats", action="store_true", help="顯示資料集統計")
    args = ap.parse_args()

    if args.stats:
        stats = dataset_stats()
        total = sum(v for v in stats.values() if v > 0)
        print(f"\nLINE API skill 資料集（共 {total} 筆）")
        print("=" * 46)
        for domain, count in stats.items():
            label = CSV_CONFIG[domain]["label"]
            shown = count if count >= 0 else "缺檔案"
            print(f"  {domain:<14}{label:<16}{shown:>8}")
        return 0

    if not args.query:
        ap.print_help()
        return 1

    if args.domain == "all":
        results = search_all(args.query, max_per_domain=args.max)
        print(json.dumps(results, ensure_ascii=False, indent=2) if args.format == "json"
              else fmt_all(results))
        return 0 if results else 2

    results = search(args.query, domain=args.domain, max_results=args.max)
    if args.format == "json":
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        domain = results[0]["_domain"] if results else (args.domain or "endpoint")
        print(fmt_results(results, domain))
    return 0 if results else 2


if __name__ == "__main__":
    raise SystemExit(main())
