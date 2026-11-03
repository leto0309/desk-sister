"""Playing Balatro through the BalatroBot mod: the local link, what the model is told and may do, and the pet's flow."""
import json
import random
import threading
import zipfile
import zlib
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from claude_pet import balatro, balatro_names, claude_client, i18n
from claude_pet.balatro import Action, LinkError
from claude_pet.config import Config

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from claude_pet import controller as controller_module  # noqa: E402

SPRITES = Path(__file__).resolve().parents[1] / "assets" / "sprites"


def card(key, set_="DEFAULT", label=None, effect="", cost=None, **modifier):
    suit, rank = (key.split("_") + [""])[:2] if set_ in ("DEFAULT", "ENHANCED") else ("", "")
    return {"key": key, "set": set_, "label": label or key, "value": {"suit": suit, "rank": rank, "effect": effect},
            "modifier": modifier or [], "state": [], "cost": cost or {"buy": 0, "sell": 1}}


def area(*cards_):
    return {"count": len(cards_), "cards": list(cards_)}


def hand_state(keys=("S_K", "H_K", "D_7", "C_2", "H_9"), discards=3, **extra):
    state = {"state": "SELECTING_HAND", "ante_num": 2, "round_num": 4, "money": 7, "won": False,
             "round": {"hands_left": 4, "discards_left": discards, "chips": 120, "reroll_cost": 5},
             "blinds": {"small": {"type": "SMALL", "status": "DEFEATED", "name": "Small Blind", "score": 800},
                        "big": {"type": "BIG", "status": "CURRENT", "name": "Big Blind", "score": 1200,
                                "effect": "No special effect"}},
             "hands": {"Pair": {"level": 3, "chips": 40, "mult": 4}, "Flush": {"level": 1, "chips": 35, "mult": 4}},
             "hand": area(*(card(k) for k in keys)),
             "jokers": area(card("j_joker", "JOKER", "Joker", "+4 Mult", {"buy": 2, "sell": 1})),
             "consumables": area(card("c_lovers", "TAROT", "The Lovers", "Enhance 2 cards"))}
    state.update(extra)
    return state


def shop_state():
    return {"state": "SHOP", "ante_num": 2, "round_num": 5, "money": 9, "won": False, "round": {"reroll_cost": 5},
            "hand": area(card("S_A")),
            "shop": area(card("j_smiley", "JOKER", "Smiley Face", "+5 Mult per face card", {"buy": 4, "sell": 2}),
                         card("c_mars", "PLANET", "Mars", "Level up Four of a Kind", {"buy": 3, "sell": 1})),
            "vouchers": area(card("v_grabber", "VOUCHER", "Grabber", "+1 hand", {"buy": 10, "sell": 0})),
            "packs": area(card("p_arcana_normal_1", "BOOSTER", "Arcana Pack", "", {"buy": 4, "sell": 0})),
            "jokers": area(card("j_joker", "JOKER", "Joker")), "consumables": area()}


def pack_state():
    return {"state": "SMODS_BOOSTER_OPENED", "ante_num": 1, "round": {}, "hand": area(card("S_A"), card("H_2")),
            "pack": area(card("j_a", "JOKER", "A"), card("j_b", "JOKER", "B"))}


@pytest.fixture(autouse=True)
def no_game_names(monkeypatch):
    """Not the copy of Balatro on the machine running the tests."""
    monkeypatch.setattr(balatro_names, "load", dict)
    balatro.set_names({})
    yield
    balatro.set_names({})


GAME_FILES = {
    "localization/en-us.lua": """return { descriptions = { Joker = { j_riff_raff = { name = "Riff-Raff", text = {"x"} },
        j_joker = { name = "Joker", text = {} }, j_long = { name = "Long" }, j_new = { name = "Only In English" } },
        Blind = { bl_wheel = { name = "The Wheel", text = {} } } },
        misc = { dictionary = { poker_hands = "Poker Hands" },
                 poker_hands = { ["Two Pair"] = "Two Pair", Flush = "Flush", Pair = "Pair" } } }""",
    "localization/zh_CN.lua": f"""return {{ descriptions = {{ Joker = {{ j_riff_raff = {{ name = "乌合之众", text = {{"x"}} }},
        j_joker = {{ name = "小丑", text = {{}} }}, j_long = {{ name = "{'长' * 31}" }} }},
        Blind = {{ bl_wheel = {{ name = "车轮", text = {{}} }} }} }},
        misc = {{ dictionary = {{ poker_hands = "牌型" }},
                  poker_hands = {{ ["Two Pair"] = "两对", Flush = "同花", Pair = "对子" }} }} }}""",
}


def fake_game(path, files=None):
    with zipfile.ZipFile(path, "w") as archive:
        for name, text in (GAME_FILES if files is None else files).items():
            archive.writestr(name, text)
    return path


def test_the_names_come_from_the_game_on_this_pc(tmp_path):
    names = balatro_names.read_names(fake_game(tmp_path / "Balatro.exe"))
    assert names["j_riff_raff"] == names["Riff-Raff"] == "乌合之众" and names["The Wheel"] == "车轮"
    assert names["Two Pair"] == "两对" and names["Flush"] == "同花" and names["Pair"] == "对子"
    assert "Only In English" not in names and "Long" not in names  # not translated; too long to be a name
    assert "dictionary" not in names and "poker_hands" not in names


@pytest.mark.parametrize("files", [{}, {"localization/en-us.lua": "x"}, {"localization/en-us.lua": "x", "localization/zh_CN.lua": b"\xff\xfe"}])
def test_a_game_without_readable_names_gives_none(tmp_path, files):
    assert balatro_names.read_names(fake_game(tmp_path / "Balatro.exe", files)) == {}


@pytest.mark.parametrize("error", [zlib.error("bad data"), RuntimeError("encrypted"), NotImplementedError("compression"), EOFError()])
def test_a_language_file_that_cannot_be_unpacked_gives_no_names(tmp_path, monkeypatch, error):
    game = fake_game(tmp_path / "Balatro.exe")

    def broken(_self, _name, *_a):
        raise error

    monkeypatch.setattr(zipfile.ZipFile, "read", broken)
    assert balatro_names.read_names(game) == {}


def test_a_missing_or_foreign_file_gives_no_names(tmp_path):
    assert balatro_names.read_names(tmp_path / "nothing.exe") == {}
    (tmp_path / "notzip.exe").write_bytes(b"MZ not a zip")
    assert balatro_names.read_names(tmp_path / "notzip.exe") == {}


def test_an_oversized_language_file_is_not_read(tmp_path, monkeypatch):
    monkeypatch.setattr(balatro_names, "FILE_MAX", 10)
    assert balatro_names.read_names(fake_game(tmp_path / "Balatro.exe")) == {}


def test_she_uses_the_games_chinese_names_and_goes_by_the_key():
    balatro.set_names({"j_joker": "小丑", "c_mars": "火星", "Mars": "火星", "Pair": "对子", "Big Blind": "大盲注",
                       "j_smiley": "笑脸"})
    state = hand_state()
    text = balatro.summary(state, 8)
    assert "盲注：大盲注" in text and "对子 L3 40×4" in text and "现在最好的是 对子（" in text
    assert "小丑 [joker]" in text and "The Lovers" in text  # no name for that one: as the mod reports it
    assert balatro.card_name(card("j_joker", "JOKER", "Some Other Spelling")) == "小丑"
    assert balatro.card_name(card("H_A")) == "♥A"
    assert balatro.describe(Action("select"), state) == "开打大盲注，目标 1200 分！"
    shop = shop_state()
    assert balatro.describe(Action("buy", {"card": 0}), shop) == "买下 笑脸"
    other = 'happy|小丑必买\n{"action":"buy","card":0}'  # her line is checked against the same names
    assert balatro.parse_decision(other, shop).text == "买下 笑脸"
    assert "牌名和牌型都说中文" in balatro.build_prompt(state, 8, "主人", [], [])
    i18n.set_language("en")
    assert balatro.card_name(card("j_joker", "JOKER", "Joker")) == "Joker" and "Pair L3" in balatro.summary(state, 8)
    i18n.set_language("zh")


def test_a_discard_is_not_offered_when_none_are_left():
    assert '"action":"discard"' in balatro.build_prompt(hand_state(discards=1), 8, "主人", [], [])
    assert '"action":"discard"' not in balatro.build_prompt(hand_state(discards=0), 8, "主人", [], [])
    i18n.set_language("en")
    assert '"action":"discard"' not in balatro.build_prompt(hand_state(discards=0), 8, "you", [], [])
    i18n.set_language("zh")


@pytest.mark.parametrize("line, said", [
    ("短句，没事", "短句，没事"),
    ("先出对Q，稳定的开局。还差不少分要慢慢积累，后面的牌再看看情况，别急着把好牌全部打光了", "先出对Q，稳定的开局。还差不少分要慢慢积累，后面的牌再看看情况"),
    ("前面一句很短，" + "后" * 60, "前面一句很短，" + "后" * 32 + "…"),
])
def test_a_long_line_ends_at_a_clause_when_it_can(line, said):
    decision = balatro.parse_decision(f'talk|{line}\n{{"action":"play","cards":[0,1]}}', hand_state())
    assert decision.text == said and len(decision.text) <= balatro.SAY_MAX


def test_what_cannot_be_done_now_is_said_on_the_spot():
    shop = shop_state()
    assert "现在不能刷新" not in balatro.summary(shop, 8, saving=False)
    shop["money"] = 2
    assert "钱不够，现在不能刷新" in balatro.summary(shop, 8, saving=False)
    assert '"action":"reroll"' not in balatro.build_prompt(shop, 8, "主人", ["买吧"], [])
    shop = shop_state()
    shop["jokers"] = {"limit": 1, "cards": [card("j_joker", "JOKER", "Joker")]}
    text = balatro.summary(shop, 8, saving=False)
    assert "Smiley Face [joker]：+5 Mult per face card $4（槽位满了，现在买不了）" in text
    assert "Mars [planet]：Level up Four of a Kind $3（买后利息" in text  # the consumables are another row
    negative = shop_state()
    negative["jokers"] = shop["jokers"]
    negative["shop"]["cards"][0]["modifier"] = {"edition": "NEGATIVE"}
    assert "槽位满了" not in balatro.summary(negative, 8, saving=False)
    full = shop_state()
    full["consumables"] = {"limit": 1, "cards": [card("c_lovers", "TAROT", "The Lovers")]}
    assert "Level up Four of a Kind $3（槽位满了，现在买不了）" in balatro.summary(full, 8, saving=False)


def rich_shop(money, ante=2, jokers=1):
    shop = shop_state()
    shop.update(money=money, ante_num=ante)
    shop["jokers"] = {"limit": 5, "cards": [card(f"j_{i}", "JOKER", f"J{i}") for i in range(jokers)]}
    return shop


@pytest.mark.parametrize("ante, floor", [(1, 5), (2, 10), (4, 20), (5, 25), (8, 25)])
def test_what_a_purchase_must_leave_grows_with_the_ante(ante, floor):
    assert balatro.money_floor(rich_shop(0, ante=ante)) == floor


def test_the_saving_floor_follows_the_interest_cap():
    assert balatro.money_floor(dict(rich_shop(0, ante=8), used_vouchers={"v_seed_money": {}})) == 40
    assert balatro.money_floor(dict(rich_shop(0, ante=8), deck="GREEN")) == 0


@pytest.mark.parametrize("money, jokers, move, allowed", [
    (13, 3, '{"action":"buy","card":1}', True),  # Mars $3 leaves $10
    (12, 3, '{"action":"buy","card":1}', False),  # leaves $9
    (4, 2, '{"action":"buy","card":0}', True),  # a joker while there are few: all the money if need be
    (13, 3, '{"action":"buy","card":0}', False),  # the third joker is there: $4 would leave $9
    (14, 3, '{"action":"buy","card":0}', True),
    (12, 1, '{"action":"buy","card":1}', False),  # few jokers exempt jokers only, not a planet
    (19, 3, '{"action":"buy","voucher":0}', False),
    (20, 3, '{"action":"buy","voucher":0}', True),
    (13, 3, '{"action":"buy","pack":0}', False),
    (14, 3, '{"action":"buy","pack":0}', True),
    (29, 3, '{"action":"reroll"}', False),  # not until the full interest is covered
    (30, 3, '{"action":"reroll"}', True),
    (0, 3, '{"action":"next_round"}', True),
    (0, 3, '{"action":"sell","joker":0}', True),  # selling never breaks it
])
def test_the_saving_rule(money, jokers, move, allowed):
    shop = rich_shop(money, jokers=jokers)
    reply = f"talk|好\n{move}"
    assert (balatro.parse_decision(reply, shop) is not None) == allowed
    assert balatro.parse_decision(reply, shop, guarded=False) is not None  # a suggestion from 主人 lifts it


def test_a_free_reroll_is_always_allowed_and_a_deck_without_interest_saves_nothing():
    free = rich_shop(1, jokers=3)
    free["round"]["reroll_cost"] = 0
    assert balatro.parse_decision('talk|好\n{"action":"reroll"}', free) is not None
    green = dict(rich_shop(5, ante=8, jokers=3), deck="GREEN")
    assert balatro.parse_decision('talk|好\n{"action":"reroll"}', green) is not None
    assert balatro.parse_decision('talk|好\n{"action":"buy","card":1}', green) is not None
    assert "存钱规则" not in balatro.summary(green, 8) and "要存钱" not in balatro.summary(green, 8)


def test_a_joker_she_can_afford_comes_first_while_she_has_few():
    assert "最缺" in balatro.summary(rich_shop(4, jokers=2), 8)
    assert "最缺" not in balatro.summary(rich_shop(4, jokers=3), 8)  # enough now
    assert "最缺" not in balatro.summary(rich_shop(3, jokers=2), 8)  # cannot afford the $4 one
    no_joker_on_sale = rich_shop(40, jokers=0)
    no_joker_on_sale["shop"]["cards"] = no_joker_on_sale["shop"]["cards"][1:]
    assert "最缺" not in balatro.summary(no_joker_on_sale, 8)
    assert "最缺" not in balatro.summary(hand_state(), 8)  # only in the shop
    i18n.set_language("en")
    assert "need them most" in balatro.summary(rich_shop(4, jokers=2), 8)
    i18n.set_language("zh")


LAST_HAND = ("S_K", "H_K", "D_7", "C_2", "H_9")


