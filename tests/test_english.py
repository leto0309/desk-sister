"""English: every interface text has a translation, her English lines mirror the Chinese, and switching works."""
import ast
import random
import re
import string
from pathlib import Path

import pytest

from claude_pet import characters, persona_presets_en, bedtime, claude_client, i18n, i18n_en, memory, persona, persona_en
from claude_pet.config import Config

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from claude_pet import controller as controller_module  # noqa: E402

SRC = Path(__file__).resolve().parents[1] / "src" / "claude_pet"
SPRITES = Path(__file__).resolve().parents[1] / "assets" / "sprites"
CJK = re.compile(r"[　-〿一-鿿＀-￯]")  # ideographs and full-width punctuation


def marked_texts():
    texts = set()
    for path in SRC.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            name = node.func.id if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) else                 node.func.attr if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) else ""
            if name in ("tr", "N_", "Msg"):
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    texts.add(node.args[0].value)
    return texts


def fields(text):
    return sorted((name, spec) for _lit, name, spec, _conv in string.Formatter().parse(text) if name is not None)


def test_every_marked_text_has_english_with_the_same_fields():
    texts = marked_texts() | set(memory.ACTIVITIES)
    missing = sorted(t for t in texts if t not in i18n_en.TEXT)
    assert missing == []
    assert sorted(t for t in i18n_en.TEXT if t not in texts) == []  # nothing stale
    assert [t for t in texts if fields(t) != fields(i18n_en.TEXT[t])] == []


def test_the_english_has_no_chinese():
    assert [v for k, v in i18n_en.TEXT.items() if CJK.search(v) and k != "语言 / Language"] == []
    for name in ("FALLBACK", "INTERACTION_TALK", "GREETINGS", "FESTIVAL_LINES", "SUMMARY_TAILS", "WEEKDAY_GREETINGS"):
        table = getattr(persona_en, name)
        for value in table.values():
            assert not CJK.search(repr(value)), (name, value)
    for name in ("WAKE_LINES", "SLEEP_LINES", "INTRO_LINES", "HELLO_LINES", "SELF_TALK", "NIGHT_TALK", "SLEEP_TALK", "TIME_TALK",
                 "BIRTHDAY_LINE", "MEMORY_TALK", "SUMMARY"):
        assert not CJK.search(repr(getattr(persona_en, name))), name
    for girl, persona_text in persona_presets_en.EN.items():
        assert not CJK.search(persona_text), girl
        assert not CJK.search(characters.system_prompt(girl, True)), girl


def shape(value):
    if isinstance(value, dict):
        return {k: shape(v) for k, v in value.items()}
    if isinstance(value, list):
        return [shape(v) for v in value]
    if isinstance(value, tuple) and len(value) == 2 and value[0] in persona.MOODS:
        return value[0]  # (mood, line): the mood must match
    if isinstance(value, tuple):
        return tuple(shape(v) for v in value)
    return type(value).__name__


@pytest.mark.parametrize("name", ["FALLBACK", "WAKE_LINES", "SLEEP_LINES", "INTRO_LINES", "HELLO_LINES", "SELF_TALK", "TIME_TALK", "NIGHT_TALK",
                                  "INTERACTION_TALK", "GREETINGS", "SLEEP_TALK", "BIRTHDAY_LINE", "SUMMARY_TAILS",
                                  "WEEKDAY_GREETINGS", "TIMER_TALK"])
def test_english_lines_mirror_the_chinese(name):
    assert shape(getattr(persona_en, name)) == shape(getattr(persona, name))


def test_english_festivals_leave_out_only_the_chinese_holidays():
    assert set(persona.FESTIVAL_LINES) - set(persona_en.FESTIVAL_LINES) == {"劳动节", "国庆节"}
    assert set(persona_en.FESTIVAL_LINES) <= set(persona.FESTIVAL_LINES)


def test_language_choice(monkeypatch):
    monkeypatch.setattr(i18n, "system_language", lambda: "en")
    assert i18n.set_language("") == "en" and i18n.english()
    assert i18n.set_language("zh") == "zh" and not i18n.english()
    assert i18n.set_language("fr") == "en"  # anything else follows the system
    monkeypatch.setattr(i18n, "system_language", lambda: "zh")
    assert i18n.set_language("") == "zh"
    assert i18n.set_language("en") == "en"


@pytest.mark.parametrize(("lang_id", "lang"), [(0x0804, "zh"), (0x0404, "zh"), (0x0C04, "zh"), (0x0409, "en"),
                                                (0x0411, "en"), (0x0809, "en")])
