# 任务 B：Stake 指数异动 & 推荐单 → 微信

本目录是本仓库里的**第二个微信通知任务**，与根目录的 Mr Banks 频道同步相互独立。

## 做什么

1. 接通 Stake API，监控体育盘指数  
2. 对比快照，发现**指数异动**  
3. 生成**推荐单**，经 PushPlus / 企业微信等通道推到手机（含微信）

定时：本机 `launchd` 每天 **11:00 / 16:30 / 21:00 / 23:30** 跑 `odds_tracker.py`。

## 源码从哪来

实现原先在 Mac：`~/Projects/stake-alert`。  
曾声称推到私有仓 `kenneth0731/Stake`，当前账号下**不可见 / 已失效**。  
云端 Agent 读不到 Mac 磁盘，因此 `.py` 需在本机导入一次：

```bash
# 在 Mac 上、本仓库根目录执行
./stake-alert/import-from-mac.sh
```

导入后应出现：`stake.py`、`odds_tracker.py`、`pick_verify.py`、`config.example.json`、plist 与安装脚本。

## 本机命令（导入后）

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
