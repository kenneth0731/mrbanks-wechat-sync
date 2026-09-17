#!/bin/zsh
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_SRC="$DIR/com.caozhongyuan.mrbanks-wechat-sync.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.caozhongyuan.mrbanks-wechat-sync.plist"
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
cp "$PLIST_SRC" "$PLIST_DST"
launchctl bootout "gui/$(id -u)/com.caozhongyuan.mrbanks-wechat-sync" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_DST"
launchctl enable "gui/$(id -u)/com.caozhongyuan.mrbanks-wechat-sync"
launchctl kickstart -k "gui/$(id -u)/com.caozhongyuan.mrbanks-wechat-sync"
echo "已安装并启动: com.caozhongyuan.mrbanks-wechat-sync"
echo "日志: $HOME/Library/Logs/mrbanks-wechat-sync.log"
