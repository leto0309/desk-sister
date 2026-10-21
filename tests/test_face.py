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


@pytest.mark.parametrize("mood", ["happy", "panic", "sleep"])
def test_some_faces_keep_their_own_eyes(window, mood):
    window.mood = mood  # happy's eyes are already closed, panic's are swirls, sleep is asleep
    window._blink(window._blink_at + 0.1)
    assert len(window._layers()) == 1


@pytest.mark.parametrize("mood", ["think", "angry", "sad"])
def test_other_faces_blink_with_their_own_eyes(window, mood):
    window.mood = mood
    window._blink(window._blink_at + 0.1)
    assert window.eyes == "eyes_closed"
    layers = window._layers()
    assert len(layers) == 2 and layers[1].cacheKey() == window.parts[f"{mood}_eyes_closed"].cacheKey()


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
    window.say("sleep", "（梦话）……")
    window._type_next()
    assert window.mouth is None  # no parts for a sleeping face


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
    assert set(pet_window.FACE_MOODS) == {"idle", "talk", "happy", "think", "panic", "angry", "sad"}


@pytest.mark.parametrize("missing", ["mouth_open", "mouth_closed"])
def test_a_talk_mouth_needs_both_its_cover_and_its_shape(window, missing):
    del window.parts[missing]
    window.mood, window.eyes, window.mouth = "talk", "eyes_half", "mouth_open"
    layers = window._layers()
    assert len(layers) == 2 and layers[1].cacheKey() == window.parts["talk_eyes_half"].cacheKey()  # still blinks
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


@pytest.mark.parametrize("mood", ["happy", "think", "panic", "angry", "sad"])
def test_every_expression_moves_its_own_mouth(window, mood):
    mouths = _typing(window, mood, "主人今天写了好多好多代码呢真的很厉害")
    assert {"mouth_half", "mouth_open"} <= set(mouths)
    window.say(mood, "嗯")
    window.mouth = "mouth_open"
    layers = window._layers()
    assert layers[1].cacheKey() == window.parts[f"{mood}_mouth_open"].cacheKey()  # made from this expression


def test_the_talk_face_blinks_with_its_own_cover(window):
    window.mood, window.eyes, window.mouth = "talk", "eyes_closed", None
    assert window._layers()[1].cacheKey() == window.parts["talk_eyes_closed"].cacheKey()


def test_the_mouth_is_drawn_under_the_eyes(window):
    window.mood, window.eyes, window.mouth = "idle", "eyes_closed", "mouth_open"
    layers = window._layers()
    assert [layer.cacheKey() for layer in layers[1:]] == [
        window.parts["mouth_open"].cacheKey(), window.parts["eyes_closed"].cacheKey()]


def test_a_missing_expression_part_leaves_that_expression_as_drawn(window):
    del window.parts["angry_mouth_open"]
    window.mood, window.eyes, window.mouth = "angry", None, "mouth_open"
    assert len(window._layers()) == 1



def _pixels(window, eyes, mouth, rect):
    window.mood, window.eyes, window.mouth = "talk", eyes, mouth
    image = window.grab().toImage()
    return [image.pixel(x, y) for x in range(rect.left(), rect.right()) for y in range(rect.top(), rect.bottom())]


