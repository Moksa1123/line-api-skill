#!/usr/bin/env bash
# 把 line-api 技能安裝到常見 AI 助理的 skill 目錄
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$HERE/line-api"

TARGET="${1:-$HOME/.claude/skills}"
DEST="$TARGET/line-api"

[ -d "$SRC" ] || { echo "找不到 $SRC"; exit 1; }
mkdir -p "$TARGET"
rm -rf "$DEST"
cp -r "$SRC" "$DEST"
find "$DEST" -name '__pycache__' -type d -prune -exec rm -rf {} +

echo "已安裝到 $DEST"
echo "驗證：python \"$DEST/scripts/test_line.py\""
