"""The right-click and tray menu in the current girl's colours, like the settings window."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMenu

from .characters import Theme


def stylesheet(t: Theme) -> str:
    return f"""
QMenu {{ background: {t.ivory}; border: 1.5px solid {t.gold}; border-radius: 12px; padding: 7px 0;
         color: {t.ink}; font-family: "Microsoft YaHei UI", "Microsoft YaHei", sans-serif; font-size: 10pt; }}
QMenu::item {{ padding: 7px 28px 7px 14px; margin: 1px 7px; border-radius: 8px; background: transparent; }}
QMenu::item:selected {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {t.deep}, stop:1 {t.main});
                        color: white; }}
QMenu::item:disabled {{ color: {t.disabled}; background: transparent; }}
QMenu::separator {{ height: 1px; background: {t.peach}; margin: 5px 16px; }}
QMenu::indicator {{ left: 10px; width: 14px; height: 14px; }}
"""


def apply(menu: QMenu, theme: Theme) -> None:
    """Rounded corners need a see-through window behind the menu; a submenu takes the same look."""
    menu.setStyleSheet(stylesheet(theme))
    for each in [menu, *menu.findChildren(QMenu)]:
        each.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        each.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint)
        each.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
