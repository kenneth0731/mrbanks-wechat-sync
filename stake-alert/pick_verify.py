#!/usr/bin/env python3
"""推单前验证：Stake 快照指数 + 本地历史库 + 近期新闻。"""

from __future__ import annotations

import json
import sqlite3
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
SNAP_DIR = ROOT / "odds_snapshots"
TZ = None  # filled on first use

ODDS_DB = Path("/Users/caozhongyuan/football-odds-db/football_odds.sqlite")
NEWS_CACHE = SNAP_DIR / "news_cache.json"
CACHE_HOURS = 12

TEAM_EN = {
    "斯洛伐克": "Slovakia",
    "哈萨克斯坦": "Kazakhstan",
    "苏格兰": "Scotland",
    "瑞士": "Switzerland",
    "芬兰": "Finland",
    "白俄罗斯": "Belarus",
    "卢森堡": "Luxembourg",
    "冰岛": "Iceland",
    "斯洛文尼亚": "Slovenia",
    "北马其顿": "North Macedonia",
    "保加利亚": "Bulgaria",
    "爱沙尼亚": "Estonia",
    "西班牙": "Spain",
    "克罗地亚": "Croatia",
    "英格兰": "England",
    "捷克": "Czech Republic",
    "法国": "France",
    "比利时": "Belgium",
    "德国": "Germany",
    "意大利": "Italy",
    "荷兰": "Netherlands",
    "丹麦": "Denmark",
    "奥地利": "Austria",
    "葡萄牙": "Portugal",
    "塞尔维亚": "Serbia",
    "希腊": "Greece",
    "威尔士": "Wales",
    "挪威": "Norway",
    "以色列": "Israel",
    "科索沃": "Kosovo",
    "爱尔兰": "Republic of Ireland",
    "爱尔兰共和国": "Republic of Ireland",
    "北爱尔兰": "Northern Ireland",
    "土耳其": "Turkey",
    "匈牙利": "Hungary",
    "格鲁吉亚": "Georgia",
    "乌克兰": "Ukraine",
    "波兰": "Poland",
    "罗马尼亚": "Romania",
    "瑞典": "Sweden",
    "波黑": "Bosnia and Herzegovina",
    "波斯尼亚": "Bosnia and Herzegovina",
}

NEG_NEWS = (
    "ruled out",
    "out for",
    "suspended",
    "injury blow",
    "muscle injury",
    "hamstring",
    "withdrawn",
    "late withdrawal",
    "doubt",
    "sidelined",
    "停赛",
    "伤缺",
    "无缘",
    "退赛",
    "重伤",
)
POS_NEWS = (
    "to win",
    "favorites",
    "favourite",
    "boost",
    "returns",
    "fit to play",
    "can stroll",
    "back-to-back",
)


def _tz():
    global TZ
    if TZ is None:
        from odds_tracker import TZ as _TZ

        TZ = _TZ
    return TZ


def _now() -> datetime:
    return datetime.now(tz=_tz())


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _team_en(name: str) -> str:
    return TEAM_EN.get(name, name)


def _match_teams(name: str) -> tuple[str, str]:
    from odds_tracker import match_teams

    return match_teams(name)


def _quote_effect(key: str, home: str, away: str):
    from odds_tracker import quote_effect

    return quote_effect(key, home, away)


def _collect_history() -> list[dict[str, Any]]:
    snaps: list[dict[str, Any]] = []
    for path in sorted(SNAP_DIR.glob("20*.json")) + [SNAP_DIR / "latest.json"]:
        if not path.exists():
            continue
        data = _load_json(path)
        if data.get("matches"):
            snaps.append(data)
    extra = Path("/Users/caozhongyuan/football-odds-db/stake_odds_snapshots.jsonl")
    if extra.exists():
        for line in extra.read_text(encoding="utf-8").splitlines()[-20:]:
            try:
                snaps.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    snaps.sort(key=lambda s: str(s.get("ts") or ""))
    return snaps


