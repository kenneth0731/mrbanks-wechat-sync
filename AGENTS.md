# 本库任务：微信提醒

本仓库就是 **微信提醒** 任务本体，不是别的项目的挂靠环境。

## 职责（仅此一项）

把 Telegram 公开频道 [@MrBanksFreeChannel](https://t.me/s/MrBanksFreeChannel) 里、包含指定文案的新消息，推送到微信。

- 匹配文案：`Use welcome code banks for weekly airdrops and bonuses`
- 推送通道：PushPlus → 微信
- 云端兜底：GitHub Actions 工作流 **Sync Mr Banks to WeChat**（约每 5 分钟）
- 本机可选：`sync.py` + `launchd`（`install.sh`）

## 任务入口（怎么找）

| 入口 | 位置 |
| --- | --- |
| 仓库本身 | 本仓库 `mrbanks-wechat-sync` |
| 定时任务 | Actions → **Sync Mr Banks to WeChat** |
| 本机安装名 | `com.caozhongyuan.mrbanks-wechat-sync` |
| 说明文档 | `README.md` |

在 Cursor Agents / Automations 里如果搜不到「微信提醒」这个名字，以**本仓库**为准；任务身份写在这里，不依赖某个会话标题。

## 明确不在范围内

不要在本仓库加入或讨论：

- OKX / Bybit / Kraken 等交易所交易、API、策略、密钥
- 其它加密货币交易机器人或无关 MCP 配置
- 足球分析、邮件报告等其它业务

以上工作请放到**独立仓库**和**独立 Cloud Agent Environment**。

## 给 Agent 的约束

1. 只改与「频道检测 → 匹配 → 微信推送 → 去重状态」相关的代码与文档。
2. 不要把本仓库当作通用交易/多项目工作区。
3. 密钥只用 GitHub Secrets / 本地 `config.json`，不要写入仓库正文。
