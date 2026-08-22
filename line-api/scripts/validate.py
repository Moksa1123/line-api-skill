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
    * https-only URLs and the four allowed uri schemes (http/https/line/tel)
    * the label rules that depend on where the action sits (quick reply 20,
      Flex button 40, image carousel 12) rather than on the action type

Severity means something specific here:
    error    LINE will reject this request (400)
    warning  LINE accepts it, but it won't do what you intended

Both are measured, not assumed. 659 generated messages and 41 rich menus were
sent through LINE's own validators (POST /v2/bot/message/validate/push and
/v2/bot/richmenu/validate) and every verdict matched. That is how the
counter-intuitive parts got found — TextMessage.text counts UTF-16 code units
rather than characters, unknown properties are fatal inside Flex but harmless
outside it, and a number where a string belongs is coerced at message level
but rejected inside Flex. `test_line.py --live` re-checks the agreement.

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
import re
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

# action 的 label 沒有單一規格：同一個欄位放在不同父物件，必填與否和上限都不同。
# 這種東西塞不進 CSV 的一欄，只有看得到父物件的驗證器才判得出來。
# reference/messaging-api.md > Action objects > Specifications of the label
LABEL_SPEC = {
    "image_carousel": (False, 12),   # ImageCarouselColumn.action
    "template":       (True, 20),    # buttons / confirm / carousel
    "richmenu":       (False, 20),
    "quickreply":     (True, 20),
    "flex-button":    (True, 40),
    "flex-other":     (False, 40),
}
LABEL_DOC = "https://developers.line.biz/en/reference/messaging-api/#action-object-label-spec"

# 哪個父物件底下的 action 適用上表的哪一列，以及 action 掛在哪個屬性上
LABEL_CONTEXT = {
    "QuickReplyItem":      ("action",  "quickreply"),
    "ImageCarouselColumn": ("action",  "image_carousel"),
    "ButtonsTemplate":     ("actions", "template"),
    "ConfirmTemplate":     ("actions", "template"),
    "CarouselColumn":      ("actions", "template"),
    "RichMenuArea":        ("action",  "richmenu"),
    "FlexButton":          ("action",  "flex-button"),
}

URI_DOC = "https://developers.line.biz/en/reference/messaging-api/#uri-action"

# action 能放哪裡是有限制的，放錯位置 LINE 會回
# 「{0} action is not available for flex message」。
# reference/messaging-api.md > Action objects
#   camera / cameraRoll / location：This action can be configured only with
#     quick reply buttons.
#   richmenuswitch：only with rich menus. It can't be used for Flex Messages
#     or quick replies.
ACTION_ONLY_IN = {
    "camera": "quickreply",
    "cameraRoll": "quickreply",
    "location": "quickreply",
    "richmenuswitch": "richmenu",
}
PLACEMENT_LABEL = {"quickreply": "quick reply 按鈕", "richmenu": "圖文選單"}

# box 能放哪些子元件由它自己的 layout 決定。放錯 LINE 回
# 「invalid box content type」，不會渲染成空白讓你以為是 CSS 問題。
# reference/messaging-api.md > Flex Message > Box > contents
BOX_CHILDREN = {
    "horizontal": {"box", "button", "image", "text", "separator", "filler"},
    "vertical": {"box", "button", "image", "text", "separator", "filler"},
    "baseline": {"icon", "text", "filler"},
}

# bubble 的 hero 只收這三種。reference > Flex Message > Bubble > hero
HERO_TYPES = {"box", "image", "video"}

# bubble 的四個區塊。文件說「It can contain four blocks」但沒明講至少要有一個；
# 實測全空時 LINE 回 400「At least one block must be specified」，所以這條的
# 依據是 API 行為而不是文件。
BUBBLE_BLOCKS = ("header", "hero", "body", "footer")

# 具名 schema 對應到哪個 flex type tag（bubble.body 標的型別是 FlexBox）
SCHEMA_AS_FLEX_TAG = {"FlexBox": "box", "FlexText": "text", "FlexBubble": "bubble"}

