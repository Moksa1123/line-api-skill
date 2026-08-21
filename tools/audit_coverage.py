#!/usr/bin/env python3
"""
audit_coverage.py — 逐條比對「官方文件寫了什麼」與「資料集收了什麼」。

不是抽查，是把 parameters.csv（1400+ 個官方參數區塊）與各 schema CSV
交叉核對，把每一種缺口列出來：

  A. 有 schema 但沒有對到文件標題（SCHEMA_HEADINGS 漏掉）
  B. 文件有這個欄位，schema CSV 沒有這一列
  C. 文件寫了上限 / enum / 預設值，但 schema CSV 是空的
  D. schema CSV 有這個欄位，但文件查無（多半是 spec-only，僅提示）
  E. 文件寫了 rate limit 卻沒抓到（E' 是官方本來就沒公開，不算缺）
  F/G. LIFF、webhook 的細節覆蓋率

用法：
    python tools/audit_coverage.py            # 摘要
    python tools/audit_coverage.py --detail   # 列出每一筆
    python tools/audit_coverage.py --strict   # 有 A/B/C 級缺口就 exit 1
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "line-api" / "data"

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def load(name: str) -> list[dict]:
    path = DATA / name
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def schema_headings() -> dict:
    """從 build_dataset.py 讀 SCHEMA_HEADINGS，避免兩邊各寫一份。"""
    spec = importlib.util.spec_from_file_location("bd", REPO / "tools" / "build_dataset.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.SCHEMA_HEADINGS, getattr(mod, "SCHEMA_PREFIXES", {})


SCHEMA_FILES = [
    ("message-objects.csv", ("message", "template", "imagemap-action", "message-part")),
    ("flex-components.csv", ("flex-component", "flex-container", "flex-background", "flex-style")),
    ("actions.csv", ("action",)),
    ("richmenu.csv", ("richmenu",)),
]


def rate_limit_gaps(endpoints: list[dict]) -> tuple[list[dict], list[dict]]:
    """把缺 rate_limit 的端點分成兩類。

    回傳 (文件有寫但我們漏抓, 官方本來就沒寫)。只有前者才是缺口——
    後者是忠實反映官方文件（例如 OAuth 端點 LINE 就沒有公開速率上限）。
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("bd", REPO / "tools" / "build_dataset.py")
    bd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bd)

    ref = REPO / ".docs-cache" / "raw" / "en" / "reference" / "messaging-api.md"
    if not ref.exists():
        return [], [r for r in endpoints
                    if not r.get("rate_limit") and r.get("api") == "messaging-api"]

    lines = ref.read_text(encoding="utf-8").splitlines()
    fenced = bd.fence_mask(lines)
    heads = [(i, l.strip("# ").strip(), len(l) - len(l.lstrip("#")))
             for i, l in enumerate(lines) if not fenced[i] and l.startswith("#")]

    missed, absent = [], []
    for e in endpoints:
        if e.get("rate_limit") or e.get("api") != "messaging-api":
            continue
        start = next((i for i, t, lv in heads if t == e["title"] and lv == 3), None)
        if start is None:
            absent.append(e)
            continue
        end = next((i for i, t, lv in heads if i > start and lv <= 3), len(lines))
        documented = any(t.lower().startswith("rate limit")
                         for i, t, lv in heads if start < i < end)
        (missed if documented else absent).append(e)
    return missed, absent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--detail", action="store_true")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    headings, prefixes = schema_headings()
    params = load("parameters.csv")

    # 文件端：以 (h3, h4, h5) 為 key
    doc_by_path: dict[tuple, dict[str, dict]] = defaultdict(dict)
    for r in params:
        key = (r.get("endpoint", ""), r.get("block", ""), r.get("subblock", ""))
        doc_by_path[key][r.get("parameter", "")] = r

    # schema 端
    schema_rows: dict[str, list[dict]] = defaultdict(list)
    for fname, groups in SCHEMA_FILES:
        for r in load(fname):
            if r.get("group") in groups:
                schema_rows[r["schema"]].append(r)

    unmapped, missing_prop, missing_detail, doc_only, spec_only = [], [], [], [], []
    elsewhere = []

    # 有些文件章節同時描述兩個 schema（例如 "Objects for the block style" 底下
    # 既有 FlexBubbleStyles 也有 FlexBlockStyle）。一個欄位只要被同章節的任一
    # schema 收了就不算缺，否則會互相誤報。
    all_properties = {r["property"] for rows in schema_rows.values() for r in rows}
    claimed_by_path: dict[tuple, set[str]] = defaultdict(set)
    for schema, rows in schema_rows.items():
        path = headings.get(schema)
        if path:
            claimed_by_path[tuple(path)].update(r["property"] for r in rows)

    for schema, rows in sorted(schema_rows.items()):
        path = headings.get(schema)
        if not path:
            unmapped.append((schema, len(rows)))
            continue
        prefix = prefixes.get(schema, "")
        raw_props = doc_by_path.get(tuple(path), {})
        # 以前綴記錄的欄位（baseSize.width）還原成 schema 上的名稱（width）
        doc_props = {}
        for name, row in raw_props.items():
            if prefix and name.startswith(prefix):
                doc_props[name[len(prefix):]] = row
            elif not prefix:
                doc_props[name] = row
        if not doc_props:
            unmapped.append((schema, len(rows)))
            continue

        have = claimed_by_path[tuple(path)]
        for prop, doc in doc_props.items():
            # 巢狀寫法（size.width、areas[].bounds）在 schema 端是獨立物件，跳過
            if "." in prop or "[" in prop:
                continue
            if prop in have:
                continue
            # 文件常把「父物件的欄位」寫在子章節裡（quickReply 寫在 Quick reply
            # 章節、items 寫在 items object 章節）。這種欄位在資料集裡是掛在
            # 父 schema 上的，不算缺，另外歸類。
            if prop in all_properties:
                elsewhere.append((schema, prop))
            else:
                doc_only.append((schema, prop, doc.get("value_type", "")))

        for r in rows:
            doc = doc_props.get(r["property"])
            if doc is None:
                spec_only.append((schema, r["property"]))
                continue
            gaps = []
            raw = (doc.get("max") or "").split()
            vtype = r.get("value_type", "")
            wants_max = raw and raw[0].isdigit() and (
                vtype == "string" or vtype.startswith("array<"))
            if wants_max and not r.get("max_length"):
                gaps.append(f"max={raw[0]}")
            if doc.get("enum_doc") and not r.get("enum"):
                gaps.append(f"enum={doc['enum_doc']}")
            if doc.get("default") and not r.get("default"):
                gaps.append(f"default={doc['default']}")
            if gaps:
                missing_detail.append((schema, r["property"], ", ".join(gaps)))

    # E. 端點 rate limit：分辨「文件有寫但我們漏抓」與「文件本來就沒寫」
    endpoints = load("endpoints.csv")
    missed_rate, no_rate_in_docs = rate_limit_gaps(endpoints)

    # F. webhook / liff 細節
    webhook = load("webhook-events.csv")
    liff = load("liff-api.csv")
    liff_no_syntax = [r for r in liff if r.get("kind") == "method" and not r.get("syntax")]

    def section(title, items, render, level):
        print(f"\n{level} {title}：{len(items)} 筆")
        if items and args.detail:
            for it in items:
                print("     " + render(it))
        elif items:
            for it in items[:5]:
                print("     " + render(it))
            if len(items) > 5:
                print(f"     … 另有 {len(items) - 5} 筆（加 --detail 看全部）")

    print("=" * 90)
    print("LINE API skill — 官方文件覆蓋率稽核")
    print("=" * 90)
    print(f"文件參數區塊 {len(params)} 個｜schema {len(schema_rows)} 個｜"
          f"端點 {len(endpoints)} 個")

    section("A. schema 沒有對到文件標題（永遠拿不到文件細節）",
            unmapped, lambda x: f"{x[0]}（{x[1]} 個欄位）", "[A]")
    section("B. 文件有這個欄位，資料集缺這一列",
            doc_only, lambda x: f"{x[0]}.{x[1]}  ({x[2]})", "[B]")
    section("B'. 文件寫在這一節，但欄位其實掛在父物件上（不算缺）",
            elsewhere, lambda x: f"{x[0]} 章節的 {x[1]}", "[B']")
    section("C. 文件寫了細節但資料集是空的",
            missing_detail, lambda x: f"{x[0]}.{x[1]}  缺 {x[2]}", "[C]")
    section("D. 資料集有、文件查無（多半是 spec-only，僅供參考）",
            spec_only, lambda x: f"{x[0]}.{x[1]}", "[D]")
    section("E. 文件寫了 rate limit 但資料集沒抓到（真缺口）",
            missed_rate, lambda x: f"{x['method']} {x['path']}  ({x['title']})", "[E]")
    section("E'. 官方文件本身就沒公開 rate limit（忠實反映，非缺口）",
            no_rate_in_docs, lambda x: f"{x['method']} {x['path']}", "[E']")
    section("F. LIFF method 缺 syntax",
            liff_no_syntax, lambda x: x["name"], "[F]")

    wprops = load("webhook-properties.csv")
    described = sum(1 for r in wprops if r.get("description"))
    print(f"\n[G] webhook：{len(webhook)} 種事件、{len(wprops)} 個欄位"
          f"（{described} 個有官方說明）")

    blocking = len(unmapped) + len(doc_only) + len(missing_detail) + len(missed_rate)
    print("\n" + "-" * 90)
    print(f"A+B+C+E 共 {blocking} 個需要處理的缺口"
          f"｜B' {len(elsewhere)}｜D {len(spec_only)}"
          f"｜E' {len(no_rate_in_docs)}（官方未公開）｜F {len(liff_no_syntax)}")
    return 1 if (args.strict and blocking) else 0


if __name__ == "__main__":
    raise SystemExit(main())