def test_system_language(monkeypatch, lang_id, lang):
    class Kernel:
        @staticmethod
        def GetUserDefaultUILanguage():
            return lang_id

    class WinDLL:
        kernel32 = Kernel

    monkeypatch.setattr(i18n.sys, "platform", "win32")
    monkeypatch.setattr(i18n.ctypes, "windll", WinDLL, raising=False)
    assert getattr(i18n.system_language, "__wrapped__", i18n.system_language)() == lang


def test_config_language():
    assert Config(language="en").normalized().language == "en"
    assert Config(language="fr").normalized().language == ""
    assert Config(language=None).normalized().language == ""
    assert Config().language == ""


def test_tr_fills_fields_in_both_languages():
    assert i18n.tr("有新版本 v{0}", "1.2") == "有新版本 v1.2"
    assert i18n.tr("已更新到 {version}。", version="1.2") == "已更新到 1.2。"
    i18n.set_language("en")
    assert i18n.tr("有新版本 v{0}", "1.2") == "New version v1.2"
    assert i18n.tr("已更新到 {version}。", version="1.2") == "Updated to 1.2."
    assert i18n.tr("not a known text") == "not a known text"


def test_her_lines_and_prompts_in_english():
    i18n.set_language("en")
    rng = random.Random(1)
    assert persona.system_prompt().startswith(persona_presets_en.EN["claude"]) and "in English" in persona.system_prompt()
    assert persona.fallback("error").text.startswith("Uh...")
    assert persona.interaction_line("pat", rng).text in {t for _m, t in persona_en.INTERACTION_TALK["pat"]}
    assert persona.greeting_line(8, None, False, rng).text in {t for _m, t in persona_en.GREETINGS["morning"]}
    assert persona.greeting_line(8, "春节", False, rng) == persona.Reply(*persona_en.FESTIVAL_LINES["春节"])
    assert persona.greeting_line(8, "国庆节", False, rng).text in {t for _m, t in persona_en.GREETINGS["morning"]}
    assert persona.greeting_line(8, "春节", True, rng) == persona.Reply(*persona_en.BIRTHDAY_LINE)
    text = persona.summary_line({"写代码": 11520, "看视频": 2400}, rng).text
    head = "Today's summary: coding about 3.2 hours, watching videos about 40 minutes. "
    assert text.startswith(head) and text[len(head):] in persona_en.SUMMARY_TAILS["写代码"]
    assert persona.memory_talk_line("写代码", 7200).text.startswith("You've spent 2.0 hours on \"coding\"")
    assert persona.self_talk_line(14, False, [], rng).text in {t for _m, t in persona_en.SELF_TALK}
    assert persona.lines("WAKE_LINES") == persona_en.WAKE_LINES
    text = persona.build_user_text("Notes", "notepad.exe", "21:30", ["old line"], "hi", memory="Today: coding.",
                                   bedtime="no")
    assert text.splitlines()[0] == "The time is now 21:30." and bedtime.MAY_NOT_EN in text
    assert "\"Notes\" (process notepad.exe)" in text and "- old line" in text and "\"hi\"" in text
    assert text.endswith("in English.") and not CJK.search(text)


def test_english_replies_may_be_longer():
    long = "x" * 150
    assert persona.parse_reply(f"talk|{long}").text.endswith("…")  # Chinese: 80 characters
    i18n.set_language("en")
    assert persona.parse_reply(f"talk|{long}").text == long
    assert len(persona.parse_reply("talk|" + "y" * 200).text) == persona.MAX_LINE_EN


def test_memory_in_english():
    i18n.set_language("en")
    mem = memory.CompanionMemory(None, now=lambda: 1_800_000_000.0)
    mem.record_look("code.exe", "写代码")
    mem.add_time("写代码", 5400)
    context = mem.context("看视频")
    assert "coding (code.exe); now: watching videos." in context and "Today: coding about 1.5 hours." in context
    assert memory.duration_text(600) == "10 minutes"


@pytest.mark.parametrize(("text", "mentioned"), [
    ("Time to sleep~", True), ("You should get some rest.", True), ("Go to bed soon!", True),
    ("Staying up late again?", True), ("Good night!", True), ("Goodnight~", True), ("She fell asleep.", True),
    ("Restraint, restraint.", False), ("That's the best restaurant.", False), ("Arrested development.", False),
    ("Your Bedrock integration works.", False), ("Sleepwalking through a refactor?", False),
    ("It's bedtime.", True), ("Still sleeping on that bug?", True), ("You look sleepy.", True), ("Off to bed!", True),
    ("The rest of the code is fine.", True),  # a word that can mean rest: counted, to be safe
])
def test_bedtime_mentions_in_english(text, mentioned):
    assert bedtime.mentions(text) is mentioned


def test_english_night_lines_are_bedtime_lines_and_held_back_when_not_due():
    assert all(bedtime.mentions(text) for _mood, text in persona_en.NIGHT_TALK)
    i18n.set_language("en")
    for seed in range(40):
        line = persona.self_talk_line(23, False, [], random.Random(seed), bedtime="no")
        assert not bedtime.mentions(line.text)