# ---- 值的格式 ----------------------------------------------------------
# 這幾條在 schema 裡都只是「string」，錯了 LINE 會回「invalid property」——
# 那句話講的是值不合法，不是屬性不存在，很容易讓人往錯的方向找。
#
# 色碼：官方說明寫「Use a hexadecimal color code」。實測 #RRGGBB 與
# #RRGGBBAA 都收，大小寫皆可；#F00、red 一律退。
COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$")
COLOR_RGB_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

# 尺寸：docs/messaging-api/flex-message-layout.md > margin property of components
#   「in pixels or with a keyword. You can't specify a percentage.」
# 實測 offset* 與 padding* 反而收 %（也收負值），margin / spacing /
# cornerRadius 不收。同一種寫法在不同屬性上結果不同，所以分兩組。
SIZE_KEYWORDS = {"none", "xs", "sm", "md", "lg", "xl", "xxl"}
SIZE_PX_RE = re.compile(r"^-?\d+(\.\d+)?px$")
SIZE_PCT_RE = re.compile(r"^-?\d+(\.\d+)?%$")
SIZE_NO_PERCENT = {"margin", "spacing", "cornerRadius"}
SIZE_WITH_PERCENT = {"offsetTop", "offsetBottom", "offsetStart", "offsetEnd",
                     "paddingAll", "paddingTop", "paddingBottom",
                     "paddingStart", "paddingEnd"}

# LINE 會去核對這些 ID 是否真的存在，轉型後的字串一樣對不上
ID_LIKE = {"packageId", "stickerId", "productId", "emojiId", "quoteToken",
           "couponId", "richMenuAliasId", "richMenuId"}

# 圖文選單的圖片規格。官方寫的是範圍不是固定清單——Developers Console
# 給的六種預設尺寸只是常用值，API 真正的條件是這三條，實測邊界完全吻合：
# 799 寬退、2501 寬退、249 高退、比例 1.4493 退、1.4514 收。
# reference/messaging-api.md > Rich menu > 圖片規格
RICHMENU_IMAGE = {"min_width": 800, "max_width": 2500,
                  "min_height": 250, "min_ratio": 1.45}
RICHMENU_DOC = "https://developers.line.biz/en/reference/messaging-api/#rich-menu-object"

# 字數怎麼算，LINE 各欄位的實作並不一致。逐一實測：
#   TextMessage.text 5000      → UTF-16 code unit（4999 個 a 加一個 😀 是
#                                 5000 個字元、5001 個 unit，會被退）
#   buttons template text 160  → 字元
#   message action text 300    → 字元
#   quick reply label 20       → 字元
#   Flex 的 text               → 完全沒有上限（2501 個 emoji 照收）
# 所以只有這一個欄位要換算，其餘照字元數。用 emoji 打招呼的機器人
# 很容易踩到——3000 個 emoji 是 3000 個字元、卻是 6000 個 unit。
UTF16_COUNTED = {("TextMessage", "text"), ("TextMessageV2", "text")}

LAYOUT_DOC = ("https://developers.line.biz/en/docs/messaging-api/"
              "flex-message-layout/#margin-property")


# --------------------------------------------------------------------------
def _rows(fname: str) -> list[dict]:
    path = DATA_DIR / fname
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _fields_whose_doc_says(marker: str) -> set[str]:
    """哪些欄位的官方說明裡出現這句話。

    「這個網址一定要 https」與「這裡只收這幾種 scheme」都只寫在說明散文裡，
    沒有對應的結構化欄位。與其手打一份清單（打漏了就是漏檢，打多了就是誤報），
    不如去問資料：官方在每個 URL 欄位的說明都寫了
    「Protocol: HTTPS (TLS 1.2 or later)」，照著撈就好。
    欄位名可能帶前綴（video.originalContentUrl），只取最後一段。
    """
    return {r["parameter"].rsplit(".", 1)[-1]
            for r in _rows("parameters.csv")
            if marker in (r.get("description") or "")}


HTTPS_ONLY = _fields_whose_doc_says("Protocol: HTTPS")
# 色碼欄位分兩種寫法，接受的位數也不同：
#   「Use a hexadecimal color code」→ Flex，實測 #RRGGBB 與 #RRGGBBAA 都收
#   「Specify a RGB color value」   → 樣板訊息，LINE 的錯誤訊息直接給了
#                                     正規式 ^#[A-Fa-f0-9]{6}$，沒有 alpha
COLOR_FIELDS = _fields_whose_doc_says("hexadecimal color code")
COLOR_FIELDS_RGB = _fields_whose_doc_says("RGB color value")
SCHEME_FIELDS = _fields_whose_doc_says("available schemes are")

