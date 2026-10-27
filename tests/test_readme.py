"""The two READMEs: linked both ways, the English one in English, its links and setting names real."""
import importlib.util
import re
from pathlib import Path

import pytest

from claude_pet import i18n_en
from claude_pet.characters import CHARACTERS
from claude_pet.persona import MOODS

ROOT = Path(__file__).resolve().parents[1]
ZH, EN = ROOT / "README.md", ROOT / "README.en.md"
SEC_ZH, SEC_EN = ROOT / "docs" / "security.md", ROOT / "docs" / "security.en.md"
CJK = re.compile(r"[一-鿿]+")
NAMES = {"中文", "冬冰"}  # the language switch's own name; a creator's name, given in English too


def test_they_link_to_each_other():
    assert "[English](README.en.md)" in ZH.read_text(encoding="utf-8").splitlines()[2]
    assert "[中文](README.md)" in EN.read_text(encoding="utf-8").splitlines()[2]


def test_the_security_notes_link_to_each_other_and_from_the_english_readme():
    assert "[English](security.en.md)" in SEC_ZH.read_text(encoding="utf-8").splitlines()[2]
    assert "[中文](security.md)" in SEC_EN.read_text(encoding="utf-8").splitlines()[2]
    assert "(docs/security.en.md)" in EN.read_text(encoding="utf-8")


@pytest.mark.parametrize("doc", [EN, SEC_EN], ids=["readme", "security"])
def test_the_english_docs_are_in_english(doc):
    assert set(CJK.findall(doc.read_text(encoding="utf-8"))) <= NAMES


@pytest.mark.parametrize("doc", [ZH, EN, SEC_ZH, SEC_EN], ids=["zh", "en", "security-zh", "security-en"])
def test_relative_links_exist(doc):
    for target in re.findall(r"\]\(([^)#]+)\)", doc.read_text(encoding="utf-8")):
        if not re.match(r"[a-z]+:", target):
            assert (doc.parent / target).exists(), target


def test_every_girl_is_shown_with_previews_in_the_readmes_language():
    zh, en = ZH.read_text(encoding="utf-8"), EN.read_text(encoding="utf-8")
    assert "(docs/images/girls.gif)" in zh and "(docs/images/moods.png)" in zh
    assert "(docs/images/girls-en.gif)" in en
    for girl in CHARACTERS:
        if girl != "claude":
            assert f"(docs/images/moods-{girl}.png)" in zh, girl
        assert f"(docs/images/moods-{girl}-en.png)" in en, girl
    images = re.findall(r"\]\((docs/images/[^)]+)\)", en)
    assert images and [i for i in images if not re.search(r"-en\.(png|gif)$", i)] == []


def _previews():
    spec = importlib.util.spec_from_file_location("make_previews", ROOT / "devtools" / "make_previews.py")
    previews = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(previews)
    return previews


def test_the_lineup_takes_turns_to_talk_and_blinks_one_girl_at_a_time():
    previews = _previews()
    frames = previews.timeline()
    loop = previews.TURN * len(CHARACTERS)
    assert sum(ms for _, ms in frames) == loop
    assert min(ms for _, ms in frames) >= previews.MIN_FRAME and all(ms % 10 == 0 for _, ms in frames)  # GIF units
    turns: list[list] = []  # [girl, milliseconds] for each stretch one girl talks
    for faces, ms in frames:
        talkers = [girl for girl, (mood, _, _) in faces.items() if mood == "talk"]
        assert len(talkers) == 1  # always exactly one girl talks
        if turns and turns[-1][0] == talkers[0]:
            turns[-1][1] += ms
        else:
            turns.append([talkers[0], ms])
        assert len([girl for girl, (_, _, eyes) in faces.items() if eyes]) <= 1  # one blink at a time
    assert turns == [[girl, previews.TURN] for girl in CHARACTERS]  # in turn, each once, unbroken
    for girl in CHARACTERS:  # each blinks twice a loop; counted round the loop, as a blink may run past its end
        shut = [faces[girl][2] == "eyes_closed" for faces, _ in frames]
        assert sum(now and not before for before, now in zip(shut[-1:] + shut[:-1], shut)) == 2, girl


def test_the_lineup_uses_only_the_parts_every_girl_has():
    from claude_pet.pet_window import IDLE_PARTS, TALK_EYES

    previews = _previews()
    used = {p for faces, _ in previews.timeline() for face in faces.values() for p in previews.face_parts(*face)}
    assert used <= set(IDLE_PARTS + TALK_EYES)
    assert {"mouth_closed", "mouth_half", "mouth_open", "eyes_half", "eyes_closed"} <= used


@pytest.mark.parametrize(("name", "lang"), [("girls.gif", "zh"), ("girls-en.gif", "en")])
def test_the_animated_lineups_are_up_to_date(name, lang):
    """Fails when the art, the names or the timing changed but devtools/make_previews.py was not re-run."""
    from PIL import Image, ImageChops, ImageSequence

    previews = _previews()
    if not all((previews.fonts / f).is_file() for f in previews.FONT_FILES):
        pytest.skip("Microsoft YaHei is not installed")
    frames = previews.timeline()
    colours = previews.palette(lang)
    talker = [next(g for g, face in faces.items() if face[0] == "talk") for faces, _ in frames]
    starts = [i for i in range(len(frames)) if i == 0 or talker[i] != talker[i - 1]]  # each girl's first word
    with Image.open(ROOT / "docs" / "images" / name) as gif:
        assert gif.info.get("loop") == 0  # plays forever
        assert [f.info["duration"] for f in ImageSequence.Iterator(gif)] == [ms for _, ms in frames]
        for i in starts:
            gif.seek(i)
            drawn = previews.frame(lang, frames[i][0], colours).convert("RGB")
            assert ImageChops.difference(drawn, gif.convert("RGB")).getbbox() is None, i
        gif.seek(0)
        assert gif.convert("RGB").getpixel((0, 0)) == previews.BACKGROUND  # white, not a near-white tint


def test_the_english_previews_are_drawn_in_english():
    previews = _previews()
    labels = [*previews.TEXT["en"].values(), *(previews.name(girl, "en") for girl in CHARACTERS)]
    assert [t for t in labels if CJK.search(t)] == []
    assert set(previews.TEXT["en"]) == set(previews.TEXT["zh"]) >= set(MOODS)


def test_setting_names_match_the_english_interface():
    text = EN.read_text(encoding="utf-8")
    shown = set(i18n_en.TEXT.values())
    for name in ("General", "How she thinks", "Watching", "Companion", "Appearance", "About", "Download and update",
                 "Check now", "Birthday wish", "Daily summary", "Late-night rest reminder", "Claude Code link",
                 "Stroll along the bottom of the screen", "Fast and cheap", "Smarter", "Settings…"):
        assert name in shown, name
        assert name in text, name
