"""The settings window: an elegant Baroque frame in Claude 娘's orange and white, with gold ornaments.

Every control applies at once through the controller's own setters (the same ones the menu and the hotkey
use), and `refresh()` reads everything back from the config, so the window and the pet never disagree.
"""
from __future__ import annotations

import calendar
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QPushButton, QRadioButton, QSlider, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from . import __version__
from .bedtime import MODE_LABELS as BEDTIME_LABELS
from .bedtime import MODES as BEDTIME_MODES
from .bedtime import NIGHT_STARTS
from .config import BLINK_CHOICES, INTERVAL_CHOICES, MODEL_CHOICES
from .providers import CLAUDE_CLI, CODEX_CLI, PROVIDERS, model_label

if TYPE_CHECKING:
    from .controller import PetController

LINK_LABEL = "Claude Code 联动（会先征得同意，再修改 ~/.claude/settings.json）"
BLINK_LABELS = {"off": "关闭", "few": "少", "normal": "正常", "often": "多"}

# Claude 娘: orange hair, white dress; Baroque: ivory, cream and gold.
IVORY = "#FFF9F1"
CREAM = "#FBEFDF"
PEACH = "#F7D9BF"
ORANGE = "#E07B39"
DEEP = "#B5531F"
GOLD = "#C9A45C"
INK = "#4A2E1F"
SERIF = '"Noto Serif SC", "Source Han Serif SC", "SimSun", "Georgia", serif'
SANS = '"Microsoft YaHei UI", "Microsoft YaHei", sans-serif'

INTERVAL_LABELS = {30: "30 秒", 60: "1 分钟", 90: "90 秒", 120: "2 分钟", 300: "5 分钟", 600: "10 分钟"}
PAGES = ("常规", "调用方式", "观察范围", "陪伴", "外观", "关于")
HEAD = (0.2575, 0.047, 0.46, 0.39)  # her face in the idle sprite, as fractions (see devtools/make_icon.py)

STYLE = f"""
QDialog {{ background: {IVORY}; }}
QWidget {{ color: {INK}; font-family: {SANS}; font-size: 10pt; }}
QFrame#frame {{ background: {IVORY}; border: 2px solid {GOLD}; border-radius: 14px; }}
QFrame#inner {{ background: transparent; border: 1px solid {PEACH}; border-radius: 10px; }}
QLabel#pageTitle {{ font-family: {SERIF}; font-size: 15pt; color: {DEEP}; font-weight: bold; }}
QLabel#hint {{ color: #8A6A55; font-size: 9pt; }}
QLabel#fleuron {{ color: {GOLD}; font-size: 13pt; }}
QListWidget#nav {{ background: {CREAM}; border: 1px solid {GOLD}; border-radius: 10px; padding: 6px;
                   font-family: {SERIF}; font-size: 11pt; outline: none; }}
QListWidget#nav::item {{ padding: 9px 14px; margin: 2px 0; border-radius: 8px; color: {INK}; }}
QListWidget#nav::item:hover {{ background: {PEACH}; }}
QListWidget#nav::item:selected {{ color: white; border-left: 3px solid {GOLD};
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {DEEP}, stop:1 {ORANGE}); }}
QPushButton {{ color: white; border: 1px solid {DEEP}; border-radius: 13px; padding: 6px 16px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #EE9152, stop:1 {DEEP}); }}
QPushButton:hover {{ background: {ORANGE}; }}
QPushButton:disabled {{ background: #D9C3B0; border-color: #C9B39F; }}
QPushButton#quiet {{ color: {DEEP}; background: {IVORY}; border: 1px solid {ORANGE}; }}
QPushButton#quiet:hover {{ background: {CREAM}; }}
QPushButton#quiet:disabled {{ color: #C9B39F; border-color: #E2D3C4; background: {IVORY}; }}
QComboBox, QSpinBox, QLineEdit {{ background: white; border: 1px solid {GOLD}; border-radius: 6px; padding: 4px 8px; }}
QComboBox:focus, QSpinBox:focus, QLineEdit:focus {{ border: 1px solid {ORANGE}; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 22px; border: none; }}
QComboBox::down-arrow {{ image: url("{{arrows}}/down.png"); width: 10px; height: 6px; }}
QComboBox QAbstractItemView {{ background: white; border: 1px solid {GOLD}; selection-background-color: {PEACH};
    selection-color: {INK}; outline: none; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 18px; border: none; background: transparent; }}
QSpinBox::up-arrow {{ image: url("{{arrows}}/up.png"); width: 9px; height: 5px; }}
QSpinBox::down-arrow {{ image: url("{{arrows}}/down.png"); width: 9px; height: 5px; }}
QListWidget#rules {{ background: white; border: 1px solid {GOLD}; border-radius: 6px; }}
QListWidget#rules::item:selected {{ background: {PEACH}; color: {INK}; }}
QCheckBox, QRadioButton {{ spacing: 8px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 15px; height: 15px; border: 1px solid {GOLD}; background: white; }}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{ background: {ORANGE}; border: 1px solid {DEEP}; }}
QSlider::groove:horizontal {{ height: 6px; background: {PEACH}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {ORANGE}; border-radius: 3px; }}
QSlider::handle:horizontal {{ width: 16px; margin: -6px 0; border-radius: 8px; background: white; border: 2px solid {GOLD}; }}
"""


