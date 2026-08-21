#!/usr/bin/env python3
"""
LINE API skill — offline validator for Messaging API message objects.

Checks a message object (or an array of them, or a whole request body) against
the schema extracted from LINE's own OpenAPI specs, so you catch mistakes
before spending an API call — and before a user sees a broken message.

What it checks
    * message / template / flex / action / imagemap type discriminators
    * required properties
    * unknown properties (typos such as "alignItems", "quickreply")
    * enum values (layout, size, weight, gravity, ...)
    * maxLength and maxItems (text 5000, quickReply 13, carousel 12, ...)
    * array cardinality of the request itself (messages ≤ 5, to ≤ 500)
    * deprecated components

Usage
    python scripts/validate.py message.json
    echo '{"type":"text","text":"hi"}' | python scripts/validate.py -
    python scripts/validate.py body.json --as push
    python scripts/validate.py flex.json --as flex
    python scripts/validate.py message.json --format json
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import use_utf8_stdout  # noqa: E402

use_utf8_stdout()

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# discriminated unions -> (csv file, group)
UNIONS = {
    "Message": ("message-objects.csv", "message"),
    "Template": ("message-objects.csv", "template"),
    "ImagemapAction": ("message-objects.csv", "imagemap-action"),
    "Action": ("actions.csv", "action"),
    "FlexComponent": ("flex-components.csv", "flex-component"),
    "FlexContainer": ("flex-components.csv", "flex-container"),
    "FlexBoxBackground": ("flex-components.csv", "flex-background"),
}
# plain named object schemas
NAMED_FILES = [
    ("message-objects.csv", "message-part"),
    ("flex-components.csv", "flex-style"),
    ("richmenu.csv", "richmenu"),
]

PRIMITIVES = {"string", "integer", "number", "boolean", "object", "array", ""}

# Request-level rules straight from the OpenAPI specs.
REQUEST_SHAPES = {
    "reply": {"required": ["replyToken", "messages"], "messages_max": 5},
    "push": {"required": ["to", "messages"], "messages_max": 5},
    "multicast": {"required": ["to", "messages"], "messages_max": 5, "to_max": 500},
    "broadcast": {"required": ["messages"], "messages_max": 5},
    "narrowcast": {"required": ["messages"], "messages_max": 5},
}

# LINE 對這兩個地方的 text 有「條件式」上限：沒有圖也沒有標題時放寬，
# 兩者任一存在時縮短。CSV 只存得下一個數字（存的是寬鬆值，避免誤報），
# 縮短後的規則在這裡補上。
# reference/messaging-api.md > Message objects > Template message
TEXT_SHRINKS_WITH_IMAGE = {
    "ButtonsTemplate": {"loose": 160, "tight": 60,
                        "when": ("thumbnailImageUrl", "title")},
    "CarouselColumn": {"loose": 120, "tight": 60,
                       "when": ("thumbnailImageUrl", "title")},
}

# Flex 容器的 JSON 體積上限。只寫在文件正文，OpenAPI 沒有。
# reference/messaging-api.md > Message objects > Flex Message > Container
FLEX_JSON_LIMITS = {
    "bubble": 30 * 1024,
    "carousel": 50 * 1024,
}

# 官方對 confirm template 的寫法是「Set 2 actions for the 2 buttons」——
# 是「剛好 2 個」而不是「最多 2 個」，所以不能存成 max_length。
# reference/messaging-api.md > Message objects > Template messages > Confirm template
EXACT_ACTION_COUNT = {
    "ConfirmTemplate": 2,
}

DEPRECATED_TYPES = {
    "filler": "filler 已淘汰，請改用 box 的 margin / offset / padding 排版",
}


# --------------------------------------------------------------------------
def _rows(fname: str) -> list[dict]:
    path = DATA_DIR / fname
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


class Registry:
    """type/schema -> {property: spec} built from the generated CSVs."""

    def __init__(self) -> None:
        self.unions: dict[str, dict[str, dict]] = {}
        self.named: dict[str, dict] = {}
        self.doc: dict[str, str] = {}
        # schema class name (FlexBox, ButtonsTemplate, ...) -> its property table.
        # Needed because a property's value_type names the concrete schema
        # ("body": FlexBox) while the union table is keyed by the type tag.
        self.by_schema: dict[str, dict] = {}

        for union, (fname, group) in UNIONS.items():
            table: dict[str, dict] = {}
            for row in _rows(fname):
                if row.get("group") != group:
                    continue
                table.setdefault(row["type"], {})[row["property"]] = row
                self.by_schema.setdefault(row["schema"], {})[row["property"]] = row
                self.doc[f"{union}:{row['type']}"] = row.get("doc_url", "")
                self.doc[row["schema"]] = row.get("doc_url", "")
            self.unions[union] = table

        for fname, group in NAMED_FILES:
            for row in _rows(fname):
                if row.get("group") != group:
                    continue
                self.named.setdefault(row["schema"], {})[row["property"]] = row
                self.by_schema.setdefault(row["schema"], {})[row["property"]] = row
                self.doc[row["schema"]] = row.get("doc_url", "")

    def union_types(self, union: str) -> list[str]:
        return sorted(self.unions.get(union, {}))

    def schema_of(self, union: str, tag: str) -> str:
        """union 的 type tag -> 具體 schema 名稱（buttons -> ButtonsTemplate）。"""
        props = self.unions.get(union, {}).get(tag) or {}
        for row in props.values():
            return row.get("schema", "")
        return ""


REG = Registry()


class Problem:
    __slots__ = ("level", "path", "message", "doc")

    def __init__(self, level: str, path: str, message: str, doc: str = ""):
        self.level, self.path, self.message, self.doc = level, path, message, doc

    def as_dict(self) -> dict:
        return {"level": self.level, "path": self.path, "message": self.message, "doc": self.doc}


class Validator:
    def __init__(self) -> None:
        self.problems: list[Problem] = []

    def err(self, path: str, msg: str, doc: str = "") -> None:
        self.problems.append(Problem("error", path, msg, doc))

    def warn(self, path: str, msg: str, doc: str = "") -> None:
        self.problems.append(Problem("warning", path, msg, doc))

    # ---------------------------------------------------------------- values
    def check_value(self, path: str, value, spec: dict) -> None:
        vtype = spec.get("value_type", "")
        enum = [e for e in (spec.get("enum") or "").split("|") if e]
        max_len = spec.get("max_length") or ""

        if vtype.startswith("array<"):
            inner = vtype[len("array<"):-1]
            if not isinstance(value, list):
                self.err(path, f"必須是陣列（array<{inner}>），實際是 {type(value).__name__}")
                return
            if max_len.isdigit() and len(value) > int(max_len):
                self.err(path, f"陣列長度 {len(value)} 超過上限 {max_len}")
            for i, item in enumerate(value):
                self.check_any(f"{path}[{i}]", item, inner)
            return

        if vtype in UNIONS:
            self.check_typed(path, value, vtype)
            return
        if vtype in REG.by_schema:
            self.check_schema(path, value, vtype)
            return

        if vtype == "string" and not isinstance(value, str):
            self.err(path, f"必須是字串，實際是 {type(value).__name__}")
            return
        if vtype in ("integer", "number") and isinstance(value, bool):
            self.err(path, "必須是數字，實際是 boolean")
            return
        if vtype == "integer" and not isinstance(value, int):
            self.err(path, f"必須是整數，實際是 {type(value).__name__}")
            return
        if vtype == "number" and not isinstance(value, (int, float)):
            self.err(path, f"必須是數字，實際是 {type(value).__name__}")
            return
        if vtype == "boolean" and not isinstance(value, bool):
            self.err(path, f"必須是 boolean，實際是 {type(value).__name__}")
            return

        if enum and isinstance(value, str) and value not in enum:
            self.err(path, f"值 {value!r} 不合法，可用值：{', '.join(enum)}")
        if max_len and isinstance(value, str):
            try:
                limit = int(max_len)
            except ValueError:
                limit = 0
            if limit and len(value) > limit:
                self.err(path, f"長度 {len(value)} 超過上限 {limit}")

    def check_any(self, path: str, value, vtype: str) -> None:
        """Dispatch a value by the type name the spec gives it."""
        if vtype in UNIONS:
            self.check_typed(path, value, vtype)
        elif vtype in REG.by_schema:
            self.check_schema(path, value, vtype)
        elif vtype == "string" and not isinstance(value, str):
            self.err(path, f"必須是字串，實際是 {type(value).__name__}")

    # ------------------------------------------------------------- unions
    def check_typed(self, path: str, obj, union: str) -> None:
        table = REG.unions.get(union)
        if table is None:
            return
        if not isinstance(obj, dict):
            self.err(path, f"必須是物件（{union}），實際是 {type(obj).__name__}")
            return
        tag = obj.get("type")
        if not tag:
            self.err(path, f"缺少 type 屬性；{union} 可用型別：{', '.join(REG.union_types(union))}")
            return
        if tag not in table:
            self.err(path, f"type={tag!r} 不是合法的 {union}；可用：{', '.join(REG.union_types(union))}")
            return
        if tag in DEPRECATED_TYPES:
            self.warn(path, DEPRECATED_TYPES[tag], REG.doc.get(f"{union}:{tag}", ""))
        doc = REG.doc.get(f"{union}:{tag}", "")
        schema = REG.schema_of(union, tag)
        self._check_props(path, obj, table[tag], doc)
        self._check_conditional_text(path, obj, schema, doc)
        self._check_exact_action_count(path, obj, schema, doc)
        self._check_column_consistency(path, obj, schema, doc)
        if union == "FlexContainer":
            self._check_flex_container(path, obj, tag, doc)

    def check_schema(self, path: str, obj, schema: str) -> None:
        props = REG.by_schema.get(schema)
        if props is None:
            return
        if not isinstance(obj, dict):
            self.err(path, f"必須是物件（{schema}），實際是 {type(obj).__name__}")
            return
        doc = REG.doc.get(schema, "")
        self._check_props(path, obj, props, doc)
        self._check_conditional_text(path, obj, schema, doc)
        self._check_exact_action_count(path, obj, schema, doc)
        self._check_column_consistency(path, obj, schema, doc)

    def _check_conditional_text(self, path: str, obj: dict, schema: str, doc: str) -> None:
        rule = TEXT_SHRINKS_WITH_IMAGE.get(schema)
        if not rule:
            return
        text = obj.get("text")
        if not isinstance(text, str):
            return
        has_image_or_title = any(obj.get(k) for k in rule["when"])
        limit = rule["tight"] if has_image_or_title else rule["loose"]
        if len(text) > limit:
            reason = ("同時有圖片或標題時" if has_image_or_title else "沒有圖片與標題時")
            self.err(f"{path}.text",
                     f"{schema} 在{reason} text 上限為 {limit}，目前 {len(text)} 字", doc)

    def _check_exact_action_count(self, path: str, obj: dict, schema: str, doc: str) -> None:
        want = EXACT_ACTION_COUNT.get(schema)
        if want is None:
            return
        actions = obj.get("actions")
        if not isinstance(actions, list):
            return
        if len(actions) != want:
            self.err(f"{path}.actions",
                     f"{schema} 必須剛好 {want} 個 action，目前 {len(actions)} 個", doc)

    def _check_flex_container(self, path: str, obj: dict, tag: str, doc: str) -> None:
        """Flex 容器的三條規則，都只寫在文件正文裡，OpenAPI 沒有。

        reference/messaging-api.md > Message objects > Flex Message > Container
          - bubble 的 JSON 最大 30 KB，carousel 最大 50 KB
          - 同一個 carousel 內的 bubble 不能有不同寬度（size）
        """
        limit = FLEX_JSON_LIMITS.get(tag)
        if limit:
            size = len(json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
                       .encode("utf-8"))
            if size > limit:
                self.err(path,
                         f"{tag} 的 JSON 為 {size/1024:.1f} KB，超過上限 {limit//1024} KB",
                         doc)

        if tag != "carousel":
            return
        bubbles = [b for b in (obj.get("contents") or []) if isinstance(b, dict)]
        if len(bubbles) < 2:
            return
        sizes = {b.get("size", "mega") for b in bubbles}
        if len(sizes) > 1:
            self.err(f"{path}.contents",
                     f"同一個 carousel 內的 bubble 寬度必須相同，目前混用了 {sorted(sizes)}",
                     doc)

    def _check_column_consistency(self, path: str, obj: dict, schema: str, doc: str) -> None:
        """輪播各欄必須長得一樣。

        官方原文：Keep the number of actions consistent for all columns. If you
        use an image or title for a column, make sure to do the same for all
        other columns.
        """
        if schema != "CarouselTemplate":
            return
        columns = obj.get("columns")
        if not isinstance(columns, list) or len(columns) < 2:
            return
        cols = [c for c in columns if isinstance(c, dict)]
        if len(cols) < 2:
            return

        counts = {len(c.get("actions") or []) for c in cols}
        if len(counts) > 1:
            self.warn(f"{path}.columns",
                      f"各欄的 action 數量不一致（{sorted(counts)}），LINE 要求所有欄位一致",
                      doc)
        for field, label in (("thumbnailImageUrl", "圖片"), ("title", "標題")):
            present = {bool(c.get(field)) for c in cols}
            if len(present) > 1:
                self.warn(f"{path}.columns",
                          f"有些欄有{label}、有些沒有；LINE 要求所有欄位一致（{field}）",
                          doc)

    def _check_props(self, path: str, obj: dict, props: dict, doc: str) -> None:
        for name, spec in props.items():
            if spec.get("required") == "true" and name not in obj:
                self.err(f"{path}.{name}", f"缺少必填屬性 {name}", doc)
        for key, value in obj.items():
            if key not in props:
                self.warn(f"{path}.{key}", f"未知屬性 {key!r}（可用：{', '.join(sorted(props))}）", doc)
                continue
            if value is None:
                continue
            self.check_value(f"{path}.{key}", value, props[key])

    # ------------------------------------------------------------- entries
    def validate_message(self, obj, path: str = "$") -> None:
        self.check_typed(path, obj, "Message")

    def validate_messages(self, arr, path: str = "$.messages") -> None:
        if not isinstance(arr, list):
            self.err(path, "messages 必須是陣列")
            return
        if not arr:
            self.err(path, "messages 不可為空陣列（minItems=1）")
        if len(arr) > 5:
            self.err(path, f"一次最多 5 則訊息，目前 {len(arr)} 則",
                     "https://developers.line.biz/en/reference/messaging-api/#send-push-message")
        for i, m in enumerate(arr):
            self.validate_message(m, f"{path}[{i}]")

    def validate_request(self, body, kind: str) -> None:
        shape = REQUEST_SHAPES[kind]
        if not isinstance(body, dict):
            self.err("$", f"{kind} 的 request body 必須是物件")
            return
        for field in shape["required"]:
            if field not in body:
                self.err(f"$.{field}", f"缺少必填欄位 {field}")
        if "to" in body and "to_max" in shape:
            to = body["to"]
            if not isinstance(to, list):
                self.err("$.to", "multicast 的 to 必須是 userId 陣列")
            elif len(to) > shape["to_max"]:
                self.err("$.to", f"一次最多 {shape['to_max']} 個 userId，目前 {len(to)} 個")
        if "messages" in body:
            self.validate_messages(body["messages"])


# --------------------------------------------------------------------------
def detect_kind(data) -> str:
    if isinstance(data, list):
        return "messages"
    if isinstance(data, dict):
        if "replyToken" in data and "messages" in data:
            return "reply"
        if "to" in data and "messages" in data:
            return "multicast" if isinstance(data.get("to"), list) else "push"
        if "messages" in data:
            return "broadcast"
        if data.get("type") == "flex":
            return "message"
        if data.get("type") in ("bubble", "carousel"):
            return "flex"
        if "type" in data:
            return "message"
    return "message"


def run(data, kind: str) -> Validator:
    v = Validator()
    if kind == "messages":
        v.validate_messages(data, "$")
    elif kind in REQUEST_SHAPES:
        v.validate_request(data, kind)
    elif kind == "flex":
        v.check_typed("$", data, "FlexContainer")
    elif kind == "action":
        v.check_typed("$", data, "Action")
    else:
        v.validate_message(data)
    return v


def main() -> int:
    ap = argparse.ArgumentParser(description="驗證 LINE Messaging API 訊息物件（離線）")
    ap.add_argument("file", help="JSON 檔路徑，或 - 讀 stdin")
    ap.add_argument("--as", dest="kind",
                    choices=["auto", "message", "messages", "flex", "action",
                             "reply", "push", "multicast", "broadcast", "narrowcast"],
                    default="auto")
    ap.add_argument("--format", choices=["text", "json"], default="text")
    ap.add_argument("--strict", action="store_true", help="把 warning 也視為失敗")
    args = ap.parse_args()

    raw = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"JSON 解析失敗：{e}")
        return 2

    kind = detect_kind(data) if args.kind == "auto" else args.kind
    v = run(data, kind)

    errors = [p for p in v.problems if p.level == "error"]
    warnings = [p for p in v.problems if p.level == "warning"]

    if args.format == "json":
        print(json.dumps({
            "kind": kind,
            "valid": not errors and (not warnings or not args.strict),
            "errors": [p.as_dict() for p in errors],
            "warnings": [p.as_dict() for p in warnings],
        }, ensure_ascii=False, indent=2))
    else:
        print(f"\n驗證模式：{kind}")
        print("=" * 78)
        if not v.problems:
            print("✅ 通過：沒有發現任何問題")
        for p in errors:
            print(f"❌ [error]   {p.path}\n             {p.message}" + (f"\n             {p.doc}" if p.doc else ""))
        for p in warnings:
            print(f"⚠️  [warning] {p.path}\n             {p.message}" + (f"\n             {p.doc}" if p.doc else ""))
        print("-" * 78)
        print(f"{len(errors)} error, {len(warnings)} warning")

    if errors:
        return 1
    if warnings and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
