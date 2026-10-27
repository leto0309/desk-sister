"""Six AI girls: each with her own default persona (Chinese and English), colours and art; the persona can be
edited and restored, and what she calls the user is a setting."""
import json
import re
from pathlib import Path

import pytest

from claude_pet import characters, claude_client, i18n, persona, persona_presets, persona_presets_en
from claude_pet.config import Config, load_config

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from claude_pet import controller as controller_module  # noqa: E402
from claude_pet.settings_window import MOTTOS  # noqa: E402

SPRITES = Path(__file__).resolve().parents[1] / "assets" / "sprites"
GIRLS = ("deepseek", "claude", "gpt", "gemini", "qwen", "glm")


# ---- the presets and the prompt ---------------------------------------------------------------------------
def test_six_girls_each_with_both_languages():
    assert tuple(sorted(characters.CHARACTERS)) == tuple(sorted(GIRLS))
    assert set(persona_presets.ZH) == set(persona_presets_en.EN) == set(GIRLS) == set(MOTTOS)
    for girl in GIRLS:
        zh, en = persona_presets.ZH[girl], persona_presets_en.EN[girl]
        assert zh.startswith("【桌宠共同规则】") and en.startswith("[Shared desktop-pet rules]")
        assert "使用说明" not in zh  # the card's own copy-paste note is left out
        assert "称用户为“你”" not in zh and "主人或亲属" not in zh  # how to address the user is the host's
        assert zh.count("【原创语气示例】") == 1 and en.count("[Original tone examples]") == 1


def test_the_prompt_is_her_persona_then_the_fixed_rules():
    for girl in GIRLS:
        for english in (False, True):
            prompt = characters.system_prompt(girl, english)
            persona_text = characters.default_persona(girl, english)
            assert prompt.startswith(persona_text)
            assert ("表情|台词" in prompt) != english and ("mood|line" in prompt) == english
            assert prompt.index("【桌宠宿主规则" if not english else "[Desktop-pet host rules") > len(persona_text) - 1


def test_her_name_and_how_she_calls_the_user():
    zh = characters.system_prompt("qwen", False)
    assert "你的名字是通义千问" in zh and "称呼用户为“主人”" in zh
    assert "称呼用户为“阿明”" in characters.system_prompt("qwen", False, address="阿明")
    en = characters.system_prompt("qwen", True)
    assert "Your name is Qwen" in en and 'simply as "you"' in en
    assert 'Call the user "Ming"' in characters.system_prompt("qwen", True, address="Ming")


def test_an_edited_persona_replaces_only_the_persona():
    prompt = characters.system_prompt("gpt", False, "  你是一条会说话的龙。  ")
    assert prompt.startswith("你是一条会说话的龙。\n\n【桌宠宿主规则") and "表情|台词" in prompt
    assert characters.system_prompt("gpt", False, "   ") == characters.system_prompt("gpt", False)


@pytest.mark.parametrize("raw, clean", [("", "主人"), ("   ", "主人"), (" 阿  明 ", "阿 明"), ("长" * 40, "长" * 12),
                                        (None, "主人"), (3, "主人")])
def test_the_address_is_one_short_line(raw, clean):
    assert characters.clean_address(raw) == clean


def test_an_unknown_girl_is_claude():
    assert characters.get("nobody").id == "claude"
    assert characters.system_prompt("nobody", False) == characters.system_prompt("claude", False)


def test_the_default_wrapper_follows_the_language():
    assert persona.system_prompt("glm").startswith(persona_presets.ZH["glm"])
    i18n.set_language("en")
    assert persona.system_prompt("glm").startswith(persona_presets_en.EN["glm"])


def test_every_theme_is_complete_and_distinct():
    colours = re.compile(r"^#[0-9A-F]{6}$")
    mains = set()
    for girl in characters.CHARACTERS.values():
        for value in vars(girl.theme).values():
            assert colours.match(value), (girl.id, value)
        mains.add(girl.theme.main)
    assert len(mains) == len(GIRLS)