# 從同一句話把 scheme 撈出來，不要自己記：
# 「The available schemes are `http`, `https`, `line`, and `tel`.」
URI_SCHEMES = sorted({
    s for r in _rows("parameters.csv")
    if "available schemes are" in (r.get("description") or "")
    for s in re.findall(r"available schemes are (.+?)\.",
                        r["description"])[:1]
    for s in re.findall(r"\b(https?|line|tel|mailto)\b", s)
}) or ["http", "https", "line", "tel"]


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
            self._type_mismatch(path, value, "字串", spec)
            return
        if vtype in ("integer", "number") and isinstance(value, bool):
            self._type_mismatch(path, value, "數字", spec)
            return
        if vtype == "integer" and not isinstance(value, int):
            self._type_mismatch(path, value, "整數", spec)
            return
        if vtype == "number" and not isinstance(value, (int, float)):
            self._type_mismatch(path, value, "數字", spec)
            return
        if vtype == "boolean" and not isinstance(value, bool):
            self._type_mismatch(path, value, "boolean", spec)
            return

        if enum and isinstance(value, str) and value not in enum:
            self.err(path, f"值 {value!r} 不合法，可用值：{', '.join(enum)}")
        if max_len and isinstance(value, str):
            try:
                limit = int(max_len)
            except ValueError:
                limit = 0
            if limit:
                if (spec.get("schema"), spec.get("property")) in UTF16_COUNTED:
                    n = len(value.encode("utf-16-le")) // 2
                    unit = "UTF-16 單位"
                else:
                    n = len(value)
                    unit = "字"
                if n > limit:
                    extra = ("" if unit == "字" or n == len(value) else
                             f"（看起來只有 {len(value)} 個字，但 emoji 之類的"
                             f"字元每個算兩個單位）")
                    self.err(path, f"長度 {n} {unit}超過上限 {limit}{extra}")

    def _type_mismatch(self, path: str, value, expected: str, spec: dict) -> None:
        """型別對不上要用 error 還是 warning，取決於 LINE 會不會退件。

        逐一實測出來的表，兩個方向的答案不一樣：

            容器            數字→字串   字串→數字/布林
            訊息物件          收          收
            樣板              退          收
            圖文選單          退          收
            Flex             退          退

        所以「LINE 會自動轉型」不是一句話講得完的事。只在量到會轉的組合
        給 warning，其餘一律 error——沒量過的組合寧可從嚴，誤擋看得見，
        誤放行看不見。
        """
        got = type(value).__name__
        schema = spec.get("schema") or ""
        key = spec.get("property") or ""
        is_flex = schema.startswith("Flex")
        plain = not (is_flex or schema.endswith("Template")
                     or schema.endswith("Column") or schema.startswith("RichMenu"))

        if expected == "字串":
            # 數字或布林被轉成字串——只有最外層的訊息物件會這樣收
            lenient = plain and isinstance(value, (int, float, bool))
        else:
            # 字串被轉成數字或布林——Flex 以外都收，但字串本身要轉得動
            lenient = not is_flex and isinstance(value, str)
            if lenient and expected in ("數字", "整數"):
                try:
                    float(value)
                except ValueError:
                    lenient = False
            if lenient and expected == "boolean":
                lenient = value.lower() in ("true", "false")

        # 有格式約束的欄位就算轉成字串也過不了自己的格式檢查：
        # 12345 轉成 "12345" 依然不是合法的 HTTPS URL、不是合法色碼、
        # 也不會是真的 sticker ID
        if key in HTTPS_ONLY or key in SCHEME_FIELDS or key in COLOR_FIELDS                 or key in COLOR_FIELDS_RGB or key in SIZE_NO_PERCENT                 or key in SIZE_WITH_PERCENT or key in ID_LIKE:
            lenient = False

        if lenient:
            self.warn(path, f"應該是{expected}，實際是 {got}；"
                            f"LINE 會自動轉型收下，但型別對不上通常是程式的問題")
        else:
            self.err(path, f"必須是{expected}，實際是 {got}")

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
        if union in ("FlexComponent", "FlexContainer"):
            self._check_flex_shape(path, obj, tag, doc)
        if union == "Message" and tag == "imagemap":
            self._check_imagemap_video(path, obj, doc)
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
        # bubble.body 的 value_type 是 FlexBox，走的是這條路而不是 check_typed。
        # 少了這一行，「box 裡放了不該放的元件」在最常見的位置反而檢查不到。
        if schema in SCHEMA_AS_FLEX_TAG:
            self._check_flex_shape(path, obj, SCHEMA_AS_FLEX_TAG[schema], doc)

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
            # 實測：LINE 對這個回 400「The use of image, title and the number of
            # actions should be consistent for all columns.」——是退件不是提醒
            self.err(f"{path}.columns",
                     f"各欄的 action 數量不一致（{sorted(counts)}），LINE 要求所有欄位一致",
                     doc)
        for field, label in (("thumbnailImageUrl", "圖片"), ("title", "標題")):
            present = {bool(c.get(field)) for c in cols}
            if len(present) > 1:
                self.err(f"{path}.columns",
                         f"有些欄有{label}、有些沒有；LINE 要求所有欄位一致（{field}）",
                         doc)

    def _check_props(self, path: str, obj: dict, props: dict, doc: str) -> None:
        for name, spec in props.items():
            if spec.get("required") == "true" and name not in obj:
                self.err(f"{path}.{name}", f"缺少必填屬性 {name}", doc)
            elif spec.get("required") == "true" and obj.get(name) is None:
                # 「有這個 key 但值是 null」跟「沒有這個 key」對 LINE 是同一件事，
                # 但對「name in obj」不是——漏掉這一行，{"size": null} 就會過關
                self.err(f"{path}.{name}", f"必填屬性 {name} 不可以是 null", doc)
        schema_name = next((sp.get("schema", "") for sp in props.values()), "")
        # 實測：Flex 的容器與元件對多出來的屬性直接回 400，其他地方（訊息物件、
        # 樣板、action、quickReply item、imagemap）一律收下但那個屬性不會生效。
        # 「請求會失敗」與「送得出去但沒作用」不該用同一個等級講。
        strict_unknown = schema_name.startswith("Flex")
        for key, value in obj.items():
            if key not in props:
                msg = f"未知屬性 {key!r}（可用：{', '.join(sorted(props))}）"
                if strict_unknown:
                    self.err(f"{path}.{key}", msg + "；Flex 對多餘的屬性會直接退件", doc)
                else:
                    self.warn(f"{path}.{key}", msg, doc)
                continue
            if value is None:
                # 實測：非 Flex 的選填欄位給 null，LINE 收；Flex 給 null 直接退
                if strict_unknown:
                    self.err(f"{path}.{key}",
                             f"{key} 是 null；Flex 不接受 null，要嘛給值要嘛整個拿掉", doc)
                continue
            self.check_value(f"{path}.{key}", value, props[key])
            self._check_url(f"{path}.{key}", key, value, doc)
            self._check_format(f"{path}.{key}", key, value, doc)

        schema = schema_name
        prop, ctx = LABEL_CONTEXT.get(schema) or (
            ("action", "flex-other") if schema.startswith("Flex") else (None, None))
        if ctx:
            target = obj.get(prop)
            for i, action in enumerate(target if isinstance(target, list) else [target]):
                suffix = f"[{i}]" if isinstance(target, list) else ""
                self._check_action_label(f"{path}.{prop}{suffix}", action, ctx)
                self._check_action_placement(f"{path}.{prop}{suffix}", action, ctx)

    def _check_format(self, path: str, key: str, value, doc: str) -> None:
        """色碼與尺寸的寫法。schema 只說是 string，格式錯了要靠這裡擋。"""
        if not isinstance(value, str) or not value:
            return
        if key in COLOR_FIELDS_RGB and not COLOR_RGB_RE.match(value):
            self.err(path, f"色碼要寫成 #RRGGBB（這個欄位不接受 alpha），實際是 {value!r}", doc)
            return
        if key in COLOR_FIELDS and not COLOR_RE.match(value):
            self.err(path, f"色碼要寫成 #RRGGBB 或 #RRGGBBAA，實際是 {value!r}", doc)
            return
        pct = key in SIZE_WITH_PERCENT
        if key in SIZE_NO_PERCENT or pct:
            ok = (value in SIZE_KEYWORDS or SIZE_PX_RE.match(value)
                  or (pct and SIZE_PCT_RE.match(value)))
            if not ok:
                units = "關鍵字、數字加 px" + ("，或百分比" if pct else "（不接受百分比）")
                self.err(path,
                         f"{key} 只能是 {units}；關鍵字：{', '.join(sorted(SIZE_KEYWORDS))}。"
                         f"實際是 {value!r}", doc or LAYOUT_DOC)

    def _check_imagemap_video(self, path: str, obj: dict, doc: str) -> None:
        """imagemap 的 video 一旦出現，它底下那幾個欄位就變成必填。

        官方的註腳寫「*1 This property is required if you set a video to play
        on the imagemap.」——是條件式必填，所以 CSV 裡照實標 false，
        條件本身只能在看得到 video 存不存在的地方判。
        """
        video = obj.get("video")
        if not isinstance(video, dict):
            return
        for field in ("originalContentUrl", "previewImageUrl", "area"):
            if not video.get(field):
                self.err(f"{path}.video.{field}",
                         f"imagemap 設了 video，{field} 就是必填", doc)

    def _check_url(self, path: str, key: str, value, doc: str) -> None:
        """網址的 scheme 限制。兩者都只寫在說明散文裡，OpenAPI 只說是 string。"""
        if not isinstance(value, str) or not value:
            return
        if key in HTTPS_ONLY and not value.lower().startswith("https://"):
            self.err(path, f"必須是 https:// 的網址（官方標明 Protocol: HTTPS），實際是 {value[:40]!r}", doc)
        elif key in SCHEME_FIELDS:
            scheme = value.split(":", 1)[0].lower()
            if scheme not in URI_SCHEMES:
                self.err(path, f"scheme {scheme!r} 不合法，可用：{', '.join(URI_SCHEMES)}",
                         doc or URI_DOC)

    def _check_flex_shape(self, path: str, obj: dict, tag: str, doc: str) -> None:
        """Flex 的三條結構規則。這些在 schema 裡看不出來——每個屬性單獨看都合法，
        錯的是它們的組合，或是這個元件被放在哪裡。"""
        if tag == "box":
            allowed = BOX_CHILDREN.get(obj.get("layout") or "")
            if allowed:
                for i, child in enumerate(obj.get("contents") or []):
                    ctype = child.get("type") if isinstance(child, dict) else None
                    if isinstance(ctype, str) and ctype not in allowed:
                        self.err(f"{path}.contents[{i}]",
                                 f"layout={obj['layout']} 的 box 不能放 {ctype}；"
                                 f"可放：{', '.join(sorted(allowed))}", doc)
        elif tag == "text":
            # 「Be sure to set either one of the text property or contents property.」
            if obj.get("text") is None and obj.get("contents") is None:
                self.err(f"{path}.text", "text 元件必須有 text 或 contents 其中之一", doc)
        elif tag == "bubble":
            if not any(obj.get(b) for b in BUBBLE_BLOCKS):
                self.err(path,
                         f"bubble 至少要有一個區塊（{' / '.join(BUBBLE_BLOCKS)}），"
                         f"否則 LINE 回 400 At least one block must be specified", doc)
            hero = obj.get("hero")
            if isinstance(hero, dict) and isinstance(hero.get("type"), str) \
                    and hero["type"] not in HERO_TYPES:
                self.err(f"{path}.hero",
                         f"hero 只能放 {', '.join(sorted(HERO_TYPES))}，實際是 {hero['type']}", doc)

    def _check_action_placement(self, path: str, action, ctx: str) -> None:
        """有些 action 只能放在特定容器裡，放錯 LINE 會退件。"""
        if not isinstance(action, dict):
            return
        tag = action.get("type")
        want = ACTION_ONLY_IN.get(tag)
        if not want or ctx == want:
            return
        doc = REG.doc.get(f"Action:{tag}", "")
        msg = f"{tag} action 只能用在{PLACEMENT_LABEL[want]}裡"
        # 實測：Flex 裡 LINE 直接退件，樣板訊息裡 LINE 收單但按了不會動。
        # 前者是「這個請求會失敗」，後者是「送得出去但不會照你想的運作」——
        # 用同一個等級講這兩件事，只會讓人學會忽略其中一種。
        if ctx.startswith("flex") or want == "richmenu":
            self.err(path, msg, doc)
        else:
            self.warn(path, msg + "；LINE 會收下這個請求，但使用者點了不會有反應", doc)

    def _check_action_label(self, path: str, action, ctx: str) -> None:
        """label 的必填與上限由「action 放在哪裡」決定，不是由 action 型別決定。

        同一個 postback action：放 quick reply 是必填、上限 20；放 Flex button
        是必填、上限 40；放 image carousel 是選填、上限 12。CSV 一欄裝不下，
        只有看得到父物件的地方判得出來。
        """
        if not isinstance(action, dict):
            return
        required, limit = LABEL_SPEC[ctx]
        label = action.get("label")
        if label is None:
            tag = action.get("type")
            spec = (REG.unions.get("Action", {}).get(tag) or {}).get("label") or {}
            # CSV 已經標必填的（camera、location…）就讓 _check_props 去講，別報兩次
            if required and spec.get("required") != "true":
                self.err(f"{path}.label", f"放在這裡的 action 必須有 label", LABEL_DOC)
        elif isinstance(label, str) and len(label) > limit:
            self.err(f"{path}.label",
                     f"label 長度 {len(label)} 超過上限 {limit}（這個位置的上限）", LABEL_DOC)

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

    def validate_richmenu(self, obj, path: str = "$") -> None:
        """圖文選單物件。走的是另一支端點（POST /v2/bot/richmenu/validate），
        規則跟訊息不一樣，所以獨立一個入口。"""
        self.check_schema(path, obj, "RichMenuRequest")
        if not isinstance(obj, dict):
            return
        size = obj.get("size")
        if isinstance(size, dict):
            w, h = size.get("width"), size.get("height")
            if isinstance(w, int) and isinstance(h, int) and h > 0:
                r = RICHMENU_IMAGE
                if not (r["min_width"] <= w <= r["max_width"]):
                    self.err(f"{path}.size.width",
                             f"寬度要在 {r['min_width']}–{r['max_width']} 之間，實際 {w}",
                             RICHMENU_DOC)
                if h < r["min_height"]:
                    self.err(f"{path}.size.height",
                             f"高度至少 {r['min_height']}，實際 {h}", RICHMENU_DOC)
                if w / h < r["min_ratio"]:
                    self.err(f"{path}.size",
                             f"長寬比要 {r['min_ratio']} 以上，實際 {w / h:.2f}"
                             f"（{w}×{h}）", RICHMENU_DOC)
        areas = obj.get("areas")
        if isinstance(areas, list) and isinstance(size, dict):
            sw, sh = size.get("width"), size.get("height")
            for i, area in enumerate(areas):
                b = area.get("bounds") if isinstance(area, dict) else None
                if not isinstance(b, dict):
                    continue
                x, y = b.get("x"), b.get("y")
                bw, bh = b.get("width"), b.get("height")
                if not all(isinstance(v, int) for v in (x, y, bw, bh, sw, sh)):
                    continue
                if x < 0 or y < 0 or x + bw > sw or y + bh > sh:
                    # LINE 的驗證端點收下這種，但超出範圍的那塊點了不會有反應
                    self.warn(f"{path}.areas[{i}].bounds",
                              f"這一塊超出圖片範圍（{x},{y} {bw}×{bh} vs {sw}×{sh}）；"
                              f"LINE 不會退件，但超出的部分點了沒反應", RICHMENU_DOC)

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
        if "chatBarText" in data and "areas" in data:
            return "richmenu"
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
    elif kind == "richmenu":
        v.validate_richmenu(data)
    else:
        v.validate_message(data)
    return v


def main() -> int:
    ap = argparse.ArgumentParser(description="驗證 LINE Messaging API 訊息物件（離線）")
    ap.add_argument("file", help="JSON 檔路徑，或 - 讀 stdin")
    ap.add_argument("--as", dest="kind",
                    choices=["auto", "message", "messages", "flex", "action",
                             "richmenu", "reply", "push", "multicast",
                             "broadcast", "narrowcast"],
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
