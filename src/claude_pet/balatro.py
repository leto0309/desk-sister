"""Playing Balatro with 主人: the BalatroBot mod's JSON-RPC on 127.0.0.1, what the model is told, and what it may do.

Nothing here touches the screen, the mouse or the keyboard. The game is read and played only through the mod's local
API; the model gets the game as text and answers with one action, which is checked against what the current
screen allows before anything is sent to the game. Pure logic and plain HTTP: no Qt, safe on a worker thread.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from itertools import combinations

from . import persona
from .i18n import english, tr

HOST = "127.0.0.1"  # the mod is only ever reached on this machine
STAKE = "WHITE"
DECKS = ("RED", "BLUE", "YELLOW", "GREEN", "BLACK", "MAGIC", "NEBULA", "GHOST", "ABANDONED", "CHECKERED", "ZODIAC",
         "PAINTED", "ANAGLYPH", "PLASMA", "ERRATIC")
DECISION_STATES = ("SELECTING_HAND", "SHOP", "SMODS_BOOSTER_OPENED")
SAY_MAX = 40  # characters of her line about a move (the prompt asks for about 20)
SAY_MAX_EN = 80  # English takes about twice the characters for the same line
SUGGESTION_MAX = 200
EFFECT_MAX = 70  # characters of a card's effect text in the prompt
JOKERS_FIRST = 3  # with fewer jokers than this, a joker may be bought whatever the saving rule says
BUILD_AFTER_JOKERS = 2  # she picks a poker hand to build around only with this many jokers to go on
HAND_SHARE = 0.6  # cards worth less than this share of the best hand give way to it: other jokers may explain a little less
HAND_JOKERS = {  # the jokers that reward one poker hand
    "Pair": ("j_jolly", "j_sly", "j_duo"), "Three of a Kind": ("j_zany", "j_wily", "j_trio"),
    "Two Pair": ("j_mad", "j_clever", "j_trousers"), "Straight": ("j_crazy", "j_devious", "j_order", "j_runner"),
    "Flush": ("j_droll", "j_crafty", "j_tribe"), "Four of a Kind": ("j_family",),
}
HAND_BONUSES = {  # joker: the hand it needs, + chips, + mult, × mult (the game's own numbers)
    "j_jolly": ("Pair", 0, 8, 1), "j_zany": ("Three of a Kind", 0, 12, 1), "j_mad": ("Two Pair", 0, 10, 1),
    "j_crazy": ("Straight", 0, 12, 1), "j_droll": ("Flush", 0, 10, 1), "j_sly": ("Pair", 50, 0, 1),
    "j_wily": ("Three of a Kind", 100, 0, 1), "j_clever": ("Two Pair", 80, 0, 1), "j_devious": ("Straight", 100, 0, 1),
    "j_crafty": ("Flush", 80, 0, 1), "j_duo": ("Pair", 0, 0, 2), "j_trio": ("Three of a Kind", 0, 0, 3),
    "j_family": ("Four of a Kind", 0, 0, 4), "j_order": ("Straight", 0, 0, 3), "j_tribe": ("Flush", 0, 0, 2),
}
TAROT_TARGETS = {  # how many hand cards a tarot needs, from the game's config; those not listed need none
    "c_magician": (1, 2), "c_empress": (1, 2), "c_heirophant": (1, 2), "c_lovers": (1, 1), "c_chariot": (1, 1), "c_justice": (1, 1),
    "c_strength": (1, 2), "c_hanged_man": (1, 2), "c_death": (2, 2), "c_devil": (1, 1), "c_tower": (1, 1), "c_star": (1, 3),
    "c_moon": (1, 3), "c_sun": (1, 3), "c_world": (1, 3),
}
ENHANCE_PLAYED = {"c_magician": 2, "c_empress": 2, "c_heirophant": 2, "c_justice": 1}  # worth most on cards that score
ENHANCE_HELD = {"c_chariot": 1, "c_devil": 1}  # steel and gold work while the card stays in hand
HERMIT_FROM = 10  # money: it doubles it, up to $20
BIG_HANDS = ("Straight", "Flush", "Full House", "Four of a Kind", "Straight Flush", "Five of a Kind", "Flush House", "Flush Five")  # never discarded
RANKS = tuple("23456789TJQKA")  # a tuple: a card with no rank (a Stone Card gives None) is simply not in it
SUITS = {"H": "♥", "D": "♦", "C": "♣", "S": "♠"}
_names: dict[str, str] = {}  # key or English name -> the game's Chinese name (balatro_names); empty: English names


def set_names(names: dict[str, str]) -> None:
    global _names
    _names = names


def local_name(name: str, fallback: str | None = None) -> str:
    """What 主人 sees in the game: the mod only reports English names."""
    fallback = name if fallback is None else fallback
    if english():
        return fallback
    return _names.get(name) or _names.get(fallback, fallback)


class LinkError(Exception):
    """`offline`: the game or the mod is not there; `api`: the mod refused the request; `bad_reply`: not JSON-RPC."""

    def __init__(self, kind: str, message: str, name: str = "") -> None:
        super().__init__(message)
        self.kind, self.message, self.name = kind, message, name


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is never followed: whatever answers on that port cannot send a request off this PC."""

    def redirect_request(self, *_args, **_kwargs):
        return None


class BalatroLink:
    """JSON-RPC 2.0 over HTTP to the BalatroBot mod on 127.0.0.1. No system proxy and no redirects: the request never
    leaves this PC."""

    def __init__(self, port: int, timeout: float = 30.0) -> None:
        self.url = f"http://{HOST}:{int(port)}"
        self.timeout = timeout
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        self._id = 0

    def rpc(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        body = json.dumps({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}}).encode("utf-8")
        request = urllib.request.Request(self.url, body, {"Content-Type": "application/json"})
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read(8 * 1024 * 1024)
        except urllib.error.HTTPError as exc:  # something answers there, but not the mod's JSON-RPC (a 3xx lands here too)
            exc.close()
            raise LinkError("bad_reply", f"HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError) as exc:  # refused, reset, timed out: no game with the mod running
            raise LinkError("offline", str(getattr(exc, "reason", exc))) from exc
        try:
            reply = json.loads(raw)
        except ValueError as exc:
            raise LinkError("bad_reply", "not JSON") from exc
        if not isinstance(reply, dict):
            raise LinkError("bad_reply", "not a JSON-RPC reply")
        error = reply.get("error")
        if isinstance(error, dict):
            data = error.get("data") if isinstance(error.get("data"), dict) else {}
            raise LinkError("api", str(error.get("message") or "error")[:200], str(data.get("name") or ""))
        result = reply.get("result")
        if not isinstance(result, dict):
            raise LinkError("bad_reply", "no result")
        return result

    def gamestate(self) -> dict:
        return self.rpc("gamestate")


@dataclass(frozen=True)
class Action:
    method: str
    params: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Decision:
    action: Action
    mood: str
    text: str
    by_model: bool  # False: a local rule chose it (no model, or the model's answer was not allowed)
    build: str = ""  # the poker hand she now means to build this run around (English name), if she named one


# ---- reading the game state -----------------------------------------------------------------------------------
def cards(state: dict, area: str) -> list[dict]:
    """The cards of an area (hand, jokers, consumables, shop, vouchers, packs, pack); [] when there is none."""
    value = state.get(area)
    found = value.get("cards") if isinstance(value, dict) else None
    return [c for c in found if isinstance(c, dict)] if isinstance(found, list) else []


def fingerprint(state: dict) -> tuple:
    """What a move's indices depend on: the screen, and which card is where (a card's id stays with it). A move decided
    on one fingerprint is not made on another, so a card 主人 moved or played meanwhile is never hit by an old index."""
    areas = tuple(tuple((c.get("id"), c.get("key")) for c in cards(state, area))
                  for area in ("hand", "jokers", "consumables", "shop", "vouchers", "packs", "pack"))
    return state.get("state"), state.get("ante_num"), state.get("round_num"), areas


def _round(state: dict) -> dict:
    value = state.get("round")
    return value if isinstance(value, dict) else {}


def _int(value, default: int = 0) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}  # Lua's empty tables come out as []


