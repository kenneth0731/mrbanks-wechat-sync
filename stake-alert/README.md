# 任务 B：Stake 指数异动 & 推荐单 → 微信

本目录是本仓库里的**第二个微信通知任务**，与根目录的 Mr Banks 频道同步相互独立。

## 做什么

1. 接通 Stake API，监控体育盘指数  
2. 对比快照，发现**指数异动**  
3. 生成**推荐单**，经 PushPlus / 企业微信等通道推到手机（含微信）

定时：本机 `launchd` 每天 **11:00 / 16:30 / 21:00 / 23:30** 跑 `odds_tracker.py`。

## 源码

已从 Mac `~/Projects/stake-alert` 导入（见 `SOURCE.md`）。  
若本机还有更新，可再跑：`./stake-alert/import-from-mac.sh`。

## 本机命令

```bash
cd stake-alert
python3 stake.py --ping            # 验证 Stake 密钥
python3 stake.py --test-notify     # 测通知（含微信 PushPlus）
python3 odds_tracker.py            # 抓一次指数快照
python3 odds_tracker.py --picks    # 立刻推推荐单
./install-odds-tracker.sh          # 安装每天四次的定时任务
```

密钥放本地 `config.json`（已 gitignore），或环境变量 `STAKE_API_TOKEN`。  
历史核对依赖本机 `~/football-odds-db/`（不进本仓库）。

## 与任务 A 的边界

| | 任务 A（根目录） | 任务 B（本目录） |
| --- | --- | --- |
| 来源 | Telegram MrBanksFreeChannel | Stake 指数 / 推荐单 |
| 入口脚本 | `../sync.py` | `stake.py` / `odds_tracker.py` |
| 定时 | GitHub Actions ≈5 分钟 | 本机 launchd 每天 4 次 |
| 微信通道 | PushPlus | PushPlus（及企业微信等） |

不要把 OKX / 其它交易所交易代码放进本目录。
