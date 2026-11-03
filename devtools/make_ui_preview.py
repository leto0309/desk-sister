"""Make the README's picture of the interface in docs/images/: ui.png and ui-en.png, from the real menu and dialogs
(drawn without ever being shown, so with no title bars), for Claude and Gemini. Run it on Windows: its own fonts.

    python devtools/make_ui_preview.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from claude_pet import characters, chat_dialog, i18n, reminder_dialog  # noqa: E402
from claude_pet import controller as controller_module  # noqa: E402
from claude_pet.config import Config  # noqa: E402

GIRLS = ("claude", "gemini")
GAP = 22


def framed(picture: QPixmap, gold: str) -> QPixmap:
    """A dialog as a card: the off-screen picture has no title bar to mark its edge."""
    out = QPixmap(picture.size())
    out.fill(QColor(0, 0, 0, 0))
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    card = QPainterPath()
    card.addRoundedRect(QRectF(picture.rect()).adjusted(1, 1, -1, -1), 12, 12)
    painter.setClipPath(card)
    painter.drawPixmap(0, 0, picture)
    painter.setClipping(False)
    painter.setPen(QPen(QColor(gold), 1.5))
    painter.drawPath(card)
    painter.end()
    return out


def save_sheet(sheet: QImage, out: Path) -> None:
    if not sheet.save(str(out)):  # a locked file or a full disk: never say it worked, the old picture would stay
        raise SystemExit(f"could not save {out}")


def render(app: QApplication, lang: str, out: Path) -> None:
    i18n.set_language(lang)
    folder = Path(tempfile.mkdtemp())
    controller_module.app_data_dir = lambda: folder
    controller_module.save_config = lambda *_a, **_k: None
    ctrl = controller_module.PetController(app, Config(language=lang, check_updates=False), ROOT / "assets" / "sprites", None)
    rows = []
    for girl in GIRLS:
        ctrl.set_character(girl)
        character = characters.get(girl)
        menu = ctrl.tray.contextMenu()
        ctrl._fill_timer_menu()
        menu.adjustSize()
        menu.setActiveAction(menu.actions()[1])
        app.processEvents()
        chat = chat_dialog.ChatDialog(ctrl._name(), character.theme, ctrl.window.face_picture(character.head))
        reminder = reminder_dialog.ReminderDialog(None, 1000.0, girl)
        for dialog in (chat, reminder):
            dialog.adjustSize()
        rows.append((framed(menu.grab(), character.theme.gold), framed(chat.grab(), character.theme.gold), framed(reminder.grab(), character.theme.gold)))
    width = max(sum(p.width() for p in row) + GAP * 4 for row in rows)
    height = sum(max(p.height() for p in row) + GAP for row in rows) + GAP
    sheet = QImage(width, height, QImage.Format.Format_ARGB32)
    sheet.fill(QColor("#ebe8f2"))
    painter = QPainter(sheet)
    y = GAP
    for row in rows:
        x = GAP
        for picture in row:
            painter.drawPixmap(x, y, picture)
            x += picture.width() + GAP
        y += max(p.height() for p in row) + GAP
    painter.end()
    save_sheet(sheet, out)
    print(f"[ok] {out.name} {width}x{height}")


def main() -> None:
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"  # the same picture at any screen scaling
    app = QApplication([])
    render(app, "zh", ROOT / "docs" / "images" / "ui.png")
    render(app, "en", ROOT / "docs" / "images" / "ui-en.png")


if __name__ == "__main__":
    main()
