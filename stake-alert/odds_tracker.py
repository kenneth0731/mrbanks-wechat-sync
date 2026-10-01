#!/usr/bin/env python3
"""Stake 五大联赛/重要杯赛指数快照：11:00 / 16:30 / 21:00 / 23:30。"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from itertools import combinations, product
from pathlib import Path
from typing import Any

from stake import (
    TZ,
    chrome_ensure_stake_tab,
    chrome_js,
    ensure_shadowrocket,
    load_json,
    parse_graphql_body,
    resolve_token,
    send_notifications,
)

ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "config.json"
SNAP_DIR = ROOT / "odds_snapshots"
SOCCER_ID = "5b4b60b9-ed95-41e7-97e3-f33aa172cf12"

TOURNAMENT_KEYS = (
    "英超",
    "西班牙足球甲级联赛",
    "意大利甲级联赛",
    "德国足球甲级",
    "德甲",
    "法国足球甲级",
    "法甲",
    "欧洲冠军联赛",
    "欧足联欧洲联赛",
    "Conference",
    # 欧国联：Stake/不同盘口中文名不一，别名都收
    "欧足协国际联赛",
    "欧足联国家联赛",
    "欧足协国家联赛",
    "欧洲国家联赛",
    "欧国联",
    "Nations League",
    "英格兰联赛杯",
    "足总杯",
    "德国杯",
    "意大利杯",
    "法国杯",
    "西班牙国王杯",
    "欧洲协会联赛",
)

EXCLUDE_KEYS = ("女子", "女足", "乙级", "丙级", "冠军联赛，", "英格兰冠军")
NATIONS_LEAGUE_HINTS = ("国联", "Nations League", "Nation League", "UEFA Nations")

WATCH_MARKETS = (
    "1x2 (1up)",
    "平局返还",
    "双胜彩",
    "赢任何半场",
    "任意半场获胜",
)
SKIP_TEAMS = ("直布罗陀", "安道尔", "立陶宛", "阿塞拜疆", "圣马力诺", "列支敦士登", "法罗")
DAILY_CAP_USD = 200
STAKE_USD = DAILY_CAP_USD
CNY_PER_USD = 7
MAX_TICKETS = 3
MIN_TICKET_ODDS = 1.70
PICKS_HORIZON_HOURS = 24
MARKET_BANDS = {
    "1x2(1up)": (1.12, 1.50),
    "赢任何半场": (1.15, 1.55),
    "平局返还": (1.18, 1.55),
    "双胜彩": (1.15, 1.55),
}
QUERY_TOURNAMENTS = """
query($id: String!) {
  sport(sportId: $id) {
    tournamentList(limit: 200) {
      id
      name
      fixtureCount
    }
  }
}
"""

QUERY_FIXTURES = """
query($id: String!) {
  sportTournament(tournamentId: $id) {
    id
    name
    fixtureList(type: upcoming, limit: 20) {
      id
      name
      status
      startTime
    }
  }
}
"""

QUERY_MARKETS = """
query($id: String!) {
  sportFixture(fixtureId: $id) {
    id
    name
    status
    startTime
    tournament { name }
    groups(groups: ["main", "winner", "1UP2UP", "1st2ndhalfmarkets", "AsianLines", "specials"]) {
      name
      templates(limit: 40) {
        name
        markets(limit: 24) {
          name
          specifiers
          extId
          outcomes { name odds active }
        }
      }
    }
  }
}
"""

def slot_name(now: datetime) -> str:
    hm = (now.hour, now.minute)
    if hm >= (23, 0) or hm < (1, 0):
        return "临场"
    if (10, 30) <= hm < (12, 0):
        return "早盘"
    if (16, 0) <= hm < (17, 30):
        return "欧早"
    if (20, 30) <= hm < (22, 0):
        return "晚盘"
    return "临时"


def parse_gmt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%a, %d %b %Y %H:%M:%S GMT").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def wanted_tournament(name: str) -> bool:
    if any(bad in name for bad in EXCLUDE_KEYS):
        return False
    if any(key in name for key in TOURNAMENT_KEYS):
        return True
    # Stake 欧国联中文名经常变动，用宽匹配兜底
    return any(hint in name for hint in NATIONS_LEAGUE_HINTS)


def gql(query: str, variables: dict[str, Any] | None, token: str) -> dict[str, Any]:
    headers = {
        "content-type": "application/json",
        "x-language": "zh",
    }
    if token:
        headers["x-access-token"] = token
    payload: dict[str, Any] = {"query": query}
    if variables:
        payload["variables"] = variables
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
    for _ in range(24):
        time.sleep(0.25)
        raw = chrome_js("String(window.__stakeResult || '')")
        if raw and raw not in {"pending", "started"}:
            break
    if not raw or raw in {"pending", "started"}:
        raise RuntimeError("Chrome GraphQL 超时")
    if raw.startswith("ERR:"):
        raise RuntimeError(raw[4:])
    return parse_graphql_body(raw)


def extract_quotes(fixture: dict[str, Any]) -> dict[str, float]:
    quotes: dict[str, float] = {}
    for group in fixture.get("groups") or []:
        for template in group.get("templates") or []:
            for market in template.get("markets") or []:
                name = str(market.get("name") or "")
                outcomes = [
                    o for o in (market.get("outcomes") or []) if o.get("active") and o.get("odds") is not None
                ]
                if (
                    name in WATCH_MARKETS
                    or name.startswith("1x2 (1up)")
                    or "赢任何半场" in name
                    or "任意半场获胜" in name
                ):
                    for o in outcomes:
                        quotes[f"{name}|{o.get('name')}"] = float(o["odds"])
    return quotes


def collect_fixtures(token: str, hours: int, limit: int) -> list[dict[str, Any]]:
    sport = gql(QUERY_TOURNAMENTS, {"id": SOCCER_ID}, token)
    tournaments = ((sport.get("sport") or {}).get("tournamentList") or [])
    now = datetime.now(timezone.utc)
    until = now + timedelta(hours=hours)
    rows: list[dict[str, Any]] = []
    matched_names: list[str] = []
    for item in tournaments:
        name = str(item.get("name") or "")
        if not wanted_tournament(name) or not item.get("fixtureCount"):
            continue
        matched_names.append(name)
        try:
            data = gql(QUERY_FIXTURES, {"id": item["id"]}, token)
        except Exception as exc:  # noqa: BLE001
            print(f"联赛拉取失败 {name}: {exc}")
            continue
        for fx in ((data.get("sportTournament") or {}).get("fixtureList") or []):
            start = parse_gmt(fx.get("startTime"))
            if not start or start < now - timedelta(hours=1) or start > until:
                continue
            rows.append(
                {
                    "id": fx["id"],
                    "name": fx.get("name"),
                    "tournament": name,
                    "start": start.astimezone(TZ).strftime("%Y-%m-%d %H:%M"),
                    "start_utc": start.isoformat(),
                }
            )
    rows.sort(key=lambda x: x["start"])
    print(f"关注联赛 {len(matched_names)} 个：{'；'.join(matched_names[:12]) or '无'}")
    return rows[:limit]


def threshold(odds: float) -> float:
    if odds < 1.40:
        return 0.05
    if odds < 1.80:
        return 0.08
    return 0.10


def _canon_side(name: str, home: str, away: str) -> str:
    text = str(name or "").strip()
    if not text:
        return ""
    if text in {"平局", "和局"}:
        return "平局"
    if home and (text == home or home in text or text in home):
        return home
    if away and (text == away or away in text or text in away):
        return away
    return text


def quote_effect(key: str, home: str, away: str) -> list[tuple[str, int]]:
    """降水（赔率变短）时，+1 表示对该方有利，-1 表示对该方不利。"""
    raw = str(key or "")
    left, _, right = raw.partition("|")
    left, right = left.strip(), right.strip()

    if "赢任何半场" in left or "任意半场" in left:
        team = _canon_side(
            left.replace("赢任何半场", "").replace("任意半场获胜", "").replace("任意半场", ""),
            home,
            away,
        )
        if not team:
            return []
        return [(team, -1 if right == "否" else 1)]

    if left.startswith("1x2") or left.startswith("平局返还"):
        side = _canon_side(right, home, away)
        return [(side, 1)] if side else []

    if left.startswith("双胜彩"):
        text = right.replace("或平局", "或 平局").replace("平局或", "平局 或")
        parts = [_canon_side(p, home, away) for p in text.split("或")]
        parts = [p for p in parts if p]
        teams = [p for p in parts if p != "平局"]
        has_draw = "平局" in parts
        if has_draw and len(teams) == 1:
            return [(teams[0], 1), ("平局", 1)]
        if not has_draw and len(teams) == 2:
            return [("平局", -1)]
        return [(p, 1) for p in parts]

    side = _canon_side(right or left, home, away)
    return [(side, 1)] if side else []


def favor_text(delta: float, effect: list[tuple[str, int]]) -> str:
    pairs = [(str(name), int(sign)) for name, sign in effect]
    if pairs == [("平局", -1)]:
        if delta < 0:
            return "对分出胜负有利，对平局不利"
        return "对平局有利，对分出胜负不利"
    helped: list[str] = []
    hurt: list[str] = []
    for name, sign in pairs:
        toward = (delta < 0 and sign > 0) or (delta > 0 and sign < 0)
        if toward:
            if name not in helped:
                helped.append(name)
        elif name not in hurt:
            hurt.append(name)
    bits: list[str] = []
    if helped:
        bits.append("对" + "/".join(helped) + "有利")
    if hurt:
        bits.append("对" + "/".join(hurt) + "不利")
    return "，".join(bits) or "方向不明"


def match_verdict(items: list[dict[str, Any]]) -> str:
    if not items:
        return "方向不明"
    home = str(items[0].get("home") or "")
    away = str(items[0].get("away") or "")
    fav = str(items[0].get("fav") or "")
    heat: dict[str, float] = {}
    if home:
        heat[home] = 0.0
    if away:
        heat[away] = 0.0
    heat["平局"] = 0.0
    for item in items:
        shorten = float(item["from"]) - float(item["to"])
        for name, sign in item.get("effect") or []:
            heat[name] = heat.get(name, 0.0) + shorten * sign
    ranked = sorted(heat.items(), key=lambda kv: kv[1], reverse=True)
    top, top_v = ranked[0]
    low, low_v = ranked[-1]
    if top_v <= 0.03 and low_v >= -0.03:
        return "方向不明显"
    bits: list[str] = []
    if top_v > 0.03:
        note = ""
        if fav and top == fav:
            note = "（热门继续被追）"
        elif fav and top not in {"", "平局"} and top != fav:
            note = "（冷门回补）"
        bits.append(f"对{top}有利{note}")
    if low_v < -0.03 and low != top:
        bits.append(f"对{low}不利")
    return "，".join(bits) or "方向不明"


def group_moves(moves: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in moves:
        grouped.setdefault(str(item.get("match") or "?"), []).append(item)
    names = sorted(
        grouped,
        key=lambda name: max(abs(float(m["delta"])) for m in grouped[name]),
        reverse=True,
    )
    return [(name, grouped[name]) for name in names]


def format_move_line(item: dict[str, Any], indent: str = "") -> str:
    sign = "+" if item["delta"] > 0 else ""
    favor = item.get("favor") or favor_text(float(item["delta"]), item.get("effect") or [])
    return (
        f"{indent}{item['direction']} {item['market']} "
        f"{item['from']} → {item['to']} ({sign}{item['delta']}) · {favor}"
    )


def format_moves_alert(moves: list[dict[str, Any]], limit: int = 4) -> str:
    blocks: list[str] = []
    for name, items in group_moves(moves)[:limit]:
        lines = [f"【{name}】{match_verdict(items)}"]
        for item in items[:3]:
            lines.append(format_move_line(item, "  "))
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def diff_quotes(prev: dict[str, Any], cur: dict[str, Any]) -> list[dict[str, Any]]:
    prev_map = {m["id"]: m.get("quotes") or {} for m in prev.get("matches") or []}
    moves: list[dict[str, Any]] = []
    for match in cur.get("matches") or []:
        old = prev_map.get(match["id"]) or {}
        new = match.get("quotes") or {}
        home, away = match_teams(str(match.get("name") or ""))
        fav = favorite_team(new, home, away)
        for key, price in new.items():
            if key not in old:
                continue
            before = float(old[key])
            after = float(price)
            delta = after - before
            if abs(delta) < threshold(min(before, after)):
                continue
            effect = quote_effect(key, home, away)
            moves.append(
                {
                    "match": match.get("name"),
                    "tournament": match.get("tournament"),
                    "start": match.get("start"),
                    "home": home,
                    "away": away,
                    "fav": fav,
                    "market": key,
                    "from": before,
                    "to": after,
                    "delta": round(delta, 3),
                    "direction": "降水" if delta < 0 else "升水",
                    "effect": effect,
                    "favor": favor_text(delta, effect),
                }
            )
    moves.sort(key=lambda x: abs(x["delta"]), reverse=True)
    return moves


def money(usd: float, signed: bool = False) -> str:
    sign = "+" if signed and usd > 0 else ""
    cny = usd * CNY_PER_USD
    if abs(usd - round(usd)) < 1e-6:
        return f"{sign}${int(round(usd))} / {sign}¥{int(round(cny))}"
    return f"{sign}${usd:.2f} / {sign}¥{cny:.2f}"


def parse_start(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
    except ValueError:
        return None


def skip_match(name: str) -> bool:
    return any(token in (name or "") for token in SKIP_TEAMS)


def match_teams(name: str) -> tuple[str, str]:
    parts = [p.strip() for p in str(name or "").replace(" vs ", " - ").split(" - ", 1)]
    if len(parts) != 2:
        return "", ""
    return parts[0], parts[1]


def favorite_team(quotes: dict[str, Any], home: str, away: str) -> str:
    ranked: list[tuple[float, str]] = []
    for key, price in quotes.items():
        if key.startswith("1x2 (1up)|") and "平局" not in key:
            ranked.append((float(price), key.split("|", 1)[1]))
        elif key.startswith("平局返还|"):
            ranked.append((float(price), key.split("|", 1)[1]))
    if ranked:
        ranked.sort()
        return ranked[0][1]
    return home or away


def in_band(play: str, odds: float) -> bool:
    low, high = MARKET_BANDS.get(play, (1.15, 1.50))
    return low <= odds <= high


def base_leg(match: dict[str, Any], **extra: Any) -> dict[str, Any]:
    row = {
        "match_id": match["id"],
        "match": match.get("name"),
        "tournament": match.get("tournament"),
        "start": match.get("start"),
    }
    row.update(extra)
    return row


def iter_selections(match: dict[str, Any]) -> list[dict[str, Any]]:
    quotes = match.get("quotes") or {}
    home, away = match_teams(str(match.get("name") or ""))
    fav = favorite_team(quotes, home, away)
    found: list[dict[str, Any]] = []

    sides = [
        (key.split("|", 1)[1], float(price))
        for key, price in quotes.items()
        if key.startswith("1x2 (1up)|") and "平局" not in key
    ]
    if len(sides) >= 2:
        sides.sort(key=lambda x: x[1])
        team, odds = sides[0]
        other = sides[1][1]
        if in_band("1x2(1up)", odds) and not (other <= 1.70 and odds >= 1.50):
            found.append(
                base_leg(
                    match,
                    team=team,
                    play="1x2(1up)",
                    play_detail=f"{team}先上1球后的胜平负",
                    settle=f"{team}不败即中；{team}输1球走1up平局；输2球及以上未中",
                    selection=f"{team}胜",
                    market=f"1x2 (1up)|{team}",
                    odds=odds,
                    option=f"{match.get('name')} · {team}胜 · 1x2(1up)",
                )
            )

    for key, price in quotes.items():
        odds = float(price)
        if key.startswith("平局返还|"):
            team = key.split("|", 1)[1]
            if team in {"平局", ""} or not in_band("平局返还", odds):
                continue
            if fav and team != fav:
                continue
            found.append(
                base_leg(
                    match,
                    team=team,
                    play="平局返还",
                    play_detail=f"{team}胜，平局退本",
                    settle=f"{team}胜即中；平局退还本金；{team}负未中",
                    selection=f"{team}（平局返还）",
                    market=key,
                    odds=odds,
                    option=f"{match.get('name')} · {team} · 平局返还",
                )
            )
        elif key.startswith("双胜彩|"):
            outcome = key.split("|", 1)[1]
            if "平局" not in outcome or "或" not in outcome:
                continue
            if fav and fav not in outcome:
                continue
            if not in_band("双胜彩", odds):
                continue
            found.append(
                base_leg(
                    match,
                    team=fav,
                    play="双胜彩",
                    play_detail="两种结果对一路",
                    settle=f"{outcome} 打出即中",
                    selection=outcome,
                    market=key,
                    odds=odds,
                    option=f"{match.get('name')} · {outcome} · 双胜彩",
                )
            )
        elif "赢任何半场" in key and key.endswith("|是"):
            team = key.split("|", 1)[0].replace(" 赢任何半场", "").replace("赢任何半场", "").strip()
            if fav and team != fav:
                continue
            if not in_band("赢任何半场", odds):
                continue
            found.append(
                base_leg(
                    match,
                    team=team,
                    play="赢任何半场",
                    play_detail=f"{team}赢上半场或下半场",
                    settle=f"{team}任一半场比分领先即中；两半场都不赢则未中",
                    selection=f"{team}赢任一半场",
                    market=key,
                    odds=odds,
                    option=f"{match.get('name')} · {team}赢任一半场",
                )
            )
    return found


def horizon_groups(matches: list[dict[str, Any]], now: datetime) -> list[list[dict[str, Any]]]:
    until = now + timedelta(hours=PICKS_HORIZON_HOURS)
    groups: list[list[dict[str, Any]]] = []
    for match in matches:
        if skip_match(str(match.get("name") or "")):
            continue
        start = parse_start(match.get("start"))
        if not start or start < now - timedelta(minutes=20) or start > until:
            continue
        cands = iter_selections(match)
        if cands:
            groups.append(cands)
    groups.sort(key=lambda g: min(float(c["odds"]) for c in g))
    quality = [g for g in groups if min(float(c["odds"]) for c in g) <= 1.38]
    return (quality if len(quality) >= 3 else groups)[:8]


def pairs_clear(legs: list[dict[str, Any]]) -> bool:
    for i, left in enumerate(legs):
        for right in legs[i + 1 :]:
            if combo_odds([left, right]) <= MIN_TICKET_ODDS:
                return False
    return True


def diversity_score(legs: list[dict[str, Any]]) -> tuple[Any, ...]:
    plays = [str(item["play"]) for item in legs]
    counts = Counter(plays)
    pair_odds = [
        combo_odds([left, right])
        for i, left in enumerate(legs)
        for right in legs[i + 1 :]
    ]
    quality = sum(1 for item in legs if float(item["odds"]) <= 1.35)
    return (
        quality,
        -sum(float(item["odds"]) for item in legs),
        len(set(plays)),
        -max(counts.values()) if counts else 0,
        min(pair_odds) if pair_odds else 0,
    )


def pick_diverse_core(groups: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    for size in (4, 3):
        if len(groups) < size:
            continue
        best: tuple[tuple[Any, ...], list[dict[str, Any]]] | None = None
        for subset in combinations(groups, size):
            for combo in product(*subset):
                legs = list(combo)
                if len({item["match_id"] for item in legs}) != size:
                    continue
                if not pairs_clear(legs):
                    continue
                score = diversity_score(legs)
                if best is None or score > best[0]:
                    best = (score, legs)
        if best:
            return list(best[1])
    return []


def candidate_legs(matches: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    core = pick_diverse_core(horizon_groups(matches, now))
    if core:
        return core
    flat = [cands[0] for cands in horizon_groups(matches, now)]
    flat.sort(key=lambda x: (x["odds"], x["start"]))
    return flat


def combo_odds(parts: list[dict[str, Any]]) -> float:
    total = 1.0
    for leg in parts:
        total *= float(leg["odds"])
    return round(total, 3)


def make_ticket(
    kind: str, parts: list[dict[str, Any]], stake_usd: float = STAKE_USD
) -> dict[str, Any] | None:
    odds = combo_odds(parts)
    if odds < MIN_TICKET_ODDS:
        return None
    return {
        "kind": kind,
        "legs": parts,
        "odds": odds,
        "roi_pct": round((odds - 1) * 100, 1),
        "stake_usd": round(stake_usd, 2),
        "return_usd": round(stake_usd * odds, 2),
        "profit_usd": round(stake_usd * odds - stake_usd, 2),
    }


def _parlay_set_score(bundles: list[list[dict[str, Any]]]) -> tuple[Any, ...]:
    legs = [leg for bundle in bundles for leg in bundle]
    plays = [str(leg["play"]) for leg in legs]
    match_ids = [leg["match_id"] for leg in legs]
    counts = Counter(plays)
    return (
        len(set(match_ids)),
        len(set(plays)),
        sum(1 for leg in legs if float(leg["odds"]) <= 1.38),
        min(combo_odds(bundle) for bundle in bundles),
        -max(Counter(match_ids).values()) if match_ids else 0,
        -max(counts.values()) if counts else 0,
        -sum(float(leg["odds"]) for leg in legs),
    )


def _best_combo(groups: list[list[dict[str, Any]]]) -> list[dict[str, Any]] | None:
    best: tuple[tuple[Any, ...], list[dict[str, Any]]] | None = None
    for combo in product(*groups):
        legs = list(combo)
        if len({leg["match_id"] for leg in legs}) != len(legs):
            continue
        if combo_odds(legs) < MIN_TICKET_ODDS:
            continue
        score = diversity_score(legs)
        if best is None or score > best[0]:
            best = (score, legs)
    return list(best[1]) if best else None


def _pick_disjoint_parlays(
    groups: list[list[dict[str, Any]]], size: int, need: int
) -> list[list[dict[str, Any]]]:
    edges: list[tuple[frozenset[int], list[dict[str, Any]]]] = []
    for idxs in combinations(range(len(groups)), size):
        legs = _best_combo([groups[i] for i in idxs])
        if legs:
            edges.append((frozenset(idxs), legs))
    best: tuple[tuple[Any, ...], list[list[dict[str, Any]]]] | None = None

    def dfs(start: int, used: set[int], picked: list[list[dict[str, Any]]]) -> None:
        nonlocal best
        if len(picked) == need:
            score = _parlay_set_score(picked)
            if best is None or score > best[0]:
                best = (score, [list(bundle) for bundle in picked])
            return
        if start >= len(edges) or len(picked) + (len(edges) - start) < need:
            return
        for pos in range(start, len(edges)):
            idxs, legs = edges[pos]
            if used & idxs:
                continue
            picked.append(legs)
            dfs(pos + 1, used | idxs, picked)
            picked.pop()

    dfs(0, set(), [])
    return list(best[1]) if best else []


def _pick_overlap_parlays(
    groups: list[list[dict[str, Any]]], size: int, need: int, max_use: int = 2
) -> list[list[dict[str, Any]]]:
    edges: list[tuple[tuple[int, ...], list[dict[str, Any]]]] = []
    for idxs in combinations(range(len(groups)), size):
        legs = _best_combo([groups[i] for i in idxs])
        if legs:
            edges.append((idxs, legs))
    best: tuple[tuple[Any, ...], list[list[dict[str, Any]]]] | None = None

    def dfs(start: int, used: Counter[int], picked: list[list[dict[str, Any]]]) -> None:
        nonlocal best
        if len(picked) == need:
            score = _parlay_set_score(picked)
            if best is None or score > best[0]:
                best = (score, [list(bundle) for bundle in picked])
            return
        if start >= len(edges) or len(picked) + (len(edges) - start) < need:
            return
        for pos in range(start, len(edges)):
            idxs, legs = edges[pos]
            if any(used[i] >= max_use for i in idxs):
                continue
            nxt = used.copy()
            nxt.update(idxs)
            picked.append(legs)
            dfs(pos + 1, nxt, picked)
            picked.pop()

    dfs(0, Counter(), [])
    return list(best[1]) if best else []


def finalize_parlays(bundles: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    if not bundles:
        return []
    letters = "ABCDEFGH"
    codes: dict[str, str] = {}
    for bundle in bundles:
        for leg in bundle:
            mid = str(leg["match_id"])
            if mid not in codes:
                codes[mid] = letters[len(codes)]
    appear = Counter(codes[str(leg["match_id"])] for bundle in bundles for leg in bundle)
    stake = DAILY_CAP_USD / len(bundles)
    tickets: list[dict[str, Any]] = []
    for bundle in bundles:
        tagged = []
        for leg in bundle:
            row = dict(leg)
            row["code"] = codes[str(leg["match_id"])]
            tagged.append(row)
        kind = {1: "单关", 2: "二串一", 3: "三串一"}.get(len(tagged), f"{len(tagged)}串一")
        ticket = make_ticket(kind, tagged, stake)
        if not ticket:
            # 单张不达标就跳过，不要整批清空（否则短热门二串常被误杀成空单）
            continue
        ticket["pair"] = "".join(leg["code"] for leg in tagged)
        for leg in ticket["legs"]:
            leg["occupy_usd"] = stake * appear[leg["code"]]
        tickets.append(ticket)
    return scale_to_daily_cap(tickets)


def _groups_avg_min_odds(groups: list[list[dict[str, Any]]]) -> float:
    mins = [min(float(c["odds"]) for c in g) for g in groups if g]
    return sum(mins) / len(mins) if mins else 99.0


def build_daily_parlays(matches: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    groups = horizon_groups(matches, now)
    if not groups:
        return []
    # 热门偏短时二串一常 < 1.70，优先三串一
    sizes = (3, 2) if _groups_avg_min_odds(groups) <= 1.34 else (2, 3)
    for size in sizes:
        bundles = _pick_disjoint_parlays(groups, size, MAX_TICKETS)
        tickets = finalize_parlays(bundles) if len(bundles) == MAX_TICKETS else []
        if len(tickets) == MAX_TICKETS:
            return tickets
    for size in sizes:
        bundles = _pick_overlap_parlays(groups, size, MAX_TICKETS)
        tickets = finalize_parlays(bundles) if len(bundles) == MAX_TICKETS else []
        if len(tickets) == MAX_TICKETS:
            return tickets
    for need in (2, 1):
        for size in sizes:
            bundles = _pick_disjoint_parlays(groups, size, need)
            tickets = finalize_parlays(bundles) if len(bundles) == need else []
            if len(tickets) == need:
                return tickets
            # finalize 可能丢掉部分票；有票就发，避免整晚空单
            if tickets:
                return tickets
    return []


def scale_to_daily_cap(tickets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not tickets:
        return tickets
    total = sum(float(t["stake_usd"]) for t in tickets)
    if total <= 0:
        return tickets
    scale = DAILY_CAP_USD / total
    for ticket in tickets:
        ticket["stake_usd"] = round(float(ticket["stake_usd"]) * scale, 2)
        ticket["return_usd"] = round(float(ticket["stake_usd"]) * float(ticket["odds"]), 2)
        ticket["profit_usd"] = round(float(ticket["return_usd"]) - float(ticket["stake_usd"]), 2)
    drift = round(DAILY_CAP_USD - sum(float(t["stake_usd"]) for t in tickets), 2)
    if tickets and abs(drift) >= 0.01:
        last = tickets[-1]
        last["stake_usd"] = round(float(last["stake_usd"]) + drift, 2)
        last["return_usd"] = round(float(last["stake_usd"]) * float(last["odds"]), 2)
        last["profit_usd"] = round(float(last["return_usd"]) - float(last["stake_usd"]), 2)
    return tickets


def diagnose_empty_picks(matches: list[dict[str, Any]], now: datetime) -> str:
    total = len(matches)
    skipped = 0
    outside = 0
    no_quotes = 0
    no_band = 0
    ok = 0
    until = now + timedelta(hours=PICKS_HORIZON_HOURS)
    for match in matches:
        if skip_match(str(match.get("name") or "")):
            skipped += 1
            continue
        start = parse_start(match.get("start"))
        if not start or start < now - timedelta(minutes=20) or start > until:
            outside += 1
            continue
        quotes = match.get("quotes") or {}
        if not quotes:
            no_quotes += 1
            continue
        if not iter_selections(match):
            no_band += 1
            continue
        ok += 1
    if total == 0:
        return (
            "本轮未组出推荐单：快照里没有关注赛事场次"
            "（请确认欧国联/五大联赛等已进 tournament 列表）。"
        )
    if ok < 2:
        return (
            f"本轮未组出推荐单：可串场次不足（候选{ok}场，需至少2场）。"
            f"快照{total}场：窗口外{outside}，跳过弱队{skipped}，无盘口{no_quotes}，"
            f"赔率不在带内{no_band}。"
        )
    return (
        f"本轮未组出推荐单：有{ok}场候选，但凑不出组合赔率≥{MIN_TICKET_ODDS:.2f}的串"
        f"（快照{total}场）。"
    )


def build_picks(snap: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(tz=TZ)
    matches = snap.get("matches") or []
    tickets = build_daily_parlays(matches, now)
    stake = round(sum(float(t["stake_usd"]) for t in tickets), 2)
    ret = sum(t["return_usd"] for t in tickets)
    card: dict[str, Any] = {
        "ts": now.isoformat(),
        "slot": snap.get("slot") or slot_name(now),
        "tickets": tickets,
        "stake_usd": stake,
        "return_usd": round(ret, 2),
        "profit_usd": round(ret - stake, 2),
        "options": [leg["market"] + "@" + leg["match_id"] for t in tickets for leg in t["legs"]],
    }
    if not tickets:
        card["empty_reason"] = diagnose_empty_picks(matches, now)
    return card


def format_leg(index: int, leg: dict[str, Any]) -> str:
    play = leg.get("play") or "1x2(1up)"
    detail = leg.get("play_detail") or ""
    selection = leg.get("selection") or leg.get("team") or ""
    settle = leg.get("settle") or ""
    return "\n".join(
        [
            f"【第{index}脚】",
            f"编号：{leg['code']}" if leg.get("code") else "",
            f"比赛：{leg.get('match')}",
            f"赛事：{leg.get('tournament')}",
            f"开球：{leg.get('start')}（上海）",
            f"玩法：{play}" + (f"，{detail}" if detail else ""),
            f"选项：{selection}",
            f"赔率：{leg.get('odds')}",
            f"结算：{settle}" if settle else "",
            f"占用：该选项约 {money(float(leg.get('occupy_usd') or DAILY_CAP_USD))}（当日总额度 {money(DAILY_CAP_USD)}）",
        ]
    ).replace("\n\n", "\n")


def format_ticket(index: int, ticket: dict[str, Any]) -> str:
    roi = ticket.get("roi_pct", round((ticket["odds"] - 1) * 100, 1))
    lines = [
        f"======== 票{index} {ticket.get('pair') or ticket['kind']} {ticket['kind']} ========",
        f"组合赔率：{ticket['odds']} · 回报率：{roi}%（须不低于 {MIN_TICKET_ODDS:.2f}）",
        f"本金：{money(ticket['stake_usd'])}",
        f"全中回本：{money(ticket['return_usd'])} · 盈：{money(ticket['profit_usd'], True)}",
        "",
    ]
    for i, leg in enumerate(ticket["legs"], 1):
        lines.append(format_leg(i, leg))
        lines.append("")
    return "\n".join(lines).rstrip()


def empty_picks_reason(card: dict[str, Any]) -> str:
    """区分：验证驳回 vs 根本没组出票（避免误报「指数或新闻冲突」）。"""
    dropped = [str(x).strip() for x in (card.get("verify_dropped") or []) if str(x).strip()]
    if dropped:
        return "验证未通过，本轮不发单。\n" + "；".join(dropped)
    detail = str(card.get("empty_reason") or "").strip()
    if detail:
        return detail
    return (
        f"本轮未组出推荐单：未来{PICKS_HORIZON_HOURS}小时内，"
        f"没有组合赔率不低于{MIN_TICKET_ODDS:.2f}的可执行串"
        "（常见原因：关注赛事未进快照、盘口不在赔率带、或可串场次不足2场）。"
    )


def format_picks(card: dict[str, Any], title: str) -> str:
    tickets = card.get("tickets") or []
    if not tickets:
        return f"{title}\n{empty_picks_reason(card)}"
    roi = (
        round((card["return_usd"] / card["stake_usd"] - 1) * 100, 1)
        if card.get("stake_usd")
        else 0
    )
    lines = [
        title,
        f"共 {len(tickets)} 张票 · 总本金 {money(card['stake_usd'])}",
        f"全部打出：回本 {money(card['return_usd'])} · 盈 {money(card['profit_usd'], True)} · 回报率 {roi}%",
        f"每天 {MAX_TICKETS} 个串子，每张组合赔率不低于 {MIN_TICKET_ODDS:.2f}。",
        f"当日总本金上限 {money(DAILY_CAP_USD)}，{len(tickets)} 张均分，不是每张再下 $200。",
        "玩法从 1x2(1up)/平局返还/双胜彩/赢任何半场里按风险分散选，不设优先级；每场一口，尽量错开盘种。开球时段不拆。",
        "",
    ]
    seen: set[str] = set()
    legend: list[str] = []
    for ticket in tickets:
        for leg in ticket.get("legs") or []:
            code = str(leg.get("code") or "")
            if code and code not in seen:
                seen.add(code)
                legend.append(f"{code} = {leg.get('option')}")
    if legend:
        lines.append("编号：" + "；".join(legend))
        lines.append("")
    if card.get("verified_at"):
        lines.append("=== 验证 ===")
        for ticket in tickets:
            report = ticket.get("verify") or {}
            lines.append(f"{ticket.get('pair') or ticket.get('kind')}：{report.get('verdict') or '未验'} · {report.get('summary') or ''}")
            for leg in ticket.get("legs") or []:
                v = leg.get("verify") or {}
                if v.get("summary"):
                    lines.append(f"  {leg.get('code')} {v['summary']}")
        if card.get("verify_dropped"):
            lines.append("驳回未发：" + "；".join(card["verify_dropped"]))
        lines.append("")
    for i, ticket in enumerate(tickets, 1):
        lines.append(format_ticket(i, ticket))
        lines.append("")
    return "\n".join(lines).strip()


def picks_changed(prev: dict[str, Any], cur: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    old = {item: True for item in prev.get("options") or []}
    new = {item: True for item in cur.get("options") or []}
    if set(old) != set(new):
        dropped = [k.split("@", 1)[0] for k in old if k not in new]
        added = [k.split("@", 1)[0] for k in new if k not in old]
        if dropped:
            reasons.append("撤 " + "、".join(dropped[:4]))
        if added:
            reasons.append("换 " + "、".join(added[:4]))
        return reasons or ["结构有变"]

    old_odds = {
        leg["market"] + "@" + leg["match_id"]: float(leg["odds"])
        for t in prev.get("tickets") or []
        for leg in t.get("legs") or []
    }
    for ticket in cur.get("tickets") or []:
        for leg in ticket.get("legs") or []:
            key = leg["market"] + "@" + leg["match_id"]
            before = old_odds.get(key)
            if before is None:
                continue
            after = float(leg["odds"])
            if abs(after - before) >= threshold(min(before, after)):
                direction = "降水" if after < before else "升水"
                home, away = match_teams(str(leg.get("match") or ""))
                favor = favor_text(after - before, quote_effect(str(leg.get("market") or ""), home, away))
                reasons.append(f"{direction} {leg['option']} {before}→{after} · {favor}")
    return reasons


def write_picks(card: dict[str, Any]) -> None:
    SNAP_DIR.mkdir(exist_ok=True)
    (SNAP_DIR / "latest_picks.json").write_text(
        json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (SNAP_DIR / "latest_picks.txt").write_text(
        format_picks(card, f"Stake 推荐单 · {card.get('slot')} · {card.get('ts')}"),
        encoding="utf-8",
    )


def notify_picks(config: dict[str, Any], snap: dict[str, Any], force: bool = False) -> None:
    ensure_shadowrocket()
    slot = snap.get("slot") or ""
    now = datetime.now(tz=TZ)
    card = build_picks(snap, now)
    verify_enabled = bool((config.get("odds_tracker") or {}).get("verify_picks", True))
    if verify_enabled and (card.get("tickets") or []):
        from pick_verify import apply_verification

        card = apply_verification(card)
    prev_path = SNAP_DIR / "latest_picks.json"
    prev = load_json(prev_path) if prev_path.exists() else {}

    early_cutoff = now.replace(hour=22, minute=0, second=0, microsecond=0)
    has_early = any(
        (start := parse_start(m.get("start"))) and now < start <= early_cutoff
        for m in (snap.get("matches") or [])
        if not skip_match(str(m.get("name") or ""))
    )

    send = False
    title = ""
    body = ""
    if force or slot == "晚盘":
        send = True
        title = f"Stake 推荐单 · {slot}"
        body = format_picks(card, title)
    elif slot == "临场" and prev:
        reasons = picks_changed(prev, card)
        if reasons:
            send = True
            title = f"Stake 推荐修订 · {slot}"
            body = "修订：" + "；".join(reasons) + "\n\n" + format_picks(card, title)
    elif slot == "欧早" and has_early:
        early_snap = {
            **snap,
            "matches": [
                m
                for m in (snap.get("matches") or [])
                if (start := parse_start(m.get("start"))) and now < start <= early_cutoff
            ],
        }
        card = build_picks(early_snap, now)
        if verify_enabled and (card.get("tickets") or []):
            from pick_verify import apply_verification

            card = apply_verification(card)
        send = True
        title = "Stake 早场推荐 · 欧早"
        body = format_picks(card, title)

    # 空票时统一走 empty_picks_reason：有驳回才说验证未通过，否则说明组单失败原因
    if send and not (card.get("tickets") or []):
        body = f"{title}\n{empty_picks_reason(card)}"

    if send or force or slot in {"晚盘", "临场"}:
        write_picks(card)
    if not send:
        return
    try:
        send_notifications(config, title, body)
        print(f"已推送：{title}")
    except Exception as exc:  # noqa: BLE001
        print(f"推荐单通知失败: {exc}")


def write_report(path: Path, snap: dict[str, Any], moves: list[dict[str, Any]]) -> None:
    lines = [
        f"Stake 指数快照 · {snap['slot']} · {snap['ts']}",
        f"场次 {len(snap.get('matches') or [])} · 异动 {len(moves)}",
        "",
    ]
    if moves:
        lines.append("=== 指数异动 ===")
        for name, items in group_moves(moves):
            lines.append(f"【{name}】{match_verdict(items)}")
            for item in items:
                lines.append(format_move_line(item, "  "))
        lines.append("")
    lines.append("=== 当前盘口 ===")
    for match in snap.get("matches") or []:
        lines.append(f"{match['start']} [{match['tournament']}] {match['name']}")
        quotes = match.get("quotes") or {}
        if not quotes:
            lines.append("  （未取到指定盘口）")
            continue
        for key, price in quotes.items():
            lines.append(f"  {key}: {price}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def run(config: dict[str, Any]) -> dict[str, Any]:
    SNAP_DIR.mkdir(exist_ok=True)
    token = resolve_token(config)
    hours = int((config.get("odds_tracker") or {}).get("hours", 48))
    limit = int((config.get("odds_tracker") or {}).get("max_fixtures", 20))
    now = datetime.now(tz=TZ)
    ensure_shadowrocket()
    chrome_ensure_stake_tab()
    fixtures = collect_fixtures(token, hours, limit)
    matches: list[dict[str, Any]] = []
    for item in fixtures:
        try:
            data = gql(QUERY_MARKETS, {"id": item["id"]}, token)
            fx = data.get("sportFixture") or {}
            item["quotes"] = extract_quotes(fx)
        except Exception as exc:  # noqa: BLE001
            item["quotes"] = {}
            item["error"] = str(exc)
        matches.append(item)
        time.sleep(0.15)

    snap = {
        "ts": now.isoformat(),
        "slot": slot_name(now),
        "matches": matches,
    }
    latest_path = SNAP_DIR / "latest.json"
    prev = load_json(latest_path) if latest_path.exists() else {}
    moves = diff_quotes(prev, snap) if prev else []
    snap["moves"] = moves

    stamp = now.strftime("%Y%m%d_%H%M")
    (SNAP_DIR / f"{stamp}_{snap['slot']}.json").write_text(
        json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    latest_path.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    with (SNAP_DIR / "history.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": snap["ts"], "slot": snap["slot"], "n": len(matches), "moves": len(moves)}, ensure_ascii=False) + "\n")
    write_report(SNAP_DIR / "latest.txt", snap, moves)

    extra = Path("/Users/caozhongyuan/football-odds-db/stake_odds_snapshots.jsonl")
    if extra.parent.exists():
        with extra.open("a", encoding="utf-8") as f:
            f.write(json.dumps(snap, ensure_ascii=False) + "\n")

    if moves:
        body = format_moves_alert(moves)
        try:
            send_notifications(config, f"Stake 指数异动 · {snap['slot']}", body)
        except Exception as exc:  # noqa: BLE001
            print(f"通知失败: {exc}")

    notify_picks(config, snap)

    print(f"{snap['slot']} 完成：{len(matches)} 场，异动 {len(moves)} 条。报告: {SNAP_DIR / 'latest.txt'}")
    return snap


def main() -> None:
    parser = argparse.ArgumentParser(description="Stake 指数定时快照")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--picks", action="store_true", help="根据最新快照立刻生成并推送推荐单")
    args = parser.parse_args()
    if not args.config.exists():
        raise SystemExit(f"找不到配置: {args.config}")
    config = load_json(args.config)
    if args.picks:
        latest = SNAP_DIR / "latest.json"
        if not latest.exists():
            raise SystemExit("还没有快照，先跑一次 python3 odds_tracker.py")
        notify_picks(config, load_json(latest), force=True)
        return
    run(config)


if __name__ == "__main__":
    main()
