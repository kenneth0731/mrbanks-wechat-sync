#!/bin/zsh
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p odds_snapshots
PLIST="$HOME/Library/LaunchAgents/com.stake.odds-tracker.plist"
cp -f com.stake.odds-tracker.plist "$PLIST"
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "已安装定时追踪：每天 11:00 / 16:30 / 21:00 / 23:30"
echo "请保持 Mac 唤醒，并让 Chrome 能打开 stake.com"
echo "手动跑一次：python3 odds_tracker.py"
echo "卸载：./uninstall-odds-tracker.sh"
