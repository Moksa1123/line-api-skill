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
EP_INLINE = re.compile(r"^Endpoint:\s*`(" + "|".join(METHODS) + r")`\s*`(https?://[^`]+)`")
EP_BARE = re.compile(r"^`(" + "|".join(METHODS) + r")\s+(https?://[^`]+)`\s*$")


def parse_reference(path: Path, api: str, base_url: str) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    out, cur, section, sub, want_http = [], None, "", "", False

    def flush():
        nonlocal cur
        if cur and cur["method"]:
            out.append(cur)
        cur = None

    for ln in lines:
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
                 "enum", "max_length", "description", "doc_url"]


# Flex limits that live only in the written reference and cannot be joined by
# doc anchor (LINE documents every flex component under the single
# "#flex-message" anchor). Each entry was read from
# reference/messaging-api.md > Message objects > Flex Message.
FLEX_DOCUMENTED_MAXIMA = {
    ("FlexMessage", "altText"): "1500",     # Max character limit: 1500
    ("FlexCarousel", "contents"): "12",     # Max: 12 bubbles
    ("FlexImage", "url"): "2000",           # Max character limit: 2000
    ("FlexVideo", "url"): "2000",
    ("FlexVideo", "previewUrl"): "2000",
    ("FlexIcon", "url"): "2000",
}


def merge_documented_maxima(schema_rows: list[dict], param_rows: list[dict]) -> list[dict]:
    """Fill max_length from the reference prose.

    The OpenAPI specs omit most size limits ("Max character limit: 5000" for a
    text message, "Max: 12 bubbles" for a carousel) — those live only in the
    written reference, which parameters.csv already captures. Both sides carry
    the same doc_url anchor, so (doc_url, property) joins them exactly.
    """
    index: dict[tuple[str, str], str] = {}
    for r in param_rows:
        raw = (r.get("max") or "").split()
        if not raw or not raw[0].isdigit():
            continue
        url = r["doc_url"]
        index.setdefault((url, r["parameter"]), raw[0])
        # the flex components are documented under a bare anchor (#carousel)
        # but referenced under the disambiguated one (#f-carousel)
        base, _, frag = url.partition("#")
        for tag, alias in FLEX_ANCHORS.items():
            if frag == tag and alias != tag:
                index.setdefault((base + "#" + alias, r["parameter"]), raw[0])
    filled = 0
    for r in schema_rows:
        if r.get("max_length"):
            continue
        vtype = r.get("value_type", "")
        # only strings (character limit) and arrays (item limit) can carry a
        # documented maximum — never a nested object such as FlexMessage.contents
        joinable = vtype == "string" or vtype.startswith("array<")
        hit = FLEX_DOCUMENTED_MAXIMA.get((r.get("schema", ""), r.get("property", "")))
        if not hit and joinable:
            hit = index.get((r.get("doc_url", ""), r.get("property", "")))
        if hit:
            r["max_length"] = hit
            filled += 1
    if filled:
        print(f"  (merged {filled} documented maxima)")
    return schema_rows


# --------------------------------------------------------------------------
# webhook-events.csv
# --------------------------------------------------------------------------
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
LIMIT_RE = re.compile(
    r"Max(?:imum)?(?: character)?(?: limit)?\s*[:：]?\s*([0-9][0-9,]*)\s*(characters?|bytes?|KB|MB)?",
    re.I,
)


def strip_md(s: str) -> str:
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)     # links -> text
    s = re.sub(r"[`*\\]", "", s)
    return one_line(s)


def build_parameters() -> list[dict]:
    rows = []
    for fname, (api, base) in REF_FILES.items():
        p = REF / fname
        if not p.exists():
            continue
        lines = p.read_text(encoding="utf-8").splitlines()
        h2 = h3 = h4 = ""
        i = 0
        while i < len(lines):
            ln = lines[i]
            hm = HEAD_RE.match(ln)
            if hm:
                lvl, title = len(hm.group(1)), hm.group(2).strip()
                if lvl == 2:
                    h2, h3, h4 = title, "", ""
                elif lvl == 3:
                    h3, h4 = title, ""
                elif lvl == 4:
                    h4 = title
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

            content = [b for b in body if b.strip() and not b.strip().startswith("<!--")]
            if not content:
                continue
            name = strip_md(content[0])
            vtype = strip_md(content[1]) if len(content) > 1 else ""
            desc_lines = content[2:] if len(content) > 1 else []
            desc = strip_md(" ".join(desc_lines))[:600]
            lm = LIMIT_RE.search(" ".join(content))
            rows.append({
                "api": api,
                "section": h2,
                "endpoint": h3,
                "block": h4,
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

    write_csv("webhook-events.csv",
              ["event", "schema", "properties", "required", "description", "doc_url"],
              build_webhook_events(specs))

    params = build_parameters()

    write_csv("message-objects.csv", SCHEMA_FIELDS,
              merge_documented_maxima(
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
              merge_documented_maxima(
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
              merge_documented_maxima(
                  flatten_variants(msg, "Action", "action", FLEX_DOC), params))

    write_csv("richmenu.csv", SCHEMA_FIELDS,
              flatten_named(msg, ["RichMenuRequest", "RichMenuResponse", "RichMenuArea",
                                  "RichMenuBounds", "RichMenuSize", "RichMenuBatchRequest",
                                  "RichMenuAliasResponse"], "richmenu",
                              "https://developers.line.biz/en/reference/messaging-api/#rich-menu-object"))

    write_csv("parameters.csv",
              ["api", "section", "endpoint", "block", "parameter", "value_type",
               "required", "props", "max", "description", "doc_url"],
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
