#!/usr/bin/env python3
"""
install-skill.py — 把 line-api 技能安裝到各家 AI 編碼助理。

    python tools/install-skill.py --list
    python tools/install-skill.py claude-code --global
    python tools/install-skill.py cursor                 # 裝到目前專案
    python tools/install-skill.py claude-ai --to ./build  # 產生可上傳的 zip

三種安裝型態，取決於平台怎麼載入技能：

  full        整個技能目錄照搬（SKILL.md + data + references + scripts + examples）
              —— Claude Code、Codex CLI、Gemini CLI、GitHub Copilot
  rule        平台只吃單一份規則檔，所以把 SKILL.md 與幾份關鍵 reference
              壓成一份 —— Cursor、Continue、Devin Desktop（原 Windsurf）
  zip-upload  打包成 zip 供網頁介面上傳 —— Claude.ai

升級時會先清掉上一版留下的檔案。裝完卻讓去年的錯資料留在今年的對的資料旁邊，
比不裝還糟。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO / "line-api"
PLATFORMS_DIR = REPO / "assets" / "templates" / "platforms"
SKILL_NAME = "line-api"

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


# --------------------------------------------------------------------------
def load_platform(name: str) -> dict:
    path = PLATFORMS_DIR / f"{name}.json"
    if not path.exists():
        raise SystemExit(f"不認得的平台：{name}\n用 --list 看有哪些。")
    return json.loads(path.read_text(encoding="utf-8"))


def all_platforms() -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(PLATFORMS_DIR.glob("*.json"))]


def skill_frontmatter() -> dict:
    """讀 SKILL.md 現有的 frontmatter（不依賴 PyYAML，只認簡單的 key: value）。"""
    raw = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    if not raw.startswith("---"):
        return {}
    end = raw.find("\n---", 3)
    if end == -1:
        return {}
    out = {}
    for line in raw[3:end].splitlines():
        if ":" in line and not line.startswith(" "):
            k, _, v = line.partition(":")
            out[k.strip()] = v.strip()
    return out


def skill_body() -> str:
    """SKILL.md 去掉 frontmatter 之後的內容。"""
    raw = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    if raw.startswith("---"):
        end = raw.find("\n---", 3)
        if end != -1:
            return raw[end + 4:].lstrip("\n")
    return raw


def render_frontmatter(keys, values: dict) -> str:
    if not keys:
        return ""
    lines = ["---"]
    for k in keys:
        v = values.get(k)
        if v is None:
            continue
        lines.append(f"{k}: {v}" if not isinstance(v, bool)
                     else f"{k}: {'true' if v else 'false'}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def embed(names: list[str]) -> str:
    """把幾份 reference 併進單一規則檔。缺檔是硬錯誤，不是略過。

    悄悄少一份平台設定明明要求的參考文件，正是這個技能存在要消滅的那種失敗：
    裝得起來、看起來正常，然後在你最需要的時候給你錯答案。
    """
    parts = []
    for name in names:
        path = SKILL_DIR / "references" / name
        if not path.exists():
            raise SystemExit(f"平台設定要求內嵌 references/{name}，但檔案不存在。")
        parts.append(f"\n\n---\n\n# 附錄：{name}\n\n" + path.read_text(encoding="utf-8"))
    return "".join(parts)


# --------------------------------------------------------------------------
COPY_DIRS = ("data", "references", "scripts", "examples")
COPY_FILES = ("SKILL.md", "EXAMPLES.md")


def install_full(dest: Path) -> list[str]:
    if dest.exists():
        shutil.rmtree(dest)          # 升級時先清掉舊版留下的東西
    dest.mkdir(parents=True, exist_ok=True)
    written = []
    for name in COPY_FILES:
        shutil.copy2(SKILL_DIR / name, dest / name)
        written.append(name)
    for folder in COPY_DIRS:
        src = SKILL_DIR / folder
        if not src.exists():
            continue
        shutil.copytree(src, dest / folder,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        written.append(folder + "/")
    return written


def build_rule(cfg: dict) -> str:
    fm_keys = cfg.get("frontmatter")
    meta = skill_frontmatter()
    values = {
        "name": SKILL_NAME,
        "description": meta.get("description", ""),
        "license": "MIT",
        "author": "Moksa",
        "version": meta.get("version", "1.0.0"),
        "alwaysApply": "false",
        "globs": '["**/*"]',
    }
    body = skill_body() + embed(cfg.get("embedReferences") or [])
    return render_frontmatter(fm_keys, values) + body


def install_rule(cfg: dict, dest_dir: Path, filename: str) -> list[str]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / filename
    target.write_text(build_rule(cfg), encoding="utf-8")
    return [str(target.name)]


def install_zip(dest_dir: Path, zip_name: str) -> list[str]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / zip_name
    if target.exists():
        target.unlink()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for name in COPY_FILES:
            z.write(SKILL_DIR / name, f"{SKILL_NAME}/{name}")
        for folder in COPY_DIRS:
            src = SKILL_DIR / folder
            if not src.exists():
                continue
            for f in sorted(src.rglob("*")):
                if f.is_file() and "__pycache__" not in f.parts:
                    z.write(f, f"{SKILL_NAME}/{f.relative_to(SKILL_DIR).as_posix()}")
    return [target.name]


# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="把 line-api 安裝到各家 AI 助理")
    ap.add_argument("platform", nargs="?", help="平台代號，見 --list")
    ap.add_argument("--global", dest="is_global", action="store_true",
                    help="裝到使用者家目錄（不是目前專案）")
    ap.add_argument("--to", help="指定安裝位置，覆寫預設路徑")
    ap.add_argument("--list", action="store_true", help="列出支援的平台")
    args = ap.parse_args()

    if args.list or not args.platform:
        print(f"{SKILL_NAME} 支援 {len(all_platforms())} 個平台：\n")
        print(f"  {'代號':<14}{'名稱':<32}{'安裝型態':<12}驗證日期")
        for cfg in all_platforms():
            print(f"  {cfg['platform']:<14}{cfg['displayName']:<32}"
                  f"{cfg['installType']:<12}{cfg.get('verifiedAsOf', '-')}")
        print("\n  python tools/install-skill.py claude-code --global")
        return 0

    cfg = load_platform(args.platform)
    fs = cfg["folderStructure"]
    kind = cfg["installType"]

    if args.to:
        root = Path(os.path.expanduser(args.to))
    elif kind == "zip-upload":
        root = REPO / "build"
    elif args.is_global:
        if not fs.get("globalRoot"):
            raise SystemExit(f"{cfg['displayName']} 沒有全域安裝路徑，請省略 --global。")
        root = Path(os.path.expanduser(fs["globalRoot"]))
    else:
        root = Path.cwd() / fs["projectRoot"]

    if kind == "full":
        dest = root / fs["skillPath"] if not args.to else root
        written = install_full(dest)
    elif kind == "rule":
        dest = root / fs["skillPath"] if not args.to else root
        written = install_rule(cfg, dest, fs["filename"])
    elif kind == "zip-upload":
        dest = root
        written = install_zip(dest, fs["skillPath"])
    else:
        raise SystemExit(f"不支援的安裝型態：{kind}")

    print(f"已安裝 {SKILL_NAME} → {cfg['displayName']}")
    print(f"  位置：{dest}")
    print(f"  內容：{', '.join(written)}")
    if cfg.get("loaderBehaviour"):
        print(f"  載入：{cfg['loaderBehaviour']}")
    for step in cfg.get("uploadSteps") or []:
        print(f"  {step}")
    if cfg.get("fallback"):
        print(f"  備用路徑：{cfg['fallback'].get('note', '')}")
    if kind == "full":
        print(f"\n  驗證：python \"{dest / 'scripts' / 'test_line.py'}\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