# ---- the config -------------------------------------------------------------------------------------------
def test_config_keeps_only_sensible_choices(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "character": "nobody", "address": "  ", "watch_mode": "allowlist",
        "personas": {"gpt": {"zh": "龙", "en": "  ", "fr": "dragon"}, "nobody": {"zh": "x"}, "glm": "flat",
                     "qwen": {"zh": "长" * 9000}},
    }), encoding="utf-8")
    config = load_config(path)
    assert config.character == "claude" and config.address == "主人" and config.watch_mode == "allowlist"
    assert config.personas == {"gpt": {"zh": "龙"}, "qwen": {"zh": "长" * characters.MAX_PERSONA}}
    assert Config(personas="oops").normalized().personas == {}


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
    ctrl = controller_module.PetController(app, Config(greeted_on="2099-01-01"), SPRITES, tmp_path / "config.json")
    yield ctrl
    if ctrl.settings_window is not None:
        ctrl.settings_window.close()


def test_switching_girls_changes_her_art_colour_and_prompt(pet):
    claude_idle = pet.window.sprites["idle"].toImage()
    pet.set_character("gemini")
    assert pet.config.character == "gemini" and pet.window.character == "gemini"
    assert pet.window.sprites["idle"].toImage() != claude_idle  # her own art, or a named placeholder for now
    assert pet.window.accent == characters.get("gemini").theme.main
    assert pet.window.full_text in {text for _mood, text in persona.girl_lines("gemini").ZH["INTRO_LINES"]}
    assert pet._system_prompt().startswith(persona_presets.ZH["gemini"])
    pet.set_character("nobody")
    assert pet.config.character == "gemini"
    pet.set_character("claude")
    assert pet.window.sprites["idle"].toImage() == claude_idle


def test_switching_drops_a_reply_asked_of_the_other_girl(pet):
    before = pet.generation
    pet.set_character("glm")
    assert pet.generation != before


def test_the_art_folder_of_each_girl(pet):
    assert pet._art_folder("claude") == SPRITES
    assert pet._art_folder("gpt") == SPRITES.parent / "characters" / "gpt"


def test_editing_and_restoring_a_persona_per_language(pet):
    pet.set_character("deepseek")
    assert pet.persona_text() == (persona_presets.ZH["deepseek"], False)
    pet.set_persona("你是一条鲸鱼。")
    assert pet.persona_text() == ("你是一条鲸鱼。", True)
    assert pet._system_prompt().startswith("你是一条鲸鱼。\n\n")
    i18n.set_language("en")
    assert pet.persona_text() == (persona_presets_en.EN["deepseek"], False)  # English kept apart
    i18n.set_language("zh")
    pet.set_character("gpt")
    assert pet.persona_text()[1] is False  # each girl her own
    pet.set_character("deepseek")
    pet.reset_persona()
    assert pet.persona_text() == (persona_presets.ZH["deepseek"], False) and pet.config.personas == {}


def test_saving_the_default_text_keeps_nothing(pet):
    pet.set_persona(persona_presets.ZH["claude"] + "\n\n")
    assert pet.config.personas == {}


def test_what_she_calls_the_user(pet):
    pet.set_address("  阿明 ")
    assert pet.config.address == "阿明" and "称呼用户为“阿明”" in pet._system_prompt()
    pet.window.say("happy", "主人好～")
    assert pet.window.full_text == "阿明好～"
    pet.set_address("")
    assert pet.config.address == "主人"
    pet.window.say("happy", "主人好～")
    assert pet.window.full_text == "主人好～"


# ---- the settings ----------------------------------------------------------------------------------------
def test_the_character_page(pet):
    pet.open_settings()
    window = pet.settings_window
    assert window.character_combo.count() == 6 and window.character_combo.currentData() == "claude"
    assert window.persona_edit.toPlainText() == persona_presets.ZH["claude"]
    assert not window.persona_save.isEnabled() and not window.persona_reset.isEnabled()
    window.character_combo.setCurrentIndex(window.character_combo.findData("qwen"))
    assert pet.config.character == "qwen"
    assert window.persona_edit.toPlainText() == persona_presets.ZH["qwen"]
    assert "通义千问 的人设提示词（中文）" == window.persona_label.text()


def test_editing_saving_and_restoring_from_the_settings(pet):
    pet.open_settings()
    window = pet.settings_window
    window.persona_edit.setPlainText("你是一位安静的读者。")
    assert window.persona_save.isEnabled() and "未保存" in window.persona_state.text()
    window.refresh()  # a refresh while typing keeps the typing
    assert window.persona_edit.toPlainText() == "你是一位安静的读者。"
    window.persona_save.click()
    assert pet.config.personas == {"claude": {"zh": "你是一位安静的读者。"}}
    assert not window.persona_save.isEnabled() and window.persona_reset.isEnabled()
    window.persona_reset.click()
    assert pet.config.personas == {} and window.persona_edit.toPlainText() == persona_presets.ZH["claude"]
    assert not window.persona_reset.isEnabled()