def test_blinking_while_talking_never_changes_her_mouth(window):
    window.set_sprite_height(400)
    sprite = window.sprites["talk"]
    mouth = window.parts["mouth_open"].toImage()
    left = (window.width() - sprite.width()) // 2
    top = window.height() - sprite.height() - 4
    xs = [x for x in range(mouth.width()) for y in range(0, mouth.height(), 2) if mouth.pixelColor(x, y).alpha() > 200]
    ys = [y for x in range(0, mouth.width(), 2) for y in range(mouth.height()) if mouth.pixelColor(x, y).alpha() > 200]
    from PySide6.QtCore import QRect

    w, h = max(xs) - min(xs), max(ys) - min(ys)
    rect = QRect(left + min(xs) + w // 4, top + min(ys) + h // 4, w // 2, h // 2)  # the mouth itself, not the cheeks
    window._phase = 0.0  # the gentle bob: the same for both pictures
    window._animate = lambda: None
    assert _pixels(window, "eyes_closed", "mouth_open", rect) == _pixels(window, None, "mouth_open", rect)


@pytest.mark.parametrize(("mood", "missing", "eyes", "mouth"), [
    ("angry", "angry_mouth_open", None, "mouth_half"),  # the other mouth frame is dropped too
    ("talk", "talk_eyes_closed", "eyes_half", None),  # and the other blink frame
    ("talk", "mouth_closed", None, "mouth_half"),
])
def test_one_missing_frame_drops_the_whole_set(window, mood, missing, eyes, mouth):
    del window.parts[missing]
    window.mood, window.eyes, window.mouth = mood, eyes, mouth
    assert len(window._layers()) == 1


def _part_script():
    import importlib.util

    script = Path(__file__).resolve().parents[1] / "devtools" / "make_face_parts.py"
    spec = importlib.util.spec_from_file_location("make_face_parts", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_part_script_writes_nothing_when_any_original_is_missing(tmp_path):
    from PIL import Image

    module = _part_script()
    raw = tmp_path / "raw"
    (raw / "parts").mkdir(parents=True)
    image = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    image.paste((240, 200, 180, 255), (300, 100, 720, 950))
    for mood in module.MOODS:
        image.save(raw / f"{mood}.png")
    image.save(raw / "parts" / "idle.png")
    for name in module.EDITS:
        image.save(raw / "parts" / f"{name}.png")
    for mood, names in module.MOOD_EDITS.items():
        for name in names:
            image.save(raw / "parts" / f"{mood}_{name}.png")
    sources = sorted(raw.rglob("*.png"))
    assert module.missing_sources(raw) == []
    out = tmp_path / "out"
    out.mkdir()
    (out / "angry_mouth_open.png").write_bytes(b"old part")
    for source in sources:  # each original on its own
        data = source.read_bytes()
        source.unlink()
        assert module.main(raw, out) == 1, source.name
        assert [p.name for p in out.iterdir()] == ["angry_mouth_open.png"]
        assert (out / "angry_mouth_open.png").read_bytes() == b"old part"
        source.write_bytes(data)


def test_an_eye_part_is_empty_over_the_whole_mouth(tmp_path):
    from PIL import Image

    module = _part_script()
    base = Image.new("RGBA", (1024, 1024), (240, 200, 180, 255))
    edit = Image.new("RGBA", (1024, 1024), (20, 20, 20, 255))  # different everywhere
    mask = module.changed_mask(base, edit, module.EYES)
    assert mask.crop(module.MOUTH_KEEP).getextrema() == (0, 0)
    assert mask.crop(module.EYES).getextrema()[1] == 255  # the eyes themselves are still covered


def test_no_shipped_eye_part_reaches_the_mouth():
    from PIL import Image

    mouth = Image.open(ASSETS / "parts" / "mouth_open.png").getchannel("A")
    core = mouth.point(lambda a: 255 if a > 200 else 0).getbbox()
    w, h = core[2] - core[0], core[3] - core[1]
    centre = (core[0] + w // 4, core[1] + h // 4, core[2] - w // 4, core[3] - h // 4)
    for name in PARTS:
        if "eyes" in name:
            assert Image.open(ASSETS / "parts" / f"{name}.png").getchannel("A").crop(centre).getextrema()[1] <= 8, name


def test_embedding_refuses_an_incomplete_set_of_parts(tmp_path):
    import importlib.util
    import shutil

    script = Path(__file__).resolve().parents[1] / "devtools" / "embed_sprites.py"
    spec = importlib.util.spec_from_file_location("embed_sprites", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sprites = tmp_path / "sprites"
    shutil.copytree(ASSETS, sprites)
    output = tmp_path / "sprite_data.py"
    output.write_text("OLD = 1", encoding="utf-8")
    assert module.missing(sprites) == []
    for name in ("angry_mouth_open", "talk_eyes_closed"):
        part = sprites / "parts" / f"{name}.png"
        data = part.read_bytes()
        part.unlink()
        assert module.main(sprites, output) == 1 and output.read_text(encoding="utf-8") == "OLD = 1"
        part.write_bytes(data)
    shutil.rmtree(sprites / "parts")
    assert module.main(sprites, output) == 1 and output.read_text(encoding="utf-8") == "OLD = 1"


@pytest.mark.parametrize(("rate", "low", "high"), [("few", 6.0, 12.0), ("normal", 3.0, 7.0), ("often", 1.5, 4.0)])
def test_blink_rates(window, rate, low, high):
    window.set_blink(rate)
    start = window.clock()
    assert start + low <= window._blink_at <= start + high
    window.mood = "idle"
    over = window._blink_at + 0.3
    window._blink(over)  # one blink over: the next one at this rate
    assert over + low <= window._blink_at <= over + high


def test_blinking_can_be_switched_off_at_once(window):
    window.mood = "idle"
    window._blink(window._blink_at + 0.1)
    assert window.eyes == "eyes_closed"
    window.set_blink("off")
    assert window.eyes is None
    window._blink(window._blink_at + 0.1)
    assert window.eyes is None and len(window._layers()) == 1


def test_the_talking_mouth_can_be_switched_off_at_once(window):
    window.say("talk", "主人今天辛苦啦")
    window.clock.now += 0.2
    window._type_next()
    window._type_next()
    assert window.mouth is not None
    window.set_talk_mouth(False)
    assert window.mouth is None
    window.clock.now += 0.2
    window._type_next()
    assert window.mouth is None


def test_face_settings_are_kept_and_broken_values_fall_back(tmp_path):
    from claude_pet.config import Config, load_config

    assert (Config().blink, Config().talk_mouth) == ("normal", True)
    path = tmp_path / "config.json"
    path.write_text('{"blink": "often", "talk_mouth": false}', encoding="utf-8")
    assert (load_config(path).blink, load_config(path).talk_mouth) == ("often", False)
    path.write_text('{"blink": "always", "interval_sec": 120}', encoding="utf-8")
    config = load_config(path)
    assert config.blink == "normal" and config.interval_sec == 120



def test_the_settings_page_sets_blinking_and_the_talking_mouth(app, tmp_path, monkeypatch):
    from claude_pet import claude_client
    from claude_pet import controller as controller_module
    from claude_pet.config import Config

    monkeypatch.setattr(claude_client, "find_claude", lambda _configured="": "claude.exe")
    saved = []
    monkeypatch.setattr(controller_module, "save_config", lambda config, *_a, **_k: saved.append((config.blink, config.talk_mouth)))
    ctrl = controller_module.PetController(app, Config(blink="few", talk_mouth=False), ASSETS, tmp_path / "config.json")
    assert ctrl.window.blink_every == (6.0, 12.0) and ctrl.window.talk_mouth is False  # the saved choice at start
    ctrl.open_settings()
    page = ctrl.settings_window
    assert page.blink_combo.currentData() == "few" and not page.mouth_box.isChecked()
    page.blink_combo.setCurrentIndex(page.blink_combo.findData("off"))
    page.mouth_box.setChecked(True)
    assert (ctrl.config.blink, ctrl.config.talk_mouth) == ("off", True) and saved[-1] == ("off", True)
    assert ctrl.window.blink_every is None and ctrl.window.talk_mouth is True
    ctrl.set_blink("sometimes")  # unknown: ignored
    assert ctrl.config.blink == "off"
    page.close()


@pytest.mark.parametrize("value", ["null", "0", "1", '""', "[]", "{}", '"false"'])
def test_a_broken_talk_mouth_value_means_the_default(tmp_path, value):
    from claude_pet.config import load_config

    path = tmp_path / "config.json"
    path.write_text('{"talk_mouth": %s, "interval_sec": 120}' % value, encoding="utf-8")
    config = load_config(path)
    assert config.talk_mouth is True and config.interval_sec == 120

