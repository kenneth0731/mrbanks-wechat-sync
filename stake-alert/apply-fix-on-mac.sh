#!/bin/bash
# 在 Mac 上执行：把已推送的修复拉到本机，并同步到 launchd 实际运行的两个目录。
set -euo pipefail

BRANCH="${1:-cursor/fix-evening-picks-verify-371e}"
MRBANKS="${HOME}/Projects/mrbanks-wechat-sync"
STAKE="${HOME}/Projects/stake-alert"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "请在 Mac 上执行（当前不是 Darwin）。" >&2
  exit 1
fi

echo "==> 更新 $MRBANKS"
cd "$MRBANKS"
git fetch origin "$BRANCH"
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"

if [[ -d "$STAKE" ]]; then
  echo "==> 同步关键文件到 $STAKE（launchd 可能仍指向这里）"
  for f in odds_tracker.py pick_verify.py test_picks_fix.py; do
    if [[ -f "$MRBANKS/stake-alert/$f" ]]; then
      cp "$MRBANKS/stake-alert/$f" "$STAKE/$f"
      echo "copied $f"
    fi
  done
fi

echo "==> 语法检查"
python3 -m py_compile "$MRBANKS/stake-alert/odds_tracker.py" "$MRBANKS/stake-alert/pick_verify.py"
if [[ -f "$STAKE/odds_tracker.py" ]]; then
  python3 -m py_compile "$STAKE/odds_tracker.py" "$STAKE/pick_verify.py"
fi

echo "==> 当前 launchd 指向"
launchctl print "gui/$(id -u)/com.stake.odds-tracker" 2>/dev/null | grep -E 'program =|working directory|path =' || true
ls -la ~/Library/LaunchAgents/com.stake.odds-tracker.plist 2>/dev/null || true
if [[ -f ~/Library/LaunchAgents/com.stake.odds-tracker.plist ]]; then
  plutil -p ~/Library/LaunchAgents/com.stake.odds-tracker.plist | grep -E 'WorkingDirectory|ProgramArguments' -A2 || true
fi

echo
echo "完成。立刻重跑推荐单（择一）："
echo "  cd $MRBANKS/stake-alert && python3 odds_tracker.py"
echo "  # 或"
echo "  cd $STAKE && python3 odds_tracker.py"
echo
echo "若仍空单，查看 odds_snapshots/latest_picks.txt 里的诊断原因。"
