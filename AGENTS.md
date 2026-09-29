# 本库任务：微信通知（两个独立任务）

本仓库承载**微信侧通知**相关工作，不是 OKX / 其它交易所的通用工作区。

## 任务 A：Mr Banks 频道 → 微信

路径：仓库根目录（`sync.py`）。

把 Telegram 公开频道 [@MrBanksFreeChannel](https://t.me/s/MrBanksFreeChannel) 里、包含指定文案的新消息，推送到微信。

- 匹配文案：`Use welcome code banks for weekly airdrops and bonuses`
- 推送通道：PushPlus → 微信
- 云端兜底：GitHub Actions **微信提醒 · Sync Mr Banks to WeChat**（约每 5 分钟）
- 本机可选：`sync.py` + `launchd`（`install.sh`）

## 任务 B：Stake 指数异动 & 推荐单 → 微信

路径：[`stake-alert/`](./stake-alert/)。

接通 Stake API，追踪足球指数异动，生成推荐单并推微信（PushPlus 等）。

- 本机定时：`launchd` 每天 11:00 / 16:30 / 21:00 / 23:30
- 入口：`odds_tracker.py`、`stake.py`
- 实现原先在 Mac `~/Projects/stake-alert`；用 `stake-alert/import-from-mac.sh` 导入进本目录
- 说明见 [`stake-alert/README.md`](./stake-alert/README.md)

在 Cursor Agents 里如果搜不到会话名，以**本仓库 + 上表**为准。

## 任务入口

| 任务 | 入口 |
| --- | --- |
| A 频道同步 | Actions → **微信提醒 · Sync Mr Banks to WeChat**；根目录 `README.md` |
| B Stake 异动/推荐单 | `stake-alert/`；本机 `com.stake.odds-tracker` |
| Agent 范围 | 本文件 |

## 明确不在范围内

- OKX / Bybit / Kraken 等交易所交易、API、策略、密钥
- 其它加密货币交易机器人或无关 MCP 配置
- 把本仓库当成通用多项目挂靠环境

以上请放到**独立仓库**和**独立 Cloud Agent Environment**。

## 给 Agent 的约束

1. 任务 A 只改「频道检测 → 匹配 → 微信推送 → 去重状态」。
2. 任务 B 只改 `stake-alert/` 内 Stake 指数 / 推荐单 / 通知相关文件；不要混进根目录 `sync.py`。
3. 不要提交 `config.json`、token、`odds_snapshots/`、`~/football-odds-db` 数据。
4. 密钥只用 GitHub Secrets / 本地配置，不要写入仓库正文。
