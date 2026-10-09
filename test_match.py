#!/usr/bin/env python3
"""匹配规则单元测试：welcome code / Bet responsibly。"""

from __future__ import annotations

from sync import (
    NEEDLE_BET_RESPONSIBLY,
    NEEDLE_WELCOME,
    matched_needles,
    matches,
    resolve_needles,
)


def test_welcome_still_matches() -> None:
    text = "Promo: Use welcome code banks for weekly airdrops and bonuses today"
    assert matches(text, NEEDLE_WELCOME)
    assert matched_needles(text, list(resolve_needles({}))) == [NEEDLE_WELCOME]


def test_bet_responsibly_matches() -> None:
    text = "Stake $50 now. Bet responsibly. Odds may change."
    assert matches(text, NEEDLE_BET_RESPONSIBLY)
    hit = matched_needles(text, list(resolve_needles({})))
    assert hit == [NEEDLE_BET_RESPONSIBLY]


def test_either_trigger_is_enough() -> None:
    needles = resolve_needles({})
    assert matched_needles("please Bet Responsibly guys", needles)
    assert matched_needles(
        "Use welcome code banks for weekly airdrops and bonuses",
        needles,
    )
    assert not matched_needles("random tip with no keyword", needles)


def test_old_filter_config_auto_adds_bet_responsibly() -> None:
    needles = resolve_needles({"filter": NEEDLE_WELCOME})
    assert len(needles) == 2
    assert any(n.lower() == NEEDLE_BET_RESPONSIBLY for n in needles)


def test_filters_list_respected() -> None:
    needles = resolve_needles({"filters": ["Bet responsibly"]})
    assert needles == ["Bet responsibly"]


if __name__ == "__main__":
    test_welcome_still_matches()
    test_bet_responsibly_matches()
    test_either_trigger_is_enough()
    test_old_filter_config_auto_adds_bet_responsibly()
    test_filters_list_respected()
    print("ok")
