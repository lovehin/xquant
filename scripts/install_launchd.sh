#!/usr/bin/env bash
# 安装本机定时任务：每个交易日 16:30 抓数据（GitHub Actions 的本机备选方案）
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="$HOME/Library/LaunchAgents/com.xquant.update.plist"

if [ ! -x "$ROOT/.venv/bin/python" ]; then
  echo "缺少虚拟环境：$ROOT/.venv/bin/python，请先执行 uv venv --python 3.12 .venv"
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents"
sed "s|__ROOT__|$ROOT|g" "$ROOT/scripts/com.xquant.update.plist" > "$TARGET"

launchctl unload "$TARGET" 2>/dev/null || true
launchctl load "$TARGET"
echo "已安装定时任务：$TARGET"
echo "日志：$ROOT/data/update.log"
echo "手动触发：launchctl start com.xquant.update"