def test_a_hand_is_not_thrown_away():
    # 2026-11-03, real runs: a low card alone, one pair of a three of a kind
    decision = balatro.parse_decision('think|出♣2试试\n{"action":"play","cards":[3]}', hand_state(LAST_HAND, discards=0))
    assert decision.action == Action("play", {"cards": [0, 1]}) and decision.text == "出：♠K ♥K" and decision.by_model
    good = 'happy|对 K\n{"action":"play","cards":[0,1]}'
    assert balatro.parse_decision(good, hand_state(LAST_HAND)).text == "对 K"
    kept = 'happy|留给小丑\n{"action":"play","cards":[0,1]}'
    close = hand_state(("S_K", "H_K", "D_Q", "C_Q", "H_9"), hands={"Pair": {"chips": 20, "mult": 2}})  # 80 of the two pair's 120
    assert balatro.parse_decision(kept, close).action == Action("play", {"cards": [0, 1]})  # perhaps for a joker's sake
    far = hand_state(("S_K", "H_K", "D_Q", "C_Q", "H_9"), hands={})  # 60 of 120
    assert balatro.parse_decision(kept, far).action == Action("play", {"cards": [0, 1, 2, 3]})


def psychic(keys):
    state = hand_state(keys, hands={})
    state["blinds"]["big"]["name"] = "The Psychic"
    return state


KINGS_AND_HEARTS = ("H_2", "H_4", "H_7", "H_9", "H_K", "S_K", "D_K", "C_K")


def test_too_few_cards_for_the_psychic_become_the_best_five():
    # 2026-11-03: 主人 saw her play too few, and lose ante 1; it had happened with thinking too
    decision = balatro.parse_decision('talk|四张 K\n{"action":"play","cards":[4,5,6,7]}', psychic(KINGS_AND_HEARTS))
    played = decision.action.params["cards"]
    assert decision.action.method == "play" and len(played) == 5 and {4, 5, 6, 7} <= set(played)
    assert balatro.classify(psychic(KINGS_AND_HEARTS)["hand"]["cards"], tuple(played))[0] == "Four of a Kind"
    assert decision.text.startswith("出：")


def test_five_cards_for_the_psychic_are_judged_like_any_other_hand():
    state = psychic(KINGS_AND_HEARTS)  # four kings and any card are far better than five hearts, and just as allowed
    swapped = balatro.parse_decision('talk|五张红心\n{"action":"play","cards":[0,1,2,3,4]}', state)
    assert balatro.classify(state["hand"]["cards"], tuple(swapped.action.params["cards"]))[0] == "Four of a Kind"
    kept = '{"action":"play","cards":[3,4,5,6,7]}'  # already those: never swapped to something worse
    assert balatro.parse_decision(f"talk|四条\n{kept}", state).action == Action("play", {"cards": [3, 4, 5, 6, 7]})
    assert balatro.parse_decision('talk|听你的\n{"action":"play","cards":[4,5]}', state, guarded=False).action == Action("play", {"cards": [4, 5]})


def test_the_score_for_the_psychic_counts_only_the_cards_that_score():
    name, played, score = balatro.estimate(psychic(("H_K", "S_K", "D_2", "C_4", "H_7", "S_9")))
    assert name == "Pair" and len(played) == 5 and score == (10 + 20) * 2


def with_blind(keys, blind, *earlier, **extra):
    state = hand_state(keys, hands={name: {"played_this_round": 1} for name in earlier}, **extra)
    state["blinds"]["big"]["name"] = blind
    return state


PAIR_AND_MORE = ("S_K", "H_K", "D_7", "C_7", "H_9", "S_2", "D_3", "C_5")  # two pair, or a pair


def test_the_eye_scores_no_poker_hand_twice():
    state = with_blind(PAIR_AND_MORE, "The Eye", "Two Pair")
    assert balatro.estimate(state)[0] == "Pair"
    decision = balatro.parse_decision('talk|两对\n{"action":"play","cards":[0,1,2,3]}', state)
    assert decision.action == Action("play", {"cards": [0, 1]})
    assert balatro.parse_decision('talk|两对\n{"action":"play","cards":[0,1,2,3]}', with_blind(PAIR_AND_MORE, "The Eye")).action == Action("play", {"cards": [0, 1, 2, 3]})


def test_the_mouth_scores_only_the_poker_hand_of_the_first():
    state = with_blind(PAIR_AND_MORE, "The Mouth", "Pair")
    assert balatro.estimate(state)[0] == "Pair"
    decision = balatro.parse_decision('talk|两对\n{"action":"play","cards":[0,1,2,3]}', state)
    assert decision.action == Action("play", {"cards": [0, 1]})
    assert balatro.estimate(with_blind(PAIR_AND_MORE, "The Mouth"))[0] == "Two Pair"  # the first hand may be anything


def test_when_nothing_can_score_she_is_left_with_her_own_move():
    lone = ("S_K", "H_J", "S_9", "C_7", "D_5", "H_3", "S_2", "C_4")
    state = with_blind(lone, "The Mouth", "Flush", discards=0)
    assert balatro.estimate(state)[0] == "High Card" and balatro.estimate(state)[1]  # still something to play
    assert balatro.estimate(state)[2] == 0  # worth nothing, whatever it would be worth elsewhere
    assert balatro.parse_decision('talk|试试\n{"action":"play","cards":[1]}', state).action == Action("play", {"cards": [1]})


@pytest.mark.parametrize("hands_left", [1, 3])
def test_a_big_hand_that_cannot_score_may_be_discarded(hands_left):
    straight = ("S_9", "H_T", "D_J", "C_Q", "H_K", "S_2", "D_3", "C_5")
    state = with_blind(straight, "The Mouth", "Flush")
    state["round"]["hands_left"] = hands_left
    reply = 'talk|弃了凑同花\n{"action":"discard","cards":[0,1]}'
    assert balatro.parse_decision(reply, state).action == Action("discard", {"cards": [0, 1]})
    state["blinds"]["big"]["score"] = 1  # a score that looks enough must not fool it
    assert balatro.parse_decision(reply, state).action == Action("discard", {"cards": [0, 1]})


@pytest.mark.parametrize("keys", [("H_K", "S_K", "D_2", "C_4"), ("H_K",)])
def test_fewer_than_five_cards_score_nothing_for_the_psychic(keys):
    state = psychic(keys)
    name, played, score = balatro.estimate(state)
    assert score == 0 and played == list(range(len(keys)))  # all there is, as in the game
    assert balatro.parse_decision('talk|出\n{"action":"play","cards":[0]}', state).action == Action("play", {"cards": [0]})


def test_an_empty_hand_is_nothing_to_worry_about():
    for blind in ("The Psychic", "The Eye", "The Mouth", "Big Blind"):
        state = with_blind((), blind)
        assert balatro.estimate(state)[1] == []
        assert balatro.card_to_use(dict(state, consumables=area(card("c_chariot", "TAROT", "Chariot")))) is None


def test_when_the_mouth_has_seen_two_hands_she_is_told_only_one_counts():
    text = balatro.summary(with_blind(PAIR_AND_MORE, "The Mouth", "Pair", "High Card"), 8)
    assert "只能出第一手的牌型" in text and "本回合出过" in text and "只能再出" not in text
    i18n.set_language("en")
    assert "Played so far" in balatro.summary(with_blind(PAIR_AND_MORE, "The Mouth", "Pair", "High Card"), 8)
    i18n.set_language("zh")


def test_a_card_only_added_for_the_psychic_may_be_discarded():
    state = psychic(("H_9", "S_T", "D_J", "C_Q", "H_K", "S_2", "D_3", "C_5"))  # a straight, all five score
    assert balatro.parse_decision('talk|弃\n{"action":"discard","cards":[0]}', state).action.method == "play"
    pair = psychic(("H_K", "S_K", "D_2", "C_4", "H_7", "S_9", "D_5", "C_8"))
    pair["blinds"]["big"]["score"] = 120  # enough to protect the pair
    assert balatro.parse_decision('talk|弃\n{"action":"discard","cards":[0]}', pair).action.method == "play"
    assert balatro.parse_decision('talk|弃\n{"action":"discard","cards":[2]}', pair).action.method == "discard"


def test_she_is_told_the_rule_of_the_boss():
    assert "必须出 5 张牌" in balatro.summary(psychic(KINGS_AND_HEARTS), 8)
    balatro.set_names({"Pair": "对子"})
    assert "已出过：对子" in balatro.summary(with_blind(PAIR_AND_MORE, "The Eye", "Pair"), 8)
    assert "已出过：无" in balatro.summary(with_blind(PAIR_AND_MORE, "The Eye"), 8)
    assert "只能再出：对子" in balatro.summary(with_blind(PAIR_AND_MORE, "The Mouth", "Pair"), 8)
    assert "第一手决定" in balatro.summary(with_blind(PAIR_AND_MORE, "The Mouth"), 8)
    assert "得 0 分" not in balatro.summary(hand_state(), 8)
    i18n.set_language("en")
    assert "needs 5 cards" in balatro.summary(psychic(KINGS_AND_HEARTS), 8)
    assert "Played so far: Pair" in balatro.summary(with_blind(PAIR_AND_MORE, "The Eye", "Pair"), 8)
    assert "from now on only Pair" in balatro.summary(with_blind(PAIR_AND_MORE, "The Mouth", "Pair"), 8)
    i18n.set_language("zh")


def test_the_local_rule_plays_five_cards_for_the_psychic():
    assert len(balatro.fallback(psychic(KINGS_AND_HEARTS)).action.params["cards"]) == 5
    picked = balatro.fallback(psychic(("H_K", "S_K", "D_2", "C_4", "H_7", "S_9"))).action.params["cards"]
    assert picked[:2] == [0, 1] and len(set(picked)) == 5
    assert balatro.fallback(psychic(("H_K", "S_K", "D_2"))).action.params["cards"] == [0, 1, 2]  # all there is
    assert len(balatro.fallback(hand_state(KINGS_AND_HEARTS, hands={})).action.params["cards"]) == 4  # any other blind


def test_cards_that_beat_the_blind_are_left_alone_and_a_suggestion_wins():
    low = 'think|出♣2\n{"action":"play","cards":[3]}'  # 7 points
    nearly = hand_state(LAST_HAND, discards=0)
    nearly["round"]["chips"] = 1193  # of 1200: exactly enough
    assert balatro.parse_decision(low, nearly).action == Action("play", {"cards": [3]})
    nearly["round"]["chips"] = 1192
    assert balatro.parse_decision(low, nearly).action == Action("play", {"cards": [0, 1]})
    assert balatro.parse_decision(low, hand_state(LAST_HAND), guarded=False).action == Action("play", {"cards": [3]})
    discard = 'think|先弃\n{"action":"discard","cards":[3]}'  # outside the best hand: hers to decide
    assert balatro.parse_decision(discard, hand_state(LAST_HAND)).action == Action("discard", {"cards": [3]})


STRAIGHT = ("D_J", "D_T", "H_9", "D_8", "H_7", "H_K", "D_K", "C_2")  # (a pair of kings and a straight, as in the real run)


def on_blind(keys, score=4000, chips=576, hands=4, discards=2, **extra):
    state = hand_state(keys, discards=discards, hands={}, **extra)
    state["blinds"]["big"]["score"] = score
    state["round"].update(chips=chips, hands_left=hands)
    return state


def test_a_big_hand_is_not_discarded():
    # 2026-11-03, real run: she threw away a straight worth 540 while far from the target
    reply = 'talk|弃了凑同花\n{"action":"discard","cards":[0,1,2,3,4]}'
    decision = balatro.parse_decision(reply, on_blind(STRAIGHT))
    assert decision.action.method == "play" and sorted(decision.action.params["cards"]) == [0, 1, 2, 3, 4]
    assert decision.text.startswith("出：") and decision.mood == "think"
    assert balatro.parse_decision(reply, on_blind(STRAIGHT), guarded=False).action.method == "discard"  # 主人 asked


FLUSH_NEAR_MORE = ("H_9", "H_T", "H_J", "H_Q", "H_2", "D_3", "S_5", "C_7")  # a flush worth 304, one card from a straight flush


def test_on_the_last_hand_a_big_hand_too_small_may_be_broken_up():
    reply = 'think|搏同花顺\n{"action":"discard","cards":[4]}'
    last = on_blind(FLUSH_NEAR_MORE, score=1000, chips=0, hands=1, discards=1)
    assert balatro.parse_decision(reply, last).action == Action("discard", {"cards": [4]})  # playing it surely loses
    two_left = on_blind(FLUSH_NEAR_MORE, score=1000, chips=0, hands=2, discards=1)
    assert balatro.parse_decision(reply, two_left).action.method == "play"
    enough = on_blind(FLUSH_NEAR_MORE, score=300, chips=0, hands=1, discards=1)
    assert balatro.parse_decision(reply, enough).action.method == "play"  # and it wins


def test_discarding_around_a_big_hand_is_fine():
    reply = 'talk|弃掉多余的\n{"action":"discard","cards":[5,7]}'
    assert balatro.parse_decision(reply, on_blind(STRAIGHT)).action == Action("discard", {"cards": [5, 7]})


KINGS = ("S_K", "H_K", "D_7", "C_2", "H_9", "S_4", "D_3", "C_6")


def test_a_small_hand_may_be_broken_up_unless_it_is_enough():
    reply = 'talk|拆对子\n{"action":"discard","cards":[0,1]}'
    assert balatro.parse_decision(reply, on_blind(KINGS)).action.method == "discard"  # 60 a hand against 856: she may dig
    enough = on_blind(KINGS, score=800, chips=600, hands=4)  # 60 × 4 hands covers the last 200
    assert balatro.parse_decision(reply, enough).action == Action("play", {"cards": [0, 1]})


LONE_CARDS = ("S_K", "H_J", "S_T", "C_9", "D_8", "H_5", "S_4", "C_3")


def test_a_lone_high_card_is_not_played_with_discards_left():
    # 2026-11-03, real run: K J 10 9 8 in hand, a discard left, and she played lone kings
    decision = balatro.parse_decision('talk|先出K打底\n{"action":"play","cards":[0]}', on_blind(LONE_CARDS))
    assert decision.action == Action("discard", {"cards": [7, 6, 5]})  # keeps what is one card from a straight
    assert decision.text == "弃：♣3 ♠4 ♥5"


def test_a_high_card_is_played_when_it_must_or_when_it_is_enough():
    reply = 'talk|先出K\n{"action":"play","cards":[0]}'
    assert balatro.parse_decision(reply, on_blind(LONE_CARDS, discards=0)).action == Action("play", {"cards": [0]})  # the best there is
    assert balatro.parse_decision(reply, on_blind(LONE_CARDS, score=586)).action == Action("play", {"cards": [0]})  # beats the blind
    assert balatro.parse_decision(reply, on_blind(LONE_CARDS), guarded=False).action == Action("play", {"cards": [0]})


