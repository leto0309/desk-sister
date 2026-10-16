import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def test_the_icon_has_every_size_windows_asks_for():
    with Image.open(ROOT / "assets" / "icon.ico") as icon:
        assert {(16, 16), (32, 32), (48, 48), (256, 256)} <= set(icon.info["sizes"])
        icon.size = (256, 256)
        icon.load()
        assert icon.getbbox() is not None  # not blank


def test_packaging_uses_the_icon():
    manifest = json.loads((ROOT / ".ai-factory.json").read_text(encoding="utf-8"))
    assert (ROOT / manifest["icon"]).is_file()
    adapter = (ROOT / "scripts" / "ProjectAdapter.ps1").read_text(encoding="utf-8")
    assert "'--icon'" in adapter
