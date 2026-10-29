"""Each girl's own local lines: the same rules as Claude's, the same shape in both languages, and used at once."""
import random
import re
from pathlib import Path

import pytest

from claude_pet import bedtime, characters, claude_client, i18n, persona, persona_en
from claude_pet.config import Config

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from claude_pet import controller as controller_module  # noqa: E402

SPRITES = Path(__file__).resolve().parents[1] / "assets" / "sprites"
WITH_LINES = [girl for girl in characters.CHARACTERS if persona.girl_lines(girl) is not None]
CJK = re.compile(r"[\u3400-\u9fff]")


def entries(value):
    """Every (mood, text) in a table, however it is nested."""
    if isinstance(value, dict):
        return [e for v in value.values() for e in entries(v)]
    if isinstance(value, tuple) and len(value) == 2 and isinstance(value[1], str):
        return [value]
    if isinstance(value, tuple) and len(value) == 3:  # (first hour, last hour, lines)
        return entries(value[2])
    if isinstance(value, (list, tuple)):
        return [e for v in value for e in entries(v)]
    return []


RESTING = re.compile(r"歇|break", re.I)  # her words on the day never tell 主人 to rest (bedtime's rule)


def plain(value):
    """Every plain text line (no mood) in a table: the summary words."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [t for v in value.values() for t in plain(v)]
    if isinstance(value, list):
        return [t for v in value for t in plain(v)]
    return []


def shape(value):
    if isinstance(value, str):  # a plain line (a summary word): any text
        return "text"
    if isinstance(value, dict):
        return {k: shape(v) for k, v in value.items()}
    if isinstance(value, tuple) and len(value) == 2 and isinstance(value[1], str):
        return value[0]
    if isinstance(value, (list, tuple)):
        return [shape(v) for v in value]
    return value


def test_the_new_girls_have_their_own_lines():
    assert set(WITH_LINES) == set(characters.CHARACTERS) - {"claude"}  # Claude's are the shared tables


@pytest.mark.parametrize("girl", WITH_LINES)
def test_every_table_is_hers_and_mirrored_in_english(girl):
    module = persona.girl_lines(girl)
    assert set(module.ZH) == set(module.EN) and set(module.ZH) <= set(persona.PER_GIRL)
    assert set(module.ZH) == set(persona.PER_GIRL)  # a girl with lines has all of them
    for name in module.ZH:
        if name == "FESTIVAL_LINES":  # each language greets its own festivals, as Claude does
            assert set(module.ZH[name]) == set(persona.FESTIVAL_LINES)
            assert set(module.EN[name]) == set(persona_en.FESTIVAL_LINES)
        else:
            assert shape(module.ZH[name]) == shape(module.EN[name]), name
        for mood, text in entries(module.ZH[name]) + entries(module.EN[name]):
            assert mood in persona.MOODS and text.strip(), (name, text)
        assert not [t for _m, t in entries(module.EN[name]) if CJK.search(t)], name
        assert not [t for t in plain(module.EN[name]) if CJK.search(t)], name


@pytest.mark.parametrize("girl", WITH_LINES)
def test_the_same_kinds_and_hours_as_claude(girl):
    module = persona.girl_lines(girl)
    for table in (module.ZH, module.EN):
        assert set(table["INTERACTION_TALK"]) == set(persona.INTERACTION_TALK)
        assert [h[:2] for h in table["TIME_TALK"]] == [h[:2] for h in persona.TIME_TALK]  # lunch, afternoon...
        assert set(table["GREETINGS"]) == set(persona.GREETINGS)
        assert set(table["WEEKDAY_GREETINGS"]) == set(persona.WEEKDAY_GREETINGS)
        assert set(table["TIMER_TALK"]) == set(persona.TIMER_TALK)
        assert set(table["FALLBACK"]) <= set(persona.FALLBACK)
        for kind, lines in table["INTERACTION_TALK"].items():
            assert len(lines) >= (3 if kind in ("max", "min") else 5), kind
            assert len({t for _m, t in lines}) == len(lines), kind
        assert len(table["SELF_TALK"]) >= 24 and len({m for m, _t in table["SELF_TALK"]}) >= 6
        assert {m for m, _t in table["SLEEP_TALK"] + table["SLEEP_LINES"]} == {"sleep"}


@pytest.mark.parametrize("girl", WITH_LINES)
def test_only_the_night_lines_talk_of_sleep(girl):
    module = persona.girl_lines(girl)
    for table in (module.ZH, module.EN):
        assert all(bedtime.mentions(t) for _m, t in table["NIGHT_TALK"])
        daytime = entries(table["SELF_TALK"]) + entries(table["TIME_TALK"])
        assert [t for _m, t in daytime if bedtime.mentions(t) or re.search(r"困|累|tired|heavy", t, re.I)] == []
        others = (entries(table["INTERACTION_TALK"]) + entries(table["GREETINGS"])
                  + entries(table["WEEKDAY_GREETINGS"]) + entries(table["FALLBACK"]))
        assert [t for _m, t in others if bedtime.mentions(t)] == []


@pytest.mark.parametrize("girl", WITH_LINES)
def test_no_line_claims_to_see_what_the_user_does(girl):
    module = persona.girl_lines(girl)
    for table in (module.ZH, module.EN):
        texts = [t for _m, t in entries(table)]
        assert [t for t in texts if re.search(r"在忙什么|在做什么|屏幕上的|看到你|what you're (up to|doing)|on your screen", t)] == []


@pytest.mark.parametrize("girl", WITH_LINES)
def test_her_lines_are_used_and_shared_ones_stay(girl):
    module = persona.girl_lines(girl)
    persona.set_girl(girl)
    rng = random.Random(1)
    own_pats = {t for _m, t in module.ZH["INTERACTION_TALK"]["pat"]}
    assert persona.interaction_line("pat", rng).text in own_pats
    said = {persona.self_talk_line(15, False, [], random.Random(s)).text for s in range(200)}
    assert said <= {t for _m, t in entries(module.ZH["SELF_TALK"]) + entries(module.ZH["TIME_TALK"])}
    assert persona.fallback("blocked") == persona.Reply(*persona.FALLBACK["blocked"])  # shared system lines
    if "error" in module.ZH["FALLBACK"]:
        assert persona.fallback("error") == persona.Reply(*module.ZH["FALLBACK"]["error"])
    assert persona.timer_line("start", rng, 25).text in {t.format(25) for _m, t in module.ZH["TIMER_TALK"]["start"]}
    i18n.set_language("en")
    assert persona.interaction_line("pat", rng).text in {t for _m, t in module.EN["INTERACTION_TALK"]["pat"]}
    persona.set_girl("claude")
    assert persona.interaction_line("pat", rng).text in {t for _m, t in persona_en.INTERACTION_TALK["pat"]}


@pytest.mark.parametrize("girl", [*WITH_LINES, "claude"])
def test_her_festival_birthday_and_summary_words(girl):
    module = persona.girl_lines(girl)
    tables = ((module.ZH, persona), (module.EN, persona_en)) if module else (
        ({n: getattr(persona, n) for n in persona.PER_GIRL}, persona),
        ({n: getattr(persona_en, n) for n in persona.PER_GIRL}, persona_en))
    for table, shared in tables:
        assert set(table["SUMMARY_TAILS"]) == set(shared.SUMMARY_TAILS)  # every activity Claude has a word for
        for activity, words in table["SUMMARY_TAILS"].items():
            assert len(words) >= 2 and len(set(words)) == len(words), activity
        assert len(table["SUMMARY_FOCUS_TAILS"]) >= 2 and table["SUMMARY_TAIL"].strip()
        assert "{activity}" in table["MEMORY_TALK"] and "{hours:.1f}" in table["MEMORY_TALK"]
        texts = ([t for _m, t in entries(table["FESTIVAL_LINES"]) + entries(table["BIRTHDAY_LINE"])]
                 + plain(table["SUMMARY_TAILS"]) + table["SUMMARY_FOCUS_TAILS"] + [table["SUMMARY_TAIL"],
                                                                                   table["MEMORY_TALK"]])
        assert [t for t in texts if bedtime.mentions(t) or RESTING.search(t)] == []
        festival_texts = [t for _m, t in entries(table["FESTIVAL_LINES"])]
        assert len(set(festival_texts)) == len(festival_texts)


@pytest.mark.parametrize("girl", [*WITH_LINES, "claude"])
@pytest.mark.parametrize("language", ["zh", "en"])
def test_she_says_her_own_wishes_and_summary_words(girl, language):
    module = persona.girl_lines(girl)
    persona.set_girl(girl)
    i18n.set_language(language)
    try:
        own = (module.ZH if language == "zh" else module.EN) if module else None
        shared = persona if language == "zh" else persona_en
        table = own or {name: getattr(shared, name) for name in persona.PER_GIRL}
        persona.set_girl("claude")
        claudes = persona.summary_line({"写代码": 7200.0}, random.Random(1)).text
        tail = next(w for w in (persona if language == "zh" else persona_en).SUMMARY_TAILS["写代码"] if claudes.endswith(w))
        facts = claudes[:-len(tail)]
        assert persona.duration_text(7200.0) in facts
        persona.set_girl(girl)
        rng = random.Random(1)
        assert persona.greeting_line(9, "春节", False, rng) == persona.Reply(*table["FESTIVAL_LINES"]["春节"])
        assert persona.greeting_line(9, None, True, rng) == persona.Reply(*table["BIRTHDAY_LINE"])
        summary = persona.summary_line({"写代码": 7200.0}, rng).text
        assert any(summary.endswith(word) for word in table["SUMMARY_TAILS"]["写代码"]), summary
        assert summary.startswith(facts), summary  # the facts worded as for everyone
        focus_only = persona.summary_line({}, rng, (3, 4500.0)).text
        assert any(focus_only.endswith(word) for word in table["SUMMARY_FOCUS_TAILS"]), focus_only
        other = persona.summary_line({"别的事": 7200.0}, rng).text
        assert other.endswith(table["SUMMARY_TAIL"]), other
        name = persona.activity_name("写代码") if language == "en" else "写代码"
        said = persona.memory_talk_line("写代码", 5400.0).text
        assert said == table["MEMORY_TALK"].format(activity=name, hours=1.5) and "1.5" in said
    finally:
        i18n.set_language("zh")
        persona.set_girl("claude")


def test_an_unknown_girl_says_claudes_lines():
    persona.set_girl("nobody")
    assert persona.lines("WAKE_LINES") == persona.WAKE_LINES


# ---- the pet ---------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def pet(app, tmp_path, monkeypatch):
    for name, value in (("idle_seconds", lambda: 0.0), ("is_fullscreen", lambda _i: False),
                        ("notification_busy", lambda: False)):
        monkeypatch.setattr(controller_module.capture, name, value)
    monkeypatch.setattr(claude_client, "find_claude", lambda _configured="": "claude.exe")
    monkeypatch.setattr(controller_module, "save_config", lambda *_a, **_k: None)
    monkeypatch.setattr(controller_module, "app_data_dir", lambda: tmp_path)
    ctrl = controller_module.PetController(app, Config(greeted_on="2099-01-01", character="deepseek"), SPRITES,
                                           tmp_path / "config.json")
    yield ctrl
    if ctrl.settings_window is not None:
        ctrl.settings_window.close()


def test_a_pet_started_as_a_girl_says_her_lines(pet):
    module = persona.girl_lines("deepseek")
    assert persona.lines("WAKE_LINES") == module.ZH["WAKE_LINES"]
    pet.set_character("claude")
    assert persona.lines("WAKE_LINES") == persona.WAKE_LINES
    pet.set_character("deepseek")
    assert persona.lines("WAKE_LINES") == module.ZH["WAKE_LINES"]


def intros(girl, english=False, table="INTRO_LINES"):
    module = persona.girl_lines(girl)
    if module is None:  # Claude's are the shared tables
        return getattr(persona_en if english else persona, table)
    return (module.EN if english else module.ZH)[table]


@pytest.mark.parametrize("table", ["INTRO_LINES", "HELLO_LINES"])
@pytest.mark.parametrize("girl", list(characters.CHARACTERS))
def test_each_girl_introduces_herself_by_name(girl, table):
    character = characters.get(girl)
    others = [name for g, c in characters.CHARACTERS.items() if g != girl for name in (c.name, c.name_en)]
    for english, name in ((False, character.name), (True, character.name_en)):
        lines = intros(girl, english, table)
        assert len(lines) >= 3 and len({t for _m, t in lines}) == len(lines)
        for mood, text in lines:
            assert mood in persona.MOODS and name in text, text  # whoever just arrived says who she is
            assert not [other for other in others if other in text], text
            if table == "HELLO_LINES":  # as she starts, she says she will look now and then
                assert ("window" if english else "窗口") in text, text
    every = [t for g in characters.CHARACTERS for english in (False, True) for _m, t in intros(g, english, table)]
    assert len(set(every)) == len(every)  # nobody borrows another girl's hello


@pytest.mark.parametrize("girl", list(characters.CHARACTERS))
def test_her_hello_does_not_repeat_her_entrance_line(girl):
    """Switched to her, then started: the two should not sound like the same line twice."""
    from difflib import SequenceMatcher

    character = characters.get(girl)
    for english, name, longest in ((False, character.name, 7), (True, character.name_en, 24)):
        hellos = [t.replace(name, "\0") for _m, t in intros(girl, english, "HELLO_LINES")]  # saying her name
        entrances = [t.replace(name, "\1") for _m, t in intros(girl, english)]  # in both is no repeat
        actions = re.compile(r"（[^）]*）|\([^)]*\)")
        assert not {a for t in hellos for a in actions.findall(t)} & {a for t in entrances for a in actions.findall(t)}
        for hello in hellos:
            for entrance in entrances:
                match = SequenceMatcher(None, hello, entrance, autojunk=False).find_longest_match()
                assert match.size < longest, hello[match.a:match.a + match.size]


def test_she_starts_with_her_own_usual_hello(pet):
    pet.set_character("gemini")
    pet.window.clear_bubble()
    pet.config.greeted_on = pet._today().isoformat()  # greeted today already: the usual hello
    pet.start()
    assert pet.window.full_text in {t for _m, t in intros("gemini", table="HELLO_LINES")}


def test_switching_girls_she_says_her_own_hello(pet, monkeypatch):
    for girl in ("gpt", "claude", "qwen"):
        pet.set_character(girl)
        assert pet.window.full_text in {t for _m, t in intros(girl)}, girl
    pet.set_address("老板")  # and a hello that says 主人, so the address is surely tried
    monkeypatch.setattr(persona, "pick", lambda choices: persona.Reply(
        *next((c for c in choices if "主人" in c[1]), choices[0])))
    pet.set_character("glm")
    assert "老板" in pet.window.full_text and "主人" not in pet.window.full_text
    assert pet.window.full_text in {t.replace("主人", "老板") for _m, t in intros("glm")}
    i18n.set_language("en")
    pet.set_character("deepseek")
    assert pet.window.full_text in {t for _m, t in intros("deepseek", english=True)}


ASSUMES = re.compile(r"主人今天也很努力|主人辛苦啦|You're working hard|看起来很悠闲|(?<!要是)坐了(这么久|好一会儿)|一直(坚持到现在|在努力|很认真)|"
                     r"那个(文件夹|图标)|桌面角落里有|你还真是……认真|You look|(?<!if )you've (been|kept|worked)|"
                     r"that (folder|icon)|in the corner of the desktop|You really are\.\.\. so focused", re.IGNORECASE)


@pytest.mark.parametrize("girl", WITH_LINES)
def test_no_line_assumes_what_the_user_is_like_or_has_on_screen(girl):
    """Her local lines are picked at random: she has not looked, so she never says how the user is doing or what
    is on the desktop; such things are put as an "if" or are about her own little world."""
    module = persona.girl_lines(girl)
    for table in (module.ZH, module.EN):
        assert [t for _m, t in entries(table) if ASSUMES.search(t)] == []


@pytest.mark.parametrize("line", ["主人辛苦啦，我在这儿陪着你", "You're working hard. I'm right here.", "周日的主人看起来很悠闲",
                                  "You look nice and relaxed this Sunday.", "那个文件夹叫「新建文件夹」",
                                  "You've worked hard today too."])
def test_the_check_rejects_what_it_should(line):
    assert ASSUMES.search(line)


@pytest.mark.parametrize("line", ["要是坐了好一会儿，就起来活动一下", "If you've been sitting a while, get up.",
                                  "我在这儿陪着主人，不吵不闹～", "I'm right here with you, nice and quiet~"])
def test_the_check_lets_an_if_or_plain_company_through(line):
    assert not ASSUMES.search(line)


def test_claudes_own_lines_follow_the_same_rule():
    """Claude's lines are the shared tables: the same check as every other girl's."""
    for module in (persona, persona_en):
        texts = [t for name in persona.PER_GIRL for _m, t in entries(getattr(module, name))]
        assert [t for t in texts if ASSUMES.search(t)] == []
        assert [t for t in texts if re.search(r"屏幕上的|on your screen|看见了！|I saw one|pop-up|弹窗", t)] == []


STATED = re.compile(r"刚才那段代码|in that code|今天不用赶进度|(?<!are )no deadlines today|都整理好了|"
                    r"sorted\. I'm pleased|越来越熟练|getting better and better|看在眼里|I saw it all|提交记录一定|commit history must|写了这么多|So much code", re.IGNORECASE)


def test_stated_outcomes_and_plans_are_never_assumed():
    """A summary knows only how long went on each kind of thing, and a weekday greeting only the day: neither says
    what the user achieved, saw or planned. Checked over every girl's tables, the summary tails included."""
    for module in (persona, persona_en):
        texts = [t for name in persona.PER_GIRL for _m, t in entries(getattr(module, name))]
        texts += [t for tails in module.SUMMARY_TAILS.values() for t in tails]
        assert [t for t in texts if STATED.search(t) or ASSUMES.search(t)] == []
    for girl in WITH_LINES:
        lines = persona.girl_lines(girl)
        for table in (lines.ZH, lines.EN):
            assert [t for _m, t in entries(table) if STATED.search(t)] == []