def arrow_folder() -> str:
    """Small gold arrows for combo and spin boxes (style sheets need image files), drawn once."""
    folder = Path(tempfile.gettempdir()) / "desk-sister-ui"
    folder.mkdir(exist_ok=True)
    for name, points in (("down", [(1, 2), (19, 2), (10, 11)]), ("up", [(1, 11), (19, 11), (10, 2)])):
        target = folder / f"{name}.png"
        if target.exists():
            continue
        image = QPixmap(20, 13)
        image.fill(Qt.GlobalColor.transparent)
        p = QPainter(image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(DEEP))
        p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in points]))
        p.end()
        image.save(str(target))
    return folder.as_posix()


class BaroqueHeader(QWidget):
    """Her face in a gold cameo, the title in serif type, and symmetric scroll flourishes."""

    def __init__(self, portrait: QPixmap, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.portrait = portrait
        self.setFixedHeight(118)

    @staticmethod
    def _scroll(path: QPainterPath, x: float, y: float, direction: float) -> None:
        """One acanthus-like curl: an S-curve that ends in a small spiral."""
        d = direction
        path.moveTo(x, y)
        path.cubicTo(x + 40 * d, y - 22, x + 80 * d, y + 22, x + 120 * d, y)
        path.cubicTo(x + 136 * d, y - 9, x + 128 * d, y - 22, x + 116 * d, y - 16)
        path.cubicTo(x + 108 * d, y - 12, x + 112 * d, y - 4, x + 118 * d, y - 7)
        path.moveTo(x + 58 * d, y + 3)
        path.cubicTo(x + 66 * d, y + 16, x + 80 * d, y + 17, x + 86 * d, y + 9)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        band = QLinearGradient(0, 0, 0, self.height())
        band.setColorAt(0, QColor(CREAM))
        band.setColorAt(1, QColor(IVORY))
        p.fillRect(self.rect(), band)
        gold = QPen(QColor(GOLD), 1.6)
        p.setPen(gold)
        p.drawLine(QPointF(18, self.height() - 6), QPointF(w - 18, self.height() - 6))
        p.drawLine(QPointF(30, self.height() - 2), QPointF(w - 30, self.height() - 2))
        # cameo: double gold oval around her face
        cx, cy = 66.0, 58.0
        oval = QRectF(cx - 40, cy - 48, 80, 96)
        clip = QPainterPath()
        clip.addEllipse(oval.adjusted(4, 4, -4, -4))
        p.save()
        p.setClipPath(clip)
        p.fillRect(oval, QColor(IVORY))
        if not self.portrait.isNull():
            face = self.portrait.scaled(int(oval.width()), int(oval.height()), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                        Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(int(cx - face.width() / 2), int(cy - face.height() / 2), face)
        p.restore()
        p.setPen(QPen(QColor(GOLD), 3))
        p.drawEllipse(oval.adjusted(3, 3, -3, -3))
        p.setPen(QPen(QColor(DEEP), 1))
        p.drawEllipse(oval)
        # title
        p.setPen(QColor(DEEP))
        title = QFont("Noto Serif SC")
        title.setFamilies(["Noto Serif SC", "Source Han Serif SC", "SimSun", "Georgia"])
        title.setPointSize(20)
        title.setBold(True)
        p.setFont(title)
        text_rect = QRectF(120, 18, w - 140, 44)
        p.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, "Desk Sister · 设置")
        sub = QFont(title)
        sub.setPointSize(10)
        sub.setBold(False)
        p.setFont(sub)
        p.setPen(QColor("#8A6A55"))
        p.drawText(QRectF(120, 60, w - 140, 22), Qt.AlignmentFlag.AlignCenter, "Anthropic 家族的长女，为主人整理一切")
        # flourishes either side of a fleuron, under the subtitle
        mid = 120 + (w - 140) / 2
        flourish = QPainterPath()
        self._scroll(flourish, mid - 14, 92, -1)
        self._scroll(flourish, mid + 14, 92, 1)
        p.setPen(QPen(QColor(GOLD), 1.4))
        p.drawPath(flourish)
        p.setPen(QColor(ORANGE))
        fleuron = QFont("Segoe UI Symbol")
        fleuron.setPointSize(13)
        p.setFont(fleuron)
        p.drawText(QRectF(mid - 12, 80, 24, 24), Qt.AlignmentFlag.AlignCenter, "❦")
        p.end()


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("hint")
    label.setWordWrap(True)
    return label


def _page(title: str) -> tuple[QWidget, QVBoxLayout]:
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(18, 10, 18, 10)
    layout.setSpacing(10)
    heading = QHBoxLayout()
    label = QLabel(title)
    label.setObjectName("pageTitle")
    fleuron = QLabel("❧")
    fleuron.setObjectName("fleuron")
    heading.addWidget(label)
    heading.addWidget(fleuron)
    heading.addStretch(1)
    layout.addLayout(heading)
    return page, layout


class SettingsWindow(QDialog):
    def __init__(self, controller: PetController) -> None:
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.WindowCloseButtonHint)
        self.ctrl = controller
        self.setWindowTitle("Desk Sister · 设置")
        self.setStyleSheet(STYLE.replace("{arrows}", arrow_folder()))
        self.setMinimumSize(760, 560)
        self._syncing = False

        frame = QFrame(self)
        frame.setObjectName("frame")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.addWidget(frame)
        body = QVBoxLayout(frame)
        body.setContentsMargins(10, 10, 10, 10)
        body.addWidget(BaroqueHeader(self._portrait()))
        inner = QFrame()
        inner.setObjectName("inner")
        row = QHBoxLayout(inner)
        row.setContentsMargins(10, 10, 10, 10)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.addItems(list(PAGES))
        self.nav.setFixedWidth(150)
        self.pages = QStackedWidget()
        for build in (self._general, self._backend, self._scope, self._companion, self._appearance, self._about):
            self.pages.addWidget(build())
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.setCurrentRow(0)
        row.addWidget(self.nav)
        row.addWidget(self.pages, 1)
        body.addWidget(inner, 1)
        for button in self.findChildren(QPushButton):
            # In a dialog, buttons become the Enter target by default: Enter in a number box must never clear memory.
            button.setAutoDefault(False)
            button.setDefault(False)
        self.refresh()

    def _portrait(self) -> QPixmap:
        idle = self.ctrl.window.sprites.get("idle", QPixmap())
        if idle.isNull():
            return idle
        x, y, w, h = HEAD
        return idle.copy(int(x * idle.width()), int(y * idle.height()), int(w * idle.width()), int(h * idle.height()))

    # ---- pages ---------------------------------------------------------
    def _general(self) -> QWidget:
        page, layout = _page("常规")
        self.pause_box = QCheckBox("暂停观察（Ctrl+Alt+P 也可以）")
        self.pause_box.toggled.connect(lambda on: self._apply(lambda: on != self.ctrl.config.paused and self.ctrl.toggle_pause()))
        grid = QGridLayout()
        self.interval_combo = QComboBox()
        for seconds in INTERVAL_CHOICES:
            self.interval_combo.addItem(INTERVAL_LABELS[seconds], seconds)
        self.interval_combo.currentIndexChanged.connect(
            lambda _i: self._apply(lambda: self.ctrl.set_interval(self.interval_combo.currentData())))
        self.model_combo = QComboBox()
        for model in MODEL_CHOICES:
            self.model_combo.addItem(model, model)  # labelled in refresh(), per provider
        self.model_combo.currentIndexChanged.connect(
            lambda _i: self._apply(lambda: self.ctrl.set_model(self.model_combo.currentData())))
        grid.addWidget(QLabel("评论间隔"), 0, 0)
        grid.addWidget(self.interval_combo, 0, 1)
        grid.addWidget(QLabel("模型"), 1, 0)
        grid.addWidget(self.model_combo, 1, 1)
        grid.setColumnStretch(2, 1)
        self.autostart_box = QCheckBox("开机自启")
        self.autostart_box.toggled.connect(lambda on: self._apply(lambda: self.ctrl.set_autostart(on)))
        layout.addWidget(self.pause_box)
        layout.addLayout(grid)
        layout.addWidget(self.autostart_box)
        layout.addWidget(_hint("评论间隔越短、选 Sonnet，消耗的额度越多。开机自启写在你自己的「启动」文件夹里，也可以在任务管理器里管理。"))
        layout.addStretch(1)
        return page

    def _backend(self) -> QWidget:
        page, layout = _page("调用方式")
        self.backend_group = QButtonGroup(self)
        self.backend_radios: dict[str, QRadioButton] = {}
        grid = QGridLayout()
        for index, (backend, provider) in enumerate(PROVIDERS.items()):
            radio = QRadioButton(provider.label + ("（按量付费）" if provider.paid else ""))
            self.backend_group.addButton(radio)
            radio.toggled.connect(lambda on, b=backend: on and self._apply(lambda: self.ctrl.set_backend(b)))
            grid.addWidget(radio, index // 2, index % 2)
            self.backend_radios[backend] = radio
        layout.addLayout(grid)
        detail = QFrame()
        detail.setObjectName("inner")
        box = QVBoxLayout(detail)
        box.setContentsMargins(12, 10, 12, 10)
        self.backend_note = _hint("")
        self.key_status = QLabel()
        keys = QHBoxLayout()
        self.set_key_button = QPushButton("设置 API Key…")
        self.set_key_button.clicked.connect(lambda: self._apply(self.ctrl.set_api_key))
        self.clear_key_button = QPushButton("清除已保存的 Key")
        self.clear_key_button.setObjectName("quiet")
        self.clear_key_button.clicked.connect(lambda: self._apply(self.ctrl.clear_api_key))
        self.key_link = QLabel()
        self.key_link.setOpenExternalLinks(True)
        keys.addWidget(self.set_key_button)
        keys.addWidget(self.clear_key_button)
        keys.addWidget(self.key_link)
        keys.addStretch(1)
        model_row = QHBoxLayout()
        self.custom_model = QLineEdit()
        self.custom_model.setMaxLength(100)
        apply_model = QPushButton("使用这个模型")
        apply_model.setObjectName("quiet")
        apply_model.clicked.connect(self._apply_custom_model)
        self.custom_model.returnPressed.connect(self._apply_custom_model)
        model_row.addWidget(QLabel("自定义模型名"))
        model_row.addWidget(self.custom_model, 1)
        model_row.addWidget(apply_model)
        box.addWidget(self.backend_note)
        box.addWidget(self.key_status)
        box.addLayout(keys)
        box.addLayout(model_row)
        box.addWidget(_hint("留空就用「常规」页选的「快速省钱 / 更聪明」预设。模型改名或下线时，在这里填新的名字即可。"))
        layout.addWidget(detail)
        layout.addWidget(_hint("Key 只保存在本机的 Windows 凭据管理器里，不会写进配置文件、日志或这个窗口。"
                               "用订阅额度运行第三方程序，以 Anthropic / OpenAI 的现行条款为准。"))
        layout.addStretch(1)
        return page

    def _apply_custom_model(self) -> None:
        backend = self.ctrl.config.backend
        self._apply(lambda: self.ctrl.set_custom_model(backend, self.custom_model.text()))

    @staticmethod
    def _backend_note(provider) -> str:
        if provider.kind == CODEX_CLI:
            return ("用本机已登录 ChatGPT 的 Codex CLI，不花 API 费用；Codex 的命令、浏览器等工具都会被关闭。"
                    "截图会短暂写入你自己的临时文件夹，调用结束后删除（被占用时会反复重试，直到删掉）。")
        if provider.kind == CLAUDE_CLI:
            return "用本机已登录 Claude 订阅的 Claude Code，不花 API 费用；截图只在内存里。"
        return (f"用你自己的 {provider.company} API Key，按量计费，截图会发给 {provider.company}；截图只在内存里。")

    def _rules_editor(self, kind: str, placeholder: str) -> tuple[QWidget, QListWidget]:
        box = QWidget()
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        rules = QListWidget()
        rules.setObjectName("rules")
        rules.setMinimumHeight(110)
        entry = QLineEdit()
        entry.setPlaceholderText(placeholder)
        add = QPushButton("添加")
        remove = QPushButton("删除选中")
        remove.setObjectName("quiet")

        def current() -> list[str]:
            return [rules.item(i).text() for i in range(rules.count())]

        def add_rule() -> None:
            text = entry.text().strip()
            if text and text.casefold() not in {r.casefold() for r in current()}:
                self._apply(lambda: self.ctrl.set_rules(kind, current() + [text]))
            entry.clear()

        def remove_rule() -> None:
            chosen = {item.text() for item in rules.selectedItems()}
            if chosen:
                self._apply(lambda: self.ctrl.set_rules(kind, [r for r in current() if r not in chosen]))

        add.clicked.connect(add_rule)
        entry.returnPressed.connect(add_rule)
        remove.clicked.connect(remove_rule)
        controls = QHBoxLayout()
        controls.addWidget(entry, 1)
        controls.addWidget(add)
        controls.addWidget(remove)
        column.addWidget(rules)
        column.addLayout(controls)
        return box, rules

    def _scope(self) -> QWidget:
        page, layout = _page("观察范围")
        self.scope_group = QButtonGroup(self)
        self.blocklist_radio = QRadioButton("除黑名单外都看（默认）")
        self.allowlist_radio = QRadioButton("只看白名单里的程序")
        self.scope_group.addButton(self.blocklist_radio)
        self.scope_group.addButton(self.allowlist_radio)
        self.blocklist_radio.toggled.connect(lambda on: on and self._apply(lambda: self.ctrl.set_watch_mode("blocklist")))
        self.allowlist_radio.toggled.connect(lambda on: on and self._apply(lambda: self.ctrl.set_watch_mode("allowlist")))
        modes = QHBoxLayout()
        modes.addWidget(self.blocklist_radio)
        modes.addWidget(self.allowlist_radio)
        modes.addStretch(1)
        block_box, self.blocklist_view = self._rules_editor("blocklist", "关键词")
        allow_box, self.allowlist_view = self._rules_editor("allowlist", "程序名")
        lists = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("黑名单（命中就不截图，任何模式下都生效）"))
        left.addWidget(block_box)
        right = QVBoxLayout()
        right.addWidget(QLabel("白名单"))
        right.addWidget(allow_box)
        lists.addLayout(left)
        lists.addLayout(right)
        rules_hint = _hint("黑名单关键词同时匹配窗口标题和程序名，如 bank、微信。白名单默认按程序名匹配，如 code.exe；"
                           "想按窗口标题匹配，写 title:*关键词*。")
        self.quiet_box = QCheckBox("全屏游戏、视频、幻灯片时不看也不说")
        self.quiet_box.toggled.connect(lambda on: self._apply(lambda: self.ctrl.set_quiet_fullscreen(on)))
        dwell = QHBoxLayout()
        self.dwell_spin = QSpinBox()
        self.dwell_spin.setRange(0, 600)
        self.dwell_spin.setKeyboardTracking(False)  # apply when typing is done, not on every digit
        self.dwell_spin.setSuffix(" 秒")
        self.dwell_spin.valueChanged.connect(lambda v: self._apply(lambda: self.ctrl.set_dwell(v)))
        dwell.addWidget(QLabel("同一个窗口停留多久后才自动评论"))
        dwell.addWidget(self.dwell_spin)
        dwell.addStretch(1)
        layout.addLayout(modes)
        layout.addLayout(lists)
        layout.addWidget(rules_hint)
        layout.addWidget(self.quiet_box)
        layout.addLayout(dwell)
        layout.addStretch(1)
        return page

    def _companion(self) -> QWidget:
        page, layout = _page("陪伴")
        self.self_talk_box = QCheckBox("自言自语（本地台词，不调用模型、不花钱）")
        self.self_talk_box.toggled.connect(lambda on: self._apply(lambda: self.ctrl.set_self_talk(on)))
        talk = QHBoxLayout()
        self.talk_min = QSpinBox()
        self.talk_min.setRange(1, 60)
        self.talk_max = QSpinBox()
        self.talk_max.setRange(1, 120)
        for spin in (self.talk_min, self.talk_max):
            spin.setSuffix(" 分钟")
            spin.setKeyboardTracking(False)  # typing "20" must not apply "2" first
        # Each end changes only itself: the other keeps its exact seconds from the config.
        set_min = lambda v: self._apply(lambda: self.ctrl.set_self_talk_range(v * 60, self.ctrl.config.self_talk_max_sec))  # noqa: E731
        set_max = lambda v: self._apply(lambda: self.ctrl.set_self_talk_range(self.ctrl.config.self_talk_min_sec, v * 60))  # noqa: E731
        self._minutes_box(self.talk_min, set_min)
        self._minutes_box(self.talk_max, set_max)
        talk.addWidget(QLabel("每隔"))
        talk.addWidget(self.talk_min)
        talk.addWidget(QLabel("到"))
        talk.addWidget(self.talk_max)
        talk.addWidget(QLabel("说一句"))
        talk.addStretch(1)
        self.memory_box = QCheckBox("陪伴记忆：记住主人在用的程序和活动类别（不存窗口标题和截图）")
        self.memory_box.toggled.connect(lambda on: self._apply(lambda: self.ctrl.set_companion_memory(on)))
        forget = QPushButton("清空陪伴记忆")
        forget.setObjectName("quiet")
        forget.clicked.connect(lambda: self._apply(self.ctrl.clear_companion_memory))
        self.link_box = QCheckBox(LINK_LABEL)
        self.link_box.toggled.connect(lambda on: self._apply(lambda: on != self.ctrl.config.claude_link and self.ctrl.set_claude_link(on)))
        sleep = QHBoxLayout()
        self.sleep_spin = QSpinBox()
        self.sleep_spin.setRange(1, 1440)  # the config allows up to a day
        self.sleep_spin.setKeyboardTracking(False)
        self.sleep_spin.setSuffix(" 分钟")
        self._minutes_box(self.sleep_spin, lambda v: self._apply(lambda: self.ctrl.set_sleep_after(v * 60)))
        sleep.addWidget(QLabel("主人离开键盘鼠标多久后她会睡着"))
        sleep.addWidget(self.sleep_spin)
        sleep.addStretch(1)
        birth = QHBoxLayout()
        self.birthday_box = QCheckBox("生日祝福")
        self.birth_month = QSpinBox()
        self.birth_month.setRange(1, 12)
        self.birth_month.setSuffix(" 月")
        self.birth_day = QSpinBox()
        self.birth_day.setRange(1, 31)
        self.birth_day.setSuffix(" 日")
        for spin in (self.birth_month, self.birth_day):
            spin.setKeyboardTracking(False)
            spin.valueChanged.connect(lambda _v: self._apply_birthday())
        self.birthday_box.toggled.connect(lambda _on: self._apply_birthday())
        birth.addWidget(self.birthday_box)
        birth.addWidget(self.birth_month)
        birth.addWidget(self.birth_day)
        birth.addStretch(1)
        night = QHBoxLayout()
        self.bedtime_combo = QComboBox()
        for mode in BEDTIME_MODES:
            self.bedtime_combo.addItem(BEDTIME_LABELS[mode], mode)
        self.bedtime_combo.currentIndexChanged.connect(
            lambda _i: self._apply(lambda: self.ctrl.set_bedtime_reminder(self.bedtime_combo.currentData())))
        self.night_combo = QComboBox()
        for hour in NIGHT_STARTS:
            self.night_combo.addItem(f"{hour}:00", hour)
        self.night_combo.currentIndexChanged.connect(
            lambda _i: self._apply(lambda: self.ctrl.set_night_start(self.night_combo.currentData())))
        night.addWidget(QLabel("深夜提醒休息"))
        night.addWidget(self.bedtime_combo)
        night.addWidget(QLabel("几点算深夜"))
        night.addWidget(self.night_combo)
        night.addStretch(1)
        memory_row = QHBoxLayout()
        memory_row.addWidget(self.memory_box, 1)
        memory_row.addWidget(forget)
        layout.addWidget(self.self_talk_box)
        layout.addLayout(talk)
        layout.addLayout(memory_row)
        layout.addWidget(self.link_box)
        layout.addLayout(sleep)
        layout.addLayout(night)
        layout.addLayout(birth)
        layout.addWidget(_hint("每天第一次见到主人时她会打个招呼；节日和主人生日那天会换成祝福。"))
        layout.addWidget(_hint("深夜指从这个时间到早上 5 点。看屏幕的评论和自言自语共用这个次数，提过一次就等下一晚（或 2 小时后）。"))
        layout.addStretch(1)
        return page

    def _appearance(self) -> QWidget:
        page, layout = _page("外观")
        size = QHBoxLayout()
        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(100, 600)  # the same limits the config enforces
        self.size_slider.setSingleStep(10)
        self.size_slider.setPageStep(20)
        self.size_value = QLabel()
        self.size_slider.valueChanged.connect(lambda v: self.size_value.setText(f"{v} 像素"))
        self.size_slider.sliderReleased.connect(lambda: self._apply(lambda: self.ctrl.set_sprite_height(self.size_slider.value())))
        self.size_slider.actionTriggered.connect(lambda _a: None if self.size_slider.isSliderDown() else self._apply(
            lambda: self.ctrl.set_sprite_height(self.size_slider.sliderPosition())))
        size.addWidget(QLabel("她的身高"))
        size.addWidget(self.size_slider, 1)
        size.addWidget(self.size_value)
        layout.addLayout(size)
        layout.addWidget(_hint("调整后立即生效，她的脚站在原来的位置。也可以把鼠标放在她身上，按住 Ctrl 滚动滚轮来调。"))
        face = QHBoxLayout()
        self.blink_combo = QComboBox()
        for rate in BLINK_CHOICES:
            self.blink_combo.addItem(BLINK_LABELS[rate], rate)
        self.blink_combo.currentIndexChanged.connect(
            lambda _i: self._apply(lambda: self.ctrl.set_blink(self.blink_combo.currentData())))
        self.mouth_box = QCheckBox("说话时动嘴")
        self.mouth_box.toggled.connect(lambda on: self._apply(lambda: self.ctrl.set_talk_mouth(on)))
        face.addWidget(QLabel("眨眼"))
        face.addWidget(self.blink_combo)
        face.addSpacing(16)
        face.addWidget(self.mouth_box)
        self.head_box = QCheckBox("头部小动作")
        self.head_box.toggled.connect(lambda on: self._apply(lambda: self.ctrl.set_head_motion(on)))
        face.addSpacing(16)
        face.addWidget(self.head_box)
        face.addStretch(1)
        layout.addLayout(face)
        self.walking_box = QCheckBox("沿屏幕底部溜达")
        self.walking_box.toggled.connect(lambda on: self._apply(lambda: self.ctrl.set_walking(on)))
        layout.addWidget(self.walking_box)
        layout.addWidget(_hint("站在屏幕最下面（任务栏上方）时，她隔一会儿会左右走几步。说话、睡觉、全屏免打扰或暂停时不走；"
                               "开着时从任何高度松手她都会掉到底部；想把她放在屏幕别处，先关掉溜达。"))
        layout.addStretch(1)
        return page

    def _about(self) -> QWidget:
        page, layout = _page("关于")
        text = QLabel(
            f"<p style='font-size:12pt'><b>Desk Sister</b> {__version__}</p>"
            "<p>非官方粉丝作品，与 Anthropic 无任何关联。</p>"
            "<p>代码：MIT 许可。角色立绘与图标：参考 B 站 UP 主 <b>ZipZipPipe</b> 的原设（BV1tE9XBbErS）用 AI 生成，"
            "经原作者同意<b>仅限非商业使用</b>。人设参考 leto0309/ai-girl-desktop-pet-prompts 中的 Claude 角色卡。</p>"
            "<p>隐私：她只看当前前台窗口，截图不写日志；黑名单里的窗口不截图；Ctrl+Alt+P 随时暂停。"
            "截图只在内存中处理——唯一的例外是 Codex 模式：Codex CLI 只能从文件读图，截图会短暂写入你自己的临时文件夹，"
            "调用结束后删除（文件被占用时稍后重试）。</p>"
            "<p><a style='color:#B5531F' href='https://github.com/leto0309/desk-sister'>github.com/leto0309/desk-sister</a></p>")
        text.setWordWrap(True)
        text.setOpenExternalLinks(True)
        text.setTextFormat(Qt.TextFormat.RichText)
        logs = QPushButton("打开日志文件夹")
        logs.setObjectName("quiet")
        logs.clicked.connect(self.ctrl.open_log_folder)
        row = QHBoxLayout()
        row.addWidget(logs)
        row.addStretch(1)
        layout.addWidget(text)
        layout.addLayout(row)
        layout.addStretch(1)
        return page

    def _apply_birthday(self) -> None:
        month = self.birth_month.value()
        day = min(self.birth_day.value(), calendar.monthrange(2028, month)[1])  # 2 月 31 日 → 29 日 (leap year)
        self._apply(lambda: self.ctrl.set_birthday(month, day, self.birthday_box.isChecked()))

    # ---- sync ------------------------------------------------------------
    def _apply(self, action) -> None:
        """Run a controller setter for a user change, then read everything back (setters may refuse)."""
        if self._syncing:
            return
        action()
        self.refresh()

    @staticmethod
    def _minutes_box(spin: QSpinBox, commit) -> None:
        """A box in whole minutes over a setting kept in seconds. Arrows apply at once; typed text applies
        when typing ends even if the shown number did not change (30 s shows as 1 min: typing 1 means 60 s)."""
        typed: list[str | None] = [None]  # text typed and not committed yet

        def changed(value: int) -> None:
            typed[0] = None  # this value is now committed; Enter must not commit the refreshed number again
            commit(value)

        spin.valueChanged.connect(changed)
        spin.lineEdit().textEdited.connect(lambda text: typed.__setitem__(0, text))

        def finished() -> None:
            text, typed[0] = typed[0], None
            digits = "".join(ch for ch in (text or "") if ch.isdigit())
            # Only the number the user really typed: when Qt put the old value back (empty, 0, out of range),
            # the shown number is not a choice and must not be saved.
            if digits and int(digits) == spin.value():
                commit(spin.value())

        spin.editingFinished.connect(finished)

    @staticmethod
    def _show_value(spin: QSpinBox, value: int) -> None:
        """Leave a box alone when its committed value is already right, so half-typed text survives a sync."""
        if spin.value() != value:
            spin.setValue(value)

    def refresh(self) -> None:
        """Show the current config; signals are muted so this never applies anything."""
        cfg = self.ctrl.config
        self._syncing = True
        try:
            self.pause_box.setChecked(cfg.paused)
            self.interval_combo.setCurrentIndex(max(0, self.interval_combo.findData(cfg.interval_sec)))
            provider = PROVIDERS.get(cfg.backend, PROVIDERS["subscription"])
            for index in range(self.model_combo.count()):
                self.model_combo.setItemText(index, model_label(provider, self.model_combo.itemData(index)))
            self.model_combo.setCurrentIndex(max(0, self.model_combo.findData(cfg.model)))
            self.autostart_box.setChecked(self.ctrl.autostart_on)
            self.autostart_box.setEnabled(self.ctrl.autostart_enabled)
            self.autostart_box.setText(self.ctrl.autostart_text)
            self.backend_radios.get(cfg.backend, self.backend_radios["subscription"]).setChecked(True)
            self.backend_note.setText(self._backend_note(provider))
            if provider.needs_key:
                saved = self.ctrl._has_key(provider.id)
                self.key_status.setText(f"{provider.company} API Key：" + ("已保存（在 Windows 凭据管理器里）" if saved else "还没有保存"))
                self.key_link.setText(f"<a style='color:#B5531F' href='{provider.key_page}'>去哪里申请 Key</a>")
            else:
                self.key_status.setText("这个方式用订阅登录，不需要 API Key。")
                self.key_link.setText("")
            self.set_key_button.setEnabled(provider.needs_key)
            self.clear_key_button.setEnabled(provider.needs_key)
            custom = cfg.custom_models.get(provider.id, "")
            if not self.custom_model.hasFocus() or self.custom_model.text() == custom:
                self.custom_model.setText(custom)
            presets = "、".join(m for m in dict.fromkeys(provider.presets.values()) if m) or "账号默认模型"
            self.custom_model.setPlaceholderText(f"留空使用预设：{presets}")
            self.blocklist_radio.setChecked(cfg.watch_mode == "blocklist")
            self.allowlist_radio.setChecked(cfg.watch_mode == "allowlist")
            for view, rules in ((self.blocklist_view, cfg.blocklist), (self.allowlist_view, cfg.allowlist)):
                if [view.item(i).text() for i in range(view.count())] != rules:
                    view.clear()
                    view.addItems(rules)
            self.quiet_box.setChecked(cfg.quiet_fullscreen)
            self._show_value(self.dwell_spin, cfg.dwell_sec)
            self.self_talk_box.setChecked(cfg.self_talk)
            self._show_value(self.talk_min, max(1, round(cfg.self_talk_min_sec / 60)))
            self._show_value(self.talk_max, max(1, round(cfg.self_talk_max_sec / 60)))
            for spin in (self.talk_min, self.talk_max):
                spin.setEnabled(cfg.self_talk)
            self.memory_box.setChecked(cfg.companion_memory)
            self.link_box.setChecked(cfg.claude_link)
            self.link_box.setText(LINK_LABEL + ("（hook 未找到或 settings.json 异常）" if self.ctrl.claude_link_broken() else ""))
            birthday = cfg.birthday
            self.birthday_box.setChecked(bool(birthday))
            if birthday:
                self._show_value(self.birth_month, int(birthday[:2]))
                self._show_value(self.birth_day, int(birthday[3:]))
            for spin in (self.birth_month, self.birth_day):
                spin.setEnabled(bool(birthday))
            self.bedtime_combo.setCurrentIndex(max(0, self.bedtime_combo.findData(cfg.bedtime_reminder)))
            self.night_combo.setCurrentIndex(max(0, self.night_combo.findData(cfg.night_start_hour)))
            self._show_value(self.sleep_spin, max(1, round(cfg.sleep_after_sec / 60)))
            self.walking_box.setChecked(cfg.walking)
            self.blink_combo.setCurrentIndex(max(0, self.blink_combo.findData(cfg.blink)))
            self.mouth_box.setChecked(cfg.talk_mouth)
            self.head_box.setChecked(cfg.head_motion)
            if not self.size_slider.isSliderDown():  # a drag in progress is the user's, not the config's
                self.size_slider.setValue(cfg.sprite_height)
                self.size_value.setText(f"{cfg.sprite_height} 像素")
        finally:
            self._syncing = False
