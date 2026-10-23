"""The two READMEs: linked both ways, the English one in English, its links and setting names real."""
import re
from pathlib import Path

import pytest

from claude_pet import i18n_en

ROOT = Path(__file__).resolve().parents[1]
ZH, EN = ROOT / "README.md", ROOT / "README.en.md"
CJK = re.compile(r"[一-鿿]+")
NAMES = {"中文", "冬冰"}  # the language switch's own name; a creator's name, given in English too


def test_they_link_to_each_other():
    assert "[English](README.en.md)" in ZH.read_text(encoding="utf-8").splitlines()[2]
    assert "[中文](README.md)" in EN.read_text(encoding="utf-8").splitlines()[2]


def test_the_english_readme_is_in_english():
    assert set(CJK.findall(EN.read_text(encoding="utf-8"))) <= NAMES


@pytest.mark.parametrize("readme", [ZH, EN], ids=["zh", "en"])
def test_relative_links_exist(readme):
    for target in re.findall(r"\]\(([^)#]+)\)", readme.read_text(encoding="utf-8")):
        if not re.match(r"[a-z]+:", target):
            assert (ROOT / target).exists(), target


def test_setting_names_match_the_english_interface():
    text = EN.read_text(encoding="utf-8")
    shown = set(i18n_en.TEXT.values())
    for name in ("General", "How she thinks", "Watching", "Companion", "Appearance", "About", "Download and update",
                 "Check now", "Birthday wish", "Daily summary", "Late-night rest reminder", "Claude Code link",
                 "Stroll along the bottom of the screen", "Fast and cheap", "Smarter", "Settings…"):
        assert name in shown, name
        assert name in text, name