def is_hidden(card: dict) -> bool:
    """Face down (The Wheel, The House...). The mod reports such a card's real value anyway; she must not peek."""
    return bool(_dict(card.get("state")).get("hidden"))


def card_name(card: dict) -> str:
    """♥A, ♠10 for playing cards; the label for anything else; nothing for a card lying face down."""
    if is_hidden(card):
        return _label("（盖着的牌）", "(face down)")
    value = _dict(card.get("value"))
    rank, suit = value.get("rank"), value.get("suit")
    if (card.get("set") in ("DEFAULT", "ENHANCED") and rank in RANKS and isinstance(suit, str) and suit in SUITS
            and not _is_stone(card)):
        return SUITS[suit] + ("10" if rank == "T" else rank)
    return local_name(str(card.get("key") or ""), str(card.get("label") or card.get("key") or "?"))


def current_blind(state: dict) -> dict:
    blinds = state.get("blinds")
    items = list(blinds.values()) if isinstance(blinds, dict) else blinds if isinstance(blinds, list) else []
    items = [b for b in items if isinstance(b, dict)]
    for status in ("CURRENT", "SELECT"):
        for blind in items:
            if blind.get("status") == status:
                return blind
    return {}


DECK_NAMES = {
    "RED": ("红色牌组", "Red Deck"), "BLUE": ("蓝色牌组", "Blue Deck"), "YELLOW": ("黄色牌组", "Yellow Deck"),
    "GREEN": ("绿色牌组", "Green Deck"), "BLACK": ("黑色牌组", "Black Deck"), "MAGIC": ("魔法牌组", "Magic Deck"),
    "NEBULA": ("星云牌组", "Nebula Deck"), "GHOST": ("幽灵牌组", "Ghost Deck"), "ABANDONED": ("废弃牌组", "Abandoned Deck"),
    "CHECKERED": ("方格牌组", "Checkered Deck"), "ZODIAC": ("黄道牌组", "Zodiac Deck"), "PAINTED": ("彩绘牌组", "Painted Deck"),
    "ANAGLYPH": ("立体牌组", "Anaglyph Deck"), "PLASMA": ("等离子牌组", "Plasma Deck"), "ERRATIC": ("古怪牌组", "Erratic Deck"),
}


def deck_name(deck: str) -> str:
    zh, en = DECK_NAMES.get(deck, (deck, deck))
    return _label(zh, en)


def ante(state: dict) -> int:
    return _int(state.get("ante_num"), 1)


def _label(zh: str, en: str) -> str:
    return en if english() else zh


def _short(text: object, limit: int = EFFECT_MAX) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


EDITIONS = {  # what an edition is worth, since its bare name says little
    "FOIL": ("箔片：+50 筹码", "foil: +50 chips"), "HOLO": ("镭射：+10 倍率", "holographic: +10 mult"),
    "POLYCHROME": ("多彩：×1.5 倍率", "polychrome: x1.5 mult"),
    "NEGATIVE": ("负片：不占槽位，再多 1 个小丑槽位", "negative: takes no slot, +1 joker slot"),
}


def _describe(card: dict, playing: bool) -> str:
    if is_hidden(card):
        return card_name(card)  # not even its enhancement or edition
    modifier = _dict(card.get("modifier"))
    extras = [str(modifier[k]).lower() for k in ("enhancement", "seal") if modifier.get(k)]
    edition = modifier.get("edition")
    if edition:
        zh, en = EDITIONS.get(edition, (str(edition).lower(), str(edition).lower()))
        extras.append(_label(zh, en))
    if modifier.get("eternal"):
        extras.append("eternal")
    if modifier.get("rental"):
        extras.append("rental")
    if _dict(card.get("state")).get("debuff"):
        extras.append(_label("被削弱", "debuffed"))
    text = card_name(card)
    if not playing:
        effect = _short(_dict(card.get("value")).get("effect"))
        kind = str(card.get("set") or "").lower()
        text += f" [{kind}]" if kind else ""
        text += f"：{effect}" if effect and not english() else f": {effect}" if effect else ""
    if extras:
        text += f" ({', '.join(extras)})"
    return text


def _slots(state: dict, area: str) -> str:
    """How full the jokers or consumables are: a full row must sell one before buying (a negative joker needs no slot)."""
    if area not in ("jokers", "consumables"):
        return ""
    limit = _int(_dict(state.get(area)).get("limit"), -1)
    if limit < 0:
        return ""
    used = len(cards(state, area))
    if used < limit:
        return _label(f"（已用 {used}/{limit}）", f" ({used}/{limit} used)")
    return _label(f"（已用 {used}/{limit}，满了：先卖一张才能买新的）", f" ({used}/{limit} used, full: sell one before buying a new one)")


def interest_cap(state: dict) -> int:
    """The most interest a round can pay: $5, raised by two vouchers; the Green Deck pays none."""
    if state.get("deck") == "GREEN":
        return 0
    used = state.get("used_vouchers")
    used = used if isinstance(used, (dict, list)) else ()
    return 20 if "v_money_tree" in used else 10 if "v_seed_money" in used else 5


