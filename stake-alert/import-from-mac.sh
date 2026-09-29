#!/bin/bash
# 在 Mac 上运行：把 ~/Projects/stake-alert 的实现拷进本仓库 stake-alert/。
set -euo pipefail

DEST="$(cd "$(dirname "$0")" && pwd)"
SRC="${STAKE_ALERT_SRC:-$HOME/Projects/stake-alert}"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "请在 Mac 上执行本脚本（当前不是 Darwin）。" >&2
  exit 1
fi

if [[ ! -d "$SRC" ]]; then
  echo "找不到源目录: $SRC" >&2
  echo "可设置 STAKE_ALERT_SRC=/实际/路径 再试。" >&2
  exit 1
fi

copy_one() {
  local name="$1"
  if [[ -f "$SRC/$name" ]]; then
    cp "$SRC/$name" "$DEST/$name"
    echo "copied $name"
  else
    echo "missing (skip): $name" >&2
  fi
}

# 只拷安全文件；绝不带真实密钥与快照
copy_one stake.py
copy_one odds_tracker.py
copy_one pick_verify.py
copy_one config.example.json
copy_one start.sh
copy_one install-odds-tracker.sh
copy_one uninstall-odds-tracker.sh
copy_one com.stake.odds-tracker.plist
copy_one .gitignore

# 把 plist 里的旧工作目录改到本仓库目录（若仍指向旧路径）
if [[ -f "$DEST/com.stake.odds-tracker.plist" ]]; then
  if grep -q '/Projects/stake-alert' "$DEST/com.stake.odds-tracker.plist"; then
    sed -i '' "s|/Users/[^/]*/Projects/stake-alert|$DEST|g" "$DEST/com.stake.odds-tracker.plist"
    echo "rewrote plist WorkingDirectory → $DEST"
  fi
fi

chmod +x "$DEST"/start.sh "$DEST"/install-odds-tracker.sh 2>/dev/null || true
chmod +x "$DEST"/uninstall-odds-tracker.sh 2>/dev/null || true

echo
echo "完成。请检查后提交："
echo "  ls -la \"$DEST\""
echo "  python3 -m py_compile \"$DEST\"/stake.py \"$DEST\"/odds_tracker.py \"$DEST\"/pick_verify.py"
echo
echo "不要提交: config.json、odds_snapshots/、密钥。"
