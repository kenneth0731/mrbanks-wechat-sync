# 微信通知（本仓库）

本仓库有两个**相互独立**的微信通知任务：

| 任务 | 目录 | 说明 |
| --- | --- | --- |
| **A. Mr Banks 频道提醒** | 根目录 | Telegram 匹配帖 → 微信 |
| **B. Stake 指数异动 / 推荐单** | [`stake-alert/`](./stake-alert/) | Stake 异动与推荐单 → 微信 |

Agent 范围见 [`AGENTS.md`](./AGENTS.md)。

---

# 任务 A：微信提醒（Mr Banks → 微信）

检查 Telegram 公开频道 [@MrBanksFreeChannel](https://t.me/s/MrBanksFreeChannel)。  
只把包含 `Use welcome code banks for weekly airdrops and bonuses` 的新消息推到微信。

## 任务入口

| 入口 | 说明 |
| --- | --- |
| 本仓库 | [kenneth0731/mrbanks-wechat-sync](https://github.com/kenneth0731/mrbanks-wechat-sync) |
| GitHub Actions | [微信提醒 · Sync Mr Banks to WeChat](https://github.com/kenneth0731/mrbanks-wechat-sync/actions/workflows/sync.yml) |
| Stake 任务 B | [`stake-alert/README.md`](./stake-alert/README.md) |

## 24 小时同步（GitHub Actions）

电脑关机或不挂 VPN 时，由 GitHub 海外机器约每 5 分钟检查一次。

1. 仓库保持 **公开**（免费账号的定时任务才稳定）。
2. 在仓库 Settings → Secrets and variables → Actions 里添加 `PUSHPLUS_TOKEN`。
3. Actions 里打开 **微信提醒 · Sync Mr Banks to WeChat**，可手动 Run workflow 测一次。

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

---

# 任务 B：Stake 指数异动 & 推荐单

见 [`stake-alert/README.md`](./stake-alert/README.md)。  
在 Mac 上执行一次 `./stake-alert/import-from-mac.sh`，把 `~/Projects/stake-alert` 的实现导入本目录后再跑定时任务。