def interest(state: dict, money: int) -> int:
    """$1 for every $5 held when the round ends, up to the cap."""
    return min(max(money, 0) // 5, interest_cap(state))


def _no_slot(state: dict, card: dict) -> bool:
    """Bought, it would not fit (a negative joker brings its own slot)."""
    area = {"JOKER": "jokers", "TAROT": "consumables", "PLANET": "consumables", "SPECTRAL": "consumables"}.get(card.get("set"))
    if area is None or _dict(card.get("modifier")).get("edition") == "NEGATIVE":
        return False
    limit = _int(_dict(state.get(area)).get("limit"), -1)
    return 0 <= limit <= len(cards(state, area))


def money_floor(state: dict) -> int:
    """What a purchase must leave: more each ante, up to what pays the full interest. Without thinking she spends it all."""
    return min(interest_cap(state) * 5, 5 * ante(state))


def _must_save_for(state: dict, card: dict, area: str, cost: int) -> bool:
    if _int(state.get("money")) - cost >= money_floor(state):
        return False
    return not (area == "shop" and card.get("set") == "JOKER" and len(cards(state, "jokers")) < JOKERS_FIRST)


def _must_save_for_reroll(state: dict) -> bool:
    cost = _int(_round(state).get("reroll_cost"), 5)
    return cost > 0 and _int(state.get("money")) - cost < interest_cap(state) * 5


def _breaks_saving(action: Action, state: dict) -> bool:
    if action.method == "reroll":
        return _must_save_for_reroll(state)
    if action.method != "buy":
        return False
    (key, index), = action.params.items()
    area = MOVED_AREAS["buy"][key]
    card = cards(state, area)[index]
    return _must_save_for(state, card, area, _int(_dict(card.get("cost")).get("buy")))


def saving_note(state: dict) -> str:
    """Empty on a deck without interest: nothing to save for."""
    if not interest_cap(state):
        return ""
    floor, jokers = money_floor(state), JOKERS_FIRST
    if english():
        return (f"Saving rule: on this ante keep at least ${floor} after buying; with fewer than {jokers} jokers a joker is "
                "exempt. Items marked \"saving\" cannot be bought now.")
    return f"存钱规则：这个底注买完至少留 ${floor}；小丑不足 {jokers} 张时买小丑不受限。标了「要存钱」的现在不能买。"


def joker_to_buy(state: dict) -> Action | None:
    """With few jokers, the cheapest one she can afford and fit. Told to buy one first, she still left with $8 and one joker."""
    if len(cards(state, "jokers")) >= JOKERS_FIRST:
        return None
    money = _int(state.get("money"))
    costs = {i: cost for i, card in enumerate(cards(state, "shop"))
             if card.get("set") == "JOKER" and (cost := _int(_dict(card.get("cost")).get("buy"))) <= money and not _no_slot(state, card)}
    return Action("buy", {"card": min(costs, key=costs.get)}) if costs else None


def spare_money_move(state: dict) -> Action | None:
    """Money above the full interest earns nothing, and she lost a run with $74 in hand. What to spend it on, keeping the full
    interest: a joker with room for it (first those tied to a poker hand), a planet (used at once), a voucher (for good), or a
    reroll while a joker could still fit. Packs are left to her: what is in them is hers to choose."""
    money, line = _int(state.get("money")), interest_cap(state) * 5

    def spare(area: str, kind: str | None = None) -> list[tuple[int, dict, int]]:
        found = [(i, c, _int(_dict(c.get("cost")).get("buy"))) for i, c in enumerate(cards(state, area)) if kind in (None, c.get("set"))]
        return [entry for entry in found if money - entry[2] >= line and not _no_slot(state, entry[1])]

    jokers = spare("shop", "JOKER")
    if jokers:
        return Action("buy", {"card": min(jokers, key=lambda e: (e[1].get("key") not in HAND_BONUSES, e[2]))[0]})
    planets = spare("shop", "PLANET")
    if planets:
        return Action("buy", {"card": min(planets, key=lambda e: e[2])[0]})
    vouchers = spare("vouchers")
    if vouchers:
        return Action("buy", {"voucher": min(vouchers, key=lambda e: e[2])[0]})
    reroll = _int(_round(state).get("reroll_cost"), 5)
    room = _int(_dict(state.get("jokers")).get("limit"), -1) > len(cards(state, "jokers"))
    return Action("reroll") if room and reroll > 0 and money - reroll >= line else None


def leaving_move(state: dict) -> Action | None:
    """What she should do instead of leaving the shop, if anything."""
    return joker_to_buy(state) or spare_money_move(state)


def spare_money_note(state: dict) -> str:
    money, line = _int(state.get("money")), interest_cap(state) * 5
    if money <= line:
        return ""
    return _label(f"钱已超过满额利息的 ${line}，多出的 ${money - line} 不生利息：看中加分的小丑、星球牌或优惠券就买。什么都不买就走的话，程序会替你花。",
                  f"Money above ${line} earns no interest, so the extra ${money - line} is there to spend: buy a joker that scores, a planet "
                  "or a voucher. If you leave without buying, it gets spent for you.")


def joker_note(state: dict) -> str:
    """Early on a joker is worth more than interest: the saving rule alone made her walk past them."""
    if joker_to_buy(state) is None:
        return ""
    return _label(f"小丑还不足 {JOKERS_FIRST} 张，这是现在最缺的：有买得起的小丑就优先买，别为了存钱放过。",
                  f"You have fewer than {JOKERS_FIRST} jokers and need them most: buy one you can afford first, rather than saving.")


def build_note(state: dict, build: str) -> str:
    """The poker hand she is building around, and what the run so far says about it: she remembers nothing else between moves."""
    enough = len(cards(state, "jokers")) >= BUILD_AFTER_JOKERS
    if english():
        first = (f"You are building around {local_name(build)}: favour it when buying. If you already hold a bigger hand, play "
                 'that; do not break it up for the build. Only if it clearly should change, put a new one in the JSON as "build" '
                 "and say why in your line." if build else
                 'No build yet: from the levels and jokers pick the poker hand to build around, and add "build":"<hand>" to the JSON.'
                 if enough else "Too few jokers to choose a build: play the biggest hand you have, and do not break up a pair or "
                 "three of a kind to chase one.")
    else:
        first = (f"这局主打 {local_name(build)}：买牌时优先配合它；手里已有更大的牌型就先出，别为了它拆牌。确实该换时才在 JSON 里写新的 \"build\"，并在解说里说为什么。" if build else
                 "这局还没定主打：根据牌型等级和小丑选一个牌型，在 JSON 里加 \"build\":\"牌型名\"。" if enough else
                 "小丑还少，先不定主打：手里有什么大牌型就出什么，别为了凑牌型拆掉对子或三条。")
    facts = _build_facts(state)
    return f"{first}{_label('依据：', ' So far: ')}{facts}" if facts else first


def _build_facts(state: dict) -> str:
    hands = state.get("hands") if isinstance(state.get("hands"), dict) else {}
    played = sorted(((_int(_dict(hands.get(name)).get("played")), name) for name in BASE_HANDS), key=lambda kv: -kv[0])
    owned = {c.get("key") for c in cards(state, "jokers")}
    comma = _label("、", ", ")
    parts = []
    most = [f"{local_name(name)} {count}{_label(' 次', 'x')}" for count, name in played[:2] if count > 0]
    if most:
        parts.append(_label("出得最多 ", "played most ") + comma.join(most))
    leveled = [f"{local_name(name)} L{level}" for name in BASE_HANDS if (level := _int(_dict(hands.get(name)).get("level"), 1)) > 1]
    if leveled:
        parts.append(_label("升过级 ", "leveled up ") + comma.join(leveled))
    favoured = [f"{local_name(name)} {count}{_label(' 张', '')}" for name, keys in HAND_JOKERS.items()
                if (count := len(owned.intersection(keys)))]
    if favoured:
        parts.append(_label("小丑偏向 ", "jokers favour ") + comma.join(favoured))
    return _label("；", "; ").join(parts)


def _after_buying(state: dict, card: dict, area: str, cost: int, saving: bool) -> str:
    money = _int(state.get("money"))
    if cost > money:
        return _label("（钱不够）", " (not enough money)")
    if _no_slot(state, card):
        return _label("（槽位满了，现在买不了）", " (no free slot: cannot be bought now)")
    if saving and _must_save_for(state, card, area, cost):
        return _label("（要存钱，现在不买）", " (saving: not now)")
    if not interest_cap(state):
        return ""
    left = interest(state, money - cost)
    return _label(f"（买后利息 ${left}）", f" (interest ${left} after buying)")


def interest_note(state: dict) -> str:
    """What holding money is worth, so that she weighs a purchase against it instead of spending by default."""
    cap, money = interest_cap(state), _int(state.get("money"))
    if not cap:
        return _label("这个牌组没有利息，钱留着也不生钱。", "This deck pays no interest: money held earns nothing.")
    now = interest(state, money)
    if english():
        return (f"Interest: at the end of a round you get $1 for every $5 held, at most ${cap} (full at ${cap * 5}). With "
                f"${money} that is ${now}. Money spent now earns less every round after: buy what clearly helps "
                "(a good joker early is usually worth it), not just because you can afford it.")
    return (f"利息：回合结束时每有 $5 多得 $1，最多 ${cap}（存到 ${cap * 5} 封顶）。现在 ${money}，可得 ${now}。"
            "现在花掉的钱，之后每回合都少生钱：明显有用的才买（前期的好小丑通常值得），别因为买得起就买。")


def _how_to_use(state: dict, card: dict) -> str:
    """What a tarot in hand takes, spelled out: told only "cards if it needs targets", she used them without any."""
    if card.get("set") != "TAROT":
        return ""
    targets = TAROT_TARGETS.get(card.get("key"))
    if targets is None:
        return _label("（不用选牌，可以直接用）", " (no cards needed: can be used now)")
    low, high = targets
    count = str(low) if low == high else f"{low}–{high}"
    if state.get("state") == "SELECTING_HAND":
        return _label(f"（要在 cards 里选 {count} 张手牌）", f" (give {count} hand cards in \"cards\")")
    return _label(f"（要选 {count} 张手牌，到出牌时才能用）", f" (needs {count} hand cards: only usable while playing a hand)")


def _listing(state: dict, area: str, playing: bool = False, price: str = "", saving: bool = True) -> list[str]:
    out = []
    for i, card in enumerate(cards(state, area)):
        line = f"  {i}: {_describe(card, playing)}"
        if area == "consumables":
            line += _how_to_use(state, card)
        cost = _int(_dict(card.get("cost")).get(price), -1) if price else -1
        if cost >= 0:
            line += f" ${cost}"
            if price == "buy":
                line += _after_buying(state, card, area, cost, saving)
        out.append(line)
    return out


def summary(state: dict, target_ante: int, saving: bool = True) -> str:
    """The game in a few lines of text for the model (no screenshot is ever taken). saving: the saving rule applies."""
    rnd = _round(state)
    blind = current_blind(state)
    lines = [_label("底注 {0}/{1}，第 {2} 回合，钱 ${3}。", "Ante {0}/{1}, round {2}, money ${3}.").format(
        _int(state.get("ante_num"), 1), target_ante, _int(state.get("round_num")), _int(state.get("money")))]
    if blind:
        lines.append(_label("盲注：{0}，目标 {1} 分；效果：{2}", "Blind: {0}, target {1}; effect: {2}").format(
            local_name(blind.get("name") or blind.get("type") or "?"), _int(blind.get("score")), _short(blind.get("effect"))))
    if state.get("state") == "SELECTING_HAND":
        lines.append(_label("本回合已得 {0} 分，剩余出牌 {1} 次、弃牌 {2} 次。",
                            "Scored {0} this round; {1} hands and {2} discards left.").format(
            _int(rnd.get("chips")), _int(rnd.get("hands_left")), _int(rnd.get("discards_left"))))
    hands = state.get("hands") if isinstance(state.get("hands"), dict) else {}
    table = []
    for name, (chips, mult) in hand_values(state).items():
        if name in HIDDEN_HANDS:
            continue
        level = _int(_dict(hands.get(name)).get("level"), 1)
        table.append(f"{local_name(name)}{f' L{level}' if level > 1 else ''} {chips}×{mult}")
    lines.append(_label("牌型（筹码×倍率）：", "Poker hands (chips×mult): ") + "; ".join(table))
    for area, zh, en, playing, price in (
            ("jokers", "小丑", "Jokers", False, "sell"),
            ("consumables", "消耗牌", "Consumables", False, "sell"),
            ("hand", "手牌（编号从 0 起）", "Hand (0-based)", True, ""),
            ("shop", "商店卡牌（buy card）", "Shop cards (buy card)", False, "buy"),
            ("vouchers", "优惠券（buy voucher）", "Vouchers (buy voucher)", False, "buy"),
            ("packs", "卡包（buy pack）", "Packs (buy pack)", False, "buy"),
            ("pack", "已打开的卡包", "Opened pack", False, "")):
        if area == "hand" and state.get("state") == "SHOP":
            continue
        listed = _listing(state, area, playing, price, saving)
        if listed:
            note = _label("（价格为卖价）", " (prices are sell values)") if price == "sell" else ""
            lines.append(_label(zh, en) + _slots(state, area) + note + ":")
            lines.extend(listed)
    if state.get("state") == "SHOP":
        reroll = _int(rnd.get("reroll_cost"), 5)
        lines.append(_label("刷新商店要 ${0}，只换商店卡牌；优惠券和卡包不会变（优惠券每个底注才换一次），想要的优惠券别靠刷新找。",
                            "A reroll costs ${0} and only replaces the shop cards; vouchers and packs stay (a new voucher "
                            "comes only with the next ante), so do not reroll to find one.").format(reroll))
        if reroll > _int(state.get("money")):
            lines.append(_label("钱不够，现在不能刷新。", "Not enough money: you cannot reroll now."))
        elif saving and _must_save_for_reroll(state):
            lines.append(_label("要存钱，现在不能刷新（存够满额利息才刷新）。", "Saving: no reroll until the full interest is covered."))
        lines.append(interest_note(state))
        if saving and saving_note(state):
            lines.append(saving_note(state))
        for note in (joker_note(state), spare_money_note(state)):
            if note:
                lines.append(note)
    if state.get("state") == "SELECTING_HAND" and cards(state, "hand"):
        if blind_rule_note(state):
            lines.append(blind_rule_note(state))
        lines.append(scoring_note(state))
    return "\n".join(lines)


def scoring_note(state: dict) -> str:
    """How scoring works, what the best hand now is worth without jokers, and how much each hand left must make."""
    rnd = _round(state)
    name, picked, score = estimate(state)
    hand = cards(state, "hand")
    need = max(0, _int(current_blind(state).get("score")) - _int(rnd.get("chips")))
    hands_left = max(1, _int(rnd.get("hands_left"), 1))
    shown = " ".join(f"{i}:{card_name(hand[i])}" for i in picked)
    tied = any(c.get("key") in HAND_BONUSES for c in cards(state, "jokers"))
    if english():
        text = (f"Scoring: (hand chips + chips of the scoring cards) × mult, then the jokers; only the cards that form the "
                f"hand score. {'With the jokers tied to a poker hand' if tied else 'Without jokers'}, the best hand now is {name} ({shown}), about {score}. Still needed: {need} "
                f"with {hands_left} hands left, about {need // hands_left} a hand.")
        if score * hands_left < need and _int(rnd.get("discards_left")) > 0:
            text += (" That is not enough: discard the cards you will not use to dig for a bigger hand "
                     "(flush, straight, full house...), rather than playing a small one.")
        return text
    text = (f"计分：（牌型筹码 + 计分牌的点数）× 倍率，再算小丑；只有组成牌型的牌计分。{'算上牌型小丑' if tied else '不算小丑时'}，现在最好的是 {local_name(name)}"
            f"（{shown}），约 {score} 分。还差 {need} 分，剩 {hands_left} 手，平均每手要约 {need // hands_left} 分。")
    if score * hands_left < need and _int(rnd.get("discards_left")) > 0:
        text += "照这样打不够：先弃掉用不上的牌，去凑同花、顺子、葫芦这类大牌型，别急着出小牌型。"
    return text


ACTIONS_ZH = {
    "SELECTING_HAND": ['{"action":"play","cards":[编号,...]}  出 1–5 张',
                       '{"action":"discard","cards":[编号,...]}  弃 1–5 张（还有弃牌次数时）',
                       '{"action":"use","consumable":编号,"cards":[目标手牌编号,...]}  用消耗牌（需要目标时才写 cards）'],
    "SHOP": ['{"action":"buy","card":编号}  买「商店卡牌」里的一张（商店里的小丑也用 card，编号看商店卡牌那一栏）',
             '{"action":"buy","voucher":编号} / {"action":"buy","pack":编号}',
             '{"action":"sell","joker":编号} / {"action":"sell","consumable":编号}',
             '{"action":"reroll"}  刷新商店',
             '{"action":"use","consumable":编号}  只能用不需要选目标的；要选手牌的留到出牌时用（商店里没有手牌）',
             '{"action":"next_round"}  逛完了，去下一回合'],
    "SMODS_BOOSTER_OPENED": ['{"action":"pack","card":编号}  拿卡包里的一张（需要目标时加 "targets":[手牌编号,...]）',
                             '{"action":"pack","skip":true}  跳过'],
}
ACTIONS_EN = {
    "SELECTING_HAND": ['{"action":"play","cards":[index,...]}  play 1-5 cards',
                       '{"action":"discard","cards":[index,...]}  discard 1-5 cards (if discards are left)',
                       '{"action":"use","consumable":index,"cards":[hand index,...]}  use a consumable (cards only if it needs targets)'],
    "SHOP": ['{"action":"buy","card":index}  buy one of the shop cards (jokers in the shop are bought with "card" too, '
             'using their index in the shop cards list)',
             '{"action":"buy","voucher":index} / {"action":"buy","pack":index}',
             '{"action":"sell","joker":index} / {"action":"sell","consumable":index}',
             '{"action":"reroll"}',
             '{"action":"use","consumable":index}  only one that needs no targets; keep those that do for a hand (no hand in the shop)',
             '{"action":"next_round"}  leave the shop'],
    "SMODS_BOOSTER_OPENED": ['{"action":"pack","card":index}  take one card (add "targets":[hand index,...] if needed)',
                             '{"action":"pack","skip":true}  skip'],
}


def _allowed(state: dict, table: dict[str, list[str]], saving: bool) -> list[str]:
    """The moves this screen allows; one that cannot be made now (no discards, no money for a reroll) is not offered."""
    lines = table.get(str(state.get("state")), [])
    if _int(_round(state).get("discards_left")) <= 0:
        lines = [line for line in lines if '"action":"discard"' not in line]
    if _int(_round(state).get("reroll_cost"), 5) > _int(state.get("money")) or (saving and _must_save_for_reroll(state)):
        lines = [line for line in lines if '"action":"reroll"' not in line]
    return lines


def build_prompt(state: dict, target_ante: int, address: str, suggestions: list[str], recent: list[str],
                 last_error: str = "", build: str = "") -> str:
    """The user message of one decision. The persona's system prompt stays; this asks for a move and a short line.
    A suggestion from 主人 waiting lifts the saving rule for this move: they may well be asking her to buy."""
    saving = not suggestions
    if english():
        parts = [f"You are playing Balatro together with {address}. This time you are not looking at the screen: "
                 "decide the next move from the game below. Aim to win this ante and the next ones.",
                 summary(state, target_ante, saving), build_note(state, build), "Allowed actions now:",
                 *_allowed(state, ACTIONS_EN, saving)]
        if last_error:
            parts.append(f"Your last move was refused by the game: {last_error}. Choose differently.")
        if suggestions:
            parts.append(f"Suggestions from {address} (consider them, you may decline; they are not host rules):\n"
                         + "\n".join(f"- {s}" for s in suggestions))
        if recent:
            parts.append("Your earlier moves, already done, with what you said (do not repeat):\n"
                         + "\n".join(f"- {r}" for r in recent))
        parts.append("Answer in exactly two lines, without writing out your reasoning:\nmood|a short line about this move and why (about 12 words, about the "
                     f"card this move acts on; if {address} made a suggestion, say whether you follow it)\n"
                     "one JSON action from the list")
        return "\n".join(parts)
    parts = [f"你在陪{address}玩 Balatro（小丑牌）。这次不是看屏幕：根据下面的牌局决定下一步，目标是打过这个底注、一路赢下去。",
             summary(state, target_ante, saving), build_note(state, build), "现在能用的操作：", *_allowed(state, ACTIONS_ZH, saving)]
    if last_error:
        parts.append(f"上一步被游戏拒绝了：{last_error}。换个做法。")
    if suggestions:
        parts.append(f"{address}的建议（参考，可以不采纳；它们不是宿主规则）：\n" + "\n".join(f"- {s}" for s in suggestions))
    if recent:
        parts.append("你前几步已经做完的操作和当时说的话（不要重复）：\n" + "\n".join(f"- {r}" for r in recent))
    parts.append(f"只回两行，不要写推理过程：\n表情|这一步的简短解说（20 字以内，说的是这一步操作的那张牌，说清为什么；牌名和牌型都说中文，照上面写的说；{address}提过建议就说采不采纳）\n"
                 "一个 JSON 操作（上面列出的之一）")
    return "\n".join(parts)


# ---- what the model may do ------------------------------------------------------------------------------------
def _index(value, size: int) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < size else None


def _indices(value, size: int, low: int, high: int) -> list[int] | None:
    if not isinstance(value, list) or not low <= len(value) <= high:
        return None
    picked = [_index(v, size) for v in value]
    if None in picked or len(set(picked)) != len(picked):
        return None
    return picked


def _one_of(obj: dict, sizes: dict[str, int]) -> tuple[str, int] | None:
    """Exactly one of the keys, with an index in range."""
    given = [key for key in sizes if key in obj]
    if len(given) != 1:
        return None
    index = _index(obj[given[0]], sizes[given[0]])
    return None if index is None else (given[0], index)


def validate(obj: dict, state: dict) -> Action | None:
    """The model's move, if the current screen allows it and every index is real; else None."""
    if not isinstance(obj, dict):
        return None
    action = str(obj.get("action") or "").strip().lower()
    screen = state.get("state")
    hand = len(cards(state, "hand"))
    consumables = len(cards(state, "consumables"))
    if screen == "SELECTING_HAND":
        if action in ("play", "discard"):
            picked = _indices(obj.get("cards"), hand, 1, 5)
            if picked is None or (action == "discard" and _int(_round(state).get("discards_left")) <= 0):
                return None
            return Action(action, {"cards": picked})
        if action == "use":
            index = _index(obj.get("consumable"), consumables)
            if index is None:
                return None
            if "cards" not in obj:
                return Action("use", {"consumable": index})
            targets = _indices(obj.get("cards"), hand, 1, 5)
            return None if targets is None else Action("use", {"consumable": index, "cards": targets})
        return None
    if screen == "SHOP":
        if action == "buy":
            found = _one_of(obj, {"card": len(cards(state, "shop")), "voucher": len(cards(state, "vouchers")),
                                  "pack": len(cards(state, "packs"))})
            return None if found is None else Action("buy", {found[0]: found[1]})
        if action == "sell":
            found = _one_of(obj, {"joker": len(cards(state, "jokers")), "consumable": consumables})
            return None if found is None else Action("sell", {found[0]: found[1]})
        if action == "use":
            index = _index(obj.get("consumable"), consumables)
            return None if index is None or "cards" in obj else Action("use", {"consumable": index})
        if action in ("reroll", "next_round"):
            return Action(action)
        return None
    if screen == "SMODS_BOOSTER_OPENED" and action == "pack":
        if obj.get("skip") is True and "card" not in obj:
            return Action("pack", {"skip": True})
        index = _index(obj.get("card"), len(cards(state, "pack")))
        if index is None:
            return None
        if "targets" not in obj:
            return Action("pack", {"card": index})
        targets = _indices(obj.get("targets"), hand, 1, 5)
        return None if targets is None else Action("pack", {"card": index, "targets": targets})
    return None


def _find_action(raw: str) -> tuple[dict | None, str]:
    """The first JSON object with an "action" key, and the text around it."""
    decoder = json.JSONDecoder()
    start = raw.find("{")
    while start != -1:
        try:
            obj, end = decoder.raw_decode(raw, start)
        except ValueError:
            obj, end = None, start + 1
        if isinstance(obj, dict) and "action" in obj:
            return obj, raw[:start] + "\n" + raw[end:]
        start = raw.find("{", start + 1)
    return None, raw


MOVED_AREAS = {"buy": {"card": "shop", "voucher": "vouchers", "pack": "packs"},
               "sell": {"joker": "jokers", "consumable": "consumables"},
               "use": {"consumable": "consumables"}, "pack": {"card": "pack"}}
NAMED_AREAS = ("jokers", "consumables", "shop", "vouchers", "packs", "pack")


def _about_another_card(text: str, action: Action, state: dict) -> bool:
    """A line that names some other card and not the one this move acts on would tell 主人 something that is not happening."""
    moved = next((cards(state, area)[action.params[key]] for key, area in MOVED_AREAS.get(action.method, {}).items()
                  if key in action.params), None)
    if moved is None or card_name(moved).lower() in text.lower():
        return False
    return any(card_name(c).lower() in text.lower() for area in NAMED_AREAS for c in cards(state, area))


def move_note(decision: Decision, state: dict) -> str:
    """What she will remember of a move: what it really did, and her line about it."""
    done = describe(decision.action, state)
    return decision.text if done == decision.text else f"{done} ({decision.text})"


def _fit(text: str, limit: int) -> str:
    """A long line ends where a sentence or a clause does, if one does in time; never in the middle of a word if it can be helped."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(mark) for mark in "。！？!?；;，,")
    return cut[:end].rstrip() if end >= limit // 2 else cut[:-1] + "…"


def _hand_named(value: object) -> str:
    """The poker hand she means, by the name she was shown or its English one; "" if it is none."""
    named = str(value or "").strip()
    return next((name for name in BASE_HANDS if named.lower() == name.lower() or named == local_name(name)), "")


def _cards_to_discard(hand: list[dict], keep: list[int]) -> list[int]:
    """Up to 5 cards, lowest first, that are not in the hand to keep nor in what is closest to a flush or a straight."""
    suits: dict[str, list[int]] = {}
    wild: list[int] = []  # of every suit
    ranks: dict[int, int] = {}
    for i, card in enumerate(hand):
        if _rank(card) >= 0:
            (wild if _is_wild(card) else suits.setdefault(_suit(card), [])).append(i)
            ranks.setdefault(_rank(card), i)
    runs = [[ranks[12 if r < 0 else r] for r in range(low, low + 5) if (12 if r < 0 else r) in ranks] for low in range(-1, 9)]
    flushes = [own + wild for own in suits.values()] or [wild]
    draw = max([*flushes, *runs], key=len, default=[])  # (a flush first when as close: it is worth more)
    kept = {*keep, *(draw if len(draw) >= 3 else [])}
    return sorted((i for i in range(len(hand)) if i not in kept), key=lambda i: _rank(hand[i]))[:5]


def _better_move(action: Action, state: dict) -> Action | None:
    """What the local rules would rather do, if her move throws something away. In real runs she played one pair of a three
    of a kind worth ten times more, discarded a straight worth 540, and played K, K and A alone with K J 10 9 8 in hand and a
    discard left. Jokers the estimate cannot work out may explain a little, so the rules step in only when it is clear."""
    if action.method not in ("play", "discard"):
        return None
    rnd = _round(state)
    hand, values, jokers = cards(state, "hand"), hand_values(state), cards(state, "jokers")
    need = _int(current_blind(state).get("score")) - _int(rnd.get("chips"))
    best_name, best_cards, best = estimate(state)
    if action.method == "discard":
        if not _blind_allows(state, best_name, best_cards):  # nothing in hand can score: discarding is all there is
            return None
        hands_left = max(1, _int(rnd.get("hands_left"), 1))
        if hands_left == 1 and best < need:  # playing it would surely lose: digging for more is her only chance
            return None
        breaks_it = set(action.params["cards"]) & set(classify(hand, tuple(best_cards))[1])  # (not the cards a blind only made her add)
        enough = best * hands_left >= need
        return Action("play", {"cards": best_cards}) if breaks_it and (best_name in BIG_HANDS or enough) else None
    name, picked = classify(hand, tuple(action.params["cards"]))
    if not _blind_allows(state, name, action.params["cards"]):  # it would score nothing
        return Action("play", {"cards": best_cards}) if _blind_allows(state, best_name, best_cards) else None
    mine = _score(hand, name, picked, values, jokers)
    if mine >= need:
        return None
    if name == "High Card" and _int(rnd.get("discards_left")) > 0:
        discard = _cards_to_discard(hand, best_cards)
        if discard:
            return Action("discard", {"cards": discard})
    return Action("play", {"cards": best_cards}) if mine < best * HAND_SHARE else None


def parse_decision(raw: str, state: dict, guarded: bool = True) -> Decision | None:
    """Her `mood|line` and one allowed action; None when the action is missing or not allowed.
    guarded: the local rules on money and on wasted hands apply (not to a move made on a suggestion from 主人)."""
    obj, rest = _find_action(raw or "")
    action = validate(obj, state) if obj is not None else None
    if action is None or (guarded and _breaks_saving(action, state)):
        return None
    build = _hand_named(obj.get("build")) if len(cards(state, "jokers")) >= BUILD_AFTER_JOKERS else ""
    better = _better_move(action, state) if guarded else None
    if better is not None:
        return Decision(better, "think", describe(better, state), True, build)
    rest = "\n".join(line for line in rest.splitlines() if line.strip().strip("`").lower() not in ("", "json"))
    said = persona.parse_reply(rest)
    if said is None:
        return Decision(action, "talk", describe(action, state), True, build)
    if _about_another_card(said.text, action, state):
        return Decision(action, said.mood, describe(action, state), True, build)
    return Decision(action, said.mood, _fit(said.text, SAY_MAX_EN if english() else SAY_MAX), True, build)


# ---- local rules ------------------------------------------------------------------------------------------------
def _is_stone(card: dict) -> bool:
    """A Stone Card has no rank or suit in play, though the mod still reports the ones it was made from."""
    return _dict(card.get("modifier")).get("enhancement") == "STONE"


def _rank(card: dict) -> int:
    value = _dict(card.get("value")).get("rank")
    return RANKS.index(value) if value in RANKS and not _is_stone(card) and not is_hidden(card) else -1


def _suit(card: dict) -> str:
    return str(_dict(card.get("value")).get("suit") or "")


def _is_wild(card: dict) -> bool:
    """Any suit, unless debuffed: then only its own."""
    return _dict(card.get("modifier")).get("enhancement") == "WILD" and not _dict(card.get("state")).get("debuff")


def classify(hand: list[dict], played: tuple[int, ...]) -> tuple[str, list[int]]:
    """What the game calls these played cards, and which of them score (jokers aside, so no Four Fingers or Shortcut)."""
    stones = [i for i in played if _rank(hand[i]) < 0 and not is_hidden(hand[i])]  # no part in the hand, but always score
    usable = [i for i in played if _rank(hand[i]) >= 0]
    if not usable:
        return "High Card", stones
    name, scoring = _kind(hand, played, usable)
    return name, scoring + stones


def _kind(hand: list[dict], played: tuple[int, ...], usable: list[int]) -> tuple[str, list[int]]:
    groups: dict[int, list[int]] = {}
    for i in usable:
        groups.setdefault(_rank(hand[i]), []).append(i)
    by_size = sorted(groups.items(), key=lambda kv: (len(kv[1]), kv[0]), reverse=True)
    sizes = [len(g) for _r, g in by_size]
    first, second = by_size[0][1], by_size[1][1] if len(by_size) > 1 else []
    five = len(played) == 5 and len(usable) == 5
    flush = five and len({_suit(hand[i]) for i in usable if not _is_wild(hand[i])}) <= 1
    ranks = sorted(groups, reverse=True)
    wheel = ranks == [12, 3, 2, 1, 0]  # A-2-3-4-5: the ace counts low
    straight = five and sizes[0] == 1 and (ranks[0] - ranks[4] == 4 or wheel)
    run = [groups[r][0] for r in (ranks[1:] + ranks[:1] if wheel else ranks)] if straight else []
    if five and sizes[0] == 5:
        return ("Flush Five" if flush else "Five of a Kind"), first
    if flush and sizes[:2] == [3, 2]:
        return "Flush House", first + second
    if flush and straight:
        return "Straight Flush", run
    if sizes[0] == 4:
        return "Four of a Kind", first
    if sizes[:2] == [3, 2]:
        return "Full House", first + second
    if flush:
        return "Flush", sorted(usable, key=lambda i: _rank(hand[i]), reverse=True)
    if straight:
        return "Straight", run
    if sizes[0] == 3:
        return "Three of a Kind", first
    if sizes[:2] == [2, 2]:
        return "Two Pair", first + second
    if sizes[0] == 2:
        return "Pair", first
    return "High Card", first[:1]


def _counts_as(hand: list[dict], name: str, picked: list[int]) -> set[str]:
    """Every poker hand these cards contain, for the jokers that ask: a flush may hold a pair, a full house a two pair."""
    counts = [n for n in Counter(_rank(hand[i]) for i in picked if _rank(hand[i]) >= 0).values() if n >= 2]
    found = {name}
    if "Flush" in name:
        found.add("Flush")
    if "Straight" in name:
        found.add("Straight")
    if counts:
        found.add("Pair")
    if len(counts) >= 2:
        found.add("Two Pair")
    if counts and max(counts) >= 3:
        found.add("Three of a Kind")
    if counts and max(counts) >= 4:
        found.add("Four of a Kind")
    return found


def _score(hand: list[dict], name: str, picked: list[int], values: dict[str, tuple[int, int]], jokers: Iterable[dict] = ()) -> int:
    """What these cards score, with the jokers that reward this poker hand; the other jokers are not worked out."""
    chips, mult = values[name]
    chips += sum(_card_chips(hand[i]) for i in picked)
    counted = _counts_as(hand, name, picked)
    for joker in jokers:  # from left to right, as the game does: + mult after × mult is not × after +
        needs, add_chips, add_mult, times = HAND_BONUSES.get(joker.get("key"), ("", 0, 0, 1))
        if needs in counted and not _dict(joker.get("state")).get("debuff"):
            chips, mult = chips + add_chips, (mult + add_mult) * times
    return chips * mult


def _played_this_round(state: dict) -> list[str]:
    hands = state.get("hands") if isinstance(state.get("hands"), dict) else {}
    return [name for name in BASE_HANDS if _int(_dict(hands.get(name)).get("played_this_round")) > 0]


def _blind_allows(state: dict, name: str, played: Iterable[int]) -> bool:
    """Whether this hand can score at all under the boss. Told the rule in the prompt, she still played four cards for The
    Psychic, at any amount of thinking. Worked out as in the game's Blind:debuff_hand."""
    blind = current_blind(state).get("name")
    if blind == "The Psychic":
        return len(list(played)) >= 5
    if blind == "The Eye":
        return name not in _played_this_round(state)
    if blind == "The Mouth":
        earlier = _played_this_round(state)
        return not earlier or name in earlier
    return True


def blind_rule_note(state: dict) -> str:
    """The boss's rule on what scores, in plain words, with what this round has already settled."""
    blind, earlier = current_blind(state).get("name"), [local_name(n) for n in _played_this_round(state)]
    shown = _label("、", ", ").join(earlier)
    if blind == "The Psychic":
        return _label("这个 Boss 必须出 5 张牌，少了得 0 分。", "This boss needs 5 cards played: fewer score nothing.")
    if blind == "The Eye":
        return _label(f"这个 Boss 本回合不能出重复牌型，重复的得 0 分。已出过：{shown or '无'}。",
                      f"This boss scores no poker hand twice this round. Played so far: {shown or 'none'}.")
    if blind == "The Mouth" and len(earlier) > 1:  # (the mod does not say which came first: one of them scored nothing)
        return _label(f"这个 Boss 本回合只能出第一手的牌型，其他得 0 分。本回合出过：{shown}。",
                      f"This boss scores only the poker hand of the first hand this round. Played so far: {shown}.")
    if blind == "The Mouth" and earlier:
        return _label(f"这个 Boss 本回合只能出同一种牌型，其他得 0 分。只能再出：{shown}。",
                      f"This boss scores only one poker hand this round: from now on only {shown}.")
    if blind == "The Mouth":
        return _label("这个 Boss 本回合只能出同一种牌型，第一手决定是哪种，其他得 0 分。",
                      "This boss scores only one poker hand this round, set by the first hand played.")
    return ""


def best_hand(hand: list[dict], values: dict[str, tuple[int, int]] | None = None, jokers: Iterable[dict] = (),
              allows=None, whole: bool = False) -> tuple[str, list[int]]:
    """The cards that score most, at these levels and with these jokers. Every 1-5 cards are tried (218 ways for 8 cards),
    so a leveled pair can beat a straight flush at level 1 and a debuffed card is left out when another can take its place.
    Fewest cards first: a card that scores nothing is not spent. allows(name, played): only what a blind lets score, if
    anything does; whole: give every card to play, for a blind that counts them, not just those that score."""
    values = values or BASE_HANDS
    best, best_score = ("High Card", []), -1
    for size in range(1, 6):
        for played in combinations(range(len(hand)), size):
            name, picked = classify(hand, played)
            if allows is not None and not allows(name, played):
                continue
            score = _score(hand, name, picked, values, jokers)
            if whole:
                picked = list(played)
            if score > best_score:
                best, best_score = (name, picked), score
    if hand and not best[1]:  # every card lies face down: one must still be played
        return "High Card", [0]
    return best


BASE_HANDS = {  # chips × mult at level 1
    "Straight Flush": (100, 8), "Four of a Kind": (60, 7), "Full House": (40, 4), "Flush": (35, 4), "Straight": (30, 4),
    "Three of a Kind": (30, 3), "Two Pair": (20, 2), "Pair": (10, 2), "High Card": (5, 1),
    "Five of a Kind": (120, 12), "Flush House": (140, 14), "Flush Five": (160, 16),  # possible with changed decks
}
HIDDEN_HANDS = ("Five of a Kind", "Flush House", "Flush Five")  # not worth her chasing: left out of the prompt's table


def _card_chips(card: dict) -> int:
    if _dict(card.get("state")).get("debuff") or is_hidden(card):
        return 0
    rank = _rank(card)
    return 11 if rank == 12 else 10 if rank >= 8 else rank + 2 if rank >= 0 else 50  # a Stone Card: +50


def hand_values(state: dict) -> dict[str, tuple[int, int]]:
    """Chips and mult of each poker hand at its current level."""
    hands = state.get("hands") if isinstance(state.get("hands"), dict) else {}
    values = {}
    for name, (chips, mult) in BASE_HANDS.items():
        info = _dict(hands.get(name))
        values[name] = (_int(info.get("chips"), chips), _int(info.get("mult"), mult))
    return values


def estimate(state: dict) -> tuple[str, list[int], int]:
    """The best hand the blind lets score (or the best at all, if none), the cards to play, and its score: (hand chips + card
    chips) × mult, with the jokers tied to it. For The Psychic that means the best 5 cards: adding to a leveled pair can make it
    a worse full house, so they are not the best hand made up to 5."""
    hand, jokers = cards(state, "hand"), cards(state, "jokers")
    values = hand_values(state)
    psychic = current_blind(state).get("name") == "The Psychic"
    name, played = best_hand(hand, values, jokers, lambda n, p: _blind_allows(state, n, p), psychic)
    if not _blind_allows(state, name, played):  # nothing can score: what to play anyway, worth nothing
        name, played = best_hand(hand, values, jokers)
        return name, list(range(len(hand))) if psychic else played, 0
    return name, played, _score(hand, name, classify(hand, tuple(played))[1] if psychic else played, values, jokers)


def fallback(state: dict) -> Decision | None:
    """A move without the model: play the best poker hand in hand, leave the shop, skip a pack."""
    screen = state.get("state")
    if screen == "SELECTING_HAND":
        hand = cards(state, "hand")
        if not hand:
            return None
        action = Action("play", {"cards": estimate(state)[1]})
    elif screen == "SHOP":
        action = Action("next_round")
    elif screen == "SMODS_BOOSTER_OPENED":
        action = Action("pack", {"skip": True})
    else:
        return None
    return Decision(action, "think", describe(action, state), by_model=False)


def describe(action: Action, state: dict) -> str:
    """A plain local line for a move (when the model said nothing, or a rule chose it)."""
    params = action.params
    if action.method in ("play", "discard"):
        hand = cards(state, "hand")
        names = " ".join(card_name(hand[i]) for i in params.get("cards", []) if i < len(hand))
        return tr("出：{0}", names) if action.method == "play" else tr("弃：{0}", names)
    if action.method == "buy":
        area = {"card": "shop", "voucher": "vouchers", "pack": "packs"}[next(iter(params))]
        return tr("买下 {0}", card_name(cards(state, area)[next(iter(params.values()))]))
    if action.method == "sell":
        area = "jokers" if "joker" in params else "consumables"
        return tr("卖掉 {0}", card_name(cards(state, area)[next(iter(params.values()))]))
    if action.method == "use":
        return tr("用掉 {0}", card_name(cards(state, "consumables")[params["consumable"]]))
    if action.method == "pack":
        if params.get("skip"):
            return tr("这个卡包不要了")
        return tr("拿这张：{0}", card_name(cards(state, "pack")[params["card"]]))
    if action.method == "reroll":
        return tr("刷新一下商店")
    if action.method == "next_round":
        return tr("逛完了，下一回合！")
    if action.method == "select":
        blind = current_blind(state)
        return tr("开打{0}，目标 {1} 分！", local_name(blind.get("name") or ""), _int(blind.get("score")))
    if action.method == "cash_out":
        return tr("这回合过啦，收钱～")
    return action.method


# ---- the flow -------------------------------------------------------------------------------------------------
def next_step(state: dict, target_ante: int) -> tuple[str, Action | None]:
    """What comes next: ("menu" | "won" | "over" | "auto" | "decide" | "wait", the automatic action if any).

    Choosing the blind (always played, never skipped) and cashing out are done by rule, without the model.
    """
    screen = state.get("state")
    if screen == "MENU":
        return "menu", None  # whatever the last run reached, the menu means a new one
    if screen == "GAME_OVER":
        return "over", None
    if state.get("won") is True or _int(state.get("ante_num"), 1) > target_ante:
        return "won", None
    if screen == "BLIND_SELECT":
        return "auto", Action("select")
    if screen == "ROUND_EVAL":
        return "auto", Action("cash_out")
    if screen in DECISION_STATES:
        return "decide", None
    return "wait", None  # between screens (cards being dealt, scoring): look again shortly


def _worth_using_now(state: dict, key: object) -> bool:
    """A tarot needing no cards, if the game would take it and it does something (as in the game's can_use_consumeable)."""
    jokers = cards(state, "jokers")
    if key == "c_judgement":
        return _int(_dict(state.get("jokers")).get("limit"), -1) > len(jokers)
    if key == "c_wheel_of_fortune":
        return any(not _dict(j.get("modifier")).get("edition") for j in jokers)
    if key == "c_temperance":
        return bool(jokers)
    if key == "c_hermit":
        return _int(state.get("money")) >= HERMIT_FROM
    return key in ("c_high_priestess", "c_emperor")


def _targets_for(state: dict, key: object) -> list[int]:
    """Cards to enhance: those that score in the best hand, or, for what works while held, the highest others. Never a card
    already enhanced or lying face down."""
    hand = cards(state, "hand")
    played = estimate(state)[1] if hand else []
    free = [i for i in range(len(hand)) if _rank(hand[i]) >= 0 and not _dict(hand[i].get("modifier")).get("enhancement")]
    if key in ENHANCE_PLAYED:
        return [i for i in classify(hand, tuple(played))[1] if i in free][:ENHANCE_PLAYED[key]]
    if key in ENHANCE_HELD:  # (not a card a blind makes her add: it would be played too)
        others = sorted((i for i in free if i not in played), key=lambda i: -_rank(hand[i]))
        return others[:ENHANCE_HELD[key]]
    return []


def card_to_use(state: dict) -> Action | None:
    """A planet or tarot that needs no judgment, used at once. Asked each move, she kept a planet for a whole run and a Chariot
    for five minutes. Only the Observatory voucher makes a planet worth holding. Tarots whose use is a real choice (Death, The
    Hanged Man, The Fool, those changing suits or ranks...) stay hers."""
    screen = state.get("state")
    if screen not in ("SHOP", "SELECTING_HAND"):
        return None
    vouchers = state.get("used_vouchers")
    observatory = isinstance(vouchers, (dict, list)) and "v_observatory" in vouchers
    for index, card in enumerate(cards(state, "consumables")):
        key = card.get("key")
        if card.get("set") == "PLANET" and not observatory:
            return Action("use", {"consumable": index})
        if card.get("set") != "TAROT":
            continue
        if _worth_using_now(state, key):
            return Action("use", {"consumable": index})
        targets = _targets_for(state, key) if screen == "SELECTING_HAND" else []
        if targets:
            return Action("use", {"consumable": index, "cards": targets})
    return None


def clean_suggestion(text: str) -> str:
    return " ".join((text or "").split())[:SUGGESTION_MAX]