def index_check(leg: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    mid = str(leg.get("match_id") or "")
    market = str(leg.get("market") or "")
    home, away = _match_teams(str(leg.get("match") or ""))
    team = str(leg.get("team") or "")
    # 只看近 36 小时快照，避免跨天漂移把正常波动判成驳回
    cutoff = (_now() - timedelta(hours=36)).isoformat()
    series: list[tuple[str, float]] = []
    for snap in history:
        ts = str(snap.get("ts") or "")
        if ts and ts < cutoff:
            continue
        for match in snap.get("matches") or []:
            if str(match.get("id") or "") != mid:
                continue
            quotes = match.get("quotes") or {}
            if market in quotes:
                series.append((ts[:16], float(quotes[market])))
            break
    note = "快照里还没有这条盘口的历史"
    verdict = "存疑"
    if len(series) >= 2:
        first, last = series[0][1], series[-1][1]
        delta = round(last - first, 3)
        effect = _quote_effect(market, home, away)
        toward = any(
            name == team and ((delta < 0 and sign > 0) or (delta > 0 and sign < 0))
            for name, sign in effect
        )
        against = any(
            name == team and ((delta < 0 and sign < 0) or (delta > 0 and sign > 0))
            for name, sign in effect
        )
        if toward and abs(delta) >= 0.05:
            note = f"Stake {series[0][1]}→{series[-1][1]}，指数偏向{team or '所选'}"
            verdict = "通过"
        elif against and abs(delta) >= 0.12:
            note = f"Stake {series[0][1]}→{series[-1][1]}，指数离开{team or '所选'}"
            verdict = "驳回"
        elif against and abs(delta) >= 0.05:
            note = f"Stake {series[0][1]}→{series[-1][1]}，指数略离开{team}"
            verdict = "存疑"
        else:
            note = f"Stake {series[0][1]}→{series[-1][1]}，指数平稳"
            verdict = "通过"
    elif len(series) == 1:
        note = f"仅有当前价 {series[0][1]}，尚无对照快照"
        verdict = "通过"
    return {"verdict": verdict, "note": note, "series": series[-4:]}


def db_check(leg: dict[str, Any]) -> dict[str, Any]:
    home, away = _match_teams(str(leg.get("match") or ""))
    home_en, away_en = _team_en(home), _team_en(away)
    team = str(leg.get("team") or "")
    team_en = _team_en(team)
    if not ODDS_DB.exists():
        return {"verdict": "存疑", "note": "找不到历史指数库"}
    try:
        con = sqlite3.connect(f"file:{ODDS_DB}?mode=ro", uri=True)
    except sqlite3.Error:
        try:
            con = sqlite3.connect(str(ODDS_DB))
        except sqlite3.Error as exc:
            return {"verdict": "存疑", "note": f"历史库打不开：{exc}"}
    try:
        rows = con.execute(
            """
            SELECT match_date, home_team, away_team, FTHG, FTAG, FTR
            FROM matches
            WHERE (home_team=? AND away_team=?) OR (home_team=? AND away_team=?)
            ORDER BY match_date DESC
            LIMIT 8
            """,
            (home_en, away_en, away_en, home_en),
        ).fetchall()
    except sqlite3.Error as exc:
        return {"verdict": "存疑", "note": f"历史库查询失败：{exc}"}
    finally:
        con.close()
    if not rows:
        return {"verdict": "通过", "note": "历史库是俱乐部赛，无这场国际比赛对阵"}
    wins = 0
    played = 0
    recs = []
    for date, h, a, hg, ag, ftr in rows:
        played += 1
        recs.append(f"{date} {h} {hg}-{ag} {a}")
        if team_en and ((h == team_en and ftr == "H") or (a == team_en and ftr == "A")):
            wins += 1
    if played >= 3 and wins == 0:
        return {"verdict": "存疑", "note": f"近{played}次交手{team}未赢：{'；'.join(recs[:3])}"}
    return {"verdict": "通过", "note": f"库内近{played}次：{'；'.join(recs[:3])}"}


def _cache_get(key: str) -> list[dict[str, str]]:
    cache = _load_json(NEWS_CACHE)
    item = cache.get(key) or {}
    ts = str(item.get("ts") or "")
    try:
        when = datetime.fromisoformat(ts)
        if when.tzinfo is None:
            when = when.replace(tzinfo=_tz())
        if _now() - when <= timedelta(hours=CACHE_HOURS):
            return list(item.get("headlines") or [])
    except ValueError:
        return []
    return []


def _cache_put(key: str, headlines: list[dict[str, str]]) -> None:
    SNAP_DIR.mkdir(exist_ok=True)
    cache = _load_json(NEWS_CACHE)
    cache[key] = {"ts": _now().isoformat(), "headlines": headlines}
    NEWS_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _http_get(url: str, timeout: int = 5) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _parse_google_rss(raw: bytes) -> list[dict[str, str]]:
    root = ET.fromstring(raw)
    items: list[dict[str, str]] = []
    for node in root.findall(".//item")[:6]:
        title = (node.findtext("title") or "").strip()
        if title:
            items.append({"title": title, "date": (node.findtext("pubDate") or "")[:22]})
    return items


def _parse_bing_html(raw: bytes) -> list[dict[str, str]]:
    import re

    text = raw.decode("utf-8", errors="replace")
    titles = re.findall(r'title="([^"]{20,180})"', text)
    seen: set[str] = set()
    items: list[dict[str, str]] = []
    for title in titles:
        title = title.replace("&amp;", "&").replace("&#39;", "'").strip()
        if title in seen or title.lower().startswith("bing"):
            continue
        seen.add(title)
        items.append({"title": title, "date": ""})
        if len(items) >= 6:
            break
    return items


def fetch_news(query: str) -> list[dict[str, str]]:
    cached = _cache_get(query)
    if cached:
        return cached
    from stake import ensure_shadowrocket

    ensure_shadowrocket()
    items: list[dict[str, str]] = []
    google = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"}
    )
    bing = "https://www.bing.com/news/search?" + urllib.parse.urlencode({"q": query})
    try:
        items = _parse_google_rss(_http_get(google, 5))
    except Exception:
        items = []
    if not items:
        try:
            items = _parse_bing_html(_http_get(bing, 6))
        except Exception:
            items = []
    if items:
        _cache_put(query, items)
    return items


