#!/usr/bin/env python3
"""Stake.com 投注平台 GraphQL 接入：余额、投注记录与新投注监控。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

GRAPHQL_PATH = "/_api/graphql"
DEFAULT_BASE_URL = "https://stake.com"
STAKE_TAB_HOSTS = ("stake.bet", "stake.games", "stake.mba", "stake.com")
STAKE_FALLBACK_URL = "https://stake.bet/zh"
ROOT = Path(__file__).resolve().parent
DEFAULT_STATE = ROOT / ".state.json"
DEFAULT_CONFIG = ROOT / "config.json"
TZ = ZoneInfo("Asia/Shanghai")

HEADERS_BASE = {
    "Content-Type": "application/json",
    "x-language": "zh",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

STATUS_CN = {
    "pending": "待结算",
    "active": "进行中",
    "won": "赢",
    "lost": "输",
    "cashout": "提前结算",
    "cancelled": "已取消",
    "settled": "已结算",
}

QUERY_USER = """
query UserBalances {
  user {
    id
    name
    balances {
      available { amount currency }
      vault { amount currency }
    }
  }
}
"""

QUERY_SPORT_BETS = """
query UserBetHistory($limit: Int, $offset: Int) {
  user {
    sportBetList(limit: $limit, offset: $offset) {
      id
      bet {
        ... on SportBet {
          id
          iid
          amount
          currency
          status
          payout
          payoutMultiplier
          potentialMultiplier
          createdAt
          outcomes {
            odds
            status
            fixtureName
            outcome { name }
            fixture {
              name
              tournament {
                name
                category { sport { name slug } }
              }
            }
          }
        }
      }
    }
  }
}
"""

QUERY_ACTIVE_SPORT_BETS = """
query ActiveSportBets {
  user {
    activeSportBets {
      id
      bet {
        ... on SportBet {
          id
          iid
          amount
          currency
          status
          payout
          payoutMultiplier
          potentialMultiplier
          createdAt
          outcomes {
            odds
            status
            fixtureName
            outcome { name }
            fixture { name }
          }
        }
      }
    }
  }
}
"""

QUERY_CASINO_BETS = """
query UserCasinoBets($limit: Int, $offset: Int) {
  user {
    casinoBetList(limit: $limit, offset: $offset) {
      id
      iid
      amount
      payout
      payoutMultiplier
      currency
      createdAt
      game { name slug }
    }
  }
}
"""

QUERY_HIGHROLLER_SPORT = """
query HighrollerSportBets($limit: Int) {
  highrollerSportBets(limit: $limit) {
    id
    bet {
      ... on SportBet {
        id
        iid
        amount
        currency
        status
        payout
        potentialMultiplier
        payoutMultiplier
        createdAt
        user { name }
        outcomes {
          odds
          fixtureName
          outcome { name }
          fixture {
            name
            tournament {
              name
              category { sport { name slug } }
            }
          }
        }
      }
    }
  }
}
"""

QUERY_HIGHROLLER_CASINO = """
query HighrollerCasinoBets($limit: Int) {
  highrollerCasinoBets(limit: $limit) {
    id
    bet {
      ... on CasinoBet {
        id
        iid
        amount
        payout
        payoutMultiplier
        currency
        createdAt
        user { name }
        game { name slug }
      }
    }
  }
}
"""


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def resolve_token(config: dict[str, Any]) -> str:
    env = (os.environ.get("STAKE_API_TOKEN") or "").strip()
    if env:
        return env
    return str(config.get("api_token") or "").strip()


def resolve_base_url(config: dict[str, Any], override: str = "") -> str:
    raw = (override or config.get("base_url") or DEFAULT_BASE_URL).strip()
    return raw.rstrip("/")


def resolve_proxy(config: dict[str, Any]) -> str:
    return (
        (os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or "")
        or str(config.get("proxy") or "")
    ).strip()


def resolve_transport(config: dict[str, Any]) -> str:
    raw = str(config.get("transport") or "auto").strip().lower()
    return raw if raw in {"auto", "direct", "chrome"} else "auto"


def parse_graphql_body(raw: str) -> dict[str, Any]:
    if raw.lstrip().startswith("<"):
        raise RuntimeError(_http_error_message(DEFAULT_BASE_URL, 0, raw))
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Stake 返回了非 JSON 内容: {raw[:180]}") from exc
    errors = body.get("errors") or []
    if errors:
        msg = errors[0].get("message") or str(errors[0])
        err_type = errors[0].get("errorType") or (errors[0].get("extensions") or {}).get("code")
        if err_type:
            msg = f"{err_type}: {msg}"
        raise RuntimeError(f"Stake GraphQL 错误: {msg}")
    if "data" not in body:
        raise RuntimeError(f"Stake 响应缺少 data: {body}")
    return body["data"]


_SHADOWROCKET_READY = False


def ensure_shadowrocket(wait: float = 2.5) -> bool:
    """打开 Shadowrocket 并发送 connect，避免新闻/API 因未开 VPN 超时。"""
    global _SHADOWROCKET_READY
    if _SHADOWROCKET_READY:
        return True
    app = Path("/Applications/Shadowrocket.app")
    if not app.exists():
        print("未找到 Shadowrocket.app，跳过自动开 VPN", file=sys.stderr)
        return False
    try:
        subprocess.run(["open", "-a", "Shadowrocket"], check=False, capture_output=True)
        time.sleep(0.8)
        subprocess.run(["open", "shadowrocket://connect"], check=False, capture_output=True)
        time.sleep(max(0.5, wait))
        _SHADOWROCKET_READY = True
        print("已打开 Shadowrocket 并连接")
        return True
    except OSError as exc:
        print(f"打开 Shadowrocket 失败: {exc}", file=sys.stderr)
        return False


def _osascript(script: str) -> str:
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "osascript 失败").strip()
        raise RuntimeError(f"无法控制 Google Chrome: {err}")
    return (result.stdout or "").strip()


def chrome_js(code: str) -> str:
    script = f'''
tell application "Google Chrome"
  if not running then error "Google Chrome 未运行"
  tell active tab of front window
    execute javascript {json.dumps(code)}
  end tell
end tell
'''
    return _osascript(script)


def _chrome_tab_host_rank(url: str) -> int:
    url = url.lower()
    for index, host in enumerate(STAKE_TAB_HOSTS):
        if host in url:
            return index
    return -1


def chrome_ensure_stake_tab() -> None:
    ensure_shadowrocket()
    listing = _osascript(
        '''
tell application "Google Chrome"
  if it is not running then
    launch
    delay 1.5
  end if
  activate
  set out to ""
  set wIndex to 0
  repeat with w in windows
    set wIndex to wIndex + 1
    set tabIndex to 0
    repeat with t in tabs of w
      set tabIndex to tabIndex + 1
      set out to out & wIndex & "\t" & tabIndex & "\t" & (URL of t) & linefeed
    end repeat
  end repeat
  return out
end tell
'''
    )
    chosen: tuple[int, int] | None = None
    chosen_rank = 99
    for line in listing.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        rank = _chrome_tab_host_rank(parts[2])
        if rank < 0 or rank >= chosen_rank:
            continue
        chosen = (int(parts[0]), int(parts[1]))
        chosen_rank = rank
    if chosen:
        w_index, t_index = chosen
        _osascript(
            f'''
tell application "Google Chrome"
  set w to window {w_index}
  set index of w to 1
  set active tab index of w to {t_index}
  activate
end tell
'''
        )
    else:
        _osascript(f'tell application "Google Chrome" to open location "{STAKE_FALLBACK_URL}"')
    for _ in range(25):
        try:
            info = chrome_js(
                "JSON.stringify({href: location.href, title: document.title, ready: document.readyState})"
            )
            data = json.loads(info) if info.startswith("{") else {}
        except Exception:
            time.sleep(0.6)
            continue
        href = str(data.get("href") or "")
        title = str(data.get("title") or "")
        if _chrome_tab_host_rank(href) >= 0 and "请稍候" not in title and "Just a moment" not in title and "__cf_chl" not in href:
            return
        # GraphQL can already work on stake.bet while CF interstitial is showing.
        if "stake.bet" in href or "stake.games" in href:
            return
        time.sleep(0.6)
    raise RuntimeError(
        "Google Chrome 仍卡在 Cloudflare 验证。请在 Chrome 里打开 https://stake.bet/zh 并完成验证后重试。"
    )


def chrome_graphql(
    query: str,
    variables: dict[str, Any] | None = None,
    token: str = "",
    operation: str | None = None,
) -> dict[str, Any]:
    chrome_ensure_stake_tab()
    payload: dict[str, Any] = {"query": query}
    if variables:
        payload["variables"] = variables
    if operation:
        payload["operationName"] = operation
    headers = {"content-type": "application/json"}
    if token:
        headers["x-access-token"] = token
    starter = f"""