@pytest.mark.parametrize("line", ["（小声）刚才那段代码的缩进……", "The indentation in that code...", "今天不用赶进度",
                                  "No deadlines today.", "这么多文档都整理好了", "I saw it all~"])
def test_the_outcome_check_rejects_what_it_should(line):
    assert STATED.search(line)


def common(girl, english=False):
    module = persona.girl_lines(girl)
    if module is None:  # Claude's are the shared tables
        return (persona_en if english else persona).COMMON_REPLIES
    return (module.EN if english else module.ZH)["COMMON_REPLIES"]


@pytest.mark.parametrize("girl", list(characters.CHARACTERS))
def test_her_own_words_for_the_common_actions(girl):
    for english in (False, True):
        table = common(girl, english)
        assert set(table) == set(persona.COMMON_REPLIES)
        for kind, lines in table.items():
            for mood, text in lines:
                assert mood in persona.MOODS and not bedtime.mentions(text), (kind, text)
        assert all("Ctrl+Alt+P" in t for _m, t in table["eyes_closed"])  # how to let her look again
        if girl != "claude":  # turning pages is Claude's (she holds a book)
            assert not [t for _m, t in entries(table) if re.search(r"翻到新的一页|turns to a fresh page", t)]
    every = [t for g in characters.CHARACTERS for english in (False, True) for _m, t in entries(common(g, english))]
    assert len(set(every)) == len(every)  # nobody borrows another girl's words


@pytest.mark.parametrize("girl", list(characters.CHARACTERS))
def test_she_answers_the_menu_in_her_own_words(pet, girl):
    pet.set_character(girl)
    table = common(girl)

    def said(kind):
        return pet.window.full_text in {t for _m, t in table[kind]}

    pet.toggle_pause()
    assert pet.config.paused and said("paused")
    pet.poke()  # asked to look while her eyes are closed
    assert said("eyes_closed")
    pet.toggle_pause()
    assert not pet.config.paused and said("resumed")
    pet.busy = True
    pet.poke()
    assert said("busy")
    pet.busy = False
    pet.clear_companion_memory()
    assert said("memory_cleared")
