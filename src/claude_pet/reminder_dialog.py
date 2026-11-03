"""「添加提醒」: what to be reminded of, and when (in so many minutes, or at a time of day)."""
from __future__ import annotations

import time

from PySide6.QtCore import QTime
from PySide6.QtWidgets import (QButtonGroup, QDialog, QDialogButtonBox, QGridLayout, QLabel, QLineEdit, QRadioButton,
                               QSpinBox, QTimeEdit, QVBoxLayout)

from . import characters, timers
from .characters import Theme
from .i18n import tr


def stylesheet(t: Theme) -> str:
    """The same look as the talk-to-her box."""
    from .settings_window import arrow_folder  # (only when the dialog opens)

    font = '"Microsoft YaHei UI", "Microsoft YaHei", sans-serif'
    arrows = arrow_folder(t.deep)
    return f"""
QDialog {{ background: {t.ivory}; }}
QLabel, QRadioButton {{ color: {t.ink}; font-family: {font}; font-size: 10pt; }}
QLineEdit, QSpinBox, QTimeEdit {{ background: white; color: {t.ink}; border: 1px solid {t.gold}; border-radius: 8px;
    padding: 6px 8px; font-family: {font}; font-size: 10pt; selection-background-color: {t.main}; }}
QLineEdit:focus, QSpinBox:focus, QTimeEdit:focus {{ border: 1px solid {t.main}; }}
QSpinBox::up-button, QSpinBox::down-button, QTimeEdit::up-button, QTimeEdit::down-button {{
    width: 18px; border: none; background: transparent; }}
QSpinBox::up-arrow, QTimeEdit::up-arrow {{ image: url("{arrows}/up.png"); width: 9px; height: 5px; }}
QSpinBox::down-arrow, QTimeEdit::down-arrow {{ image: url("{arrows}/down.png"); width: 9px; height: 5px; }}
QPushButton {{ color: white; border: 1px solid {t.deep}; border-radius: 14px; padding: 6px 22px; font-family: {font};
    font-size: 10pt; background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {t.deep}, stop:1 {t.main}); }}
QPushButton:hover {{ background: {t.main}; }}
QPushButton:disabled {{ background: {t.disabled}; border-color: {t.disabled}; }}
QPushButton#quiet {{ color: {t.deep}; background: {t.ivory}; border: 1px solid {t.main}; }}
QPushButton#quiet:hover {{ background: {t.cream}; }}
"""


class ReminderDialog(QDialog):
    def __init__(self, parent=None, now: float | None = None, girl: str = characters.DEFAULT) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("添加提醒"))
        self.setStyleSheet(stylesheet(characters.get(girl).theme))
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        layout.addWidget(QLabel(tr("提醒主人什么？")))
        self.text = QLineEdit()
        self.text.setMaxLength(timers.MAX_TEXT)
        self.text.setPlaceholderText(tr("比如：喝口水、开会、看一眼烤箱"))
        layout.addWidget(self.text)
        grid = QGridLayout()
        self.in_minutes = QRadioButton(tr("多久以后"))
        self.minutes = QSpinBox()
        self.minutes.setRange(1, 24 * 60)
        self.minutes.setValue(30)
        self.minutes.setSuffix(tr(" 分钟"))
        self.at_time = QRadioButton(tr("到了这个时间"))
        self.time = QTimeEdit()
        self.time.setDisplayFormat("HH:mm")
        start = time.localtime((now if now is not None else time.time()) + 3600)
        self.time.setTime(QTime(start.tm_hour, 0))
        group = QButtonGroup(self)
        for button in (self.in_minutes, self.at_time):
            group.addButton(button)
        self.in_minutes.setChecked(True)
        self.minutes.valueChanged.connect(lambda _v: self.in_minutes.setChecked(True))
        self.time.timeChanged.connect(lambda _t: self.at_time.setChecked(True))
        grid.addWidget(self.in_minutes, 0, 0)
        grid.addWidget(self.minutes, 0, 1)
        grid.addWidget(self.at_time, 1, 0)
        grid.addWidget(self.time, 1, 1)
        layout.addLayout(grid)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("好"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("算了"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setObjectName("quiet")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.text.textChanged.connect(lambda t: self.ok_button.setEnabled(bool(t.strip())))
        self.ok_button.setEnabled(False)

    def chosen(self, now: float) -> tuple[float, str] | None:
        text = self.text.text().strip()
        if not text:
            return None
        if self.in_minutes.isChecked():
            return timers.due_in(now, self.minutes.value()), text
        moment = self.time.time()
        return timers.due_at(now, moment.hour(), moment.minute()), text


def ask(clock, girl: str = characters.DEFAULT) -> tuple[float, str] | None:
    """(when, what) or None if cancelled. When is worked out as the dialog closes, from the clock then."""
    dialog = ReminderDialog(None, clock(), girl)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.chosen(clock())