def test_the_discard_rules_hold_under_a_boss_too():
    state = on_blind(STRAIGHT)
    state["blinds"]["big"]["name"] = "The Eye"
    assert balatro.parse_decision('talk|弃\n{"action":"discard","cards":[0]}', state).action.method == "play"
    lone = on_blind(LONE_CARDS)
    lone["blinds"]["big"]["name"] = "The Eye"
    assert balatro.parse_decision('talk|出\n{"action":"play","cards":[0]}', lone).action.method == "discard"


def test_what_she_keeps_when_the_rule_discards_for_her():
    flush = hand_state(("H_K", "H_J", "H_7", "H_3", "S_9", "C_5", "D_2", "S_4"))["hand"]["cards"]
    assert balatro._cards_to_discard(flush, []) == [6, 7, 5, 4]  # four hearts stay
    wheel = hand_state(("D_A", "H_2", "S_3", "C_4", "H_K", "D_J", "S_9", "C_7"))["hand"]["cards"]
    assert set(balatro._cards_to_discard(wheel, [])) == {4, 5, 6, 7}  # A 2 3 4: the ace counts low
    nothing = hand_state(("D_A", "H_K", "S_9", "C_6", "H_3"))["hand"]["cards"]
    assert balatro._cards_to_discard(nothing, [0]) == [4, 3, 2, 1]  # no draw worth keeping: only the best hand stays
    held = hand_state(("D_A", "H_K"))["hand"]["cards"]
    assert balatro._cards_to_discard(held, [0, 1]) == []


def wild_hand(**state):
    hearts = [card(k) for k in ("H_2", "H_5", "H_8")]
    wild = dict(card("D_K", "ENHANCED", enhancement="WILD"), state=state)
    return [*hearts, wild, *(card(k) for k in ("S_A", "C_3", "D_7", "S_J"))]


def test_a_wild_card_counts_for_the_flush_she_keeps():
    assert balatro._cards_to_discard(wild_hand(), [4]) == [5, 6, 7]  # three hearts and the wild king make four
    assert 3 in balatro._cards_to_discard(wild_hand(debuff=True), [4])  # debuffed: only its own suit


def test_only_wild_cards_are_a_flush_of_their_own():
    wilds = [dict(card(k, "ENHANCED", enhancement="WILD")) for k in ("D_K", "S_9", "H_3")] + [dict(card("C_5", "ENHANCED", enhancement="STONE"))]
    assert balatro._cards_to_discard(wilds, []) == [3]


def test_the_psychic_gets_the_best_five_cards_not_the_best_hand_made_up_to_five():
    # adding the first three cards to a leveled pair of kings would make a full house worth far less
    state = psychic(("H_K", "S_K", "D_2", "C_2", "H_2", "S_4", "H_7", "C_9"))
    state["hands"] = {"Pair": {"chips": 100, "mult": 10}}
    played = balatro.fallback(state).action.params["cards"]
    hand = state["hand"]["cards"]
    assert len(played) == 5 and {0, 1} <= set(played)
    assert balatro.classify(hand, tuple(played))[0] == "Pair"
    many = hand_state(("D_A", "H_K", "S_9", "C_6", "H_3", "D_2", "C_8", "S_T"))["hand"]["cards"]
    assert len(balatro._cards_to_discard(many, [])) <= 5


def joker(key, **state):
    return dict(card(key, "JOKER", key), state=state)


def fives(*jokers):
    return hand_state(("S_5", "H_5", "C_5", "D_A", "H_2", "S_8", "D_J", "C_3"), hands={}, jokers=area(*jokers))


def test_the_best_hand_counts_the_jokers_tied_to_a_poker_hand():
    # 2026-11-03, real run: three fives and this joker, (30 + 15 + 100) × 3 = 435, and she played a pair for 40
    assert balatro.estimate(fives(joker("j_wily"))) == ("Three of a Kind", [0, 1, 2], 435)
    decision = balatro.parse_decision('talk|先出对子\n{"action":"play","cards":[0,1]}', fives(joker("j_wily")))
    assert decision.action == Action("play", {"cards": [0, 1, 2]})


@pytest.mark.parametrize("key, score", [("j_zany", (30 + 15) * 15), ("j_trio", (30 + 15) * 3 * 3), ("j_jolly", (30 + 15) * 11),
                                        ("j_sly", (30 + 15 + 50) * 3), ("j_duo", (30 + 15) * 3 * 2), ("j_mad", (30 + 15) * 3),
                                        ("j_joker", (30 + 15) * 3)])
def test_a_three_of_a_kind_with_each_joker(key, score):
    assert balatro.estimate(fives(joker(key)))[2] == score


def test_jokers_are_worked_out_from_left_to_right_as_in_the_game():
    assert balatro.estimate(fives(joker("j_zany"), joker("j_trio")))[2] == 45 * (3 + 12) * 3
    assert balatro.estimate(fives(joker("j_trio"), joker("j_zany")))[2] == 45 * (3 * 3 + 12)


def test_a_flush_holding_a_pair_counts_for_a_pair_joker():
    hearts = ("H_2", "H_5", "H_8", "H_K", "H_K")
    state = hand_state(hearts, hands={}, jokers=area(joker("j_jolly")))
    name, picked, score = balatro.estimate(state)
    assert name == "Flush" and sorted(picked) == [0, 1, 2, 3, 4] and score == (35 + 2 + 5 + 8 + 10 + 10) * (4 + 8)
    state = hand_state(("H_K", "H_K", "H_K", "H_2", "H_5"), hands={}, jokers=area(joker("j_wily"), joker("j_mad")))
    assert balatro.estimate(state)[2] == (35 + 30 + 7 + 100) * 4  # a three of a kind in it, no two pair


def test_a_straight_flush_counts_for_both_and_a_straight_has_no_pair():
    state = hand_state(("H_5", "H_6", "H_7", "H_8", "H_9"), hands={}, jokers=area(joker("j_crafty"), joker("j_devious"), joker("j_jolly")))
    assert balatro.estimate(state)[0] == "Straight Flush"
    assert balatro.estimate(state)[2] == (100 + 35 + 80 + 100) * 8


def test_several_jokers_add_up_and_a_debuffed_one_counts_for_nothing():
    assert balatro.estimate(fives(joker("j_wily"), joker("j_zany"), joker("j_trio")))[2] == (30 + 15 + 100) * 15 * 3
    assert balatro.estimate(fives(joker("j_wily", debuff=True)))[2] == (30 + 15) * 3


def test_a_full_house_counts_for_a_two_pair_joker_and_a_four_of_a_kind_does_not():
    full = hand_state(("S_5", "H_5", "C_5", "D_8", "H_8"), hands={}, jokers=area(joker("j_mad")))
    assert balatro.estimate(full) == ("Full House", [0, 1, 2, 3, 4], (40 + 15 + 16) * 14)
    four = hand_state(("S_5", "H_5", "C_5", "D_5"), hands={}, jokers=area(joker("j_mad")))
    assert balatro.estimate(four)[2] == (60 + 20) * 7
    four = hand_state(("S_5", "H_5", "C_5", "D_5"), hands={}, jokers=area(joker("j_zany")))
    assert balatro.estimate(four)[2] == (60 + 20) * 19


def test_a_joker_can_change_which_hand_is_best():
    state = hand_state(("S_K", "H_K", "D_K", "S_2", "S_5", "S_8", "S_J", "S_3"), hands={})
    assert balatro.estimate(state)[0] == "Flush"
    state["jokers"] = area(joker("j_wily"))
    assert balatro.estimate(state)[0] == "Three of a Kind"


def test_the_prompt_says_which_jokers_the_estimate_counts():
    assert "算上牌型小丑，现在最好的是" in balatro.summary(fives(joker("j_wily")), 8)
    assert "不算小丑时，现在最好的是" in balatro.summary(fives(joker("j_joker")), 8)
    i18n.set_language("en")
    assert "With the jokers tied to a poker hand, the best hand" in balatro.summary(fives(joker("j_wily")), 8)
    i18n.set_language("zh")


TWO_JOKERS = area(card("j_joker", "JOKER", "Joker"), card("j_egg", "JOKER", "Egg"))


def test_she_chooses_what_to_build_around_only_with_jokers_to_go_on():
    few = balatro.build_prompt(hand_state(), 8, "主人", [], [])
    assert "先不定主打" in few and "别为了凑牌型拆掉" in few and '"build"' not in few
    text = balatro.build_prompt(hand_state(jokers=TWO_JOKERS), 8, "主人", [], [])
    assert "这局还没定主打" in text and '"build"' in text
    text = balatro.build_prompt(hand_state(), 8, "主人", [], [], "", "Flush")
    assert "这局主打 Flush" in text and "别为了它拆牌" in text and "还没定" not in text  # once chosen it stays
    balatro.set_names({"Flush": "同花"})
    assert "这局主打 同花" in balatro.build_prompt(hand_state(), 8, "主人", [], [], "", "Flush")
    i18n.set_language("en")
    assert "You are building around Flush" in balatro.build_prompt(hand_state(), 8, "you", [], [], "", "Flush")
    assert "No build yet" in balatro.build_prompt(hand_state(jokers=TWO_JOKERS), 8, "you", [], [])
    assert "Too few jokers" in balatro.build_prompt(hand_state(), 8, "you", [], [])
    i18n.set_language("zh")


def test_a_build_named_too_early_is_ignored():
    reply = 'happy|定同花\n{"action":"discard","cards":[2],"build":"Flush"}'
    assert balatro.parse_decision(reply, hand_state()).build == ""
    assert balatro.parse_decision(reply, hand_state(jokers=TWO_JOKERS)).build == "Flush"


def test_what_the_run_says_about_a_build_is_worked_out_locally():
    state = hand_state(hands={"Pair": {"level": 3, "chips": 40, "mult": 4, "played": 5},
                              "Flush": {"level": 1, "chips": 35, "mult": 4, "played": 2},
                              "Straight": {"level": 1, "played": 1}, "High Card": {"level": 1, "played": 0}})
    state["jokers"] = area(card("j_crafty", "JOKER", "Crafty Joker"), card("j_droll", "JOKER", "Droll Joker"), card("j_joker", "JOKER", "Joker"))
    text = balatro.build_note(state, "")
    assert "依据：出得最多 Pair 5 次、Flush 2 次；升过级 Pair L3；小丑偏向 Flush 2 张" in text
    assert "Straight" not in text  # the two played most
    assert "依据" not in balatro.build_note(hand_state(hands={}, jokers=area()), "")  # nothing to go on yet
    i18n.set_language("en")
    assert "So far: played most Pair 5x, Flush 2x; leveled up Pair L3; jokers favour Flush 2" in balatro.build_note(state, "")
    i18n.set_language("zh")


@pytest.mark.parametrize("named, build", [("Flush", "Flush"), ("flush", "Flush"), (" Full House ", "Full House"), ("同花", "Flush"),
                                          ("不存在的牌型", ""), ("", ""), (None, ""), (3, ""), (["Flush"], "")])
def test_only_a_real_poker_hand_is_taken_as_the_build(named, build):
    balatro.set_names({"Flush": "同花"})
    reply = "happy|好\n" + json.dumps({"action": "play", "cards": [0, 1], "build": named}, ensure_ascii=False)
    decision = balatro.parse_decision(reply, hand_state(jokers=TWO_JOKERS))
    assert decision.build == build and decision.action == Action("play", {"cards": [0, 1]})


def test_she_is_told_the_saving_rule_and_what_it_stops():
    shop = rich_shop(12, jokers=3)
    text = balatro.build_prompt(shop, 8, "主人", [], [])
    assert "存钱规则：这个底注买完至少留 $10" in text and "小丑不足 3 张" in text
    assert "Level up Four of a Kind $3（要存钱，现在不买）" in text
    assert "要存钱，现在不能刷新" in text and '"action":"reroll"' not in text
    asked = balatro.build_prompt(shop, 8, "主人", ["买火星"], [])
    assert "存钱规则" not in asked and "要存钱" not in asked and '"action":"reroll"' in asked
    i18n.set_language("en")
    english = balatro.build_prompt(shop, 8, "you", [], [])
    assert "Saving rule: on this ante keep at least $10" in english and "$3 (saving: not now)" in english
    i18n.set_language("zh")


# ---- what the model is told -----------------------------------------------------------------------------------
def test_the_summary_tells_the_game_with_hand_indices():
    text = balatro.summary(hand_state(), 8)
    assert "底注 2/8" in text and "钱 $7" in text
    assert "Big Blind" in text and "1200" in text  # the current blind, not the beaten one
    assert "剩余出牌 4 次、弃牌 3 次" in text
    assert "  0: ♠K" in text and "  4: ♥9" in text
    assert "Pair L3 40×4" in text and "Flush 35×4" in text and "Straight Flush 100×8" in text  # every hand, level shown
    assert "Joker [joker]" in text and "The Lovers" in text
    assert "现在最好的是 Pair（0:♠K 1:♥K），约 240 分" in text  # (40 + 10 + 10) × 4
    assert "还差 1080 分，剩 4 手，平均每手要约 270 分" in text
    assert "照这样打不够：先弃掉用不上的牌" in text  # 240 × 4 < 1080 and discards are left


def test_no_discard_advice_when_the_best_hand_will_do_or_no_discard_is_left():
    enough = hand_state(round={"hands_left": 4, "discards_left": 3, "chips": 1100})
    assert "照这样打不够" not in balatro.summary(enough, 8) and "还差 100 分" in balatro.summary(enough, 8)
    assert "照这样打不够" not in balatro.summary(hand_state(discards=0), 8)


@pytest.mark.parametrize("keys, name, picked", [
    (("H_9", "H_T", "H_J", "H_Q", "H_K", "S_2"), "Straight Flush", [4, 3, 2, 1, 0]),
    (("S_7", "H_7", "D_7", "C_7", "S_2"), "Four of a Kind", [0, 1, 2, 3]),
    (("S_7", "H_7", "D_7", "C_2", "S_2", "H_K"), "Full House", [0, 1, 2, 3, 4]),
    (("H_2", "H_5", "H_9", "S_K", "H_J", "H_3"), "Flush", [4, 2, 1, 5, 0]),
    (("S_A", "H_2", "D_3", "C_4", "S_5", "H_9"), "Straight", [4, 3, 2, 1, 0]),  # the ace counts low
    (("S_T", "H_J", "D_Q", "C_K", "S_A"), "Straight", [4, 3, 2, 1, 0]),
    (("S_7", "H_7", "D_7", "C_2", "S_9"), "Three of a Kind", [0, 1, 2]),
    (("S_7", "H_7", "D_2", "C_2", "S_K", "H_K"), "Two Pair", [4, 5, 0, 1]),
    (("S_7", "H_7", "D_2", "C_4", "S_K"), "Pair", [0, 1]),
    (("H_2", "S_5", "D_9", "S_K", "C_J", "H_3", "D_A"), "High Card", [6]),
    ((), "High Card", []),
])
def test_the_best_poker_hand_in_hand(keys, name, picked):
    assert balatro.best_hand([card(k) for k in keys]) == (name, picked)