# ---- switching in the running pet --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def pet(app, tmp_path, monkeypatch):
    for name, value in (("idle_seconds", lambda: 0.0), ("is_fullscreen", lambda _i: False),
                        ("notification_busy", lambda: False)):
        monkeypatch.setattr(controller_module.capture, name, value)
    monkeypatch.setattr(claude_client, "find_claude", lambda _configured="": "claude.exe")
    saved = []
    monkeypatch.setattr(controller_module, "save_config", lambda config, *_a, **_k: saved.append(config.language))
    monkeypatch.setattr(controller_module, "app_data_dir", lambda: tmp_path)
    ctrl = controller_module.PetController(app, Config(greeted_on="2099-01-01"), SPRITES, tmp_path / "config.json")
    yield ctrl, saved
    if ctrl.settings_window is not None:
        ctrl.settings_window.close()


def menu_texts(ctrl):
    return [action.text() for action in ctrl.tray.contextMenu().actions() if action.text()]


def test_switching_language_from_the_settings(pet):
    ctrl, saved = pet
    assert "退出" in menu_texts(ctrl)
    ctrl.open_settings()
    window = ctrl.settings_window
    assert window.windowTitle() == "Desk Sister · 设置" and window.language_combo.currentData() == ""
    window.language_combo.setCurrentIndex(window.language_combo.findData("en"))
    assert ctrl.config.language == "en" and saved[-1] == "en" and i18n.english()
    assert "Quit" in menu_texts(ctrl) and "Settings…" in menu_texts(ctrl)
    new = ctrl.settings_window
    assert new is not window and new.isVisible() and new.windowTitle() == "Desk Sister · Settings"
    assert [new.nav.item(i).text() for i in range(new.nav.count())] == [
        "General", "Character", "How she thinks", "Watching", "Companion", "Appearance", "About"]
    assert new.language_combo.currentData() == "en"
    ctrl.poke = lambda: None
    ctrl.toggle_pause()
    assert ctrl.window.full_text.startswith("All right, I'll close my eyes")
    new.language_combo.setCurrentIndex(new.language_combo.findData("zh"))
    assert "退出" in menu_texts(ctrl) and ctrl.settings_window.windowTitle() == "Desk Sister · 设置"


def test_an_unknown_language_is_refused(pet):
    ctrl, saved = pet
    ctrl.set_language("fr")
    assert ctrl.config.language == "" and saved == []


def test_english_types_faster_and_stays_as_long_as_the_same_line_in_chinese(app):
    from claude_pet import pet_window

    assert pet_window.reading_length("主人好～") == 4 and pet_window.reading_length("Hi you") == 3
    window = pet_window.PetWindow(SPRITES, 220)
    window.say("talk", "主人今天也辛苦啦")
    assert window._typer.interval() == pet_window.TYPE_MS
    assert window._hide_bubble.interval() == pet_window.HOLD_MS + 8 * pet_window.HOLD_PER_CHAR_MS
    window.say("talk", "You're working hard today too.")
    assert window._typer.interval() == round(pet_window.TYPE_MS / 2)
    assert window._hide_bubble.interval() == round(pet_window.HOLD_MS + 15 * pet_window.HOLD_PER_CHAR_MS)
    window.say("talk", "x", hold_ms=1234)
    assert window._hide_bubble.interval() == 1234
    window.close()



def test_a_new_pet_speaks_the_configured_or_system_language(app, tmp_path, monkeypatch):
    monkeypatch.setattr(claude_client, "find_claude", lambda _configured="": "claude.exe")
    monkeypatch.setattr(controller_module, "app_data_dir", lambda: tmp_path)
    for choice, system, expected in (("en", "zh", "en"), ("zh", "en", "zh"), ("", "en", "en"), ("", "zh", "zh")):
        monkeypatch.setattr(i18n, "system_language", lambda system=system: system)
        ctrl = controller_module.PetController(app, Config(language=choice), SPRITES, tmp_path / "config.json")
        assert i18n.current() == expected, (choice, system)
        assert ("Quit" if expected == "en" else "退出") in menu_texts(ctrl)


def test_switching_drops_a_reply_in_the_old_language(pet):
    ctrl, _saved = pet

    class Call:
        cancelled = False

        def cancel(self):
            self.cancelled = True

    call = Call()
    ctrl.current_call, ctrl.busy, generation = call, True, ctrl.generation
    ctrl.deferred = persona.Reply("talk", "攒着的一句")
    ctrl.set_language("en")
    assert call.cancelled and ctrl.generation == generation + 1 and not ctrl.busy and ctrl.deferred is None
    ctrl.current_call = call2 = Call()
    ctrl.set_language("en")  # no change: nothing cancelled
    assert not call2.cancelled


