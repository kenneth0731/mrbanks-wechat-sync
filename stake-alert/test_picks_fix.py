#!/usr/bin/env python3
"""回归：晚盘空票误报、欧国联赛事名、空票诊断。"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from odds_tracker import (
    TZ,
    build_picks,
    empty_picks_reason,
    format_picks,
    wanted_tournament,
)
from pick_verify import _news_competition, apply_verification


def test_nations_league_aliases() -> None:
    assert wanted_tournament("欧洲国家联赛")
    assert wanted_tournament("欧国联 - A联赛")
    assert wanted_tournament("UEFA Nations League")
    assert wanted_tournament("欧足联国家联赛")
    assert wanted_tournament("欧足协国际联赛")
    assert not wanted_tournament("英格兰冠军联赛")


def test_empty_message_not_fake_verify() -> None:
    card = {
        "tickets": [],
        "verify_dropped": [],
        "empty_reason": "本轮未组出推荐单：快照里没有关注赛事场次。",
    }
    text = empty_picks_reason(card)
    assert "验证未通过" not in text
    assert "指数或新闻与选项冲突" not in text
    assert "未组出推荐单" in text
    body = format_picks(card, "Stake 推荐单 · 晚盘")
    assert "指数或新闻与选项冲突" not in body


def test_verify_dropped_still_says_failed() -> None:
    card = {
        "tickets": [],
        "verify_dropped": ["AB A 驳回；B 通过"],
    }
    text = empty_picks_reason(card)
    assert text.startswith("验证未通过")
    assert "AB A 驳回" in text


def test_diagnose_zero_matches() -> None:
    now = datetime(2026, 10, 1, 20, 30, tzinfo=TZ)
    card = build_picks({"slot": "晚盘", "matches": []}, now)
    assert card["tickets"] == []
    assert "没有关注赛事" in card["empty_reason"]


def test_diagnose_too_few_candidates() -> None:
    now = datetime(2026, 10, 1, 20, 30, tzinfo=TZ)
    start = (now + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")
    matches = [
        {
            "id": "m1",
            "name": "德国 - 塞尔维亚",
            "tournament": "欧洲国家联赛",
            "start": start,
            "quotes": {},
        },
        {
            "id": "m2",
            "name": "丹麦 - 葡萄牙",
            "tournament": "欧洲国家联赛",
            "start": start,
            "quotes": {"1x2 (1up)|丹麦": 1.28, "1x2 (1up)|葡萄牙": 3.8},
        },
    ]
    card = build_picks({"slot": "晚盘", "matches": matches}, now)
    assert card["tickets"] == []
    reason = card["empty_reason"]
    assert "可串场次不足" in reason or "未组出推荐单" in reason


def test_build_parlay_with_nations_league_quotes() -> None:
    now = datetime(2026, 10, 1, 20, 30, tzinfo=TZ)
    start = (now + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")
    matches = [
        {
            "id": "g1",
            "name": "德国 - 塞尔维亚",
            "tournament": "欧洲国家联赛",
            "start": start,
            "quotes": {
                "1x2 (1up)|德国": 1.22,
                "1x2 (1up)|塞尔维亚": 4.5,
                "平局返还|德国": 1.35,
            },
        },
        {
            "id": "g2",
            "name": "希腊 - 荷兰",
            "tournament": "欧洲国家联赛",
            "start": start,
            "quotes": {
                "1x2 (1up)|荷兰": 1.30,
                "1x2 (1up)|希腊": 3.9,
                "双胜彩|荷兰或平局": 1.28,
            },
        },
        {
            "id": "g3",
            "name": "丹麦 - 葡萄牙",
            "tournament": "欧洲国家联赛",
            "start": start,
            "quotes": {
                "1x2 (1up)|葡萄牙": 1.26,
                "1x2 (1up)|丹麦": 4.1,
                "平局返还|葡萄牙": 1.33,
            },
        },
        {
            "id": "g4",
            "name": "威尔士 - 挪威",
            "tournament": "欧洲国家联赛",
            "start": start,
            "quotes": {
                "1x2 (1up)|挪威": 1.32,
                "1x2 (1up)|威尔士": 3.6,
                "双胜彩|挪威或平局": 1.25,
            },
        },
        {
            "id": "g5",
            "name": "爱尔兰 - 奥地利",
            "tournament": "欧洲国家联赛",
            "start": start,
            "quotes": {
                "1x2 (1up)|奥地利": 1.29,
                "1x2 (1up)|爱尔兰": 3.8,
                "平局返还|奥地利": 1.34,
            },
        },
        {
            "id": "g6",
            "name": "以色列 - 科索沃",
            "tournament": "欧洲国家联赛",
            "start": start,
            "quotes": {
                "1x2 (1up)|以色列": 1.31,
                "1x2 (1up)|科索沃": 3.7,
                "双胜彩|以色列或平局": 1.27,
            },
        },
    ]
    card = build_picks({"slot": "晚盘", "matches": matches}, now)
    assert card["tickets"], card.get("empty_reason")
    assert len(card["tickets"]) >= 1
    for ticket in card["tickets"]:
        assert float(ticket["odds"]) >= 1.70


def test_news_competition_from_tournament() -> None:
    assert _news_competition({"tournament": "欧洲国家联赛"}) == "Nations League"
    assert _news_competition({"tournament": "英超"}) == "Premier League"
    assert _news_competition({"tournament": "友谊赛"}) == "football"


def test_apply_verification_preserves_empty_reason() -> None:
    card = {
        "tickets": [],
        "empty_reason": "本轮未组出推荐单：快照里没有关注赛事场次。",
    }
    out = apply_verification(card)
    assert out["tickets"] == []
    assert out["verify_dropped"] == []
    assert "没有关注赛事" in out["empty_reason"]


if __name__ == "__main__":
    # TZ 在 stake 里可能是固定上海时区；测试环境无 stake 时用 ZoneInfo 兜底
    assert TZ is not None or ZoneInfo("Asia/Shanghai")
    tests = [
        test_nations_league_aliases,
        test_empty_message_not_fake_verify,
        test_verify_dropped_still_says_failed,
        test_diagnose_zero_matches,
        test_diagnose_too_few_candidates,
        test_build_parlay_with_nations_league_quotes,
        test_news_competition_from_tournament,
        test_apply_verification_preserves_empty_reason,
    ]
    for fn in tests:
        fn()
        print(f"ok {fn.__name__}")
    print("all passed")
