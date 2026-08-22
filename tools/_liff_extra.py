"""LIFF 功能的版本相容性。

## 為什麼要獨立一份

liff-api.csv 的 introduced_in 是「這個 API 從哪一版 **LIFF SDK** 開始有」。
但線上最常見的 LIFF 問題不是那個——是「我用了最新的 SDK，為什麼使用者
按了沒反應」。答案往往是使用者的 **LINE App** 版本太舊：
shareTargetPicker 要 LINE 10.3.0、scanCodeV2 要 11.7.0 而且 iOS 14.3。

這兩個版本是不同的東西，混在同一欄會害人。所以另開一份表，欄位直接
寫明是 LINE App 版本。

資料來源是 liff.getContext() 回應範例裡的 availability 物件——官方沒有
把它整理成表格，但那份 JSON 就是完整清單，而且 liff.isApiAvailable()
查的就是它。
"""
from __future__ import annotations

import json
import re

AVAIL_DOC = "https://developers.line.biz/en/reference/liff/#is-api-available"
CONTEXT_DOC = "https://developers.line.biz/en/reference/liff/#get-context"


def build_availability(liff_md: str) -> list[dict]:
    """從 getContext() 的範例回應抽出 availability 清單。"""
    best: dict = {}
    for block in re.findall(r"```json\n(.*?)```", liff_md, re.S):
        try:
            data = json.loads(block)
        except Exception:
            continue
        avail = data.get("availability") if isinstance(data, dict) else None
        if isinstance(avail, dict) and len(avail) > len(best):
            best = avail

    rows = []
    for feature, spec in best.items():
        if not isinstance(spec, dict):
            continue
        rows.append({
            "feature": feature,
            "needs_permission": str(spec.get("permission", "")).lower(),
            "min_line_version": spec.get("minVer", ""),
            "min_os_version": spec.get("minOsVer", ""),
            "unsupported_from_version": spec.get("unsupportedFromVer", ""),
            "how_to_check": f"liff.isApiAvailable('{feature}')",
            "doc_url": AVAIL_DOC if not spec.get("unsupportedFromVer") else CONTEXT_DOC,
        })
    return rows