def test_update_texts_follow_a_switch(pet):
    ctrl, _saved = pet
    ctrl._on_update_found("99.0", False)
    ctrl.download_text = i18n.Msg("已取消下载。")
    assert ctrl.update_status == "有新版本 v99.0" and ctrl.download_text == "已取消下载。"
    ctrl.open_settings()
    ctrl.set_language("en")
    assert ctrl.update_status == "New version v99.0" and ctrl.download_text == "Download cancelled."
    label = ctrl.settings_window.update_label.text()
    assert "New version v99.0" in label and "Download cancelled." in label and not CJK.search(label)


def test_about_page_texts_are_never_stored_translated():
    """update_status and download_text must hold an i18n.Msg (or ""), never a tr() result fixed in one language."""
    source = (SRC / "controller.py").read_text(encoding="utf-8")
    stored = [line.strip() for line in source.splitlines()
              if re.search(r"(update_status|download_text)\b.*=", line) and "tr(" in line]
    assert stored == []


def test_preparing_a_download_follows_a_switch(pet, monkeypatch):
    ctrl, _saved = pet
    jobs = []
    ctrl._spawn = jobs.append
    ctrl._exe_path = lambda: SRC / "desk-sister.exe"
    ctrl.update_available = "99.0"
    ctrl.update_action()
    assert ctrl.download_state == "downloading" and ctrl.download_text == "正在准备下载…"
    ctrl.set_language("en")
    assert ctrl.download_text == "Preparing the download…"



def test_new_english_greetings_and_tails_never_mention_sleep():
    texts = [t for part in persona_en.GREETINGS.values() for _m, t in part]
    texts += [t for part in persona_en.WEEKDAY_GREETINGS.values() for _m, t in part]
    texts += [t for tails in persona_en.SUMMARY_TAILS.values() for t in tails]
    assert [t for t in texts if bedtime.mentions(t)] == []


@pytest.mark.parametrize("lines_of", [persona, persona_en], ids=["zh", "en"])
def test_plenty_of_different_self_talk(lines_of):
    texts = [t for _m, t in lines_of.SELF_TALK] + [t for _f, _l, part in lines_of.TIME_TALK for _m, t in part]
    assert len(lines_of.SELF_TALK) >= 40 and len(texts) == len(set(texts))
    assert len({m for m, _t in lines_of.SELF_TALK}) >= 6  # many moods, not one face all day
    assert any(first <= 15 <= last for first, last, _part in lines_of.TIME_TALK)  # the afternoon has its own



OLD_REST_LINES = {"如果累了，可以闭上眼睛休息二十秒，我帮你看着屏幕。",
                  "If you're tired, close your eyes and rest for twenty seconds. I'll watch the screen."}


@pytest.mark.parametrize("lines_of", [persona, persona_en], ids=["zh", "en"])
def test_daytime_self_talk_says_nothing_about_sleep_or_tiredness(lines_of):
    texts = [t for _m, t in lines_of.SELF_TALK] + [t for _f, _l, part in lines_of.TIME_TALK for _m, t in part]
    assert [t for t in texts if t not in OLD_REST_LINES
            and (bedtime.mentions(t) or re.search(r"困|累|tired|heavy", t, re.IGNORECASE))] == []


@pytest.mark.parametrize("lang", ["zh", "en"])
def test_afternoon_lines_only_in_the_afternoon(lang):
    i18n.set_language(lang)
    table = persona_en if lang == "en" else persona
    afternoon = {t for first, last, part in table.TIME_TALK if (first, last) == (14, 16) for _m, t in part}
    for hour, expected in ((13, False), (14, True), (16, True), (17, False)):
        said = {persona.self_talk_line(hour, False, [], random.Random(seed)).text for seed in range(400)}
        assert bool(said & afternoon) is expected, hour



@pytest.mark.parametrize("lines_of", [persona, persona_en], ids=["zh", "en"])
def test_plenty_of_different_reactions(lines_of):
    for kind, lines in lines_of.INTERACTION_TALK.items():
        assert len(lines) >= (3 if kind in ("max", "min") else 5), kind
        texts = [t for _m, t in lines]
        assert len(texts) == len(set(texts)), kind
        assert not [t for t in texts if bedtime.mentions(t)], kind


def test_new_reactions_do_not_claim_to_see_what_the_user_does():
    """Reactions come from local tables: she has not looked at the screen, so no line says what the user is doing."""
    for table in (persona.INTERACTION_TALK, persona_en.INTERACTION_TALK):
        texts = [t for lines in table.values() for _m, t in lines]
        assert [t for t in texts if re.search(r"在忙什么|在做什么|what you're (up to|doing)", t)] == []