@pytest.mark.parametrize("value", [
    {"effect": "+50 Chips"},  # a Stone Card has no rank or suit
    {"rank": None, "suit": None},
    {"rank": "", "suit": []},  # Lua's empty tables come out as []
    {"rank": "23", "suit": "H"},
])
def test_a_card_without_a_rank_does_not_stop_the_game(value):
    stone = {"key": "m_stone", "set": "ENHANCED", "label": "Stone Card", "value": value, "modifier": [], "state": []}
    assert balatro.card_name(stone) == "Stone Card"
    hand = [stone, card("S_K"), card("H_K")]
    assert balatro.best_hand(hand) == ("Pair", [1, 2, 0])  # it always scores: worth playing along
    assert balatro.best_hand([stone]) == ("High Card", [0])
    state = hand_state(hand=area(*hand))
    assert "0: Stone Card" in balatro.summary(state, 8)
    assert balatro.fallback(state).action == Action("play", {"cards": [1, 2, 0]})
    assert balatro.estimate(state)[2] == (40 + 20 + 50) * 4


def test_a_stone_card_does_not_count_as_the_rank_the_mod_reports():
    stone = card("H_K", "ENHANCED", label="Stone Card", enhancement="STONE")  # the mod still says king of hearts
    assert balatro.card_name(stone) == "Stone Card"
    hand = [stone, card("S_K"), card("D_9")]
    name, picked = balatro.best_hand(hand)
    assert name == "High Card" and 0 in picked  # no pair of kings
    flush = [card(k) for k in ("H_2", "H_5", "H_9", "H_J")] + [stone]
    assert balatro.classify(flush, (0, 1, 2, 3, 4))[0] == "High Card"  # no flush either


def test_a_debuffed_stone_card_adds_nothing():
    stone = card("H_K", "ENHANCED", label="Stone Card", enhancement="STONE")
    stone["state"] = {"debuff": True}
    assert balatro.best_hand([stone, card("S_K"), card("H_K")]) == ("Pair", [1, 2])


def test_a_debuffed_wild_card_keeps_its_own_suit():
    wild = card("S_J", "ENHANCED", enhancement="WILD")
    wild["state"] = {"debuff": True}
    hand = [card(k) for k in ("H_2", "H_5", "H_9", "H_K")] + [wild, card("S_A"), card("D_A")]
    assert balatro.classify(hand, (0, 1, 2, 3, 4))[0] == "High Card"
    assert balatro.best_hand(hand) == ("Pair", [5, 6])


def test_the_best_hand_is_the_one_that_scores_most_at_its_level():
    keys = ("S_K", "H_K", "D_7", "C_7", "S_2")
    assert balatro.best_hand([card(k) for k in keys]) == ("Two Pair", [0, 1, 2, 3])  # at level 1
    state = hand_state(keys=keys)  # Pair is level 3 here: (40 + 20) × 4 = 240 against (20 + 34) × 2 = 108
    assert balatro.estimate(state) == ("Pair", [0, 1], 240)
    assert balatro.fallback(state).action == Action("play", {"cards": [0, 1]})
    one_hand_left = hand_state(keys=keys, round={"hands_left": 1, "discards_left": 3, "chips": 1000})
    assert "照这样打不够" not in balatro.summary(one_hand_left, 8)  # 240 covers the 200 still needed; two pair would not


@pytest.mark.parametrize("keys, name, scoring", [
    (("H_2", "H_3", "H_4", "H_5", "H_6"), "Straight Flush", [4, 3, 2, 1, 0]),  # never a mere flush or straight
    (("H_A", "H_2", "H_3", "H_4", "H_5"), "Straight Flush", [4, 3, 2, 1, 0]),
    (("S_7", "H_7", "D_7", "C_7", "S_2"), "Four of a Kind", [0, 1, 2, 3]),
    (("S_7", "H_7", "D_7", "C_2", "S_2"), "Full House", [0, 1, 2, 3, 4]),
    (("H_7", "H_7", "H_7", "H_2", "H_2"), "Flush House", [0, 1, 2, 3, 4]),
    (("S_7", "H_7", "D_7", "C_7", "S_7"), "Five of a Kind", [0, 1, 2, 3, 4]),
    (("H_7", "H_7", "H_7", "H_7", "H_7"), "Flush Five", [0, 1, 2, 3, 4]),
    (("S_K", "H_A", "D_2", "C_3", "S_4"), "High Card", [1]),  # K-A-2-3-4 does not wrap around
    (("S_2", "H_3", "D_4", "C_5"), "High Card", [3]),  # a run of four is no straight
    (("H_2", "H_5", "H_9", "H_K"), "High Card", [3]),  # nor four of a suit a flush
])
def test_what_the_game_calls_the_played_cards(keys, name, scoring):
    hand = [card(k) for k in keys]
    assert balatro.classify(hand, tuple(range(len(hand)))) == (name, scoring)


def test_a_wild_card_fits_any_flush():
    hand = [card(k) for k in ("H_2", "H_5", "H_9", "H_K", "S_J")]
    assert balatro.classify(hand, (0, 1, 2, 3, 4))[0] == "High Card"
    hand[4] = card("S_J", "ENHANCED", enhancement="WILD")
    assert balatro.classify(hand, (0, 1, 2, 3, 4))[0] == "Flush"


def test_a_straight_flush_is_scored_as_one_even_when_flush_is_leveled():
    values = dict(balatro.BASE_HANDS, **{"Flush": (95, 12), "Pair": (115, 9)})
    hand = [card(k) for k in ("H_2", "H_3", "H_4", "H_5", "H_6", "S_K", "C_K")]
    assert balatro.best_hand(hand, values) == ("Pair", [5, 6])  # (115 + 20) × 9 = 1215 beats (100 + 20) × 8 = 960


def test_a_debuffed_card_is_left_out_when_another_can_take_its_place():
    state = hand_state(keys=("S_A", "H_A", "D_A"))
    state["hand"]["cards"][0]["state"] = {"debuff": True}
    state["hands"]["Three of a Kind"] = {"level": 1, "chips": 0, "mult": 1}
    assert balatro.estimate(state) == ("Pair", [1, 2], (40 + 11 + 11) * 4)
    assert balatro.fallback(state).action == Action("play", {"cards": [1, 2]})


def test_she_does_not_peek_at_face_down_cards():
    state = hand_state(keys=("S_K", "H_K", "D_7", "C_2", "H_9"))
    state["hand"]["cards"][1]["state"] = {"hidden": True}  # the mod still says king of hearts
    text = balatro.summary(state, 8)
    assert "♥K" not in text and "  1: （盖着的牌）" in text
    assert balatro.estimate(state)[0] == "High Card"  # no pair of kings she cannot see
    assert 1 not in balatro.estimate(state)[1]
    assert balatro.describe(Action("play", {"cards": [1]}), state) == "出：（盖着的牌）"
    joker = card("j_secret", "JOKER", "Secret", "Very secret")
    joker["state"] = {"hidden": True}
    described = balatro.summary(dict(state, jokers=area(joker)), 8)
    assert "Secret" not in described and "Very secret" not in described


def test_a_face_down_card_is_neither_a_stone_nor_worth_chips():
    hidden = card("S_K")
    hidden["state"] = {"hidden": True}
    assert balatro.classify([hidden], (0,)) == ("High Card", [])
    assert balatro.best_hand([hidden, card("S_2")]) == ("High Card", [1])


def test_something_is_played_when_every_card_is_face_down():
    state = hand_state(keys=("S_K", "H_K"))
    for c in state["hand"]["cards"]:
        c["state"] = {"hidden": True}
    assert balatro.fallback(state).action == Action("play", {"cards": [0]})


def test_the_hidden_hands_stay_out_of_the_prompt():
    text = balatro.summary(hand_state(), 8)
    assert "Five of a Kind" not in text and "Flush House" not in text and "Flush Five" not in text


def test_the_estimate_uses_levels_and_skips_debuffed_cards():
    state = hand_state(keys=("S_A", "H_A", "D_3"))
    assert balatro.estimate(state) == ("Pair", [0, 1], (40 + 11 + 11) * 4)
    state["hand"]["cards"][1]["state"] = {"debuff": True}
    assert balatro.estimate(state)[2] == (40 + 11) * 4


def test_the_shop_summary_lists_prices_and_leaves_out_the_hand():
    text = balatro.summary(shop_state(), 8)
    assert "Smiley Face" in text and "$4" in text and "Grabber" in text and "Arcana Pack" in text
    assert "♠A" not in text  # no hand in the shop
    assert "刷新商店要 $5" in text


def test_the_shop_tells_what_interest_a_purchase_costs():
    text = balatro.summary(shop_state(), 8)  # $9
    assert "利息：回合结束时每有 $5 多得 $1，最多 $5（存到 $25 封顶）。现在 $9，可得 $1" in text
    assert "Smiley Face [joker]：+5 Mult per face card $4（买后利息 $1）" in text
    assert "Grabber [voucher]：+1 hand $10（钱不够）" in text
    assert "（买后利息" not in balatro.summary(hand_state(), 8)  # only in the shop
    assert "利息：" not in balatro.summary(hand_state(), 8)
    rich = dict(shop_state(), money=26)
    assert "现在 $26，可得 $5" in balatro.summary(rich, 8)
    assert "Smiley Face [joker]：+5 Mult per face card $4（买后利息 $4）" in balatro.summary(rich, 8)


def test_the_shop_says_what_a_reroll_changes():
    text = balatro.summary(shop_state(), 8)
    assert "刷新商店要 $5，只换商店卡牌；优惠券和卡包不会变" in text
    i18n.set_language("en")
    assert "only replaces the shop cards; vouchers and packs stay" in balatro.summary(shop_state(), 8)


def test_how_full_the_slots_are():
    state = shop_state()
    state["jokers"]["limit"] = 2
    state["consumables"]["limit"] = 2
    text = balatro.summary(state, 8)
    assert "小丑（已用 1/2）" in text
    state["jokers"]["cards"].append(card("j_b", "JOKER", "B"))
    assert "小丑（已用 2/2，满了：先卖一张才能买新的）" in balatro.summary(state, 8)
    assert "已用" not in balatro.summary(shop_state(), 8)  # no limit reported: nothing claimed


@pytest.mark.parametrize("edition, words", [
    ("FOIL", "箔片：+50 筹码"), ("HOLO", "镭射：+10 倍率"), ("POLYCHROME", "多彩：×1.5 倍率"), ("NEGATIVE", "负片"),
    ("SOMETHING_NEW", "something_new"),
])
def test_an_edition_says_what_it_is_worth(edition, words):
    state = shop_state()
    state["shop"]["cards"][0]["modifier"] = {"edition": edition}
    assert words in balatro.summary(state, 8)


def test_a_face_down_card_gives_away_no_enhancement():
    state = hand_state(keys=("S_K", "H_K"))
    state["hand"]["cards"][0].update(state={"hidden": True}, modifier={"enhancement": "GLASS", "edition": "HOLO"})
    text = balatro.summary(state, 8)
    assert "glass" not in text and "镭射" not in text


def test_interest_in_english():
    i18n.set_language("en")
    text = balatro.summary(shop_state(), 8)
    assert "Interest: at the end of a round you get $1 for every $5 held, at most $5" in text
    assert "$4 (interest $1 after buying)" in text and "$10 (not enough money)" in text


@pytest.mark.parametrize("state, money, cap, paid", [
    ({}, 26, 5, 5),
    ({}, 4, 5, 0),
    ({}, -3, 5, 0),
    ({"used_vouchers": {"v_seed_money": "x"}}, 60, 10, 10),
    ({"used_vouchers": {"v_seed_money": "x", "v_money_tree": "y"}}, 200, 20, 20),
    ({"used_vouchers": []}, 26, 5, 5),  # Lua's empty table
    ({"deck": "GREEN"}, 50, 0, 0),
])
def test_interest(state, money, cap, paid):
    assert balatro.interest_cap(state) == cap and balatro.interest(state, money) == paid


def test_the_green_deck_is_told_there_is_no_interest():
    text = balatro.summary(dict(shop_state(), deck="GREEN"), 8)
    assert "这个牌组没有利息" in text and "买后利息" not in text and "（钱不够）" in text


def test_the_shop_says_targets_wait_for_a_hand():
    assert "要选手牌的留到出牌时用" in balatro.build_prompt(shop_state(), 8, "主人", [], [])


def test_the_prompt_carries_suggestions_the_last_refusal_and_the_allowed_moves():
    text = balatro.build_prompt(hand_state(), 8, "主人", ["留两张K"], ["先弃小牌"], "Not enough money")
    assert "主人的建议" in text and "- 留两张K" in text and "不是宿主规则" in text
    assert "上一步被游戏拒绝了：Not enough money" in text
    assert '"action":"play"' in text and '"action":"discard"' in text and '"action":"buy"' not in text
    assert "- 先弃小牌" in text and "表情|" in text


def test_the_prompt_in_english():
    i18n.set_language("en")
    text = balatro.build_prompt(shop_state(), 6, "you", ["buy the joker"], [])
    assert "Ante 2/6" in text and "Suggestions from you" in text and "- buy the joker" in text
    assert '"action":"next_round"' in text and "Answer in exactly two lines" in text
    assert "Smiley Face [joker]: +5 Mult per face card $4" in text


def test_the_shop_prompt_says_jokers_are_bought_as_shop_cards():
    # Seen in a real game: the model answered {"action":"buy","joker":N}, which the whitelist refuses.
    assert "小丑也用 card" in balatro.build_prompt(shop_state(), 8, "主人", [], [])
    i18n.set_language("en")
    assert 'jokers in the shop are bought with "card" too' in balatro.build_prompt(shop_state(), 8, "you", [], [])


