"""「和她说话」: a line for her, in the current girl's colours and with her face."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPen, QColor, QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from .characters import Theme
from .i18n import tr

MAX_MESSAGE = 300
PORTRAIT = 64


def stylesheet(t: Theme) -> str:
    return f"""
QDialog {{ background: {t.ivory}; }}
QLabel {{ color: {t.ink}; font-family: "Microsoft YaHei UI", "Microsoft YaHei", sans-serif; font-size: 11pt; }}
QLabel#hint {{ color: {t.hint}; font-size: 9pt; }}
QLineEdit {{ background: white; color: {t.ink}; border: 1px solid {t.gold}; border-radius: 8px; padding: 7px 9px;
             font-family: "Microsoft YaHei UI", "Microsoft YaHei", sans-serif; font-size: 10pt;
             selection-background-color: {t.main}; }}
QLineEdit:focus {{ border: 1px solid {t.main}; }}
QPushButton {{ color: white; border: 1px solid {t.deep}; border-radius: 14px; padding: 6px 22px; font-size: 10pt;
               font-family: "Microsoft YaHei UI", "Microsoft YaHei", sans-serif;
               background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {t.deep}, stop:1 {t.main}); }}
QPushButton:hover {{ background: {t.main}; }}
QPushButton:disabled {{ background: {t.disabled}; border-color: {t.disabled}; }}
QPushButton#quiet {{ color: {t.deep}; background: {t.ivory}; border: 1px solid {t.main}; }}
QPushButton#quiet:hover {{ background: {t.cream}; }}
"""


def round_portrait(face: QPixmap, theme: Theme, size: int = PORTRAIT) -> QPixmap:
    """Her face in a circle with a gold ring, sharp on a scaled display."""
    ratio = 2
    out = QPixmap(size * ratio, size * ratio)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    area = QRectF(2, 2, out.width() - 4, out.height() - 4)
    circle = QPainterPath()
    circle.addEllipse(area)
    painter.fillPath(circle, QColor(theme.cream))
    if not face.isNull():
        painter.setClipPath(circle)
        target = area.toRect()
        fitted = face.scaled(target.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                             Qt.TransformationMode.SmoothTransformation)
        painter.drawPixmap(target.x() + (target.width() - fitted.width()) // 2,
                           target.y() + (target.height() - fitted.height()) // 2, fitted)
        painter.setClipping(False)
    painter.setPen(QPen(QColor(theme.gold), 3))
    painter.drawEllipse(area)
    painter.end()
    out.setDevicePixelRatio(ratio)
    return out


class ChatDialog(QDialog):
    def __init__(self, name: str, theme: Theme, face: QPixmap) -> None:
        super().__init__(None, Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint | Qt.WindowType.WindowTitleHint)
        self.setWindowTitle(tr("和 {0} 说话", name))
        self.setStyleSheet(stylesheet(theme))
        self.setMinimumWidth(440)
        portrait = QLabel()
        portrait.setPixmap(round_portrait(face, theme))
        self.entry = QLineEdit()
        self.entry.setMaxLength(MAX_MESSAGE)
        hint = QLabel(tr("说「记住：……」她就会记下，说「忘掉：……」就删掉。"))
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        talk = QVBoxLayout()
        talk.setSpacing(7)
        talk.addWidget(QLabel(tr("想对她说什么？")))
        talk.addWidget(self.entry)
        talk.addWidget(hint)
        top = QHBoxLayout()
        top.setSpacing(14)
        top.addWidget(portrait, 0, Qt.AlignmentFlag.AlignTop)
        top.addLayout(talk, 1)
        self.send_button = QPushButton(tr("发送"))
        self.send_button.setDefault(True)  # Enter sends
        self.send_button.setEnabled(False)
        self.send_button.clicked.connect(self.accept)
        cancel = QPushButton(tr("算了"))
        cancel.setObjectName("quiet")
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(self.send_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(12)
        layout.addLayout(top)
        layout.addLayout(buttons)
        self.entry.textChanged.connect(lambda text: self.send_button.setEnabled(bool(text.strip())))
        self.entry.setFocus()

    def message(self) -> str:
        return self.entry.text().strip()


def ask(name: str, theme: Theme, face: QPixmap) -> str | None:
    """What was written, or None if nothing or cancelled."""
    dialog = ChatDialog(name, theme, face)
    return dialog.message() or None if dialog.exec() == QDialog.DialogCode.Accepted else None
