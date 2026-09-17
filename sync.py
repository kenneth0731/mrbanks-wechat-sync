#!/usr/bin/env python3
"""把 Mr Banks Free Channel 里含指定文案的新消息实时推到微信。"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "config.json"
DEFAULT_STATE = ROOT / ".state.json"
TZ = ZoneInfo("Asia/Shanghai")
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

NEEDLE = "use welcome code banks for weekly airdrops and bonuses"


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def normalize(text: str) -> str:
    lowered = text.lower()
    lowered = re.sub(r"['’`\"“”]", "", lowered)
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered.strip()


def matches(text: str, needle: str) -> bool:
    return normalize(needle) in normalize(text)


def html_to_text(raw: str) -> str:
    raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
    raw = re.sub(r"</p>", "\n", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", "", raw)
    raw = html_lib.unescape(raw)
    return re.sub(r"\n{3,}", "\n\n", raw).strip()


def fetch(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_messages(page_html: str) -> list[dict[str, str]]:
    chunks = re.split(r'<div class="tgme_widget_message_wrap[^"]*"', page_html)
    items: list[dict[str, str]] = []
    for chunk in chunks:
        post = re.search(r'data-post="([^"]+)"', chunk)
        if not post:
            continue
        text_m = re.search(
            r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
            chunk,
            flags=re.S,
        )
        date_m = re.search(r'datetime="([^"]+)"', chunk)
        text = html_to_text(text_m.group(1)) if text_m else ""
        if not text:
            continue
        items.append(
            {
                "id": post.group(1),
                "text": text,
                "date": date_m.group(1) if date_m else "",
                "url": "https://t.me/" + post.group(1),
            }
        )
    return items


def format_time(value: str) -> str:
    if not value:
        return "未知时间"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(TZ)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return value


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


def resolve_token(config: dict[str, Any]) -> str:
    return str(os.environ.get("PUSHPLUS_TOKEN") or config.get("pushplus_token") or "").strip()


def send_wechat(token: str, title: str, content: str) -> None:
    if not token:
        raise RuntimeError("未配置 pushplus_token 或环境变量 PUSHPLUS_TOKEN，无法推送到微信")
    body = post_json(
        "https://www.pushplus.plus/send",
        {
            "token": token,
            "title": title,
            "content": content,
            "template": "txt",
            "channel": "wechat",
        },
    )
    if body.get("code") != 200:
        detail = body.get("data")
        msg = body.get("msg") or "PushPlus 发送失败"
        if detail:
            msg = f"{msg}：{detail}"
        raise RuntimeError(msg)


def format_push(item: dict[str, str]) -> tuple[str, str]:
    title = "Mr Banks 新消息"
    content = "\n".join(
        [
            f"时间: {format_time(item['date'])}",
            f"链接: {item['url']}",
            "",
            item["text"],
        ]
    )
    return title, content


def collect(config: dict[str, Any]) -> list[dict[str, str]]:
    channel = str(config.get("channel") or "MrBanksFreeChannel").lstrip("@")
    url = f"https://t.me/s/{channel}"
    page = fetch(url)
    needle = str(config.get("filter") or NEEDLE)
    return [item for item in parse_messages(page) if matches(item["text"], needle)]


def run_once(
    config: dict[str, Any],
    state_path: Path,
    *,
    bootstrap: bool,
    dry_run: bool,
) -> int:
    items = collect(config)
    state = load_json(state_path) if state_path.exists() else {"seen_ids": []}
    seen = set(state.get("seen_ids") or [])
    fresh = [item for item in items if item["id"] not in seen]

    if bootstrap and not state.get("initialized"):
        for item in items:
            seen.add(item["id"])
        state["seen_ids"] = sorted(seen)[-400:]
        state["initialized"] = True
        save_json(state_path, state)
        print(f"初始化完成：已记住 {len(items)} 条匹配消息，之后只推送新的。")
        return 0

    if not fresh:
        print(f"[{datetime.now(tz=TZ).strftime('%H:%M:%S')}] 没有新的匹配消息")
        state["seen_ids"] = sorted(seen)[-400:]
        save_json(state_path, state)
        return 0

    sent = 0
    for item in fresh:
        title, content = format_push(item)
        print(f"{title} {item['id']}")
        print(content)
        print("-" * 40)
        if not dry_run:
            send_wechat(resolve_token(config), title, content)
        seen.add(item["id"])
        sent += 1

    state["seen_ids"] = sorted(seen)[-400:]
    state["initialized"] = True
    save_json(state_path, state)
    return sent


def watch(config_path: Path, state_path: Path) -> None:
    print("Mr Banks → 微信 同步已启动，按 Ctrl+C 停止。")
    while True:
        config = load_json(config_path)
        interval = int(config.get("poll_interval_seconds") or 8)
        try:
            count = run_once(config, state_path, bootstrap=True, dry_run=False)
            if count:
                print(f"本轮推送 {count} 条。")
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # noqa: BLE001
            print(f"轮询出错: {exc}", file=sys.stderr)
        time.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="Mr Banks Free Channel → 微信")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--once", action="store_true", help="只检查一轮")
    parser.add_argument("--dry-run", action="store_true", help="只打印不推送")
    parser.add_argument("--reset", action="store_true", help="清空已见记录")
    parser.add_argument("--test-wechat", action="store_true", help="发送一条微信测试")
    args = parser.parse_args()

    if args.config.exists():
        config = load_json(args.config)
    elif resolve_token({}):
        config = {}
    else:
        raise SystemExit(f"找不到配置文件: {args.config}")

    if args.reset and args.state.exists():
        args.state.unlink()
        print("状态已重置。")

    if args.test_wechat:
        title = "Mr Banks 同步 · 测试"
        message = f"[{datetime.now(tz=TZ).strftime('%H:%M:%S')}] 微信通道正常。"
        send_wechat(resolve_token(config), title, message)
        print("测试消息已发送。")
        return

    if args.once or args.dry_run:
        run_once(
            config,
            args.state,
            bootstrap=not args.dry_run,
            dry_run=args.dry_run,
        )
        return

    watch(args.config, args.state)


if __name__ == "__main__":
    main()