def _news_competition(leg: dict[str, Any]) -> str:
    tour = str(leg.get("tournament") or "")
    keys = (
        ("欧国联", "Nations League"),
        ("国家联赛", "Nations League"),
        ("Nations League", "Nations League"),
        ("冠军联赛", "Champions League"),
        ("欧洲联赛", "Europa League"),
        ("英超", "Premier League"),
        ("西甲", "La Liga"),
        ("德甲", "Bundesliga"),
        ("意甲", "Serie A"),
        ("法甲", "Ligue 1"),
    )
    for needle, label in keys:
        if needle in tour:
            return label
    return "football"


def news_check(leg: dict[str, Any]) -> dict[str, Any]:
    home, away = _match_teams(str(leg.get("match") or ""))
    team = str(leg.get("team") or "")
    query = f"{_team_en(home)} vs {_team_en(away)} {_news_competition(leg)}"
    headlines = fetch_news(query)
    if not headlines:
        cached = _cache_get(str(leg.get("match") or query))
        headlines = cached
    if not headlines:
        return {"verdict": "存疑", "note": "未取到近况新闻", "headlines": []}
    blob = " ".join(h["title"].lower() for h in headlines)
    team_en = _team_en(team).lower()
    # 负面词必须同时命中所选队名，避免把对面伤停算到本队头上
    neg = sum(1 for w in NEG_NEWS if w in blob and team_en and team_en in blob)
    pos = sum(1 for w in POS_NEWS if w in blob)
    titles = "；".join(h["title"][:48] for h in headlines[:2])
    if neg >= 3 and pos == 0:
        return {"verdict": "驳回", "note": f"新闻偏空：{titles}", "headlines": headlines[:4]}
    if neg >= 2:
        return {"verdict": "存疑", "note": f"有伤停/缺阵：{titles}", "headlines": headlines[:4]}
    if pos:
        return {"verdict": "通过", "note": f"新闻未推翻所选：{titles}", "headlines": headlines[:4]}
    return {"verdict": "通过", "note": f"近况：{titles}", "headlines": headlines[:4]}


def _worse(a: str, b: str) -> str:
    rank = {"通过": 0, "存疑": 1, "驳回": 2}
    return a if rank.get(a, 0) >= rank.get(b, 0) else b


def verify_leg(leg: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    idx = index_check(leg, history)
    db = db_check(leg)
    news = news_check(leg)
    verdict = "通过"
    for part in (idx, db, news):
        verdict = _worse(verdict, part["verdict"])
    return {
        "verdict": verdict,
        "index": idx,
        "db": db,
        "news": news,
        "summary": f"{verdict}｜指数 {idx['note']}｜库 {db['note']}｜新闻 {news['note']}",
    }


def verify_ticket(ticket: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    legs = []
    verdict = "通过"
    for leg in ticket.get("legs") or []:
        row = verify_leg(leg, history)
        leg["verify"] = row
        legs.append(row)
        verdict = _worse(verdict, row["verdict"])
    return {
        "verdict": verdict,
        "pair": ticket.get("pair") or ticket.get("kind"),
        "legs": legs,
        "summary": "；".join(f"{(ticket.get('legs') or [{}])[i].get('code', i+1)} {r['verdict']}" for i, r in enumerate(legs)),
    }


def apply_verification(card: dict[str, Any]) -> dict[str, Any]:
    history = _collect_history()
    kept: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    dropped: list[str] = []
    prior_empty = str(card.get("empty_reason") or "")
    for ticket in card.get("tickets") or []:
        report = verify_ticket(ticket, history)
        ticket["verify"] = report
        reports.append(report)
        if report["verdict"] == "驳回":
            dropped.append(f"{ticket.get('pair') or ticket.get('kind')} {report['summary']}")
            continue
        kept.append(ticket)
    from odds_tracker import scale_to_daily_cap

    card["tickets"] = scale_to_daily_cap(kept) if kept else []
    if card["tickets"]:
        card["stake_usd"] = round(sum(float(t["stake_usd"]) for t in card["tickets"]), 2)
        card["return_usd"] = round(sum(float(t["return_usd"]) for t in card["tickets"]), 2)
        card["profit_usd"] = round(card["return_usd"] - card["stake_usd"], 2)
        card["options"] = [
            leg["market"] + "@" + leg["match_id"] for t in card["tickets"] for leg in t["legs"]
        ]
        card.pop("empty_reason", None)
    else:
        card["stake_usd"] = 0
        card["return_usd"] = 0
        card["profit_usd"] = 0
        card["options"] = []
        if dropped:
            card["empty_reason"] = "验证未通过，本轮不发单。\n" + "；".join(dropped)
        elif prior_empty:
            card["empty_reason"] = prior_empty
    card["verify_reports"] = reports
    card["verify_dropped"] = dropped
    card["verified_at"] = _now().isoformat()
    return card
