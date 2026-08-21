#!/usr/bin/env python3
"""
build_dataset.py — regenerate line-api/data/*.csv from authoritative sources.

Sources (both fetched into .docs-cache/, which is git-ignored):
  1. https://github.com/line/line-openapi  ....... OpenAPI specs (field-exact)
  2. https://developers.line.biz/en/...index.html.md  official docs in Markdown

Usage:
    python tools/fetch_sources.py      # download / refresh .docs-cache/
    python tools/build_dataset.py      # regenerate line-api/data/*.csv

The generated CSVs are committed; .docs-cache/ is not.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("PyYAML required:  pip install pyyaml")

REPO = Path(__file__).resolve().parent.parent
CACHE = REPO / ".docs-cache"
SPECS = CACHE / "line-openapi"
RAW = CACHE / "raw"
REF = RAW / "en" / "reference"
DOCS = RAW / "en" / "docs"
OUT = REPO / "line-api" / "data"

METHODS = ("GET", "POST", "PUT", "DELETE", "PATCH")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
# Some externalDocs URLs in the OpenAPI specs point at pages that now redirect.
# Rewrite them to the final location so no shipped link bounces.
URL_FIXUPS = {
    "https://developers.line.biz/en/docs/messaging-api/channel-access-tokens/":
        "https://developers.line.biz/en/docs/basics/channel-access-token/",
    "https://developers.line.biz/en/docs/partner-docs/line-notification-messages/#":
        "https://developers.line.biz/en/docs/partner-docs/line-notification-messages/overview/#",
}


def fix_url(url: str) -> str:
    for old, new in URL_FIXUPS.items():
        if url.startswith(old):
            return new + url[len(old):]
    return url


def write_csv(name: str, fieldnames: list[str], rows: list[dict]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            out = {k: ("" if r.get(k) is None else str(r.get(k))) for k in fieldnames}
            for k in out:
                if k.endswith("url") and out[k].startswith("http"):
                    out[k] = fix_url(out[k])
            w.writerow(out)
    print(f"  {name:26s} {len(rows):4d} rows")


def one_line(s) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", str(s)).strip()


def anchor(title: str) -> str:
    a = title.lower().strip()
    a = re.sub(r"[`'\"().,/:]", "", a)
    a = re.sub(r"[^a-z0-9一-鿿]+", "-", a)
    return a.strip("-")


def load_specs() -> dict[str, dict]:
    out = {}
    for p in sorted(SPECS.glob("*.yml")):
        if p.name == "docker-compose.yml":
            continue
        out[p.name] = yaml.safe_load(p.read_text(encoding="utf-8"))
    return out


# --------------------------------------------------------------------------
# 1. endpoints.csv
# --------------------------------------------------------------------------
REF_FILES = {
    "messaging-api.md": ("messaging-api", "https://developers.line.biz/en/reference/messaging-api/"),
    "line-login.md": ("line-login", "https://developers.line.biz/en/reference/line-login/"),
    "line-login-v2.md": ("line-login-v2", "https://developers.line.biz/en/reference/line-login-v2/"),
    "liff-server.md": ("liff-server", "https://developers.line.biz/en/reference/liff-server/"),
    "line-mini-app.md": ("line-mini-app", "https://developers.line.biz/en/reference/line-mini-app/"),
    "line-notification-messages.md": ("line-notification-messages", "https://developers.line.biz/en/reference/line-notification-messages/"),
    "partner-docs.md": ("partner-docs", "https://developers.line.biz/en/reference/partner-docs/"),
}

HEAD_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")


def fence_mask(lines: list[str]) -> list[bool]:
    """標出每一行是否位在 ``` 程式碼區塊內。

    非做不可：官方文件的 shell 範例裡有 `# Example of creating rich menu alias A`
    這種註解，長得跟 h1 標題一模一樣。不濾掉的話解析器會以為章節結束，
    把後面的 Rate limit、參數區塊整段丟掉。
    """
    mask, inside = [], False
    for ln in lines:
        if ln.lstrip().startswith("```"):
            inside = not inside
            mask.append(True)          # 圍籬本身也不是內容
            continue
        mask.append(inside)
    return mask


EP_INLINE = re.compile(r"^Endpoint:\s*`(" + "|".join(METHODS) + r")`\s*`(https?://[^`]+)`")
EP_BARE = re.compile(r"^`(" + "|".join(METHODS) + r")\s+(https?://[^`]+)`\s*$")


def parse_reference(path: Path, api: str, base_url: str) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    fenced = fence_mask(lines)
    out, cur, section, sub, want_http = [], None, "", "", False

    def flush():
        nonlocal cur
        if cur and cur["method"]:
            out.append(cur)
        cur = None

    for idx, ln in enumerate(lines):
        if fenced[idx]:
            continue
        hm = HEAD_RE.match(ln)
        if hm:
            level, title = len(hm.group(1)), hm.group(2).strip()
            if level <= 3:
                flush()
                sub, want_http = "", False
                if level == 2:
                    section = title
                if level == 3:
                    cur = {
                        "api": api, "category": section, "title": title,
                        "method": "", "host": "", "path": "", "query_params": "",
                        "rate_limit": "", "operation_id": "",
                        "doc_url": base_url + "#" + anchor(title),
                    }
            else:
                sub = title.lower()
                want_http = sub.startswith("http request")
            continue
        if cur is None:
            continue
        s = ln.strip()
        m = EP_INLINE.match(s) or (EP_BARE.match(s) if want_http else None)
        if m and not cur["method"]:
            url = m.group(2).strip()
            base, _, qs = url.partition("?")
            host = "/".join(base.split("/")[:3])
            cur["method"] = m.group(1)
            cur["host"] = host
            cur["path"] = base[len(host):]
            cur["query_params"] = ",".join(
                p.split("=")[0] for p in qs.split("&") if p
            )
            want_http = False
            continue
        if sub.startswith("rate limit") and s and not cur["rate_limit"]:
            if not s.startswith(("<!--", "For more", "|", "-", "*")):
                cur["rate_limit"] = one_line(s)
    flush()
    return out


def spec_index(specs: dict[str, dict]) -> dict[tuple[str, str], dict]:
    idx = {}
    for fname, doc in specs.items():
        default = (doc.get("servers") or [{}])[0].get("url", "").rstrip("/")
        for path, item in (doc.get("paths") or {}).items():
            for method, op in item.items():
                if method.upper() not in METHODS:
                    continue
                host = (op.get("servers") or [{"url": default}])[0]["url"].rstrip("/")
                key = (method.upper(), re.sub(r"\{[^}]+\}", "{}", (host + path).rstrip("/")))
                idx[key] = {
                    "spec": fname,
                    "operation_id": op.get("operationId", ""),
                    "description": one_line(op.get("description") or op.get("summary") or ""),
                }
    return idx


def build_endpoints(specs) -> list[dict]:
    rows = []
    for fname, (api, base) in REF_FILES.items():
        p = REF / fname
        if p.exists():
            rows.extend(parse_reference(p, api, base))

    idx = spec_index(specs)
    seen, out = set(), []
    for r in rows:
        key = (r["method"], re.sub(r"\{[^}]+\}", "{}", (r["host"] + r["path"]).rstrip("/")))
        if key in seen:
            continue
        seen.add(key)
        hit = idx.get(key)
        if hit:
            r["operation_id"] = hit["operation_id"]
            r["spec"] = hit["spec"]
            r["description"] = hit["description"]
        else:
            r["spec"] = ""
            r["description"] = ""
        r["auth"] = auth_for(r)
        out.append(r)

    # endpoints only present in the OpenAPI specs (defensive: never lose one)
    for key, hit in idx.items():
        if key in seen or key[1].startswith("https://example.com"):
            continue
        method, url = key
        host = "/".join(url.split("/")[:3])
        out.append({
            "api": "messaging-api", "category": "(spec only)",
            "title": hit["operation_id"], "method": method, "host": host,
            "path": url[len(host):], "query_params": "", "rate_limit": "",
            "operation_id": hit["operation_id"], "spec": hit["spec"],
            "description": hit["description"], "auth": "channel access token",
            "doc_url": "https://developers.line.biz/en/reference/messaging-api/",
        })
    return sorted(out, key=lambda r: (r["api"], r["path"], r["method"]))


def auth_for(r: dict) -> str:
    p, api = r["path"], r["api"]
    if api in ("line-login", "line-login-v2"):
        if p.startswith("/oauth2"):
            return "channel ID + channel secret (or none)"
        return "user access token"
    if p.startswith("/v2/profile") or p.startswith("/friendship"):
        return "user access token"
    if p.startswith("/oauth2/v2.1/token") or p.startswith("/v2/oauth"):
        return "channel ID + channel secret"
    if api == "line-mini-app":
        return "channel access token / user access token"
    return "channel access token"


# --------------------------------------------------------------------------
# schema flattening (messages, flex, actions, webhook events, all schemas)
# --------------------------------------------------------------------------
def resolve(schemas: dict, node: dict, depth: int = 0) -> dict:
    """Merge allOf chains into a single {required, properties, externalDocs} view."""
    if depth > 12 or not isinstance(node, dict):
        return {"required": [], "properties": {}, "externalDocs": {}}
    if "$ref" in node:
        name = node["$ref"].split("/")[-1]
        return resolve(schemas, schemas.get(name, {}), depth + 1)
    req = list(node.get("required") or [])
    props = dict(node.get("properties") or {})
    ext = dict(node.get("externalDocs") or {})
    for sub in node.get("allOf") or []:
        r = resolve(schemas, sub, depth + 1)
        req = r["required"] + req
        merged = dict(r["properties"])
        merged.update(props)
        props = merged
        ext = ext or r["externalDocs"]
    return {"required": sorted(set(req)), "properties": props, "externalDocs": ext}


def type_of(schemas: dict, prop: dict) -> str:
    if not isinstance(prop, dict):
        return ""
    if "$ref" in prop:
        return prop["$ref"].split("/")[-1]
    t = prop.get("type", "")
    if t == "array":
        return "array<" + type_of(schemas, prop.get("items") or {}) + ">"
    if prop.get("enum"):
        return t or "string"
    return t or ("object" if prop.get("properties") else "")


def max_of(prop) -> str:
    """maxLength for strings, maxItems for arrays — one column covers both."""
    if not isinstance(prop, dict):
        return ""
    for key in ("maxLength", "maxItems"):
        if key in prop:
            return str(prop[key])
    return ""


def enum_of(prop: dict) -> str:
    if isinstance(prop, dict) and prop.get("enum"):
        return "|".join(str(e) for e in prop["enum"])
    return ""


def flatten_variants(schemas: dict, parent: str, group: str, doc_fallback: str = "") -> list[dict]:
    """Flatten a discriminated union (Message / Action / FlexComponent ...)."""
    base = schemas.get(parent) or {}
    mapping = (base.get("discriminator") or {}).get("mapping") or {}
    rows = []
    for tag, ref in sorted(mapping.items()):
        name = ref.split("/")[-1]
        info = resolve(schemas, schemas.get(name, {}))
        # a curated per-type anchor is more precise than the spec's section-level
        # externalDocs, so it wins when we have one
        curated = ACTION_ANCHORS.get(tag) or FLEX_ANCHORS.get(tag)
        if doc_fallback and curated:
            doc = doc_fallback.format(type=curated)
        else:
            doc = (info["externalDocs"] or {}).get("url", "")
            if not doc and doc_fallback:
                doc = doc_fallback.format(type=tag)
        for pname, prop in info["properties"].items():
            rows.append({
                "group": group,
                "type": tag,
                "schema": name,
                "property": pname,
                "value_type": type_of(schemas, prop),
                "required": "true" if pname in info["required"] else "false",
                "enum": enum_of(prop),
                "max_length": max_of(prop),
                "description": one_line(prop.get("description") if isinstance(prop, dict) else ""),
                "doc_url": doc,
            })
    return rows


def flatten_named(schemas: dict, names: list[str], group: str, doc_fallback: str = "") -> list[dict]:
    rows = []
    for name in names:
        info = resolve(schemas, schemas.get(name, {}))
        doc = (info["externalDocs"] or {}).get("url", "") or doc_fallback
        for pname, prop in info["properties"].items():
            rows.append({
                "group": group, "type": name, "schema": name, "property": pname,
                "value_type": type_of(schemas, prop),
                "required": "true" if pname in info["required"] else "false",
                "enum": enum_of(prop),
                "max_length": max_of(prop),
                "description": one_line(prop.get("description") if isinstance(prop, dict) else ""),
                "doc_url": doc,
            })
    return rows


# LINE uses an "f-" prefix only where a flex component name collides with a
# message-object name (image / video / text / carousel).
FLEX_ANCHORS = {
    "box": "box", "button": "button", "icon": "icon", "span": "span",
    "separator": "separator", "filler": "filler", "bubble": "bubble",
    "image": "f-image", "video": "f-video", "text": "f-text", "carousel": "f-carousel",
}
FLEX_DOC = "https://developers.line.biz/en/reference/messaging-api/#{type}"

ACTION_ANCHORS = {
    "camera": "camera-action",
    "cameraRoll": "camera-roll-action",
    "clipboard": "clipboard-action",
    "datetimepicker": "datetime-picker-action",
    "location": "location-action",
    "message": "message-action",
    "postback": "postback-action",
    "richmenuswitch": "richmenu-switch-action",
    "uri": "uri-action",
}


SCHEMA_FIELDS = ["group", "type", "schema", "property", "value_type", "required",
                 "enum", "max_length", "default", "description", "doc_url"]


# Which reference heading documents each schema, as the (h3, h4, h5) path.
#
# LINE gives every message object, template and flex component the *same* doc
# anchor (#message-objects, #template-message, #flex-message) and reuses
# property names across them (text / actions / columns / url), so the anchor
# alone can never say which schema a documented parameter belongs to.
# The heading path can, and it is what the reference itself is organised by.
SCHEMA_HEADINGS = {
    # ---- message objects -------------------------------------------------
    "TextMessage": ("Text message", "", ""),
    "TextMessageV2": ("Text message (v2)", "", ""),
    "StickerMessage": ("Sticker message", "", ""),
    "ImageMessage": ("Image message", "", ""),
    "VideoMessage": ("Video message", "", ""),
    "AudioMessage": ("Audio message", "", ""),
    "LocationMessage": ("Location message", "", ""),
    "CouponMessage": ("Coupon message", "", ""),
    "ImagemapMessage": ("Imagemap message", "", ""),
    "FlexMessage": ("Flex Message", "", ""),
    # ---- shared message parts --------------------------------------------
    "QuickReply": ("Common properties for messages", "Quick reply", ""),
    "QuickReplyItem": ("Common properties for messages", "Quick reply", "items object"),
    "Sender": ("Common properties for messages", "Customize icon and display name", ""),
    # v1 的 emoji 物件寫成 emojis.index / emojis.productId（見 SCHEMA_PREFIXES）；
    # "Text message (v2)" 底下的 Emoji object 是 v2 substitution，不是同一個 schema
    "Emoji": ("Text message", "", ""),
    # ---- templates -------------------------------------------------------
    "ButtonsTemplate": ("Template messages", "Buttons template", ""),
    "ConfirmTemplate": ("Template messages", "Confirm template", ""),
    "CarouselTemplate": ("Template messages", "Carousel template", ""),
    "CarouselColumn": ("Template messages", "Carousel template",
                       "Column object for carousel"),
    "ImageCarouselTemplate": ("Template messages", "Image carousel template", ""),
    "ImageCarouselColumn": ("Template messages", "Image carousel template",
                            "Column object for image carousel"),
    "TemplateMessage": ("Template messages",
                        "Common properties of template message objects", ""),
    # ---- imagemap --------------------------------------------------------
    "URIImagemapAction": ("Imagemap message", "Imagemap action objects",
                          "Imagemap URI action object"),
    "MessageImagemapAction": ("Imagemap message", "Imagemap action objects",
                              "Imagemap message action object"),
    "ClipboardImagemapAction": ("Imagemap message", "Imagemap action objects",
                                "Imagemap clipboard action object"),
    # the area object's x/y/width/height are documented inside the clipboard
    # action section; the names don't collide, so the same path works
    "ImagemapArea": ("Imagemap message", "Imagemap action objects",
                     "Imagemap clipboard action object"),
    "ImagemapBaseSize": ("Imagemap message", "", ""),
    "ImagemapVideo": ("Imagemap message", "", ""),
    "ImagemapExternalLink": ("Imagemap message", "", ""),
    # ---- flex ------------------------------------------------------------
    "FlexBubble": ("Flex Message", "Container", "Bubble"),
    "FlexCarousel": ("Flex Message", "Container", "Carousel"),
    "FlexBox": ("Flex Message", "Component", "Box"),
    "FlexButton": ("Flex Message", "Component", "Button"),
    "FlexImage": ("Flex Message", "Component", "Image"),
    "FlexVideo": ("Flex Message", "Component", "Video"),
    "FlexIcon": ("Flex Message", "Component", "Icon"),
    "FlexText": ("Flex Message", "Component", "Text"),
    "FlexSpan": ("Flex Message", "Component", "Span"),
    "FlexSeparator": ("Flex Message", "Component", "Separator"),
    "FlexFiller": ("Flex Message", "Component", "Filler"),
    # ---- actions ---------------------------------------------------------
    "PostbackAction": ("Postback action", "", ""),
    "MessageAction": ("Message action", "", ""),
    "URIAction": ("URI action", "", ""),
    "DatetimePickerAction": ("Datetime picker action", "", ""),
    "CameraAction": ("Camera action", "", ""),
    "CameraRollAction": ("Camera roll action", "", ""),
    "LocationAction": ("Location action", "", ""),
    "RichMenuSwitchAction": ("Rich menu switch action", "", ""),
    "ClipboardAction": ("Clipboard action", "", ""),
    # ---- flex block style ------------------------------------------------
    # FlexBubbleStyles (header/hero/body/footer) and FlexBlockStyle
    # (backgroundColor/separator/separatorColor) share one section; their
    # property names don't overlap, so one path serves both.
    "FlexBubbleStyles": ("Flex Message", "Container", "Objects for the block style"),
    "FlexBlockStyle": ("Flex Message", "Container", "Objects for the block style"),
    "FlexBoxLinearGradient": ("Flex Message", "Component", "Box"),
    # ---- rich menu -------------------------------------------------------
    "RichMenuRequest": ("Rich menu object", "", ""),
    "RichMenuResponse": ("Rich menu response object", "", ""),
    "RichMenuSize": ("Rich menu response object", "`size` object", ""),
    "RichMenuArea": ("Rich menu response object", "Area object", ""),
    "RichMenuBounds": ("Rich menu response object", "Area object", "`bounds` object"),
    "RichMenuBatchRequest": ("Replace or unlink the linked rich menus in batches",
                             "Request body", ""),
    "RichMenuAliasResponse": ("Get rich menu alias information", "Response", ""),
}


# A few schemas are documented as *nested* properties of their parent rather
# than in a section of their own — the reference writes "baseSize.width", not
# "width". The prefix lets the same heading join still find them.
SCHEMA_PREFIXES = {
    "ImagemapBaseSize": "baseSize.",
    "ImagemapVideo": "video.",
    "ImagemapExternalLink": "video.externalLink.",
    "FlexBoxLinearGradient": "background.",
    "Emoji": "emojis.",
}


def merge_from_docs(schema_rows: list[dict], param_rows: list[dict]) -> list[dict]:
    """Fill max_length / enum / default from the written reference.

    The OpenAPI specs carry types and required-ness but omit most size limits
    ("Max character limit: 5000"), most enums (imageAspectRatio is just a
    "string" there) and every default value. All three are written in the
    reference, which parameters.csv already captures — SCHEMA_HEADINGS says
    which heading belongs to which schema, so the join is exact.

    Where a limit is conditional (buttons / carousel-column `text` shrinks when
    an image or title is present) the reference states the looser bound first,
    so that is what lands here; the conditional rule itself lives in
    validate.py (TEXT_SHRINKS_WITH_IMAGE) where it can see the sibling fields.
    """
    by_heading: dict[tuple, dict] = {}
    for r in param_rows:
        key = (r.get("endpoint", ""), r.get("block", ""), r.get("subblock", ""),
               r.get("parameter", ""))
        by_heading.setdefault(key, r)

    filled = {"max_length": 0, "enum": 0, "default": 0}
    for row in schema_rows:
        schema = row.get("schema", "")
        path = SCHEMA_HEADINGS.get(schema)
        if not path:
            continue
        prop = row.get("property", "")
        prefix = SCHEMA_PREFIXES.get(schema, "")
        doc = (by_heading.get((path[0], path[1], path[2], prefix + prop))
               or (by_heading.get((path[0], path[1], path[2], prop)) if prefix else None))
        if not doc:
            continue

        if not row.get("max_length"):
            raw = (doc.get("max") or "").split()
            vtype = row.get("value_type", "")
            # only a string (character limit) or an array (item limit) can carry
            # a maximum — never a nested object such as FlexMessage.contents
            if raw and raw[0].isdigit() and (vtype == "string" or vtype.startswith("array<")):
                row["max_length"] = raw[0]
                filled["max_length"] += 1

        if not row.get("enum") and doc.get("enum_doc"):
            row["enum"] = doc["enum_doc"]
            filled["enum"] += 1

        if not row.get("default") and doc.get("default"):
            row["default"] = doc["default"]
            filled["default"] += 1

    if any(filled.values()):
        print("  (from docs: {max_length} maxima, {enum} enums, {default} defaults)"
              .format(**filled))
    return schema_rows


# --------------------------------------------------------------------------
# webhook-events.csv
# --------------------------------------------------------------------------
WEBHOOK_DOC = "https://developers.line.biz/en/reference/messaging-api/#webhook-event-objects"

# webhook.yml 裡不屬於任何判別聯集的具名物件
WEBHOOK_OBJECTS = [
    "BeaconContent", "CallbackRequest", "ChatControl", "ContentProvider",
    "DeliveryContext", "Emoji", "EventMode", "FollowDetail", "ImageSet",
    "JoinedMembers", "LeftMembers", "LinkContent", "Mention", "PnpDelivery",
    "PostbackContent", "UnsendDetail", "VideoPlayComplete",
]

WEBHOOK_UNIONS = [
    ("Event", "event"),
    ("MessageContent", "message-content"),
    ("Source", "source"),
    ("MembershipContent", "membership-content"),
    ("ModuleContent", "module-content"),
    ("Mentionee", "mentionee"),
]


def build_webhook_properties(specs) -> list[dict]:
    """webhook 事件的逐欄位表。

    webhook-events.csv 只列出每個事件有哪些屬性名稱，回答不了「postback.params
    是什麼型別」「source 有哪幾種」。這裡把 webhook.yml 的 6 個判別聯集與 17 個
    具名物件全部攤平，補上型別、必填、說明。
    """
    doc = specs.get("webhook.yml") or {}
    schemas = (doc.get("components") or {}).get("schemas") or {}
    rows: list[dict] = []
    for parent, group in WEBHOOK_UNIONS:
        rows.extend(flatten_variants(schemas, parent, group))
    rows.extend(flatten_named(schemas, WEBHOOK_OBJECTS, "webhook-object"))
    for r in rows:
        if not r.get("doc_url"):
            r["doc_url"] = WEBHOOK_DOC
    return rows


def build_webhook_events(specs) -> list[dict]:
    doc = specs.get("webhook.yml") or {}
    schemas = (doc.get("components") or {}).get("schemas") or {}
    mapping = ((schemas.get("Event") or {}).get("discriminator") or {}).get("mapping") or {}
    rows = []
    for tag, ref in sorted(mapping.items()):
        name = ref.split("/")[-1]
        info = resolve(schemas, schemas.get(name, {}))
        props = info["properties"]
        rows.append({
            "event": tag,
            "schema": name,
            "properties": ",".join(sorted(props)),
            "required": ",".join(info["required"]),
            "description": one_line((schemas.get(name) or {}).get("description", "")),
            "doc_url": (info["externalDocs"] or {}).get(
                "url", "https://developers.line.biz/en/reference/messaging-api/#webhook-event-objects"),
        })
    # message event sub-types
    mm = ((schemas.get("MessageContent") or {}).get("discriminator") or {}).get("mapping") or {}
    for tag, ref in sorted(mm.items()):
        name = ref.split("/")[-1]
        info = resolve(schemas, schemas.get(name, {}))
        rows.append({
            "event": "message." + tag,
            "schema": name,
            "properties": ",".join(sorted(info["properties"])),
            "required": ",".join(info["required"]),
            "description": one_line((schemas.get(name) or {}).get("description", "")),
            "doc_url": "https://developers.line.biz/en/reference/messaging-api/#" + tag + "-message",
        })
    return rows


# --------------------------------------------------------------------------
# parameters.csv — every documented request/response parameter
# --------------------------------------------------------------------------
PARAM_START = re.compile(r"<!--\s*parameter start(?:\s*\(props:\s*([^)]*)\))?\s*-->")
PARAM_END = "<!-- parameter end -->"
# The reference writes a cardinality limit in several shapes:
#   "Max character limit: 5000"   "Max: 12 bubbles"
#   "Max objects: 4"              "Max columns: 10"
# It also writes limits that are NOT about character or item count and must
# never be picked up here:
#   "Max file size: 10 MB"        "Max width: 1024px"
# so the qualifier between "Max" and the colon is an explicit whitelist.
LIMIT_RE = re.compile(
    r"Max(?:imum)?\s*(?:character\s+limit|objects?|columns?|items?)?\s*[:：]\s*"
    r"([0-9][0-9,]*)\s*([A-Za-z]+)?",
    re.I,
)


def strip_md(s: str) -> str:
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)     # links -> text
    s = re.sub(r"[`*\\]", "", s)
    return one_line(s)


ONE_OF_RE = re.compile(r"One of[:：](.*)$", re.S)
BACKTICKED_RE = re.compile(r"`([A-Za-z0-9_][A-Za-z0-9_\-]*)`")
DEFAULT_RE = re.compile(
    r"(?:The default value is|Defaults? (?:to|is)|Default)\s*[:：]?\s*`([^`]+)`", re.I)


def prose_enum(desc: str) -> list[str]:
    """Pull allowed values out of a written "One of: - `a` - `b`" list.

    Many enums (imageAspectRatio, imageSize, ...) are documented only in prose;
    the OpenAPI spec declares them as plain strings, so without this the
    dataset would say "string" and nothing else.
    """
    m = ONE_OF_RE.search(desc or "")
    if not m:
        return []
    # the description arrives as one joined line, so cut at the first phrase
    # that is clearly no longer part of the value list
    tail = re.split(r"Applies to all columns|The default value is|Default[:：]",
                    m.group(1))[0]
    values, seen = [], set()
    for item in re.split(r"\s+-\s+", tail):
        hit = BACKTICKED_RE.search(item)
        if not hit:
            continue
        val = hit.group(1)
        if val not in seen:
            seen.add(val)
            values.append(val)
    return values if len(values) > 1 else []


def prose_default(desc: str) -> str:
    m = DEFAULT_RE.search(desc or "")
    if not m:
        return ""
    val = m.group(1).strip()
    return val if len(val) <= 40 else ""


def build_parameters() -> list[dict]:
    rows = []
    for fname, (api, base) in REF_FILES.items():
        p = REF / fname
        if not p.exists():
            continue
        lines = p.read_text(encoding="utf-8").splitlines()
        fenced = fence_mask(lines)
        h2 = h3 = h4 = h5 = ""
        i = 0
        while i < len(lines):
            ln = lines[i]
            if fenced[i]:
                i += 1
                continue
            hm = HEAD_RE.match(ln)
            if hm:
                lvl, title = len(hm.group(1)), hm.group(2).strip()
                if lvl == 2:
                    h2, h3, h4, h5 = title, "", "", ""
                elif lvl == 3:
                    h3, h4, h5 = title, "", ""
                elif lvl == 4:
                    h4, h5 = title, ""
                elif lvl == 5:
                    h5 = title
                i += 1
                continue
            m = PARAM_START.search(ln)
            if not m:
                i += 1
                continue
            props = (m.group(1) or "").strip()
            body = []
            i += 1
            depth = 1
            while i < len(lines):
                if PARAM_START.search(lines[i]):
                    depth += 1
                elif lines[i].strip() == PARAM_END:
                    depth -= 1
                    if depth == 0:
                        break
                body.append(lines[i])
                i += 1
            i += 1

            content = [b for b in body
                       if b.strip() and not b.strip().startswith(("<!--", "```"))]
            if not content:
                continue
            name = strip_md(content[0])
            vtype = strip_md(content[1]) if len(content) > 1 else ""
            desc_lines = content[2:] if len(content) > 1 else []
            desc = strip_md(" ".join(desc_lines))[:600]
            lm = LIMIT_RE.search(" ".join(content))
            raw_desc = " ".join(desc_lines)
            rows.append({
                "api": api,
                "section": h2,
                "endpoint": h3,
                "block": h4,
                "subblock": h5,
                "enum_doc": "|".join(prose_enum(raw_desc)),
                "default": prose_default(raw_desc),
                "parameter": name,
                "value_type": vtype,
                "required": "true" if props.lower().startswith("required") else
                            ("false" if props else ""),
                "props": props,
                "max": (lm.group(1) + (" " + lm.group(2) if lm.group(2) else "")) if lm else "",
                "description": desc,
                "doc_url": base + "#" + anchor(h3 or h2),
            })
    return rows


# --------------------------------------------------------------------------
# error-codes.csv — status codes, error messages and per-endpoint error tables
# --------------------------------------------------------------------------
def md_tables(lines: list[str], start: int) -> tuple[list[list[str]], int]:
    """Read the first markdown table appearing at/after `start`."""
    i = start
    while i < len(lines) and not lines[i].strip().startswith("|"):
        if lines[i].strip().startswith("#"):
            return [], i
        i += 1
    rows = []
    while i < len(lines) and lines[i].strip().startswith("|"):
        cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
        if not all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
            rows.append(cells)
        i += 1
    return rows, i


def build_errors() -> list[dict]:
    rows = []
    for fname, (api, base) in REF_FILES.items():
        p = REF / fname
        if not p.exists():
            continue
        lines = p.read_text(encoding="utf-8").splitlines()
        h2 = h3 = ""
        i = 0
        while i < len(lines):
            hm = HEAD_RE.match(lines[i])
            if not hm:
                i += 1
                continue
            lvl, title = len(hm.group(1)), hm.group(2).strip()
            if lvl == 2:
                h2, h3 = title, ""
            elif lvl == 3:
                h3 = title
            low = title.lower()
            kind = ""
            if low.startswith("status code"):
                kind = "status-code"
            elif low.startswith("error message"):
                kind = "error-message"
            elif low.startswith("error response"):
                kind = "endpoint-error"
            if kind:
                table, nxt = md_tables(lines, i + 1)
                for cells in table[1:] if table else []:
                    if len(cells) < 2:
                        continue
                    rows.append({
                        "api": api,
                        "kind": kind,
                        "scope": h3 if kind == "endpoint-error" else (h2 or "Common specifications"),
                        "code_or_message": strip_md(cells[0]),
                        "description": strip_md(cells[1])[:600],
                        "doc_url": base + "#" + anchor(h3 or h2 or title),
                    })
                i = nxt
                continue
            i += 1
    # dedupe
    seen, out = set(), []
    for r in rows:
        k = (r["api"], r["kind"], r["scope"], r["code_or_message"])
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


# --------------------------------------------------------------------------
# limits.csv — numeric constraints straight out of the OpenAPI specs
# --------------------------------------------------------------------------
CONSTRAINTS = ("maxLength", "minLength", "maxItems", "minItems", "maximum", "minimum")


def build_limits(specs) -> list[dict]:
    rows = []
    for fname, doc in specs.items():
        schemas = (doc.get("components") or {}).get("schemas") or {}

        def walk(schema_name, node, path=""):
            if not isinstance(node, dict):
                return
            found = {k: node[k] for k in CONSTRAINTS if k in node}
            if found:
                for k, v in found.items():
                    rows.append({
                        "spec": fname, "schema": schema_name,
                        "field": (schema_name + path),
                        "constraint": k, "value": v,
                        "description": one_line(node.get("description", "")),
                    })
            for pname, sub in (node.get("properties") or {}).items():
                walk(schema_name, sub, path + "." + pname)
            for sub in node.get("allOf") or []:
                walk(schema_name, sub, path)
            if "items" in node:
                walk(schema_name, node["items"], path + "[]")

        for name, sch in schemas.items():
            walk(name, sch)
    # collapse: one row per (field, constraint)
    seen, out = set(), []
    for r in rows:
        k = (r["field"], r["constraint"])
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return sorted(out, key=lambda r: (r["spec"], r["field"], r["constraint"]))


# --------------------------------------------------------------------------
# liff-api.csv  (from the scraped LIFF API reference)
# --------------------------------------------------------------------------
def build_liff_api() -> list[dict]:
    p = REF / "liff.md"
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").splitlines()
    rows, cur, section, sub = [], None, "", ""
    buf: list[str] = []

    def flush():
        nonlocal cur
        if cur:
            cur["description"] = one_line(" ".join(cur["_desc"])[:400])
            cur.pop("_desc", None)
            rows.append(cur)
        cur = None

    for ln in lines:
        hm = HEAD_RE.match(ln)
        if hm:
            level, title = len(hm.group(1)), hm.group(2).strip()
            if level <= 3:
                flush()
                sub = ""
                if level == 2:
                    section = title
                if level == 3 and (title.startswith("liff.") or title.startswith("`liff.")):
                    name = title.strip("`")
                    cur = {
                        "name": name,
                        "kind": "method" if name.endswith(")") else "property",
                        "category": section,
                        "syntax": "",
                        "returns": "",
                        "description": "",
                        "_desc": [],
                        "doc_url": "https://developers.line.biz/en/reference/liff/#" + anchor(name),
                    }
            else:
                sub = title.lower()
            continue
        if cur is None:
            continue
        s = ln.strip()
        if not s or s.startswith(("<!--", "```", "|", "![")):
            continue
        if sub.startswith("syntax") and not cur["syntax"]:
            cur["syntax"] = one_line(s)
        elif sub.startswith("return") and not cur["returns"]:
            cur["returns"] = one_line(s)
        elif not sub and len(cur["_desc"]) < 4:
            cur["_desc"].append(s)
    flush()
    return rows


# --------------------------------------------------------------------------
# emoji.csv (LINE emoji product IDs)
# --------------------------------------------------------------------------
def build_emoji() -> list[dict]:
    """LINE emoji: product ID -> available emoji IDs."""
    p = DOCS / "messaging-api" / "emoji-list.md"
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8")
    rows = []
    blocks = re.split(r"\*\*Product ID:\*\*", text)[1:]
    for blk in blocks:
        m = re.match(r"\s*\[`([0-9a-f]{16,})`", blk)
        if not m:
            continue
        ids = re.findall(r"\[`(\d{3,4})`", blk)
        rows.append({
            "product_id": m.group(1),
            "emoji_id_from": ids[0] if ids else "",
            "emoji_id_to": ids[-1] if ids else "",
            "count": len(ids),
            "emoji_ids": ",".join(ids),
        })
    return rows


def build_stickers() -> list[dict]:
    """Sendable LINE stickers: package ID, title, sticker IDs."""
    p = DOCS / "messaging-api" / "sticker-list.md"
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8")
    rows = []
    blocks = re.split(r"\*\*Package ID:\*\*", text)[1:]
    for blk in blocks:
        m = re.match(r"\s*\[`(\d+)`", blk)
        if not m:
            continue
        tm = re.search(r"Title:\s*\[en\]\s*\*\*(.+?)\*\*", blk)
        ids = re.findall(r"\[`(\d{3,})`", blk)
        ids = [i for i in ids if i != m.group(1)]
        rows.append({
            "package_id": m.group(1),
            "title_en": tm.group(1).strip() if tm else "",
            "sticker_id_from": ids[0] if ids else "",
            "sticker_id_to": ids[-1] if ids else "",
            "count": len(ids),
            "sticker_ids": ",".join(ids),
        })
    return rows


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main() -> int:
    if not SPECS.exists() or not RAW.exists():
        sys.exit("Missing .docs-cache/ — run: python tools/fetch_sources.py")

    specs = load_specs()
    msg = (specs["messaging-api.yml"]["components"]["schemas"])
    print("Generating line-api/data/ ...")

    write_csv("endpoints.csv",
              ["api", "category", "title", "method", "host", "path", "query_params",
               "auth", "rate_limit", "operation_id", "spec", "description", "doc_url"],
              build_endpoints(specs))

    write_csv("webhook-properties.csv", SCHEMA_FIELDS,
              build_webhook_properties(specs))

    write_csv("webhook-events.csv",
              ["event", "schema", "properties", "required", "description", "doc_url"],
              build_webhook_events(specs))

    params = build_parameters()

    write_csv("message-objects.csv", SCHEMA_FIELDS,
              merge_from_docs(
              flatten_variants(msg, "Message", "message")
              + flatten_variants(msg, "Template", "template")
              + flatten_variants(msg, "ImagemapAction", "imagemap-action")
              + flatten_named(msg, ["Emoji", "Sender", "QuickReply", "QuickReplyItem",
                                    "ImagemapArea", "ImagemapVideo", "ImagemapExternalLink",
                                    "ImagemapBaseSize", "Template", "ButtonsTemplate",
                                    "ConfirmTemplate", "CarouselTemplate", "CarouselColumn",
                                    "ImageCarouselTemplate", "ImageCarouselColumn"], "message-part",
                              "https://developers.line.biz/en/reference/messaging-api/#message-objects"),
              params))

    write_csv("flex-components.csv", SCHEMA_FIELDS,
              merge_from_docs(
              flatten_variants(msg, "FlexComponent", "flex-component",
                               FLEX_DOC)
              + flatten_variants(msg, "FlexContainer", "flex-container",
                                 FLEX_DOC)
              + flatten_variants(msg, "FlexBoxBackground", "flex-background",
                                 "https://developers.line.biz/en/reference/messaging-api/#box")
              + flatten_named(msg, ["FlexBubbleStyles", "FlexBlockStyle"], "flex-style",
                              "https://developers.line.biz/en/reference/messaging-api/#bubble-style"),
              params))

    write_csv("actions.csv", SCHEMA_FIELDS,
              merge_from_docs(
                  flatten_variants(msg, "Action", "action", FLEX_DOC), params))

    write_csv("richmenu.csv", SCHEMA_FIELDS,
              merge_from_docs(
              flatten_named(msg, ["RichMenuRequest", "RichMenuResponse", "RichMenuArea",
                                  "RichMenuBounds", "RichMenuSize", "RichMenuBatchRequest",
                                  "RichMenuAliasResponse"], "richmenu",
                              "https://developers.line.biz/en/reference/messaging-api/#rich-menu-object"),
              params))

    write_csv("parameters.csv",
              ["api", "section", "endpoint", "block", "subblock", "parameter",
               "value_type", "required", "props", "max", "enum_doc", "default",
               "description", "doc_url"],
              params)

    write_csv("error-codes.csv",
              ["api", "kind", "scope", "code_or_message", "description", "doc_url"],
              build_errors())

    write_csv("limits.csv",
              ["spec", "schema", "field", "constraint", "value", "description"],
              build_limits(specs))

    write_csv("liff-api.csv",
              ["name", "kind", "category", "syntax", "returns", "description", "doc_url"],
              build_liff_api())

    write_csv("emoji.csv",
              ["product_id", "emoji_id_from", "emoji_id_to", "count", "emoji_ids"],
              build_emoji())

    write_csv("stickers.csv",
              ["package_id", "title_en", "sticker_id_from", "sticker_id_to", "count", "sticker_ids"],
              build_stickers())

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