def test_the_address_box(pet):
    pet.open_settings()
    window = pet.settings_window
    window.address_edit.setText("小林")
    window.address_edit.editingFinished.emit()
    assert pet.config.address == "小林"


def test_each_girl_dresses_the_window(pet):
    pet.open_settings()
    window = pet.settings_window
    assert characters.get("claude").theme.main in window.styleSheet()
    pet.set_character("glm")
    window.refresh()
    assert characters.get("glm").theme.main in window.styleSheet()
    assert window.header.theme == characters.get("glm").theme and "狐耳" in window.header.motto
    assert characters.get("glm").theme.deep in window.about_label.text()


def test_the_english_persona_in_the_editor(pet):
    pet.set_language("en")
    window = pet.settings_window or (pet.open_settings() or pet.settings_window)
    assert window.persona_edit.toPlainText() == persona_presets_en.EN["claude"]
    assert window.persona_label.text() == "Claude's persona prompt (English)"


# ---- what a persona can and cannot do --------------------------------------------------------------------
@pytest.mark.parametrize("raw, mood, text", [
    ('{"mood": "happy", "line": "你好"}', "happy", "你好"),
    ('```json\n{"表情": "sad", "台词": "呜"}\n```', "sad", "呜"),
    ('{"text": "只有台词"}', "talk", "只有台词"),
    ('{"mood": "nonsense", "reply": "嗯"}', "talk", "嗯"),
])
def test_a_json_reply_becomes_her_line(raw, mood, text):
    reply = persona.parse_reply(raw)
    assert (reply.mood, reply.text) == (mood, text) and reply.model


@pytest.mark.parametrize("raw", ['{"mood": "happy"}', '{"a": [1, 2]}', "{broken json", "[1, 2, 3]", '{"line": ""}'])
def test_json_without_a_line_is_never_shown(raw):
    assert persona.parse_reply(raw) is None  # the pet says its "lost for words" line instead


def test_a_model_reply_is_shown_as_written(pet):
    pet.set_address("小主人")
    pet._on_reply(controller_module.Outcome(pet.generation, "reply", force=True,
                                             result=claude_client.ClaudeResult(True, "happy|小主人的主人公写得真好")))
    assert pet.window.full_text == "小主人的主人公写得真好"  # not 小小主人, not 小主人公
    pet.window.say("talk", "主人好～")  # one of her own lines
    assert pet.window.full_text == "小主人好～"


def test_a_reminder_keeps_its_own_text(pet, monkeypatch):
    import time as clock

    from claude_pet import timers

    pet.set_address("阿明")
    pet.window.clear_bubble()
    pet.reminders.add(clock.time() - 1, "给主人公回信")
    pet._update_timers()
    assert "给主人公回信" in pet.window.full_text and "阿明公" not in pet.window.full_text
    assert timers.MAX_REMINDERS  # (the store really was used)


def test_a_persona_too_long_is_refused_not_cut(pet):
    limit = characters.MAX_PERSONA
    assert pet.set_persona("长" * limit) and pet.persona_text() == ("长" * limit, True)
    assert pet.set_persona("短" * (limit + 1)) is False and pet.persona_text() == ("长" * limit, True)


def test_the_settings_refuse_a_persona_too_long_and_keep_the_draft(pet):
    pet.open_settings()
    window = pet.settings_window
    draft = "长" * (characters.MAX_PERSONA + 1)
    window.persona_edit.setPlainText(draft)
    assert "太长了" in window.persona_state.text()
    window.persona_save.click()
    assert pet.config.personas == {} and window.persona_edit.toPlainText() == draft  # nothing lost, nothing saved


def test_an_unsaved_draft_waits_while_another_girl_is_shown(pet):
    pet.open_settings()
    window = pet.settings_window
    window.persona_edit.setPlainText("Claude 的草稿")
    window.character_combo.setCurrentIndex(window.character_combo.findData("gpt"))
    assert window.persona_edit.toPlainText() == persona_presets.ZH["gpt"] and not window.persona_save.isEnabled()
    window.character_combo.setCurrentIndex(window.character_combo.findData("claude"))
    assert window.persona_edit.toPlainText() == "Claude 的草稿" and window.persona_save.isEnabled()
    assert pet.config.personas == {}  # still only a draft


