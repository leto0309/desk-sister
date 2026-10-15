import hashlib
from pathlib import Path

import pytest
from PIL import Image

from claude_pet import sprite_data
from claude_pet.persona import MOODS

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from claude_pet.pet_window import embedded_sprite, load_sprites  # noqa: E402

SPRITES = Path(__file__).resolve().parents[1] / "assets" / "sprites"


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_embedded_module_matches_current_pngs():
    """Fails when assets/sprites changed but devtools/embed_sprites.py was not re-run."""
    assert set(sprite_data.SOURCES) == set(MOODS) == set(sprite_data.SPRITES)
    for mood in MOODS:
        digest = hashlib.sha256((SPRITES / f"{mood}.png").read_bytes()).hexdigest()
        assert sprite_data.SOURCES[mood] == digest, f"{mood}: run python devtools/embed_sprites.py"


def test_embedded_sprites_decode_with_alpha_at_full_size(app):
    import base64
    import io

    from PIL import ImageChops, ImageStat

    for mood in MOODS:
        pixmap = embedded_sprite(mood)
        with Image.open(SPRITES / f"{mood}.png") as png:
            original = png.convert("RGBA").getchannel("A")
        assert (pixmap.width(), pixmap.height()) == original.size
        assert pixmap.hasAlphaChannel() and pixmap.toImage().pixelColor(0, 0).alpha() == 0
        # The transparency mask survives the WebP round trip: same silhouette, near-identical alpha.
        decoded = Image.open(io.BytesIO(base64.b64decode(sprite_data.SPRITES[mood]))).convert("RGBA").getchannel("A")
        assert decoded.getbbox() == original.getbbox()
        assert ImageStat.Stat(ImageChops.difference(decoded, original)).mean[0] < 1.0
    assert embedded_sprite("no-such-mood").isNull()


def test_without_assets_folder_the_embedded_art_is_used(app):
    """What a one-file exe sees: no assets/ next to it, real sprites anyway (not placeholders)."""
    from_files = load_sprites(SPRITES, 220)
    embedded = load_sprites(Path("definitely-missing-folder"), 220)
    for mood in MOODS:
        assert embedded[mood].size() == from_files[mood].size()


def _damaged(mood: str) -> str:
    """Valid RIFF/VP8X headers, wrecked bitstream: a lossy decoder may still return pixels for this."""
    import base64

    raw = bytearray(base64.b64decode(sprite_data.SPRITES[mood]))
    for i in range(len(raw) // 2, len(raw) - 64):
        raw[i] ^= 0xA5
    return base64.b64encode(bytes(raw)).decode("ascii")


def test_damaged_or_truncated_art_is_rejected():
    import base64

    from claude_pet.sprites import decode_embedded

    good = sprite_data.SPRITES["idle"]
    assert decode_embedded(good, sprite_data.CHECKSUMS["idle"]).size == (435, 512)
    with pytest.raises(ValueError):
        decode_embedded(_damaged("idle"), sprite_data.CHECKSUMS["idle"])
    truncated = base64.b64encode(base64.b64decode(good)[:2000]).decode("ascii")
    with pytest.raises(ValueError):
        decode_embedded(truncated, sprite_data.CHECKSUMS["idle"])
    assert set(sprite_data.CHECKSUMS) == set(MOODS)


def test_damaged_embedded_art_falls_back_to_placeholder(app, monkeypatch):
    monkeypatch.setitem(sprite_data.SPRITES, "sad", _damaged("sad"))
    assert embedded_sprite("sad").isNull()
    sprites = load_sprites(Path("definitely-missing-folder"), 220)
    assert not sprites["sad"].isNull()  # placeholder drawn, app keeps running


def test_self_test_fails_on_damaged_embedded_art(monkeypatch):
    import importlib.util

    monkeypatch.setitem(sprite_data.SPRITES, "sad", _damaged("sad"))
    spec = importlib.util.spec_from_file_location("pet_app", Path(__file__).resolve().parents[1] / "app.py")
    app_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app_module)
    with pytest.raises(ValueError):
        app_module.self_test()
