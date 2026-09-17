# Mr Banks → 微信

检查 Telegram 公开频道 [@MrBanksFreeChannel](https://t.me/s/MrBanksFreeChannel)。  
只把包含 `Use welcome code banks for weekly airdrops and bonuses` 的新消息推到微信。

## 24 小时同步（GitHub Actions）

电脑关机或不挂 VPN 时，由 GitHub 海外机器每 5 分钟检查一次。

1. 仓库保持 **公开**（免费账号的定时任务才稳定）。
2. 在仓库 Settings → Secrets and variables → Actions 里添加 `PUSHPLUS_TOKEN`。
3. Actions 里打开 **Sync Mr Banks to WeChat**，可手动 Run workflow 测一次。

推送密钥只放 Secrets，不会进代码。已见消息记在 `ci-state` 分支，避免重复推送。

本机也在跑时，同一条新帖两边可能各推一次。只要云端兜底的话，可以停掉本机：

```bash
launchctl bootout "gui/$(id -u)/com.caozhongyuan.mrbanks-wechat-sync"
```

## 本机（可选，约 20 秒一次）

```bash
python3 sync.py --dry-run --once   # 只看匹配结果
python3 sync.py --test-wechat      # 测微信
./install.sh                       # 开机自启
```

`config.json` 里的 `pushplus_token` 用于本机推送；GitHub 用的是同名环境变量。
