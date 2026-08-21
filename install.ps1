# 舊入口，保留相容性。實際工作交給支援 8 個平台的安裝器。
#   python tools/install-skill.py --list
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
python (Join-Path $here 'tools/install-skill.py') claude-code --global @args
