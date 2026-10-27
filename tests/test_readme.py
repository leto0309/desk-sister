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
    assert "(docs/images/girls.png)" in zh and "(docs/images/moods.png)" in zh
    assert "(docs/images/girls-en.png)" in en
    for girl in CHARACTERS:
        if girl != "claude":
            assert f"(docs/images/moods-{girl}.png)" in zh, girl
        assert f"(docs/images/moods-{girl}-en.png)" in en, girl
    images = re.findall(r"\]\((docs/images/[^)]+)\)", en)
    assert images and [i for i in images if not i.endswith("-en.png")] == []


def test_the_english_previews_are_drawn_in_english():
    spec = importlib.util.spec_from_file_location("make_previews", ROOT / "devtools" / "make_previews.py")
    previews = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(previews)
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