def test_an_unsaved_edit_can_be_thrown_away_at_once(pet):
    pet.open_settings()
    window = pet.settings_window
    assert not window.persona_reset.isEnabled()
    window.persona_edit.setPlainText("随手改的")
    assert window.persona_reset.isEnabled()
    window.persona_reset.click()
    assert window.persona_edit.toPlainText() == persona_presets.ZH["claude"] and not window.persona_save.isEnabled()


@pytest.mark.parametrize("raw, text", [
    ('{"mood": "talk", "line": "请看 &quot;设置&quot; 页"}', '请看 "设置" 页'),
    ('{"line": "\\u003cb\\u003e加粗\\u003c/b\\u003e 的话"}', "加粗 的话"),  # tags as JSON escapes
    ('json\n{"line": "第一行\\n第二行"}', "第一行 第二行"),
])
def test_json_is_read_as_written_then_the_line_is_cleaned(raw, text):
    assert persona.parse_reply(raw).text == text


def test_a_line_that_merely_starts_with_json_is_a_line():
    assert persona.parse_reply("talk|json 文件格式很整齐").text == "json 文件格式很整齐"
    assert persona.parse_reply("json 文件格式很整齐").text == "json 文件格式很整齐"


def test_drafts_survive_a_language_switch(pet):
    pet.open_settings()
    window = pet.settings_window
    window.persona_edit.setPlainText("Claude 的中文草稿")
    window.character_combo.setCurrentIndex(window.character_combo.findData("gpt"))
    window.persona_edit.setPlainText("GPT 的中文草稿")
    pet.set_language("en")
    pet.set_language("zh")
    window = pet.settings_window
    assert window.persona_edit.toPlainText() == "GPT 的中文草稿" and window.persona_save.isEnabled()
    window.character_combo.setCurrentIndex(window.character_combo.findData("claude"))
    assert window.persona_edit.toPlainText() == "Claude 的中文草稿"
    assert pet.config.personas == {}


def test_a_wider_girl_gets_a_wider_window_with_her_feet_in_place(app, tmp_path):
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QColor, QPixmap

    from claude_pet.pet_window import MOODS, PetWindow

    wide = tmp_path / "wide"
    wide.mkdir()
    for mood in MOODS:
        image = QPixmap(1000, 250)
        image.fill(QColor("#336699"))
        image.save(str(wide / f"{mood}.png"))
    window = PetWindow(tmp_path / "nothing", 220, "deepseek", "DeepSeek")
    window.move(QPoint(300, 200))
    feet = (window.x() + window.width() / 2, window.y() + window.height())
    window.set_character("gpt", wide, "GPT", "#8C7BC4")
    assert window.width() >= max(p.width() for p in window.sprites.values())
    assert (window.x() + window.width() / 2, window.y() + window.height()) == pytest.approx(feet, abs=1)
    window.close()


# ---- their art -------------------------------------------------------------------------------------------
ART = Path(__file__).resolve().parents[1] / "assets" / "characters"


@pytest.mark.parametrize("girl", ["deepseek", "gpt", "gemini", "qwen", "glm"])
def test_each_girl_carries_her_own_art(app, girl):
    import hashlib

    from claude_pet.pet_window import MOODS, load_sprites
    from claude_pet.sprites import decode_embedded, sprite_module

    module = sprite_module(girl)
    assert module is not None and set(module.SPRITES) == set(MOODS)
    for mood in MOODS:
        digest = hashlib.sha256((ART / girl / f"{mood}.png").read_bytes()).hexdigest()
        assert module.SOURCES[mood] == digest, f"{girl} {mood}: run python devtools/embed_sprites.py --girl {girl}"
        assert decode_embedded(module.SPRITES[mood], module.CHECKSUMS[mood]).height == 512
    embedded = load_sprites(Path("definitely-missing-folder"), 220, girl)  # as in the one-file exe
    from_files = load_sprites(ART / girl, 220, girl)
    assert embedded["idle"].size() == from_files["idle"].size() and embedded["idle"].height() == 220


def test_art_that_is_missing_gets_a_named_placeholder(app):
    from claude_pet.pet_window import load_sprites
    from claude_pet.sprites import sprite_module

    assert sprite_module("nobody") is None
    sprites = load_sprites(Path("definitely-missing-folder"), 220, "nobody", "某某")
    assert not sprites["idle"].isNull()


