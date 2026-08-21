#!/usr/bin/env bash
# 舊入口，保留相容性。實際工作交給支援 8 個平台的安裝器。
#   python tools/install-skill.py --list
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python "$HERE/tools/install-skill.py" claude-code --global "$@"
