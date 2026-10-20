"""Face parts over the sprite: blinking, and the mouth moving while she talks."""
import hashlib
from pathlib import Path

import pytest
from PySide6 import QtWidgets
from PySide6.QtCore import QTimer

from claude_pet import pet_window, sprite_data
from claude_pet.pet_window import BLINK_EVERY, PARTS, PetWindow

ASSETS = Path(__file__).resolve().parents[1] / "assets" / "sprites"


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


@pytest.fixture
def window(app):
    window = PetWindow(ASSETS, 220)
    window.clock = Clock()
    yield window
    window.close()


def test_the_embedded_parts_match_the_part_files():
    """Fails when assets/sprites/parts changed but devtools/embed_sprites.py was not re-run."""
    assert set(sprite_data.PART_SOURCES) == set(PARTS) == set(sprite_data.PART_IMAGES) == set(sprite_data.PART_CHECKSUMS)
    for name in PARTS:
        digest = hashlib.sha256((ASSETS / "parts" / f"{name}.png").read_bytes()).hexdigest()
        assert sprite_data.PART_SOURCES[name] == digest, f"{name}: run python devtools/embed_sprites.py"


def test_every_part_is_the_size_of_her_sprite(window):
    assert set(window.parts) == set(PARTS)
    for part in window.parts.values():
        assert part.size() == window.sprites["idle"].size()
    window.set_sprite_height(330)
    assert all(part.size() == window.sprites["idle"].size() for part in window.parts.values())


def test_she_blinks_now_and_then(window):
    window.mood = "idle"
    start = window._blink_at
    window._blink(start - 0.01)
    assert window.eyes is None
    seen = []
    for t in (0.03, 0.1, 0.2):
        window._blink(start + t)
        seen.append(window.eyes)
    assert seen == ["eyes_half", "eyes_closed", "eyes_half"]
    window._blink(start + 0.3)
    assert window.eyes is None
    assert start + 0.3 + BLINK_EVERY[0] <= window._blink_at <= start + 0.3 + BLINK_EVERY[1]


@pytest.mark.parametrize("mood", ["happy", "sleep", "sad", "think"])
def test_other_faces_keep_their_own_eyes(window, mood):
    window.mood = mood
    window._blink(window._blink_at + 0.1)
    assert window.eyes is None
    assert len(window._layers()) == 1


def _typing(window, mood, text):
    window.say(mood, text)
    mouths = []
    while window._typer.isActive():
        window.clock.now += 0.035  # the typing speed
        window._type_next()
        mouths.append(window.mouth)
    return mouths


def _runs(mouths):
    runs = []
    for mouth in mouths:
        if runs and runs[-1][0] == mouth:
            runs[-1][1] += 1
        else:
            runs.append([mouth, 1])
    return runs


def test_her_mouth_moves_while_the_words_appear(window):
    mouths = _typing(window, "talk", "你好呀，主人今天写了好多好多代码呢真厉害")
    assert mouths[3] == "mouth_closed"  # the comma: a pause
    assert {"mouth_half", "mouth_open", "mouth_closed"} <= set(mouths)  # it really opens and closes
    assert "mouth_o" not in mouths
    assert window.mouth is None  # done: the sprite's own mouth again


def test_each_mouth_shape_is_held_long_enough(window):
    mouths = _typing(window, "talk", "主人今天写了好多好多代码呢真的很厉害哦我都看呆了")[:-1]
    inner = _runs(mouths)[1:-1]  # the first and last runs may be cut short
    assert inner and min(count for _mouth, count in inner) * 0.035 >= 0.1  # not flickering every character


def test_an_idle_face_pauses_with_its_own_mouth(window):
    mouths = _typing(window, "idle", "嗯，好")
    assert mouths[1] is None and window.mouth is None
    window.say("happy", "开心！")
    window._type_next()
    assert window.mouth is None  # parts are only for the faces they were made for


def test_the_talk_sprite_covers_its_own_mouth_before_another_shape(window):
    window.mood, window.eyes, window.mouth = "talk", None, "mouth_o"
    layers = window._layers()
    assert len(layers) == 3 and layers[1].cacheKey() == window.parts["mouth_closed"].cacheKey()
    window.mood = "idle"
    assert len(window._layers()) == 2


def test_parts_turn_with_her_when_she_walks_right(window):
    window.mood, window.eyes, window.mouth = "idle", "eyes_closed", None
    window.set_walking(1)
    layers = window._layers()
    assert layers[1].cacheKey() != window.parts["eyes_closed"].cacheKey()  # the mirrored copy
    window.set_walking(-1)
    assert window._layers()[1].cacheKey() == window.parts["eyes_closed"].cacheKey()
    window.grab()


def test_missing_or_damaged_parts_only_leave_the_sprite(app, tmp_path, monkeypatch):
    for mood in ("idle", "talk"):
        (tmp_path / f"{mood}.png").write_bytes((ASSETS / f"{mood}.png").read_bytes())
    monkeypatch.setattr(sprite_data, "PART_IMAGES", {**sprite_data.PART_IMAGES, "eyes_closed": "AAAA"})
    monkeypatch.setitem(sprite_data.PART_IMAGES, "mouth_open", "")
    window = PetWindow(tmp_path, 200)  # no parts folder here: embedded copies, two of them unusable
    assert "eyes_closed" not in window.parts and "mouth_open" not in window.parts and "eyes_half" in window.parts
    window.mood, window.eyes, window.mouth = "idle", "eyes_closed", "mouth_open"
    assert len(window._layers()) == 1
    window.grab()  # paints without errors
    window.close()


def test_no_extra_timer_runs_for_the_face(window):
    assert len(window.findChildren(QTimer)) == 3  # typing, bubble and the existing gentle bob
    assert pet_window.FACE_MOODS == ("idle", "talk")


@pytest.mark.parametrize("missing", ["mouth_open", "mouth_closed"])
def test_a_talk_mouth_needs_both_its_cover_and_its_shape(window, missing):
    del window.parts[missing]
    window.mood, window.eyes, window.mouth = "talk", "eyes_half", "mouth_open"
    layers = window._layers()
    assert len(layers) == 2 and layers[1].cacheKey() == window.parts["eyes_half"].cacheKey()  # the eyes still blink
    window.grab()


def test_a_pause_keeps_her_mouth_closed_for_a_moment(window):
    mouths = _typing(window, "talk", "嗯嗯嗯，好的好的好的好的")
    assert mouths[3:7] == ["mouth_closed"] * 4  # the comma and the next few characters


def test_short_english_words_still_move_her_mouth(window):
    mouths = _typing(window, "talk", "I am a cat and I can do it now ok")
    assert "mouth_open" in mouths and "mouth_closed" in mouths[:-1]  # opens and closes right through the spaces
    assert all(count * 0.035 >= 0.1 for _mouth, count in _runs(mouths[:-1])[1:-1])


def test_no_shape_is_cut_short_after_a_pause(window):
    mouths = _typing(window, "talk", "嗯嗯嗯，好的好的好的好的好的好的")[:-1]
    after = _runs(mouths[7:])  # once the pause after the comma is over
    assert after[0][0] == "mouth_half" and all(count * 0.035 >= 0.1 for _mouth, count in after[:-1])