def test_doubao_is_not_one_of_them(tmp_path):
    assert "doubao" not in characters.CHARACTERS and "doubao" not in persona_presets.ZH
    assert "doubao" not in persona_presets_en.EN and "doubao" not in MOTTOS
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"character": "doubao", "personas": {"doubao": {"zh": "x"}, "gpt": {"zh": "龙"}}}),
                    encoding="utf-8")
    config = load_config(path)  # someone who had chosen her before: back to Claude, her edits dropped
    assert config.character == "claude" and config.personas == {"gpt": {"zh": "龙"}}


def test_the_pet_shows_the_new_art(pet):
    from claude_pet.pet_window import IDLE_PARTS, TALK_EYES

    pet.set_character("gpt")
    sprite = pet.window.sprites["idle"]
    assert sprite.height() == pet.config.sprite_height and sprite.width() != int(pet.config.sprite_height * 0.7)
    assert set(IDLE_PARTS + TALK_EYES) <= set(pet.window.parts)  # she blinks and moves her mouth too
    assert all(part.size() == sprite.size() for part in pet.window.parts.values())


def test_missing_face_parts_are_logged_in_one_line(app, tmp_path, caplog):
    import logging
    import shutil

    from claude_pet.pet_window import load_parts

    with caplog.at_level(logging.INFO, logger="claude_pet"):
        assert load_parts(tmp_path / "nothing", 220, None) == {}  # every girl has parts now: none embedded here
    lines = [r for r in caplog.records if "face part" in r.getMessage()]
    assert len(lines) == 1 and lines[0].levelno == logging.INFO and "nothing" in lines[0].getMessage()
    caplog.clear()
    folder = tmp_path / "some"
    (folder / "parts").mkdir(parents=True)
    for name in ("eyes_half", "eyes_closed"):
        shutil.copy(SPRITES / "parts" / f"{name}.png", folder / "parts" / f"{name}.png")
    with caplog.at_level(logging.INFO, logger="claude_pet"):
        assert set(load_parts(folder, 220, None)) == {"eyes_half", "eyes_closed"}
    lines = [r for r in caplog.records if "face part" in r.getMessage()]
    assert len(lines) == 1 and lines[0].levelno == logging.WARNING and "mouth_open" in lines[0].getMessage()
    caplog.clear()
    from claude_pet.pet_window import IDLE_PARTS, TALK_EYES

    for name in (*IDLE_PARTS, *TALK_EYES, "happy_mouth_half", "happy_mouth_open"):  # what a new girl may have so far
        shutil.copy(SPRITES / "parts" / f"{name}.png", folder / "parts" / f"{name}.png")
    with caplog.at_level(logging.INFO, logger="claude_pet"):
        load_parts(folder, 220, None)
    lines = [r for r in caplog.records if "face part" in r.getMessage()]
    assert len(lines) == 1 and lines[0].levelno == logging.INFO  # expected, so not a warning
    assert "think, panic, angry, sad" in lines[0].getMessage() and "happy" not in lines[0].getMessage()
    caplog.clear()
    (folder / "parts" / "happy_mouth_open.png").unlink()  # half an expression is damage
    with caplog.at_level(logging.INFO, logger="claude_pet"):
        load_parts(folder, 220, None)
    lines = [r for r in caplog.records if "face part" in r.getMessage()]
    assert len(lines) == 1 and lines[0].levelno == logging.WARNING and "happy_mouth_open" in lines[0].getMessage()


def test_a_new_girls_expression_moves_only_with_its_own_parts(pet):
    from claude_pet.pet_window import MOOD_PARTS

    pet.set_character("gpt")
    window = pet.window
    window.walking = 0

    def keys() -> list[int]:  # the overlays over her sprite, by identity
        return [layer.cacheKey() for layer in window._layers()[1:]]

    for mood, names in MOOD_PARTS.items():
        window.mood, window.eyes, window.mouth = mood, "eyes_closed", "mouth_open"
        own = [n for n in ("mouth_open", "eyes_closed") if n in names and f"{mood}_{n}" in window.parts]
        assert keys() == [window.parts[f"{mood}_{n}"].cacheKey() for n in own], mood  # none: she keeps still
    window.mood = "happy"
    assert keys() == [window.parts["happy_mouth_open"].cacheKey()]  # GPT's happy parts are made
    window.mood = "talk"
    assert keys() == [window.parts[n].cacheKey() for n in ("mouth_closed", "mouth_open", "talk_eyes_closed")]