window.__stakeResult = 'pending';
fetch('/_api/graphql', {{
  method: 'POST',
  headers: {json.dumps(headers)},
  credentials: 'include',
  body: {json.dumps(json.dumps(payload))}
}}).then(r => r.text()).then(t => window.__stakeResult = t)
  .catch(e => window.__stakeResult = 'ERR:' + String(e));
'started';
"""
    chrome_js(starter)
    raw = ""
    for _ in range(20):
        time.sleep(0.25)
        raw = chrome_js("String(window.__stakeResult || '')")
        if raw and raw not in {"pending", "started"}:
            break
    if not raw or raw in {"pending", "started"}:
        raise RuntimeError("Chrome 请求 Stake API 超时。")
    if raw.startswith("ERR:"):
        raise RuntimeError(f"Chrome 请求 Stake API 失败: {raw[4:]}")
    return parse_graphql_body(raw)


def graphql(
    base_url: str,
    query: str,
    variables: dict[str, Any] | None = None,
    token: str = "",
    operation: str | None = None,
    timeout: int = 20,
    proxy: str = "",
    transport: str = "auto",
) -> dict[str, Any]:
    if transport == "chrome":
        return chrome_graphql(query, variables, token, operation)

    endpoint = base_url.rstrip("/") + GRAPHQL_PATH
    headers = {
        **HEADERS_BASE,
        "Origin": base_url,
        "Referer": base_url + "/",
    }
    if token:
        headers["x-access-token"] = token

    payload: dict[str, Any] = {"query": query}
    if variables:
        payload["variables"] = variables
    if operation:
        payload["operationName"] = operation

    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        if proxy:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": proxy, "https": proxy})
            )
            resp_cm = opener.open(req, timeout=timeout)
        else:
            resp_cm = urllib.request.urlopen(req, timeout=timeout)
        with resp_cm as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        return parse_graphql_body(raw)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        direct_error = RuntimeError(_http_error_message(base_url, exc.code, body))
        if transport == "auto" and exc.code in {403, 451}:
            try:
                return chrome_graphql(query, variables, token, operation)
            except Exception as chrome_exc:  # noqa: BLE001
                raise RuntimeError(f"{direct_error}；Chrome 通道也失败: {chrome_exc}") from chrome_exc
        raise direct_error from exc
    except urllib.error.URLError as exc:
        url_error = RuntimeError(f"无法连接 {endpoint}: {exc.reason}")
        if transport == "auto":
            try:
                return chrome_graphql(query, variables, token, operation)
            except Exception as chrome_exc:  # noqa: BLE001
                raise RuntimeError(f"{url_error}；Chrome 通道也失败: {chrome_exc}") from chrome_exc
        raise url_error from exc


def _http_error_message(base_url: str, code: int, body: str) -> str:
    snippet = " ".join(body.split())[:180]
    if code == 451:
        return (
            f"Stake 在当前出口地区不可用 (HTTP 451，{base_url})。"
            "可把 config.json 里 base_url 改成镜像（如 https://stake.ac），"
            "或在能打开 Stake 的网络上运行。"
        )
    if code == 403:
        if "ip-bloc" in body.lower() or "ip block" in body.lower():
            return (
                f"当前出口 IP 被 Stake 屏蔽 (HTTP 403，{base_url})。"
                "中国大陆 IP 通常无法直连。请在能打开 Stake 的网络运行，"
                "或在 config.json 填写 proxy / 设置 HTTPS_PROXY。"
            )
        return (
            f"请求被 Cloudflare 拦截 (HTTP 403，{base_url})。"
            "通常是地区或风控限制，请更换 base_url、出口 IP，或配置 proxy。"
        )
    if code:
        return f"Stake HTTP {code} ({base_url}): {snippet}"
    return f"Stake 返回了网页而不是 API 数据 ({base_url}): {snippet}"


def unwrap_bet(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    bet = item.get("bet")
    if isinstance(bet, dict):
        return bet
    return item


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def format_amount(amount: Any, currency: Any) -> str:
    cur = str(currency or "?").upper()
    num = _num(amount)
    if num is None:
        return f"{amount} {cur}"
    if abs(num) >= 1:
        text = f"{num:.8f}".rstrip("0").rstrip(".")
    else:
        text = f"{num:.10f}".rstrip("0").rstrip(".")
    return f"{text} {cur}"


def sport_label(bet: dict[str, Any]) -> str:
    outcomes = bet.get("outcomes") or []
    if not outcomes:
        return "体育投注"
    first = outcomes[0] if isinstance(outcomes[0], dict) else {}
    fixture = first.get("fixtureName") or (first.get("fixture") or {}).get("name") or "?"
    pick = ((first.get("outcome") or {}).get("name")) or "?"
    odds = first.get("odds")
    sport = (
        ((first.get("fixture") or {}).get("tournament") or {})
        .get("category", {})
        .get("sport", {})
        .get("name")
    )
    bits = [str(fixture), f"选项 {pick}"]
    if odds is not None:
        bits.append(f"赔率 {odds}")
    if sport:
        bits.append(str(sport))
    if len(outcomes) > 1:
        bits.append(f"串关 x{len(outcomes)}")
    return " · ".join(bits)


def format_time(value: Any) -> str:
    if not value:
        return "未知时间"
    if isinstance(value, (int, float)):
        ts = value / 1000 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(ts, tz=TZ).strftime("%Y-%m-%d %H:%M:%S")
    text = str(value)
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(TZ)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return text


def format_sport_message(item: dict[str, Any], who: str) -> str:
    bet = unwrap_bet(item)
    status = str(bet.get("status") or "?")
    lines = [
        f"[{who}] 体育投注",
        f"时间: {format_time(bet.get('createdAt'))}",
        f"内容: {sport_label(bet)}",
        f"金额: {format_amount(bet.get('amount'), bet.get('currency'))}",
        f"状态: {STATUS_CN.get(status.lower(), status)}",
    ]
    if bet.get("payout") is not None:
        lines.append(f"派彩: {format_amount(bet.get('payout'), bet.get('currency'))}")
    if bet.get("payoutMultiplier") is not None:
        lines.append(f"倍数: {bet['payoutMultiplier']}")
    elif bet.get("potentialMultiplier") is not None:
        lines.append(f"潜在倍数: {bet['potentialMultiplier']}")
    return "\n".join(lines)


def format_casino_message(item: dict[str, Any], who: str) -> str:
    bet = unwrap_bet(item)
    game = bet.get("game") if isinstance(bet.get("game"), dict) else {}
    status = str(bet.get("status") or "")
    lines = [
        f"[{who}] 娱乐城投注",
        f"时间: {format_time(bet.get('createdAt'))}",
        f"游戏: {game.get('name') or game.get('slug') or '?'}",
        f"金额: {format_amount(bet.get('amount'), bet.get('currency'))}",
    ]
    if status:
        lines.append(f"状态: {STATUS_CN.get(status.lower(), status)}")
    if bet.get("payoutMultiplier") is not None:
        lines.append(f"倍数: {bet['payoutMultiplier']}")
    if bet.get("payout") is not None:
        lines.append(f"派彩: {format_amount(bet.get('payout'), bet.get('currency'))}")
    return "\n".join(lines)


def bet_key(kind: str, item: dict[str, Any]) -> str:
    bet = unwrap_bet(item)
    return "|".join(
        str(part)
        for part in (
            kind,
            item.get("id") or bet.get("id") or "",
            bet.get("iid") or "",
            bet.get("createdAt") or "",
            bet.get("status") or "",
            bet.get("payout") or "",
            bet.get("payoutMultiplier") or "",
        )
    )


def list_from(data: dict[str, Any], *path: str) -> list[Any]:
    cur: Any = data
    for key in path:
        if not isinstance(cur, dict):
            return []
        cur = cur.get(key)
    return cur if isinstance(cur, list) else []


def notify_macos(title: str, message: str, sound: bool) -> None:
    safe_title = title.replace('"', '\\"')
    safe_message = message.replace('"', '\\"')
    script = f'display notification "{safe_message}" with title "{safe_title}"'
    if sound:
        script += ' sound name "Glass"'
    subprocess.run(["osascript", "-e", script], check=False)


def post_json(url: str, payload: dict[str, Any], timeout: int = 20) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def notify_pushplus(token: str, title: str, content: str) -> dict[str, Any]:
    if not token:
        raise RuntimeError("未配置 pushplus_token")
    body = post_json(
        "https://www.pushplus.plus/send",
        {
            "token": token,
            "title": title,
            "content": content,
            "template": "txt",
        },
    )
    if body.get("code") != 200:
        detail = body.get("data")
        msg = body.get("msg") or "PushPlus 发送失败"
        if detail:
            msg = f"{msg}：{detail}"
        raise RuntimeError(msg)
    return body


def notify_wecom(webhook_url: str, content: str) -> None:
    if not webhook_url:
        return
    post_json(webhook_url, {"msgtype": "text", "text": {"content": content}})


def notify_telegram(token: str, chat_id: str, message: str) -> None:
    if not token or not chat_id:
        return
    payload = json.dumps({"chat_id": chat_id, "text": message}).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=20)


def notify_bark(bark_url: str, title: str, message: str) -> None:
    if not bark_url:
        return
    url = bark_url.rstrip("/") + "/" + urllib.parse.quote(title) + "/" + urllib.parse.quote(message)
    urllib.request.urlopen(url, timeout=20)


def send_notifications(config: dict[str, Any], title: str, message: str) -> None:
    notify_cfg = config.get("notify", {})
    if notify_cfg.get("macos", True):
        notify_macos(title, message.replace("\n", " | "), notify_cfg.get("sound", True))

    channels = [
        ("微信(PushPlus)", lambda: notify_pushplus(notify_cfg.get("pushplus_token", ""), title, message)),
        ("微信(企业微信)", lambda: notify_wecom(notify_cfg.get("wecom_webhook", ""), f"{title}\n{message}")),
        ("Telegram", lambda: notify_telegram(
            notify_cfg.get("telegram_bot_token", ""),
            notify_cfg.get("telegram_chat_id", ""),
            message,
        )),
        ("Bark", lambda: notify_bark(notify_cfg.get("bark_url", ""), title, message.replace("\n", " | "))),
    ]
    for name, sender in channels:
        try:
            sender()
        except urllib.error.URLError as exc:
            print(f"{name} 通知失败: {exc}", file=sys.stderr)
        except RuntimeError as exc:
            print(f"{name} 通知失败: {exc}", file=sys.stderr)


class StakeClient:
    def __init__(self, base_url: str, token: str = "", proxy: str = "", transport: str = "auto") -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.proxy = proxy
        self.transport = transport

    def query(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
        operation: str | None = None,
    ) -> dict[str, Any]:
        return graphql(
            self.base_url,
            query,
            variables,
            self.token,
            operation,
            proxy=self.proxy,
            transport=self.transport,
        )

    def require_token(self) -> None:
        if not self.token:
            raise RuntimeError(
                "未配置 Stake API 密钥。请在 Stake：头像 → Settings → Security → API Tokens "
                "创建 Token，填入 config.json 的 api_token，或设置环境变量 STAKE_API_TOKEN。"
            )

    def user(self) -> dict[str, Any]:
        self.require_token()
        user = self.query(QUERY_USER, operation="UserBalances").get("user")
        if not user:
            raise RuntimeError("未能读取 Stake 用户信息，请检查 API Token 是否有效。")
        return user

    def sport_bets(self, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
        self.require_token()
        data = self.query(QUERY_SPORT_BETS, {"limit": limit, "offset": offset}, "UserBetHistory")
        return list_from(data, "user", "sportBetList")

    def active_sport_bets(self) -> list[dict[str, Any]]:
        self.require_token()
        data = self.query(QUERY_ACTIVE_SPORT_BETS, operation="ActiveSportBets")
        return list_from(data, "user", "activeSportBets")

    def casino_bets(self, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
        self.require_token()
        data = self.query(QUERY_CASINO_BETS, {"limit": limit, "offset": offset}, "UserCasinoBets")
        return list_from(data, "user", "casinoBetList")

    def highroller_sport(self, limit: int = 20) -> list[dict[str, Any]]:
        data = self.query(QUERY_HIGHROLLER_SPORT, {"limit": limit}, "HighrollerSportBets")
        return list_from(data, "highrollerSportBets")

    def highroller_casino(self, limit: int = 20) -> list[dict[str, Any]]:
        data = self.query(QUERY_HIGHROLLER_CASINO, {"limit": limit}, "HighrollerCasinoBets")
        return list_from(data, "highrollerCasinoBets")


def print_balances(user: dict[str, Any]) -> None:
    name = user.get("name") or user.get("id") or "?"
    print(f"用户: {name}")
    shown = 0
    for item in user.get("balances") or []:
        if not isinstance(item, dict):
            continue
        avail = item.get("available") or {}
        vault = item.get("vault") or {}
        amount = _num(avail.get("amount")) or 0
        vault_amount = _num(vault.get("amount")) or 0
        if amount == 0 and vault_amount == 0:
            continue
        line = f"  {format_amount(avail.get('amount'), avail.get('currency'))}"
        if vault_amount:
            line += f"  金库 {format_amount(vault.get('amount'), vault.get('currency'))}"
        print(line)
        shown += 1
    if not shown:
        print("  （各币种可用余额均为 0）")


def collect_events(client: StakeClient, config: dict[str, Any]) -> list[tuple[str, str, str]]:
    page_size = int(config.get("page_size", 20))
    events: list[tuple[str, str, str]] = []

    if config.get("watch_own_bets", True):
        user = client.user()
        who = str(user.get("name") or "我")
        for item in client.sport_bets(page_size):
            events.append((bet_key("sport", item), f"Stake 体育 · {who}", format_sport_message(item, who)))
        try:
            for item in client.casino_bets(page_size):
                events.append(
                    (bet_key("casino", item), f"Stake 娱乐城 · {who}", format_casino_message(item, who))
                )
        except RuntimeError as exc:
            print(f"娱乐城投注拉取失败（可忽略）: {exc}", file=sys.stderr)

    if config.get("watch_highrollers"):
        limit = int(config.get("highroller_limit", page_size))
        for item in client.highroller_sport(limit):
            bet = unwrap_bet(item)
            who = ((bet.get("user") or {}).get("name")) or "高额玩家"
            events.append(
                (bet_key("hr-sport", item), f"Stake 高额体育 · {who}", format_sport_message(item, who))
            )
        try:
            for item in client.highroller_casino(limit):
                bet = unwrap_bet(item)
                who = ((bet.get("user") or {}).get("name")) or "高额玩家"
                events.append(
                    (bet_key("hr-casino", item), f"Stake 高额娱乐城 · {who}", format_casino_message(item, who))
                )
        except RuntimeError as exc:
            print(f"高额娱乐城拉取失败（可忽略）: {exc}", file=sys.stderr)

    return events


def run_once(config: dict[str, Any], state_path: Path, client: StakeClient, bootstrap: bool) -> int:
    events = collect_events(client, config)
    state = load_json(state_path) if state_path.exists() else {"seen_keys": []}
    seen = set(state.get("seen_keys", []))
    new_items: list[tuple[str, str, str]] = []

    for key, title, message in reversed(events):
        if key not in seen:
            new_items.append((key, title, message))
            seen.add(key)

    if bootstrap and not state.get("initialized"):
        print(f"初始化完成：已记录 {len(seen)} 条投注，后续仅提醒新变化。")
        state["seen_keys"] = list(seen)[-800:]
        state["initialized"] = True
        save_json(state_path, state)
        return 0

    if not new_items:
        print(f"[{datetime.now(tz=TZ).strftime('%H:%M:%S')}] 暂无新投注")
        state["seen_keys"] = list(seen)[-800:]
        save_json(state_path, state)
        return 0

    for _key, title, message in new_items:
        print(message)
        print("-" * 40)
        send_notifications(config, title, message)

    state["seen_keys"] = list(seen)[-800:]
    state["initialized"] = True
    save_json(state_path, state)
    return len(new_items)


def watch(config_path: Path, state_path: Path, base_url_override: str) -> None:
    print("Stake 投注监控已启动，按 Ctrl+C 停止。")
    while True:
        config = load_json(config_path)
        interval = int(config.get("poll_interval_seconds") or 30)
        client = StakeClient(
            resolve_base_url(config, base_url_override),
            resolve_token(config),
            resolve_proxy(config),
            resolve_transport(config),
        )
        try:
            count = run_once(config, state_path, client, bootstrap=True)
            if count:
                print(f"本轮发现 {count} 条新记录。")
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # noqa: BLE001
            print(f"轮询出错: {exc}", file=sys.stderr)
        time.sleep(interval)


def print_bet_list(items: list[dict[str, Any]], kind: str) -> None:
    if not items:
        print("没有记录。")
        return
    for item in items:
        who = ((unwrap_bet(item).get("user") or {}).get("name")) or "我"
        if kind == "casino":
            print(format_casino_message(item, who))
        else:
            print(format_sport_message(item, who))
        print("-" * 40)


def main() -> None:
    parser = argparse.ArgumentParser(description="Stake.com 投注平台 API")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--base-url", default="", help="覆盖 base_url，例如 https://stake.ac")
    parser.add_argument(
        "--transport",
        choices=["auto", "direct", "chrome"],
        default="",
        help="auto 遇拦截时改走 Chrome；chrome 强制走已打开的 Stake 页面",
    )
    parser.add_argument("--ping", action="store_true", help="验证密钥并打印余额")
    parser.add_argument("--balance", action="store_true", help="查询账户余额")
    parser.add_argument("--bets", action="store_true", help="查询最近体育投注")
    parser.add_argument("--casino-bets", action="store_true", help="查询最近娱乐城投注")
    parser.add_argument("--active", action="store_true", help="查询未结算体育投注")
    parser.add_argument("--highrollers", action="store_true", help="查询公开高额投注（可不需密钥）")
    parser.add_argument("--once", action="store_true", help="只检查一次新记录")
    parser.add_argument("--reset", action="store_true", help="清空已见记录")
    parser.add_argument("--test-notify", action="store_true", help="发送一条测试通知")
    args = parser.parse_args()

    if not args.config.exists():
        raise SystemExit(f"找不到配置文件: {args.config}")

    config = load_json(args.config)
    if args.transport:
        config["transport"] = args.transport
    client = StakeClient(
        resolve_base_url(config, args.base_url),
        resolve_token(config),
        resolve_proxy(config),
        resolve_transport(config),
    )

    if args.test_notify:
        title = "Stake 提醒 · 测试"
        message = f"[测试 {datetime.now(tz=TZ).strftime('%H:%M:%S')}] Stake 通知通道正常。"
        token = config.get("notify", {}).get("pushplus_token", "")
        print("正在发送微信测试（PushPlus）...")
        try:
            body = notify_pushplus(token, title, message)
            print(f"✅ PushPlus 返回成功: {body.get('msg')}，流水号: {body.get('data')}")
        except Exception as exc:  # noqa: BLE001
            print(f"❌ 微信发送失败: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        if config.get("notify", {}).get("macos", True):
            notify_macos(title, message, config.get("notify", {}).get("sound", True))
        return

    if args.ping or args.balance:
        print_balances(client.user())
        return

    if args.bets:
        print_bet_list(client.sport_bets(int(config.get("page_size", 20))), "sport")
        return

    if args.casino_bets:
        print_bet_list(client.casino_bets(int(config.get("page_size", 20))), "casino")
        return

    if args.active:
        print_bet_list(client.active_sport_bets(), "sport")
        return

    if args.highrollers:
        print("=== 高额体育 ===")
        print_bet_list(client.highroller_sport(int(config.get("highroller_limit", 20))), "sport")
        print("=== 高额娱乐城 ===")
        try:
            print_bet_list(client.highroller_casino(int(config.get("highroller_limit", 20))), "casino")
        except RuntimeError as exc:
            print(f"高额娱乐城不可用: {exc}", file=sys.stderr)
        return

    if args.reset and args.state.exists():
        args.state.unlink()
        print("状态已重置。")

    if args.once:
        run_once(config, args.state, client, bootstrap=False)
        return

    watch(args.config, args.state, args.base_url)


if __name__ == "__main__":
    main()
