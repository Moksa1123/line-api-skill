# 把 line-api 技能安裝到 AI 助理的 skill 目錄（Windows）
param([string]$Target = "$env:USERPROFILE\.claude\skills")

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$src  = Join-Path $here 'line-api'
$dest = Join-Path $Target 'line-api'

if (-not (Test-Path $src)) { throw "找不到 $src" }
New-Item -ItemType Directory -Force -Path $Target | Out-Null
if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
Copy-Item -Recurse $src $dest
Get-ChildItem -Path $dest -Filter '__pycache__' -Recurse -Directory |
    Remove-Item -Recurse -Force

Write-Output "已安裝到 $dest"
Write-Output "驗證：python `"$dest\scripts\test_line.py`""