# ---- what the model may do ------------------------------------------------------------------------------------
@pytest.mark.parametrize("obj, expected", [
    ({"action": "play", "cards": [0, 1]}, Action("play", {"cards": [0, 1]})),
    ({"action": "discard", "cards": [4]}, Action("discard", {"cards": [4]})),
    ({"action": "use", "consumable": 0, "cards": [0, 1]}, Action("use", {"consumable": 0, "cards": [0, 1]})),
    ({"action": "use", "consumable": 0}, Action("use", {"consumable": 0})),
    ({"action": "play", "cards": [0, 5]}, None),  # no sixth card
    ({"action": "play", "cards": [1, 1]}, None),
    ({"action": "play", "cards": []}, None),
    ({"action": "play", "cards": [0, 1, 2, 3, 4, 0]}, None),
    ({"action": "play", "cards": [True]}, None),
    ({"action": "play", "cards": "0,1"}, None),
    ({"action": "buy", "card": 0}, None),  # not in this screen
    ({"action": "use", "consumable": 1}, None),
    ({"action": "rm -rf"}, None),
])
def test_moves_in_hand_are_checked(obj, expected):
    assert balatro.validate(obj, hand_state()) == expected


def test_no_discard_without_discards_left():
    assert balatro.validate({"action": "discard", "cards": [0]}, hand_state(discards=0)) is None


@pytest.mark.parametrize("obj, expected", [
    ({"action": "buy", "card": 1}, Action("buy", {"card": 1})),
    ({"action": "buy", "voucher": 0}, Action("buy", {"voucher": 0})),
    ({"action": "buy", "pack": 0}, Action("buy", {"pack": 0})),
    ({"action": "sell", "joker": 0}, Action("sell", {"joker": 0})),
    ({"action": "reroll"}, Action("reroll")),
    ({"action": "NEXT_ROUND"}, Action("next_round")),
    ({"action": "buy", "card": 2}, None),
    ({"action": "buy", "card": 0, "pack": 0}, None),  # exactly one thing
    ({"action": "buy", "joker": 0}, None),  # shop jokers are bought as "card"; owned jokers can only be sold
    ({"action": "sell", "consumable": 0}, None),  # there is none
    ({"action": "use", "consumable": 0, "cards": [0]}, None),
    ({"action": "play", "cards": [0]}, None),
])
def test_moves_in_the_shop_are_checked(obj, expected):
    assert balatro.validate(obj, shop_state()) == expected


@pytest.mark.parametrize("obj, expected", [
    ({"action": "pack", "skip": True}, Action("pack", {"skip": True})),
    ({"action": "pack", "card": 1}, Action("pack", {"card": 1})),
    ({"action": "pack", "card": 0, "targets": [1]}, Action("pack", {"card": 0, "targets": [1]})),
    ({"action": "pack", "card": 2}, None),
    ({"action": "pack", "skip": "yes"}, None),
    ({"action": "pack", "card": 0, "targets": [2]}, None),
])
def test_moves_in_an_opened_pack_are_checked(obj, expected):
    assert balatro.validate(obj, pack_state()) == expected


def test_a_reply_gives_her_line_and_the_move():
    raw = 'happy|留这对 K，凑葫芦\n{"action":"play","cards":[0,1]}'
    decision = balatro.parse_decision(raw, hand_state())
    assert decision == balatro.Decision(Action("play", {"cards": [0, 1]}), "happy", "留这对 K，凑葫芦", True)


def test_a_fenced_reply_and_a_missing_line():
    raw = '```json\n{"action": "discard", "cards": [2, 3]}\n```'
    decision = balatro.parse_decision(raw, hand_state())
    assert decision.action == Action("discard", {"cards": [2, 3]}) and decision.text == "弃：♦7 ♣2"


def test_a_long_line_is_cut_and_a_bad_move_is_no_decision():
    long = "think|" + "很长" * 40 + '\n{"action":"play","cards":[0,1]}'
    assert len(balatro.parse_decision(long, hand_state()).text) == balatro.SAY_MAX
    i18n.set_language("en")
    english = 'happy|keeping the pair of kings for a full house\n{"action":"play","cards":[0,1]}'
    assert balatro.parse_decision(english, hand_state()).text == "keeping the pair of kings for a full house"
    i18n.set_language("zh")
    assert balatro.parse_decision('talk|买！\n{"action":"buy","card":0}', hand_state()) is None
    assert balatro.parse_decision("talk|只说话不出牌", hand_state()) is None
    assert balatro.parse_decision("", hand_state()) is None


def test_a_line_about_another_card_gives_way_to_what_really_happens():
    # 2026-11-02, real run: she bought the card at index 0 saying it was the joker she already owned
    other = 'happy|Joker 必买，$2 花得值\n{"action":"buy","card":0}'
    decision = balatro.parse_decision(other, shop_state())
    assert decision.action == Action("buy", {"card": 0}) and decision.text == "买下 Smiley Face" and decision.mood == "happy"
    both = 'happy|Smiley Face 配 Joker 很强\n{"action":"buy","card":0}'
    assert balatro.parse_decision(both, shop_state()).text == "Smiley Face 配 Joker 很强"
    named_in_lower_case = 'happy|smiley face 好用\n{"action":"buy","card":0}'
    assert balatro.parse_decision(named_in_lower_case, shop_state()).text == "smiley face 好用"
    no_name = 'happy|这张便宜又好用\n{"action":"buy","card":0}'
    assert balatro.parse_decision(no_name, shop_state()).text == "这张便宜又好用"
    selling = 'think|留着 Smiley Face\n{"action":"sell","joker":0}'
    assert balatro.parse_decision(selling, shop_state()).text == "卖掉 Joker"
    using = 'think|Joker 配这张\n{"action":"use","consumable":0}'
    assert balatro.parse_decision(using, hand_state()).text == "用掉 The Lovers"
    picked = 'happy|B 更好\n{"action":"pack","card":0}'
    assert balatro.parse_decision(picked, pack_state()).text == "拿这张：A"
    skipping = 'think|Joker 够用了\n{"action":"next_round"}'  # a move on no card: anything she says goes
    assert balatro.parse_decision(skipping, shop_state()).text == "Joker 够用了"
    played = 'happy|Joker 加成够了\n{"action":"play","cards":[0,1]}'
    assert balatro.parse_decision(played, hand_state()).text == "Joker 加成够了"


def test_she_remembers_what_a_move_really_did():
    said = balatro.parse_decision('happy|这张便宜\n{"action":"buy","card":0}', shop_state())
    assert balatro.move_note(said, shop_state()) == "买下 Smiley Face (这张便宜)"
    plain = balatro.Decision(Action("next_round"), "think", balatro.describe(Action("next_round"), shop_state()), False)
    assert balatro.move_note(plain, shop_state()) == plain.text  # not the same words twice
    text = balatro.build_prompt(shop_state(), 8, "主人", [], ["买下 Smiley Face (这张便宜)"])
    assert "已经做完的操作" in text and "- 买下 Smiley Face (这张便宜)" in text
    i18n.set_language("en")
    assert "already done" in balatro.build_prompt(shop_state(), 8, "you", [], ["x"])
    i18n.set_language("zh")


# ---- local rules ----------------------------------------------------------------------------------------------
def test_local_rules_play_the_best_poker_hand():
    assert balatro.fallback(hand_state()).action == Action("play", {"cards": [0, 1]})  # the pair of kings
    flush = [card(k) for k in ("H_2", "H_5", "H_9", "S_K", "H_J", "H_3")]
    assert balatro.best_hand(flush)[1] == [4, 2, 1, 5, 0]


def test_local_rules_for_each_screen():
    assert balatro.fallback(hand_state()).action == Action("play", {"cards": [0, 1]})
    assert balatro.fallback(shop_state()).action == Action("next_round")
    assert balatro.fallback(pack_state()).action == Action("pack", {"skip": True})
    assert balatro.fallback({"state": "SELECTING_HAND"}) is None
    assert not balatro.fallback(shop_state()).by_model


@pytest.mark.parametrize("state, expected", [
    ({"state": "MENU", "won": True, "ante_num": 9}, ("menu", None)),
    ({"state": "GAME_OVER"}, ("over", None)),
    ({"state": "SHOP", "won": True}, ("won", None)),
    ({"state": "BLIND_SELECT", "ante_num": 9}, ("won", None)),
    ({"state": "BLIND_SELECT", "ante_num": 3}, ("auto", Action("select"))),
    ({"state": "ROUND_EVAL", "ante_num": 3}, ("auto", Action("cash_out"))),
    ({"state": "SHOP", "ante_num": 3}, ("decide", None)),
    ({"state": "HAND_PLAYED", "ante_num": 3}, ("wait", None)),
])
def test_what_comes_next(state, expected):
    assert balatro.next_step(state, 8) == expected


def test_a_lower_target_stops_once_passed():
    assert balatro.next_step({"state": "BLIND_SELECT", "ante_num": 4}, 3)[0] == "won"


def test_moves_are_described_locally():
    blind_state = hand_state(state="BLIND_SELECT")
    assert balatro.describe(Action("select"), blind_state) == "开打Big Blind，目标 1200 分！"
    assert balatro.describe(Action("buy", {"voucher": 0}), shop_state()) == "买下 Grabber"
    assert balatro.describe(Action("sell", {"joker": 0}), shop_state()) == "卖掉 Joker"
    assert balatro.describe(Action("pack", {"card": 1}), pack_state()) == "拿这张：B"


# ---- the local link -------------------------------------------------------------------------------------------
class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.seen.append(request)
        body = self.server.answer(request)
        status, headers = 200, {}
        if isinstance(body, tuple):
            status, headers, body = body
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args):
        pass


