#!/bin/zsh
set -euo pipefail
PLIST="$HOME/Library/LaunchAgents/com.stake.odds-tracker.plist"
launchctl unload "$PLIST" 2>/dev/null || true
rm -f "$PLIST"
echo "已卸载 Stake 指数定时追踪。"