@pytest.fixture
def mod_server():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    server.seen = []
    server.answer = lambda req: {"jsonrpc": "2.0", "id": req["id"], "result": {"state": "MENU"}}
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def test_the_link_speaks_json_rpc_on_this_pc_only(mod_server, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:9")  # a system proxy must not be used
    link = balatro.BalatroLink(mod_server.server_address[1], timeout=5)
    assert link.url.startswith("http://127.0.0.1:")
    assert link.gamestate() == {"state": "MENU"}
    link.rpc("play", {"cards": [0, 2]})
    assert mod_server.seen[-1]["method"] == "play" and mod_server.seen[-1]["params"] == {"cards": [0, 2]}
    assert mod_server.seen[-1]["jsonrpc"] == "2.0"


def test_a_refusal_from_the_mod(mod_server):
    mod_server.answer = lambda req: {"jsonrpc": "2.0", "id": req["id"], "error": {
        "code": -32001, "message": "Invalid card index: 99", "data": {"name": "BAD_REQUEST"}}}
    with pytest.raises(LinkError) as caught:
        balatro.BalatroLink(mod_server.server_address[1], timeout=5).rpc("play", {"cards": [99]})
    assert (caught.value.kind, caught.value.message, caught.value.name) == ("api", "Invalid card index: 99", "BAD_REQUEST")


def test_a_reply_that_is_not_json_rpc(mod_server):
    mod_server.answer = lambda _req: b"<html>"
    with pytest.raises(LinkError) as caught:
        balatro.BalatroLink(mod_server.server_address[1], timeout=5).gamestate()
    assert caught.value.kind == "bad_reply"


def test_a_redirect_is_never_followed(mod_server):
    elsewhere = HTTPServer(("127.0.0.1", 0), _Handler)
    elsewhere.seen = []
    elsewhere.answer = lambda req: {"jsonrpc": "2.0", "id": req["id"], "result": {"state": "MENU"}}
    threading.Thread(target=elsewhere.serve_forever, daemon=True).start()
    try:
        target = f"http://127.0.0.1:{elsewhere.server_address[1]}/"
        for status in (301, 302, 303, 307, 308):
            mod_server.answer = lambda _req, s=status: (s, {"Location": target}, b"")
            with pytest.raises(LinkError) as caught:
                balatro.BalatroLink(mod_server.server_address[1], timeout=5).gamestate()
            assert caught.value.kind == "bad_reply" and str(status) in caught.value.message
        assert elsewhere.seen == []
    finally:
        elsewhere.shutdown()
        elsewhere.server_close()


def test_an_http_error_is_not_mistaken_for_no_game(mod_server):
    mod_server.answer = lambda _req: (500, {}, b"oops")
    with pytest.raises(LinkError) as caught:
        balatro.BalatroLink(mod_server.server_address[1], timeout=5).gamestate()
    assert caught.value.kind == "bad_reply"


def test_no_game_running():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    server.server_close()  # nothing listens there now
    with pytest.raises(LinkError) as caught:
        balatro.BalatroLink(port, timeout=2).gamestate()
    assert caught.value.kind == "offline"


# ---- the pet playing ------------------------------------------------------------------------------------------
class FakeLink:
    """The mod: a script of game states; every move is recorded; a move may be refused."""

    def __init__(self, *states):
        self.states = list(states)
        self.moves = []
        self.refuse = None  # a LinkError to raise on the next moves

    def gamestate(self):
        if isinstance(self.refuse, LinkError) and self.refuse.kind == "offline":
            raise self.refuse
        return self.states[0]

    def rpc(self, method, params=None):
        if self.refuse is not None:
            raise self.refuse
        self.moves.append((method, params or {}))
        if len(self.states) > 1:
            self.states.pop(0)  # a move takes the game to its next state
        return {}


@pytest.fixture
def pet(app, tmp_path, monkeypatch):
    for name, value in (("idle_seconds", lambda: 0.0), ("is_fullscreen", lambda _i: False),
                        ("notification_busy", lambda: False)):
        monkeypatch.setattr(controller_module.capture, name, value)
    monkeypatch.setattr(claude_client, "find_claude", lambda _configured="": "claude.exe")
    monkeypatch.setattr(controller_module, "save_config", lambda *_a, **_k: None)
    ctrl = controller_module.PetController(app, Config(sprite_height=220), SPRITES, tmp_path / "config.json")
    monkeypatch.setattr(ctrl, "_spawn", lambda fn: fn())
    monkeypatch.setattr(ctrl, "_ask_claude", lambda *_a: pytest.fail("no screen look while playing"))
    ctrl._rng = random.Random(3)
    monkeypatch.setattr(controller_module, "GAME_SAY_GAP_SEC", 0)  # (a test takes every move at once)
    calls = []

    def model(reply="", ok=True, **flags):
        def run(job, system_prompt, text, jpeg):
            calls.append(text)
            assert jpeg is None and system_prompt  # words only, in her persona
            return claude_client.ClaudeResult(ok, text=reply, error="" if ok else "boom", **flags), True
        monkeypatch.setattr(ctrl, "_run_model", run)

    model()
    yield ctrl, calls, model
    # A game left running would keep its timer: it must not fire into later tests (and start real threads there).
    ctrl.game = None
    ctrl.game_timer.stop()


@pytest.fixture
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def play(ctrl, link):
    ctrl._game_link = lambda _port: link
    ctrl.start_game()
    ctrl.game_timer.stop()


def step(ctrl):
    ctrl._game_next()


def test_starting_says_so_and_stops_automatic_looks_and_self_talk(pet):
    ctrl, _calls, _model = pet
    play(ctrl, FakeLink({"state": "BLIND_SELECT", "ante_num": 1}))
    assert ctrl.window.full_text.startswith("好，我来打 Balatro")
    assert ctrl.game_action.isChecked()
    assert ctrl._auto_gate() == "playing Balatro"
    ctrl.window.clear_bubble()
    ctrl.window.last_said_at = -1e9
    assert not ctrl.maybe_self_talk()
    assert "打牌中" in ctrl.window.status


def test_she_does_not_fall_asleep_while_playing_and_wakes_to_play(pet, monkeypatch):
    ctrl, _calls, _model = pet
    monkeypatch.setattr(controller_module.capture, "idle_seconds", lambda: 1e6)  # 主人 is only watching
    play(ctrl, FakeLink(hand_state()))
    ctrl._update_sleep()
    assert not ctrl.asleep
    ctrl.stop_game()
    ctrl._update_sleep()
    assert ctrl.asleep  # once she stops, as usual
    play(ctrl, FakeLink(hand_state()))
    assert not ctrl.asleep and ctrl.game is not None


def test_the_blind_and_the_cash_out_need_no_model(pet):
    ctrl, calls, _model = pet
    link = FakeLink(hand_state(state="BLIND_SELECT"), {"state": "ROUND_EVAL", "ante_num": 2})
    play(ctrl, link)
    step(ctrl)  # look: choose the blind
    assert ctrl.window.full_text == "开打Big Blind，目标 1200 分！" and ctrl.game.next == "act"
    step(ctrl)  # do it
    assert link.moves == [("select", {})] and ctrl.game.next == "step"
    step(ctrl)
    step(ctrl)
    assert link.moves[-1] == ("cash_out", {}) and calls == []


def test_she_says_her_move_then_makes_it(pet):
    ctrl, calls, model = pet
    model('happy|留这对 K，凑葫芦\n{"action":"discard","cards":[2,3,4]}')
    link = FakeLink(hand_state())
    play(ctrl, link)
    step(ctrl)
    assert ctrl.window.full_text == "留这对 K，凑葫芦" and ctrl.window.mood == "happy"
    assert link.moves == []  # said first
    step(ctrl)
    assert link.moves == [("discard", {"cards": [2, 3, 4]})]
    assert "手牌（编号从 0 起）" in calls[0]


def test_starting_reads_the_names_once_and_a_game_without_them_keeps_playing(pet, monkeypatch):
    ctrl, calls, model = pet
    loads = []
    monkeypatch.setattr(controller_module.balatro_names, "load", lambda: loads.append(1) or {"Big Blind": "大盲注"})
    model('happy|好\n{"action":"discard","cards":[2]}')
    play(ctrl, FakeLink(hand_state(), hand_state()))
    step(ctrl)
    assert "盲注：大盲注" in calls[-1] and len(loads) == 1
    step(ctrl)
    step(ctrl)
    assert len(loads) == 1
    ctrl.stop_game()
    i18n.set_language("en")
    balatro.set_names({})
    play(ctrl, FakeLink(hand_state()))
    step(ctrl)
    assert len(loads) == 1  # her English needs no Chinese names
    i18n.set_language("zh")


def test_she_does_not_say_a_line_for_every_quick_move(pet, monkeypatch):
    ctrl, calls, model = pet
    monkeypatch.setattr(controller_module, "GAME_SAY_GAP_SEC", 15)
    clock = [100.0]
    monkeypatch.setattr(controller_module.time, "monotonic", lambda: clock[0])
    link = FakeLink(hand_state(), hand_state(), hand_state(), hand_state(state="BLIND_SELECT"))
    play(ctrl, link)
    model('talk|第一句\n{"action":"discard","cards":[2]}')
    step(ctrl)
    assert ctrl.window.full_text == "第一句"
    step(ctrl)
    clock[0] += 8
    model('talk|第二句\n{"action":"discard","cards":[3]}')
    step(ctrl)
    assert ctrl.window.full_text == "第一句"
    step(ctrl)
    assert link.moves[-1] == ("discard", {"cards": [3]})  # made all the same
    assert "第二句" in ctrl.game.recent[-1]  # and remembered
    clock[0] += 1
    ctrl.game.suggestions.append("留 K")  # an answer to 主人 does not wait
    model('talk|好，听你的\n{"action":"discard","cards":[4]}')
    step(ctrl)
    assert ctrl.window.full_text == "好，听你的"
    step(ctrl)
    clock[0] += 1
    step(ctrl)  # a new blind does not wait either
    assert ctrl.window.full_text == "开打Big Blind，目标 1200 分！"
    step(ctrl)
    clock[0] += 16
    link.states[:] = [hand_state()]
    model('talk|隔了一会儿\n{"action":"discard","cards":[0]}')
    step(ctrl)
    assert ctrl.window.full_text == "隔了一会儿"


def venus():
    return card("c_venus", "PLANET", "Venus", "Level up Three of a Kind")


def test_a_planet_card_is_used_at_once_without_asking_the_model(pet):
    # 2026-11-03, real run: she bought Venus and held it unused for the ten minutes until she lost
    ctrl, calls, model = pet
    state = hand_state(consumables=area(card("c_lovers", "TAROT", "The Lovers"), venus()))
    link = FakeLink(state, hand_state())
    play(ctrl, link)
    step(ctrl)
    assert ctrl.window.full_text == "用掉 Venus" and calls == []
    step(ctrl)
    assert link.moves == [("use", {"consumable": 1})]
    model('talk|弃\n{"action":"discard","cards":[2]}')
    step(ctrl)
    assert len(calls) == 1  # none left: back to her


def test_a_planet_refused_by_the_game_goes_back_to_the_model(pet):
    ctrl, calls, model = pet
    link = FakeLink(hand_state(consumables=area(venus())))
    original = link.rpc

    def rpc(method, params=None):
        if method == "use":
            raise LinkError("api", "Cannot use this now")
        return original(method, params)

    link.rpc = rpc
    model('talk|弃\n{"action":"discard","cards":[2]}')
    play(ctrl, link)
    step(ctrl)
    step(ctrl)  # refused
    assert ctrl.game.last_error == "Cannot use this now"
    step(ctrl)
    assert len(calls) == 1 and ctrl.window.full_text == "弃"  # not asked to use it for ever


@pytest.mark.parametrize("screen, used, expected", [
    ("SELECTING_HAND", None, Action("use", {"consumable": 0})), ("SHOP", None, Action("use", {"consumable": 0})),
    ("SMODS_BOOSTER_OPENED", None, None), ("SHOP", {"v_observatory": {}}, None), ("SHOP", ["v_observatory"], None),
    ("SHOP", {"v_grabber": {}}, Action("use", {"consumable": 0})), ("SHOP", [], Action("use", {"consumable": 0})),
])
def test_when_a_planet_is_used(screen, used, expected):
    state = {"state": screen, "consumables": area(venus())}
    if used is not None:
        state["used_vouchers"] = used
    assert balatro.card_to_use(state) == expected


def test_a_tarot_whose_use_is_a_choice_stays_hers():
    assert balatro.card_to_use({"state": "SHOP"}) is None
    for key in ("c_lovers", "c_death", "c_hanged_man", "c_strength", "c_tower", "c_star", "c_moon", "c_sun", "c_world", "c_fool"):
        tarot = area(card(key, "TAROT", key))
        assert balatro.card_to_use(hand_state(consumables=tarot)) is None
        assert balatro.card_to_use(dict(shop_state(), consumables=tarot)) is None


def tarot(key):
    return area(card(key, "TAROT", key))


def state_with(key, screen="SHOP", money=9, jokers=None, limit=5):
    joker_cards = [card("j_joker", "JOKER", "Joker")] if jokers is None else jokers
    base = shop_state() if screen == "SHOP" else hand_state()
    base.update(consumables=tarot(key), money=money, jokers={"limit": limit, "cards": joker_cards})
    return base


USE_IT = Action("use", {"consumable": 0})


@pytest.mark.parametrize("key, state, used", [
    ("c_high_priestess", {}, True), ("c_emperor", {}, True),
    ("c_temperance", {}, True), ("c_temperance", {"jokers": []}, False),
    ("c_hermit", {"money": 10}, True), ("c_hermit", {"money": 9}, False),
    ("c_judgement", {}, True), ("c_judgement", {"limit": 1}, False),  # no room for the joker it makes
    ("c_wheel_of_fortune", {}, True),
    ("c_wheel_of_fortune", {"jokers": [card("j_a", "JOKER", "A", edition="FOIL")]}, False),  # nothing it could improve
    ("c_wheel_of_fortune", {"jokers": []}, False),
])
def test_a_tarot_needing_no_cards_is_used_when_it_does_something(key, state, used):
    assert balatro.card_to_use(state_with(key, **state)) == (USE_IT if used else None)
    assert balatro.card_to_use(state_with(key, "SELECTING_HAND", **state)) == (USE_IT if used else None)


KINGS_HAND = ("S_K", "H_K", "D_7", "C_2", "H_9")


@pytest.mark.parametrize("key, targets", [("c_magician", [0, 1]), ("c_empress", [0, 1]), ("c_heirophant", [0, 1]), ("c_justice", [0])])
def test_an_enhancing_tarot_goes_on_cards_that_score(key, targets):
    state = hand_state(KINGS_HAND, consumables=tarot(key))
    assert balatro.card_to_use(state) == Action("use", {"consumable": 0, "cards": targets})
    assert balatro.card_to_use(dict(shop_state(), consumables=tarot(key))) is None  # no hand in the shop


@pytest.mark.parametrize("key", ["c_chariot", "c_devil"])
def test_what_works_while_held_goes_on_the_highest_card_kept(key):
    # steel and gold pay for a card staying in hand, so not one of those to be played
    state = hand_state(KINGS_HAND, consumables=tarot(key))
    assert balatro.card_to_use(state) == Action("use", {"consumable": 0, "cards": [4]})  # the 9


@pytest.mark.parametrize("key", ["c_chariot", "c_devil"])
def test_what_works_while_held_is_not_put_on_a_card_the_psychic_makes_her_play(key):
    five = psychic(KINGS_HAND)
    five["consumables"] = tarot(key)
    assert balatro.card_to_use(five) is None  # all five will be played: the card stays for later
    eight = psychic(("S_K", "H_K", "D_7", "C_2", "H_9", "S_3", "D_4", "C_6"))
    eight["consumables"] = tarot(key)
    used = balatro.card_to_use(eight)
    assert used is not None and used.params["cards"][0] not in balatro.estimate(eight)[1]


def test_what_scores_is_what_gets_enhanced_for_the_psychic():
    state = psychic(("S_K", "H_K", "D_7", "C_2", "H_9", "S_3", "D_4", "C_6"))
    state["consumables"] = tarot("c_empress")
    used = balatro.card_to_use(state)
    assert sorted(used.params["cards"]) == [0, 1]  # the kings, not the cards added to make five


def test_cards_already_enhanced_or_face_down_are_not_chosen():
    hand = [card("S_K", "ENHANCED", enhancement="GLASS"), card("H_K"), card("D_7"), dict(card("C_A"), state={"hidden": True})]
    state = hand_state(consumables=tarot("c_empress"))
    state["hand"] = area(*hand)
    assert balatro.card_to_use(state) == Action("use", {"consumable": 0, "cards": [1]})
    state = hand_state(consumables=tarot("c_chariot"))
    state["hand"] = area(*hand)
    assert balatro.card_to_use(state) == Action("use", {"consumable": 0, "cards": [2]})
    nothing = hand_state(consumables=tarot("c_chariot"))
    nothing["hand"] = area(card("S_K"), card("H_K"))
    assert balatro.card_to_use(nothing) is None  # both to be played


def test_a_tarot_used_by_itself_goes_through_the_game(pet):
    ctrl, calls, model = pet
    link = FakeLink(hand_state(KINGS_HAND, consumables=tarot("c_chariot")), hand_state(KINGS_HAND))
    play(ctrl, link)
    step(ctrl)
    assert ctrl.window.full_text == "用掉 c_chariot" and calls == []
    step(ctrl)
    assert link.moves == [("use", {"consumable": 0, "cards": [4]})]


def test_a_suggestion_comes_before_a_card_used_by_itself(pet):
    ctrl, calls, model = pet
    model('talk|听你的，先留着\n{"action":"discard","cards":[2]}')
    link = FakeLink(hand_state(KINGS_HAND, consumables=tarot("c_chariot")))
    play(ctrl, link)
    ctrl.game.suggestions.append("战车先留着")
    step(ctrl)
    step(ctrl)
    assert link.moves == [("discard", {"cards": [2]})]


def test_no_card_is_used_by_itself_again_after_a_refusal(pet):
    ctrl, calls, model = pet
    model('talk|弃\n{"action":"discard","cards":[2]}')
    link = FakeLink(*(hand_state(KINGS_HAND, consumables=tarot("c_chariot")) for _ in range(4)))
    real = link.rpc

    def refuse_using(method, params=None):
        if method == "use":
            raise LinkError("api", "Cannot use this now")
        return real(method, params)

    link.rpc = refuse_using
    play(ctrl, link)
    step(ctrl)
    step(ctrl)  # refused
    assert ctrl.game.no_auto_use
    step(ctrl)
    step(ctrl)  # she discards, which clears the refusal
    assert ctrl.game.last_error == ""
    step(ctrl)
    assert ctrl.window.full_text == "弃" and len(calls) == 2  # asked again, not used again
    assert [m for m, _ in link.moves] == ["discard"]


def test_she_is_told_how_each_tarot_is_used():
    hand = hand_state(consumables=area(card("c_strength", "TAROT", "Strength"), card("c_fool", "TAROT", "The Fool"), card("c_death", "TAROT", "Death"), card("c_star", "TAROT", "Star")))
    text = balatro.summary(hand, 8)
    assert "要在 cards 里选 1–2 张手牌" in text and "要在 cards 里选 2 张手牌" in text and "要在 cards 里选 1–3 张手牌" in text
    assert "不用选牌，可以直接用" in text
    shop = dict(shop_state(), consumables=tarot("c_strength"))
    assert "要选 1–2 张手牌，到出牌时才能用" in balatro.summary(shop, 8)
    planets = dict(shop_state(), consumables=area(venus()))
    assert "选牌" not in balatro.summary(planets, 8).split("Mars")[0]
    i18n.set_language("en")
    assert 'give 1–2 hand cards in "cards"' in balatro.summary(hand, 8)
    assert "no cards needed" in balatro.summary(hand, 8)
    assert "only usable while playing a hand" in balatro.summary(shop, 8)
    i18n.set_language("zh")


def joker_shop(money, jokers=1):
    shop = rich_shop(money, jokers=jokers)
    shop["shop"]["cards"] = [card("j_dear", "JOKER", "Dear", "", {"buy": 6, "sell": 3}), card("c_mars", "PLANET", "Mars", "", {"buy": 3, "sell": 1}),
                             card("j_cheap", "JOKER", "Cheap", "", {"buy": 4, "sell": 2})]
    return shop


@pytest.mark.parametrize("money, jokers, bought", [
    (8, 1, 2), (4, 2, 2), (6, 0, 2),  # the cheapest of them
    (3, 1, None),  # none she can afford
    (8, 3, None),  # enough jokers
])
def test_which_joker_she_must_buy(money, jokers, bought):
    expected = None if bought is None else Action("buy", {"card": bought})
    assert balatro.joker_to_buy(joker_shop(money, jokers)) == expected


def test_a_joker_that_would_not_fit_is_not_forced():
    shop = joker_shop(8)
    shop["jokers"]["limit"] = 1
    assert balatro.joker_to_buy(shop) is None
    only_a_planet = rich_shop(40, jokers=0)
    only_a_planet["shop"]["cards"] = only_a_planet["shop"]["cards"][1:]
    assert balatro.joker_to_buy(only_a_planet) is None


def test_she_does_not_leave_the_shop_with_too_few_jokers(pet):
    # 2026-11-03, real run: one joker, $8, a $4 joker on sale and the prompt saying buy it first, and she left
    ctrl, calls, model = pet
    model('talk|先存钱\n{"action":"next_round","build":"Flush"}')
    link = FakeLink(joker_shop(8, jokers=2))
    play(ctrl, link)
    step(ctrl)
    assert ctrl.window.full_text == "买下 Cheap"
    step(ctrl)
    assert link.moves == [("buy", {"card": 2})] and ctrl.game.build == "Flush"  # what else she said still counts


def test_buying_something_else_or_having_enough_jokers_is_left_alone(pet):
    ctrl, calls, model = pet
    model('talk|买火星\n{"action":"buy","card":1}')
    link = FakeLink(joker_shop(20))
    play(ctrl, link)
    step(ctrl)
    step(ctrl)
    assert link.moves == [("buy", {"card": 1})]
    ctrl.stop_game()
    model('talk|走了\n{"action":"next_round"}')
    link = FakeLink(joker_shop(20, jokers=3))
    play(ctrl, link)
    step(ctrl)
    step(ctrl)
    assert link.moves == [("next_round", {})]


def test_a_suggestion_can_leave_the_shop_without_a_joker(pet):
    ctrl, calls, model = pet
    model('talk|听你的\n{"action":"next_round"}')
    link = FakeLink(joker_shop(8))
    play(ctrl, link)
    ctrl.game.suggestions.append("这轮什么都别买")
    step(ctrl)
    step(ctrl)
    assert link.moves == [("next_round", {})]


def test_a_forced_joker_the_game_refuses_is_not_tried_for_ever(pet):
    ctrl, calls, model = pet
    model('talk|走了\n{"action":"next_round"}')
    link = FakeLink(joker_shop(8))
    real = link.rpc

    def refuse_buying(method, params=None):
        if method == "buy":
            raise LinkError("api", "Cannot purchase")
        return real(method, params)

    link.rpc = refuse_buying
    play(ctrl, link)
    step(ctrl)
    step(ctrl)  # refused
    step(ctrl)
    step(ctrl)
    assert link.moves == [("next_round", {})]


def spare_shop(money, jokers=3, limit=5, shop=None, vouchers=None):
    state = rich_shop(money, jokers=jokers)
    state["jokers"]["limit"] = limit
    if shop is not None:
        state["shop"]["cards"] = shop
    if vouchers is not None:
        state["vouchers"]["cards"] = vouchers
    return state


def on_sale(key, set_, cost):
    return card(key, set_, key, "", {"buy": cost, "sell": 1})


@pytest.mark.parametrize("money, expected", [
    (40, Action("buy", {"card": 0})),  # the joker leaves $36
    (29, Action("buy", {"card": 0})),  # $25 left: exactly the full interest
    (28, Action("buy", {"card": 1})),  # the joker would leave $24, the planet $25
    (27, None),  # the planet would leave $24 too
    (25, None),  # nothing to spare
    (9, None),
])
def test_money_to_spare_goes_on_what_keeps_the_full_interest(money, expected):
    assert balatro.spare_money_move(spare_shop(money)) == expected


def test_a_joker_tied_to_a_poker_hand_comes_first():
    shop = [on_sale("j_cheap", "JOKER", 2), on_sale("j_wily", "JOKER", 9), on_sale("j_other", "JOKER", 3)]
    assert balatro.spare_money_move(spare_shop(60, shop=shop)) == Action("buy", {"card": 1})
    shop = [on_sale("j_dear", "JOKER", 7), on_sale("j_cheap", "JOKER", 2)]
    assert balatro.spare_money_move(spare_shop(60, shop=shop)) == Action("buy", {"card": 1})  # none: the cheapest


def test_with_no_slot_for_a_joker_the_money_goes_on_a_planet_or_a_voucher():
    full = spare_shop(60, limit=3)
    assert balatro.spare_money_move(full) == Action("buy", {"card": 1})  # the planet
    no_planet = spare_shop(60, limit=3, shop=[on_sale("j_a", "JOKER", 2)])
    assert balatro.spare_money_move(no_planet) == Action("buy", {"voucher": 0})
    no_room_for_it = spare_shop(60, limit=3, shop=[on_sale("c_mars", "PLANET", 3)])
    no_room_for_it["consumables"] = {"limit": 1, "cards": [card("c_lovers", "TAROT", "The Lovers")]}
    assert balatro.spare_money_move(no_room_for_it) == Action("buy", {"voucher": 0})


@pytest.mark.parametrize("money, jokers, limit, reroll, expected", [
    (40, 3, 5, 5, Action("reroll")),
    (30, 3, 5, 5, Action("reroll")),
    (29, 3, 5, 5, None),  # it would cut into the interest
    (40, 5, 5, 5, None),  # no joker could fit: a reroll buys nothing
    (40, 3, 5, 0, None),  # never pushed for free: it costs her nothing to choose
])
def test_a_reroll_only_while_a_joker_could_still_fit(money, jokers, limit, reroll, expected):
    state = spare_shop(money, jokers=jokers, limit=limit, shop=[], vouchers=[])
    state["round"]["reroll_cost"] = reroll
    assert balatro.spare_money_move(state) == expected


def test_a_deck_without_interest_has_no_line_to_keep():
    state = dict(spare_shop(9), deck="GREEN")
    assert balatro.spare_money_move(state) == Action("buy", {"card": 0})


def test_she_is_told_when_money_is_to_spare():
    assert "多出的 $15 不生利息" in balatro.summary(spare_shop(40), 8)
    assert "不生利息" not in balatro.summary(spare_shop(25), 8)
    assert "不生利息" not in balatro.summary(hand_state(money=40), 8)  # only in the shop
    i18n.set_language("en")
    assert "the extra $15 is there to spend" in balatro.summary(spare_shop(40), 8)
    i18n.set_language("zh")


def test_she_does_not_leave_the_shop_with_money_to_spare(pet):
    # 2026-11-03, real run: she lost her furthest run with $74 in hand
    ctrl, calls, model = pet
    model('talk|存钱\n{"action":"next_round"}')
    link = FakeLink(spare_shop(40))
    play(ctrl, link)
    step(ctrl)
    assert ctrl.window.full_text == "买下 Smiley Face"
    step(ctrl)
    assert link.moves == [("buy", {"card": 0})]


def test_her_own_choice_or_a_suggestion_keeps_the_money(pet):
    ctrl, calls, model = pet
    model('talk|买火星\n{"action":"buy","card":1}')
    link = FakeLink(spare_shop(40))
    play(ctrl, link)
    step(ctrl)
    step(ctrl)
    assert link.moves == [("buy", {"card": 1})]
    ctrl.stop_game()
    model('talk|听你的\n{"action":"next_round"}')
    link = FakeLink(spare_shop(40))
    play(ctrl, link)
    ctrl.game.suggestions.append("这轮别花钱")
    step(ctrl)
    step(ctrl)
    assert link.moves == [("next_round", {})]


def test_spending_stops_when_the_game_refuses(pet):
    ctrl, calls, model = pet
    model('talk|走了\n{"action":"next_round"}')
    link = FakeLink(spare_shop(40))
    real = link.rpc

    def refuse(method, params=None):
        if method == "buy":
            raise LinkError("api", "Cannot purchase")
        return real(method, params)

    link.rpc = refuse
    play(ctrl, link)
    step(ctrl)
    step(ctrl)  # refused
    step(ctrl)
    step(ctrl)
    assert link.moves == [("next_round", {})]


def test_the_build_she_names_carries_over_to_the_next_moves(pet):
    ctrl, calls, model = pet
    link = FakeLink(*(hand_state(jokers=TWO_JOKERS) for _ in range(3)))
    play(ctrl, link)
    model('happy|定同花\n{"action":"discard","cards":[2],"build":"Flush"}')
    step(ctrl)
    assert "这局还没定主打" in calls[-1] and ctrl.game.build == "Flush"
    step(ctrl)
    model('talk|继续\n{"action":"discard","cards":[3]}')  # not named again: it stays
    step(ctrl)
    assert "这局主打 Flush" in calls[-1] and ctrl.game.build == "Flush"
    step(ctrl)
    model('talk|改打对子\n{"action":"discard","cards":[4],"build":"Pair"}')
    step(ctrl)
    assert "这局主打 Flush" in calls[-1] and ctrl.game.build == "Pair"
    ctrl.stop_game()
    play(ctrl, FakeLink(hand_state()))
    assert ctrl.game.build == ""  # a new game, a new build


def test_a_purchase_below_the_saving_floor_leaves_the_shop_unless_asked_for(pet):
    ctrl, calls, model = pet
    shop = rich_shop(12, jokers=3)
    model('happy|火星不错\n{"action":"buy","card":1}')
    link = FakeLink(shop)
    play(ctrl, link)
    step(ctrl)
    step(ctrl)
    assert link.moves == [("next_round", {})]  # nothing spent
    ctrl.stop_game()
    link = FakeLink(rich_shop(12, jokers=3))
    play(ctrl, link)
    ctrl.game.suggestions.append("买火星")
    step(ctrl)
    step(ctrl)
    assert link.moves == [("buy", {"card": 1})]  # 主人 asked


def test_a_move_the_game_refused_is_not_remembered_as_done(pet):
    ctrl, calls, model = pet
    link = FakeLink(shop_state())
    real = link.rpc

    def refuse_buying(method, params=None):
        if method == "buy":
            raise LinkError("api", "Not enough money")
        return real(method, params)

    link.rpc = refuse_buying
    model('happy|这张便宜\n{"action":"buy","card":0}')
    play(ctrl, link)
    step(ctrl)  # decide
    assert not ctrl.game.recent
    step(ctrl)  # refused
    step(ctrl)  # decide again
    assert "买下" not in calls[-1] and "Not enough money" in calls[-1]


def test_a_move_dropped_because_the_game_changed_is_not_remembered_as_done(pet):
    ctrl, calls, model = pet
    first, second = hand_state(), hand_state(("H_2", "H_3", "H_4", "H_5", "H_6"))
    link = FakeLink(first)
    play(ctrl, link)
    model('happy|先弃\n{"action":"discard","cards":[2]}')
    step(ctrl)  # decided on the first hand
    link.states[:] = [second]  # 主人 moved the cards
    step(ctrl)
    assert link.moves == [] and not ctrl.game.recent and not ctrl.game.deciding


def test_the_next_prompt_says_what_the_last_move_really_bought(pet):
    ctrl, calls, model = pet
    model('happy|这张便宜\n{"action":"buy","card":0}')
    link = FakeLink(shop_state(), shop_state())
    play(ctrl, link)
    step(ctrl)  # decide
    step(ctrl)  # buy
    step(ctrl)  # decide again
    assert "- 买下 Smiley Face (这张便宜)" in calls[-1]


def test_a_move_is_asked_with_the_configured_thinking_limit(pet, monkeypatch):
    ctrl, _calls, _model = pet
    ctrl.config.balatro_thinking_tokens = 2000
    seen = []

    class Call:
        cancelled = False

        def run(self, args, _message):
            seen.append(args)
            return claude_client.ClaudeResult(True, text='happy|好\n{"action":"play","cards":[0]}')

    monkeypatch.setattr(ctrl, "_run_model", controller_module.PetController._run_model.__get__(ctrl))
    monkeypatch.setattr(ctrl, "_new_call", lambda _provider: Call())
    ctrl.auth_ok_until = float("inf")
    play(ctrl, FakeLink(hand_state()))
    step(ctrl)
    settings = seen[0][seen[0].index("--settings") + 1]
    assert json.loads(settings) == {"env": {"MAX_THINKING_TOKENS": "2000"}}


def test_a_move_that_is_not_allowed_is_replaced_by_the_local_rule(pet):
    ctrl, _calls, model = pet
    model('angry|全买了！\n{"action":"buy","card":0}')
    link = FakeLink(hand_state())
    play(ctrl, link)
    step(ctrl)
    step(ctrl)
    assert link.moves == [("play", {"cards": [0, 1]})]
    assert ctrl.window.full_text == "出：♠K ♥K"


@pytest.mark.parametrize("words, handler", [("忘掉：我的生日", "forget"), ("记住：喜欢同花", "remember")])
def test_remember_and_forget_while_playing_are_not_suggestions(pet, monkeypatch, words, handler):
    ctrl, calls, model = pet  # they never go to a model, and a suggestion would
    play(ctrl, FakeLink(hand_state()))
    handled = []
    monkeypatch.setattr(ctrl, handler, handled.append)
    monkeypatch.setattr(ctrl, "_ask_chat", lambda *_a: words)
    ctrl.chat()
    assert len(handled) == 1 and not ctrl.game.suggestions
    model('talk|弃\n{"action":"discard","cards":[2]}')
    step(ctrl)
    assert words not in calls[-1]


def test_suggestions_wait_for_the_next_decision_and_go_once_seen(pet, monkeypatch):
    ctrl, calls, model = pet
    play(ctrl, FakeLink(hand_state()))
    monkeypatch.setattr(ctrl, "_ask_chat", lambda *_a: "留着两张 K")
    ctrl.chat()
    assert ctrl.window.full_text == "收到！下一步我会参考～" and list(ctrl.game.suggestions) == ["留着两张 K"]
    assert "1 条建议" in ctrl.window.status
    model("", ok=False)
    step(ctrl)  # the call failed: the suggestion stays for the next one
    assert "- 留着两张 K" in calls[-1] and list(ctrl.game.suggestions) == ["留着两张 K"]
    step(ctrl)
    model('happy|好，听你的，留 K\n{"action":"discard","cards":[2]}')
    step(ctrl)
    assert "- 留着两张 K" in calls[-1] and not ctrl.game.suggestions
    assert ctrl.window.full_text == "好，听你的，留 K"


def test_a_failed_model_call_is_asked_again_before_any_move(pet):
    ctrl, calls, model = pet
    model("", ok=False)
    link = FakeLink(hand_state())
    play(ctrl, link)
    for delay in controller_module.GAME_MODEL_RETRY_MS:
        step(ctrl)
        assert link.moves == [] and ctrl.game.next == "step" and ctrl.game_timer.interval() == delay
        assert ctrl.window.full_text == "脑子卡了一下，等等再想这手～"
    step(ctrl)  # still failing: now the local rule, one move
    assert ctrl.window.full_text == "出：♠K ♥K" and ctrl.game.next == "act"
    step(ctrl)
    assert link.moves == [("play", {"cards": [0, 1]})]
    asked = len(calls)
    step(ctrl)  # no more waiting in a long outage, but the model is still asked first
    assert len(calls) == asked + 1 and ctrl.game.next == "act"


def test_a_model_that_answers_again_starts_the_count_over(pet):
    ctrl, _calls, model = pet
    model("", ok=False)
    link = FakeLink(hand_state())
    play(ctrl, link)
    step(ctrl)
    assert ctrl.game.model_failures == 1
    model('happy|好了\n{"action":"play","cards":[0,1]}')
    step(ctrl)
    assert ctrl.game.model_failures == 0 and ctrl.window.full_text == "好了"


def test_too_many_suggestions(pet, monkeypatch):
    ctrl, _calls, _model = pet
    play(ctrl, FakeLink(hand_state()))
    for i in range(controller_module.SUGGESTIONS_MAX):
        ctrl.suggest(f"建议 {i}")
    ctrl.suggest("再一条")
    assert ctrl.window.full_text == "建议有点多啦，我先消化前面的～"
    assert len(ctrl.game.suggestions) == controller_module.SUGGESTIONS_MAX


def test_a_refused_move_is_told_and_retried_then_rules_then_she_stops(pet):
    ctrl, calls, model = pet
    model('talk|买它\n{"action":"play","cards":[0]}')
    link = FakeLink(hand_state())
    play(ctrl, link)
    link.refuse = LinkError("api", "Not enough money", "NOT_ALLOWED")
    for _ in range(controller_module.GAME_RULES_AFTER):
        step(ctrl)
        step(ctrl)
    assert ctrl.window.full_text == "这步不行，我换个做法～"
    assert ctrl.game.last_error == "Not enough money"  # the reason is for her to decide again
    assert ctrl.game.refused == controller_module.GAME_RULES_AFTER
    asked = len(calls)
    assert "上一步被游戏拒绝了：Not enough money" in calls[-1]
    step(ctrl)  # now by rule, without the model
    assert len(calls) == asked and ctrl.window.full_text == "出：♠K ♥K"
    for _ in range(controller_module.GAME_REFUSED_STOP - controller_module.GAME_RULES_AFTER):
        step(ctrl)
        step(ctrl)
    assert ctrl.game is None and ctrl.window.full_text == "一直被游戏拒绝，先不玩了……"
    assert not ctrl.game_action.isChecked()


def test_no_game_running_ends_the_game_mode(pet):
    ctrl, _calls, _model = pet
    link = FakeLink(hand_state())
    link.refuse = LinkError("offline", "refused")
    play(ctrl, link)
    step(ctrl)
    assert ctrl.game is None
    assert ctrl.window.full_text == "连不上 Balatro：要先打开游戏，并装好 BalatroBot mod。"


def test_a_menu_starts_a_run_with_the_chosen_deck(pet):
    ctrl, _calls, _model = pet
    ctrl.config.balatro_deck = "RED"
    link = FakeLink({"state": "MENU"})
    play(ctrl, link)
    step(ctrl)
    assert link.moves == [("start", {"deck": "RED", "stake": "WHITE"})]
    assert ctrl.window.full_text == "开一局红色牌组！"


@pytest.mark.parametrize("state, line", [
    ({"state": "SHOP", "won": True, "ante_num": 9}, "打满 8 个底注啦！这局我们赢了～"),
    ({"state": "GAME_OVER", "ante_num": 5}, "输在第 5 个底注……下次再来！"),
])
def test_the_end_of_a_run_ends_the_game_mode(pet, state, line):
    ctrl, calls, _model = pet
    link = FakeLink(state)
    play(ctrl, link)
    ctrl.game.looked = True  # it ended while she played
    step(ctrl)
    assert ctrl.game is None and ctrl.window.full_text == line and link.moves == [] and calls == []


@pytest.mark.parametrize("state", [
    {"state": "SHOP", "ante_num": 9, "won": False},  # past the target, still going
    {"state": "SELECTING_HAND", "ante_num": 9, "won": True},  # won, playing on in endless mode
])
def test_a_run_past_the_target_is_left_alone_when_she_starts(pet, state):
    ctrl, calls, _model = pet
    link = FakeLink(state)
    play(ctrl, link)
    step(ctrl)
    assert link.moves == [] and calls == []  # never back to the menu: that would throw the run away
    assert ctrl.game is None and ctrl.window.full_text == "这一局已经过了目标底注，我就不接手了。"


def test_a_move_is_not_made_if_the_cards_moved_since_she_decided(pet):
    ctrl, calls, model = pet
    model('happy|弃这张\n{"action":"discard","cards":[0]}')
    link = FakeLink(hand_state())
    play(ctrl, link)
    step(ctrl)
    assert ctrl.game.next == "act"
    link.states[0] = hand_state(keys=("H_9", "S_K", "H_K", "D_7", "C_2"))  # 主人 rearranged the hand
    step(ctrl)
    assert link.moves == [] and ctrl.window.full_text == "牌局变了，我重新看看～"
    assert ctrl.game.next == "step" and ctrl.game.decision is None and ctrl.game.last_error == ""
    step(ctrl)  # decides again on what is there now
    step(ctrl)
    assert link.moves == [("discard", {"cards": [0]})] and len(calls) == 2


@pytest.mark.parametrize("interrupt", ["toggle_pause", "stop_game"])
def test_pausing_or_stopping_during_the_last_look_sends_no_move(pet, interrupt):
    ctrl, _calls, model = pet
    model('happy|弃这张\n{"action":"discard","cards":[0]}')
    link = FakeLink(hand_state())
    play(ctrl, link)
    step(ctrl)
    assert ctrl.game.next == "act"
    read = link.gamestate

    def slow_read():
        getattr(ctrl, interrupt)()  # 主人 presses pause while this read is on its way
        return read()

    link.gamestate = slow_read
    step(ctrl)
    assert link.moves == []  # the same game came back, but the move must not go out


def test_a_move_without_indices_does_not_wait_for_the_cards_to_settle(pet):
    ctrl, _calls, _model = pet
    link = FakeLink(hand_state(state="ROUND_EVAL"))
    play(ctrl, link)
    step(ctrl)
    link.states[0] = hand_state(state="ROUND_EVAL", keys=("S_K",))  # the hand is flying back to the deck
    step(ctrl)
    assert link.moves == [("cash_out", {})] and ctrl.game.refused == 0


def test_a_game_that_never_holds_still_is_given_up(pet):
    ctrl, calls, model = pet
    model('happy|弃这张\n{"action":"discard","cards":[0]}')
    link = FakeLink(hand_state())
    play(ctrl, link)
    orders = iter(["S_K", "H_K", "D_7", "C_2", "H_9", "S_2", "S_3", "S_4"])
    for _ in range(controller_module.GAME_REFUSED_STOP):
        step(ctrl)
        if ctrl.game is None:
            break
        link.states[0] = hand_state(keys=(next(orders), "C_A"))
        step(ctrl)
    assert ctrl.game is None and link.moves == []
    assert len(calls) == controller_module.GAME_RULES_AFTER  # local rules after that, no more calls


def test_the_fingerprint_follows_the_cards_not_their_scores():
    state = hand_state()
    for i, c in enumerate(state["hand"]["cards"]):
        c["id"] = i
    same = dict(state, money=99, round={"chips": 999})  # money and score may change: the indices still mean the same
    assert balatro.fingerprint(same) == balatro.fingerprint(state)
    other = hand_state()
    for i, c in enumerate(other["hand"]["cards"]):
        c["id"] = i + 100  # the same faces, other cards
    assert balatro.fingerprint(other) != balatro.fingerprint(state)
    assert balatro.fingerprint(dict(state, state="SHOP")) != balatro.fingerprint(state)
    assert balatro.fingerprint({"state": "MENU", "hand": []}) == ("MENU", None, None, ((), (), (), (), (), (), ()))


def test_suggestions_survive_a_pause_but_not_stopping(pet):
    ctrl, _calls, _model = pet
    play(ctrl, FakeLink(hand_state()))
    ctrl.suggest("留着两张 K")
    ctrl.toggle_pause()
    ctrl.toggle_pause()
    assert list(ctrl.game.suggestions) == ["留着两张 K"]
    ctrl.stop_game()
    play(ctrl, FakeLink(hand_state()))  # maybe another run by now
    assert not ctrl.game.suggestions


def test_a_run_that_ended_before_she_started_is_followed_by_a_new_one(pet):
    ctrl, _calls, _model = pet
    link = FakeLink({"state": "GAME_OVER", "ante_num": 3}, {"state": "MENU"})
    play(ctrl, link)
    step(ctrl)
    assert link.moves == [("menu", {})] and ctrl.window.full_text == "上一局已经结束了，重新开一局～"
    step(ctrl)
    assert link.moves[-1] == ("start", {"deck": "BLUE", "stake": "WHITE"}) and ctrl.game is not None


def test_pausing_cancels_the_step_and_drops_its_late_answer(pet):
    ctrl, _calls, _model = pet
    link = FakeLink(hand_state())
    play(ctrl, link)
    late = []
    ctrl._spawn = late.append  # the step stays "running"
    step(ctrl)
    assert ctrl.busy
    ctrl.toggle_pause()
    assert not ctrl.busy and ctrl.config.paused and not ctrl.game_timer.isActive()
    ctrl._spawn = lambda fn: fn()
    late[0]()  # its answer arrives after the pause
    assert ctrl.game.decision is None and link.moves == []
    step(ctrl)
    assert link.moves == []  # paused: nothing happens
    ctrl.toggle_pause()
    assert ctrl.game_timer.isActive() and ctrl.game.next == "step"


def test_a_step_cancelled_by_something_else_does_not_stall_the_game(pet):
    ctrl, _calls, _model = pet
    link = FakeLink(hand_state())
    play(ctrl, link)
    late = []
    ctrl._spawn = late.append
    step(ctrl)
    ctrl.set_backend("subscription")  # any change that cancels the request in progress
    ctrl._cancel_inflight()
    assert ctrl.game_timer.isActive() and ctrl.game.next == "step"
    ctrl._spawn = lambda fn: fn()
    late[0]()
    assert ctrl.game.decision is None  # its late answer is dropped
    ctrl.shutdown()
    assert not ctrl.game_timer.isActive()


def test_pokes_while_playing_get_a_local_line(pet):
    ctrl, _calls, _model = pet
    play(ctrl, FakeLink(hand_state()))
    ctrl.poke()
    assert ctrl.window.full_text == "我在专心打牌呢～有话就用「和她说话」告诉我。"
    ctrl._on_poked()
    assert ctrl.window.full_text == "我在专心打牌呢～有话就用「和她说话」告诉我。"


def test_the_menu_switch_starts_and_stops(pet):
    ctrl, _calls, _model = pet
    ctrl._game_link = lambda _port: FakeLink(hand_state())
    ctrl.game_action.trigger()
    assert ctrl.game is not None
    ctrl.game_action.trigger()
    assert ctrl.game is None and ctrl.window.full_text == "不玩啦，我接着陪主人～"
    assert not ctrl.game_timer.isActive()


def test_not_while_paused(pet):
    ctrl, _calls, _model = pet
    ctrl.config.paused = True
    ctrl._game_link = lambda _port: pytest.fail("no link while paused")
    ctrl.start_game()
    assert ctrl.game is None and not ctrl.game_action.isChecked()


def test_a_subscription_problem_ends_the_game_mode(pet):
    ctrl, _calls, model = pet
    model("", ok=False, not_subscription=True)
    play(ctrl, FakeLink(hand_state()))
    step(ctrl)
    assert ctrl.game is None


@pytest.mark.parametrize("raw, deck, ante, port", [
    ({"balatro_deck": "PURPLE", "balatro_target_ante": 12, "balatro_port": 80}, "BLUE", 8, 1024),
    ({"balatro_deck": "RED", "balatro_target_ante": 0, "balatro_port": 99999}, "RED", 1, 65535),
    ({"balatro_target_ante": True, "balatro_port": "x"}, "BLUE", 8, 12346),
])
def test_settings_are_kept_in_range(raw, deck, ante, port):
    config = Config(**raw).normalized()
    assert (config.balatro_deck, config.balatro_target_ante, config.balatro_port) == (deck, ante, port)


@pytest.mark.parametrize("raw, tokens", [(0, 0), (2000, 2000), (-5, 0), (99999, 8000), (True, 0), ("x", 0)])
def test_the_thinking_limit_is_kept_in_range(raw, tokens):
    assert Config(balatro_thinking_tokens=raw).normalized().balatro_thinking_tokens == tokens


def test_only_a_game_limits_her_thinking():
    assert "--settings" not in claude_client.build_args("claude.exe", "haiku", "SYS")
    assert Config().balatro_thinking_tokens == 0
    args = claude_client.build_args("claude.exe", "haiku", "SYS", 0)
    assert json.loads(args[args.index("--settings") + 1]) == {"env": {"MAX_THINKING_TOKENS": "0"}}
