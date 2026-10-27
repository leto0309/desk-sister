"""The settings window: an elegant Baroque frame in Claude 娘's orange and white, with gold ornaments.

Every control applies at once through the controller's own setters (the same ones the menu and the hotkey
use), and `refresh()` reads everything back from the config, so the window and the pet never disagree.
"""
from __future__ import annotations

import calendar
import html
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QPlainTextEdit, QPushButton, QRadioButton, QSlider, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from .i18n import N_, english, tr
from . import __version__
from .updates import RELEASES_PAGE
from .bedtime import MODE_LABELS as BEDTIME_LABELS
from .bedtime import MODES as BEDTIME_MODES
from .bedtime import NIGHT_STARTS
from .config import BLINK_CHOICES, INTERVAL_CHOICES, MODEL_CHOICES
from .persona import SUMMARY_HOURS
from .timers import BREAK_RANGE, FOCUS_RANGE
from . import characters
from .characters import DEFAULT as DEFAULT_CHARACTER
from .characters import Theme
from .voice import STYLE_NAMES as VOICE_STYLE_NAMES
from .voice import CHOICES as VOICE_STYLES  # her own voice first, then the shared styles
from .providers import CLAUDE_CLI, CODEX_CLI, PROVIDERS, model_label

if TYPE_CHECKING:
    from .controller import PetController

LINK_LABEL = N_("Claude Code 联动（会先征得同意，再修改 ~/.claude/settings.json）")
BLINK_LABELS = {"off": N_("关闭"), "few": N_("少"), "normal": N_("正常"), "often": N_("多")}

# Each girl has her own colours (characters.Theme); the Baroque frame, serif titles and flourishes stay.
SERIF = '"Noto Serif SC", "Source Han Serif SC", "SimSun", "Georgia", serif'
SANS = '"Microsoft YaHei UI", "Microsoft YaHei", sans-serif'

INTERVAL_LABELS = {30: N_("30 秒"), 60: N_("1 分钟"), 90: N_("90 秒"), 120: N_("2 分钟"), 300: N_("5 分钟"), 600: N_("10 分钟")}
UPDATE_BUTTON = {"downloading": N_("取消下载"), "ready": N_("重启并更新")}
PAGES = (N_("常规"), N_("角色"), N_("调用方式"), N_("观察范围"), N_("陪伴"), N_("外观"), N_("关于"))
MOTTOS = {  # the header's subtitle for each girl
    "claude": N_("Anthropic 家族的长女，为主人整理一切"),
    "deepseek": N_("抱着饭盆的小机灵鬼，开饭和干活都积极"),
    "gpt": N_("长着龙角龙翼的领队：这件事交给我"),
    "gemini": N_("好奇心满满的猫娘，怪东西也很可爱"),
    "qwen": N_("执扇的生活搭档，先挑最值得做的事"),
    "glm": N_("温和的狐耳女仆：我这里还有，你也来一点"),
}
LINK_COLOR = "#B5531F"  # the colour links are written with; shown in the current girl's deep colour

def stylesheet(t: Theme, arrows: str) -> str:
    """The settings window's look in one girl's colours."""
    return f"""
QDialog {{ background: {t.ivory}; }}
QWidget {{ color: {t.ink}; font-family: {SANS}; font-size: 10pt; }}
QFrame#frame {{ background: {t.ivory}; border: 2px solid {t.gold}; border-radius: 14px; }}
QFrame#inner {{ background: transparent; border: 1px solid {t.peach}; border-radius: 10px; }}
QLabel#pageTitle {{ font-family: {SERIF}; font-size: 15pt; color: {t.deep}; font-weight: bold; }}
QLabel#hint {{ color: {t.hint}; font-size: 9pt; }}
QLabel#fleuron {{ color: {t.gold}; font-size: 13pt; }}
QListWidget#nav {{ background: {t.cream}; border: 1px solid {t.gold}; border-radius: 10px; padding: 6px;
                   font-family: {SERIF}; font-size: 11pt; outline: none; }}
QListWidget#nav::item {{ padding: 9px 14px; margin: 2px 0; border-radius: 8px; color: {t.ink}; }}
QListWidget#nav::item:hover {{ background: {t.peach}; }}
QListWidget#nav::item:selected {{ color: white; border-left: 3px solid {t.gold};
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {t.deep}, stop:1 {t.main}); }}
QPushButton {{ color: white; border: 1px solid {t.deep}; border-radius: 13px; padding: 6px 16px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {t.light}, stop:1 {t.deep}); }}
QPushButton:hover {{ background: {t.main}; }}
QPushButton:disabled {{ background: {t.disabled}; border-color: {t.disabled}; }}
QPushButton#quiet {{ color: {t.deep}; background: {t.ivory}; border: 1px solid {t.main}; }}
QPushButton#quiet:hover {{ background: {t.cream}; }}
QPushButton#quiet:disabled {{ color: {t.disabled}; border-color: {t.disabled}; background: {t.ivory}; }}
QComboBox, QSpinBox, QLineEdit, QPlainTextEdit {{ background: white; border: 1px solid {t.gold}; border-radius: 6px;
    padding: 4px 8px; }}
QComboBox:focus, QSpinBox:focus, QLineEdit:focus, QPlainTextEdit:focus {{ border: 1px solid {t.main}; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 22px; border: none; }}
QComboBox::down-arrow {{ image: url("{arrows}/down.png"); width: 10px; height: 6px; }}
QComboBox QAbstractItemView {{ background: white; border: 1px solid {t.gold}; selection-background-color: {t.peach};
    selection-color: {t.ink}; outline: none; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 18px; border: none; background: transparent; }}
QSpinBox::up-arrow {{ image: url("{arrows}/up.png"); width: 9px; height: 5px; }}
QSpinBox::down-arrow {{ image: url("{arrows}/down.png"); width: 9px; height: 5px; }}
QListWidget#rules {{ background: white; border: 1px solid {t.gold}; border-radius: 6px; }}
QListWidget#rules::item:selected {{ background: {t.peach}; color: {t.ink}; }}
QCheckBox, QRadioButton {{ spacing: 8px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 15px; height: 15px; border: 1px solid {t.gold}; background: white; }}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{ background: {t.main}; border: 1px solid {t.deep}; }}
QSlider::groove:horizontal {{ height: 6px; background: {t.peach}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {t.main}; border-radius: 3px; }}
QSlider::handle:horizontal {{ width: 16px; margin: -6px 0; border-radius: 8px; background: white; border: 2px solid {t.gold}; }}
"""


def arrow_folder(color: str) -> str:
    """Small arrows in `color` for combo and spin boxes (style sheets need image files), drawn once per colour."""
    folder = Path(tempfile.gettempdir()) / "desk-sister-ui" / color.lstrip("#").lower()
    folder.mkdir(parents=True, exist_ok=True)
    for name, points in (("down", [(1, 2), (19, 2), (10, 11)]), ("up", [(1, 11), (19, 11), (10, 2)])):
        target = folder / f"{name}.png"
        if target.exists():
            continue
        image = QPixmap(20, 13)
        image.fill(Qt.GlobalColor.transparent)
        p = QPainter(image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
        p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in points]))
        p.end()
        image.save(str(target))
    return folder.as_posix()


class BaroqueHeader(QWidget):
    """Her face in a gold cameo, the title in serif type, and symmetric scroll flourishes."""

    def __init__(self, portrait: QPixmap, theme: Theme, motto: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.portrait, self.theme, self.motto = portrait, theme, motto
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
        t = self.theme
        band = QLinearGradient(0, 0, 0, self.height())
        band.setColorAt(0, QColor(t.cream))
        band.setColorAt(1, QColor(t.ivory))
        p.fillRect(self.rect(), band)
        gold = QPen(QColor(t.gold), 1.6)
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
        p.fillRect(oval, QColor(t.ivory))
        if not self.portrait.isNull():
            face = self.portrait.scaled(int(oval.width()), int(oval.height()), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                        Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(int(cx - face.width() / 2), int(cy - face.height() / 2), face)
        p.restore()
        p.setPen(QPen(QColor(t.gold), 3))
        p.drawEllipse(oval.adjusted(3, 3, -3, -3))
        p.setPen(QPen(QColor(t.deep), 1))
        p.drawEllipse(oval)
        # title
        p.setPen(QColor(t.deep))
        title = QFont("Noto Serif SC")
        title.setFamilies(["Noto Serif SC", "Source Han Serif SC", "SimSun", "Georgia"])
        title.setPointSize(20)
        title.setBold(True)
        p.setFont(title)
        text_rect = QRectF(120, 18, w - 140, 44)
        p.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, tr("Desk Sister · 设置"))
        sub = QFont(title)
        sub.setPointSize(10)
        sub.setBold(False)
        p.setFont(sub)
        p.setPen(QColor(t.hint))
        p.drawText(QRectF(120, 60, w - 140, 22), Qt.AlignmentFlag.AlignCenter, self.motto)
        # flourishes either side of a fleuron, under the subtitle
        mid = 120 + (w - 140) / 2
        flourish = QPainterPath()
        self._scroll(flourish, mid - 14, 92, -1)
        self._scroll(flourish, mid + 14, 92, 1)
        p.setPen(QPen(QColor(t.gold), 1.4))
        p.drawPath(flourish)
        p.setPen(QColor(t.main))
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
        self.setWindowTitle(tr("Desk Sister · 设置"))
        self._themed = ""  # the girl whose look the window has now
        self.setMinimumSize(760, 560)
        self._syncing = False

        frame = QFrame(self)
        frame.setObjectName("frame")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.addWidget(frame)
        body = QVBoxLayout(frame)
        body.setContentsMargins(10, 10, 10, 10)
        self.header = BaroqueHeader(QPixmap(), characters.get(DEFAULT_CHARACTER).theme, "")
        body.addWidget(self.header)
        inner = QFrame()
        inner.setObjectName("inner")
        row = QHBoxLayout(inner)
        row.setContentsMargins(10, 10, 10, 10)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.addItems([tr(page) for page in PAGES])
        self.nav.setFixedWidth(150)
        self.pages = QStackedWidget()
        for build in (self._general, self._character, self._backend, self._scope, self._companion, self._appearance,
                      self._about):
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

    def _theme(self) -> None:
        """Dress the window in the current girl's colours, with her face and words in the header."""
        character = characters.get(self.ctrl.config.character)
        if self._themed == character.id:
            return
        self._themed = character.id
        theme = character.theme
        self.setStyleSheet(stylesheet(theme, arrow_folder(theme.deep)))
        self.header.portrait, self.header.theme = self._portrait(), theme
        self.header.motto = tr(MOTTOS.get(character.id, MOTTOS[DEFAULT_CHARACTER]))
        self.header.update()
        self.about_label.setText(self._link(self._about_text()))

    @staticmethod
    def _about_text() -> str:
        return tr("<p style='font-size:12pt'><b>Desk Sister</b> {0}</p><p>非官方粉丝作品，与 Anthropic、OpenAI、DeepSeek、Google、阿里云、智谱等公司无任何关联。</p><p>代码：MIT 许可。角色立绘与图标：参考 B 站 UP 主 <b>ZipZipPipe</b> 的原设用 AI 生成，经原作者同意<b>仅限非商业使用</b>。默认人设来自 leto0309/ai-girl-desktop-pet-prompts（根据 B 站 UP 主冬冰的《五个 AI 玩我的世界》系列归纳）。</p><p>隐私：她只看当前前台窗口，截图不写日志；黑名单里的窗口不截图；Ctrl+Alt+P 随时暂停。截图只在内存中处理——唯一的例外是 Codex 模式：Codex CLI 只能从文件读图，截图会短暂写入你自己的临时文件夹，调用结束后删除（文件被占用时稍后重试）。</p><p><a style='color:#B5531F' href='https://github.com/leto0309/desk-sister'>github.com/leto0309/desk-sister</a></p>", __version__)

    def _link(self, html: str) -> str:
        return html.replace(LINK_COLOR, characters.get(self.ctrl.config.character).theme.deep)

    def _portrait(self) -> QPixmap:
        idle = self.ctrl.window.sprites.get("idle", QPixmap())
        if idle.isNull():
            return idle
        x, y, w, h = characters.get(self.ctrl.config.character).head
        return idle.copy(int(x * idle.width()), int(y * idle.height()), int(w * idle.width()), int(h * idle.height()))

    # ---- pages ---------------------------------------------------------
    def _general(self) -> QWidget:
        page, layout = _page(tr("常规"))
        self.pause_box = QCheckBox(tr("暂停观察（Ctrl+Alt+P 也可以）"))
        self.pause_box.toggled.connect(lambda on: self._apply(lambda: on != self.ctrl.config.paused and self.ctrl.toggle_pause()))
        grid = QGridLayout()
        self.interval_combo = QComboBox()
        for seconds in INTERVAL_CHOICES:
            self.interval_combo.addItem(tr(INTERVAL_LABELS[seconds]), seconds)
        self.interval_combo.currentIndexChanged.connect(
            lambda _i: self._apply(lambda: self.ctrl.set_interval(self.interval_combo.currentData())))
        self.model_combo = QComboBox()
        for model in MODEL_CHOICES:
            self.model_combo.addItem(model, model)  # labelled in refresh(), per provider
        self.model_combo.currentIndexChanged.connect(
            lambda _i: self._apply(lambda: self.ctrl.set_model(self.model_combo.currentData())))
        grid.addWidget(QLabel(tr("评论间隔")), 0, 0)
        grid.addWidget(self.interval_combo, 0, 1)
        grid.addWidget(QLabel(tr("模型")), 1, 0)
        grid.addWidget(self.model_combo, 1, 1)
        grid.setColumnStretch(2, 1)
        self.language_combo = QComboBox()
        for choice, name in (("", tr("跟随系统")), ("zh", "中文"), ("en", "English")):
            self.language_combo.addItem(name, choice)
        self.language_combo.currentIndexChanged.connect(
            lambda _i: self._apply(lambda: self.ctrl.set_language(self.language_combo.currentData())))
        grid.addWidget(QLabel(tr("语言 / Language")), 2, 0)
        grid.addWidget(self.language_combo, 2, 1)
        self.autostart_box = QCheckBox(tr("开机自启"))
        self.autostart_box.toggled.connect(lambda on: self._apply(lambda: self.ctrl.set_autostart(on)))
        layout.addWidget(self.pause_box)
        layout.addLayout(grid)
        layout.addWidget(self.autostart_box)
        layout.addWidget(_hint(tr("评论间隔越短、选 Sonnet，消耗的额度越多。开机自启写在你自己的「启动」文件夹里，也可以在任务管理器里管理。")))
        layout.addStretch(1)
        return page

    def _character(self) -> QWidget:
        page, layout = _page(tr("角色"))
        grid = QGridLayout()
        self.character_combo = QComboBox()
        for character in characters.CHARACTERS.values():
            self.character_combo.addItem(tr(character.name), character.id)
        self.character_combo.currentIndexChanged.connect(
            lambda _i: self._apply(lambda: self.ctrl.set_character(self.character_combo.currentData())))
        self.address_edit = QLineEdit()
        self.address_edit.setMaxLength(characters.MAX_ADDRESS)
        self.address_edit.setPlaceholderText(characters.DEFAULT_ADDRESS)
        self.address_edit.editingFinished.connect(lambda: self._apply(lambda: self.ctrl.set_address(self.address_edit.text())))
        grid.addWidget(QLabel(tr("陪着你的是")), 0, 0)
        grid.addWidget(self.character_combo, 0, 1)
        grid.addWidget(QLabel(tr("她怎么称呼你")), 1, 0)
        grid.addWidget(self.address_edit, 1, 1)
        grid.setColumnStretch(2, 1)
        layout.addLayout(grid)
        layout.addWidget(_hint(tr("默认称呼「主人」，提示词和本地台词都会用你填的称呼。")))
        self.persona_label = QLabel()
        layout.addWidget(self.persona_label)
        self.persona_edit = QPlainTextEdit()
        self.persona_edit.setMinimumHeight(90)
        self.persona_edit.textChanged.connect(self._persona_edited)
        layout.addWidget(self.persona_edit, 1)
        buttons = QHBoxLayout()
        self.persona_save = QPushButton(tr("保存人设"))
        self.persona_save.clicked.connect(self._save_persona)
        self.persona_reset = QPushButton(tr("恢复默认"))
        self.persona_reset.setObjectName("quiet")
        self.persona_reset.clicked.connect(self._reset_persona)
        self.persona_state = _hint("")
        buttons.addWidget(self.persona_save)
        buttons.addWidget(self.persona_reset)
        buttons.addWidget(self.persona_state, 1)
        layout.addLayout(buttons)
        layout.addWidget(_hint(tr("这里只写人设；看截图的任务、回复格式和隐私规则会自动接在后面。人设里要求的其他格式不会显示成乱码。中文和英文各存一份。")))
        self._persona_shown: tuple[str, bool] | None = None  # (girl, English) the editor holds
        self._drafts = self.ctrl.persona_drafts  # unsaved edits of girls not shown now (outlive this window)
        return page

    def keep_draft(self) -> None:
        """Before this window goes (say, rebuilt in another language): what is typed here is kept."""
        if self.persona_save.isEnabled() and self._persona_shown is not None:
            self._drafts[self._persona_shown] = self.persona_edit.toPlainText()

    def _persona_edited(self) -> None:
        if not self._syncing:
            self._mark_edited()

    def _mark_edited(self) -> None:
        """The editor holds text that is not saved: it can be saved (if not too long) or thrown away."""
        self.persona_save.setEnabled(True)
        self.persona_reset.setEnabled(True)  # an unsaved edit can be thrown away too
        length = len(self.persona_edit.toPlainText().strip())
        self.persona_state.setText(tr("（有未保存的修改）") if length <= characters.MAX_PERSONA else
                                   tr("（太长了：{0} / {1} 字，保存不了）", length, characters.MAX_PERSONA))

    def _save_persona(self) -> None:
        text = self.persona_edit.toPlainText()
        if len(text.strip()) > characters.MAX_PERSONA:
            self._mark_edited()  # says how long it is; the draft stays exactly as typed
            return
        self._apply(lambda: self.ctrl.set_persona(text))
        self._drafts.pop((self.ctrl.config.character, english()), None)
        self._show_persona(force=True)

    def _reset_persona(self) -> None:
        self._apply(self.ctrl.reset_persona)
        self._drafts.pop((self.ctrl.config.character, english()), None)
        self._show_persona(force=True)

    def _show_persona(self, force: bool = False) -> None:
        """The editor follows the girl and the language; unsaved typing survives other refreshes."""
        key = (self.ctrl.config.character, english())
        edited = self.persona_save.isEnabled()
        if not force and key == self._persona_shown and edited:
            return
        if edited and self._persona_shown is not None and key != self._persona_shown:
            self._drafts[self._persona_shown] = self.persona_edit.toPlainText()  # kept for when she comes back
        text, custom = self.ctrl.persona_text()
        draft = None if force else self._drafts.pop(key, None)
        if draft is not None:
            text = draft
        was, self._syncing = self._syncing, True
        try:
            if self.persona_edit.toPlainText() != text:
                self.persona_edit.setPlainText(text)
        finally:
            self._syncing = was
        self._persona_shown = key
        self.persona_save.setEnabled(False)
        self.persona_reset.setEnabled(custom)
        if draft is not None:
            self._mark_edited()  # an unsaved draft from before: still unsaved
            name = tr(characters.get(key[0]).name)
            self.persona_label.setText(tr("{0} 的人设提示词（{1}）", name, "English" if key[1] else "中文"))
            return
        name = tr(characters.get(key[0]).name)
        self.persona_label.setText(tr("{0} 的人设提示词（{1}）", name, "English" if key[1] else "中文"))
        self.persona_state.setText(tr("（已修改，和默认不同）") if custom else tr("（默认）"))

    def _backend(self) -> QWidget:
        page, layout = _page(tr("调用方式"))
        self.backend_group = QButtonGroup(self)
        self.backend_radios: dict[str, QRadioButton] = {}
        grid = QGridLayout()
        for index, (backend, provider) in enumerate(PROVIDERS.items()):
            radio = QRadioButton(provider.label + (tr("（按量付费）") if provider.paid else ""))
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
        self.set_key_button = QPushButton(tr("设置 API Key…"))
        self.set_key_button.clicked.connect(lambda: self._apply(self.ctrl.set_api_key))
        self.clear_key_button = QPushButton(tr("清除已保存的 Key"))
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
        apply_model = QPushButton(tr("使用这个模型"))
        apply_model.setObjectName("quiet")
        apply_model.clicked.connect(self._apply_custom_model)
        self.custom_model.returnPressed.connect(self._apply_custom_model)
        model_row.addWidget(QLabel(tr("自定义模型名")))
        model_row.addWidget(self.custom_model, 1)
        model_row.addWidget(apply_model)
        box.addWidget(self.backend_note)
        box.addWidget(self.key_status)
        box.addLayout(keys)
        box.addLayout(model_row)
        box.addWidget(_hint(tr("留空就用「常规」页选的「快速省钱 / 更聪明」预设。模型改名或下线时，在这里填新的名字即可。")))
        layout.addWidget(detail)
        layout.addWidget(_hint(tr("Key 只保存在本机的 Windows 凭据管理器里，不会写进配置文件、日志或这个窗口。用订阅额度运行第三方程序，以 Anthropic / OpenAI 的现行条款为准。")))
        layout.addStretch(1)
        return page

    def _apply_custom_model(self) -> None:
        backend = self.ctrl.config.backend
        self._apply(lambda: self.ctrl.set_custom_model(backend, self.custom_model.text()))

    @staticmethod
    def _backend_note(provider) -> str:
        if provider.kind == CODEX_CLI:
            return (tr("用本机已登录 ChatGPT 的 Codex CLI，不花 API 费用；Codex 的命令、浏览器等工具都会被关闭。截图会短暂写入你自己的临时文件夹，调用结束后删除（被占用时会反复重试，直到删掉）。"))
        if provider.kind == CLAUDE_CLI:
            return tr("用本机已登录 Claude 订阅的 Claude Code，不花 API 费用；截图只在内存里。")
        return (tr("用你自己的 {0} API Key，按量计费，截图会发给 {1}；截图只在内存里。", provider.company, provider.company))

    def _rules_editor(self, kind: str, placeholder: str) -> tuple[QWidget, QListWidget]:
        box = QWidget()
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        rules = QListWidget()
        rules.setObjectName("rules")
        rules.setMinimumHeight(110)
        entry = QLineEdit()
        entry.setPlaceholderText(placeholder)
        add = QPushButton(tr("添加"))
        remove = QPushButton(tr("删除选中"))
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
        page, layout = _page(tr("观察范围"))
        self.scope_group = QButtonGroup(self)
        self.blocklist_radio = QRadioButton(tr("除黑名单外都看（默认）"))
        self.allowlist_radio = QRadioButton(tr("只看白名单里的程序"))
        self.scope_group.addButton(self.blocklist_radio)
        self.scope_group.addButton(self.allowlist_radio)
        self.blocklist_radio.toggled.connect(lambda on: on and self._apply(lambda: self.ctrl.set_watch_mode("blocklist")))
        self.allowlist_radio.toggled.connect(lambda on: on and self._apply(lambda: self.ctrl.set_watch_mode("allowlist")))
        modes = QHBoxLayout()
        modes.addWidget(self.blocklist_radio)
        modes.addWidget(self.allowlist_radio)
        modes.addStretch(1)
        block_box, self.blocklist_view = self._rules_editor("blocklist", tr("关键词"))
        allow_box, self.allowlist_view = self._rules_editor("allowlist", tr("程序名"))
        lists = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel(tr("黑名单（命中就不截图，任何模式下都生效）")))
        left.addWidget(block_box)
        right = QVBoxLayout()
        right.addWidget(QLabel(tr("白名单")))
        right.addWidget(allow_box)
        lists.addLayout(left)
        lists.addLayout(right)
        rules_hint = _hint(tr("黑名单关键词同时匹配窗口标题和程序名，如 bank、微信。白名单默认按程序名匹配，如 code.exe；想按窗口标题匹配，写 title:*关键词*。"))
        self.quiet_box = QCheckBox(tr("全屏游戏、视频、幻灯片时不看也不说"))
        self.quiet_box.toggled.connect(lambda on: self._apply(lambda: self.ctrl.set_quiet_fullscreen(on)))
        dwell = QHBoxLayout()
        self.dwell_spin = QSpinBox()
        self.dwell_spin.setRange(0, 600)
        self.dwell_spin.setKeyboardTracking(False)  # apply when typing is done, not on every digit
        self.dwell_spin.setSuffix(tr(" 秒"))
        self.dwell_spin.valueChanged.connect(lambda v: self._apply(lambda: self.ctrl.set_dwell(v)))
        dwell.addWidget(QLabel(tr("同一个窗口停留多久后才自动评论")))
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
        page, layout = _page(tr("陪伴"))
        self.self_talk_box = QCheckBox(tr("自言自语（本地台词，不调用模型、不花钱）"))
        self.self_talk_box.toggled.connect(lambda on: self._apply(lambda: self.ctrl.set_self_talk(on)))
        talk = QHBoxLayout()
        self.talk_min = QSpinBox()
        self.talk_min.setRange(1, 60)
        self.talk_max = QSpinBox()
        self.talk_max.setRange(1, 120)
        for spin in (self.talk_min, self.talk_max):
            spin.setSuffix(tr(" 分钟"))
            spin.setKeyboardTracking(False)  # typing "20" must not apply "2" first
        # Each end changes only itself: the other keeps its exact seconds from the config.
        set_min = lambda v: self._apply(lambda: self.ctrl.set_self_talk_range(v * 60, self.ctrl.config.self_talk_max_sec))  # noqa: E731
        set_max = lambda v: self._apply(lambda: self.ctrl.set_self_talk_range(self.ctrl.config.self_talk_min_sec, v * 60))  # noqa: E731
        self._minutes_box(self.talk_min, set_min)
        self._minutes_box(self.talk_max, set_max)
        talk.addWidget(QLabel(tr("每隔")))
        talk.addWidget(self.talk_min)
        talk.addWidget(QLabel(tr("到")))
        talk.addWidget(self.talk_max)
        talk.addWidget(QLabel(tr("说一句")))
        talk.addStretch(1)
        self.memory_box = QCheckBox(tr("陪伴记忆：记住主人在用的程序和活动类别（不存窗口标题和截图）"))
        self.memory_box.toggled.connect(lambda on: self._apply(lambda: self.ctrl.set_companion_memory(on)))
        forget = QPushButton(tr("清空陪伴记忆"))
        forget.setObjectName("quiet")
        forget.clicked.connect(lambda: self._apply(self.ctrl.clear_companion_memory))
        self.link_box = QCheckBox(tr(LINK_LABEL))
        self.link_box.toggled.connect(lambda on: self._apply(lambda: on != self.ctrl.config.claude_link and self.ctrl.set_claude_link(on)))
        sleep = QHBoxLayout()
        self.sleep_spin = QSpinBox()
        self.sleep_spin.setRange(1, 1440)  # the config allows up to a day
        self.sleep_spin.setKeyboardTracking(False)
        self.sleep_spin.setSuffix(tr(" 分钟"))
        self._minutes_box(self.sleep_spin, lambda v: self._apply(lambda: self.ctrl.set_sleep_after(v * 60)))
        sleep.addWidget(QLabel(tr("主人离开键盘鼠标多久后她会睡着")))
        sleep.addWidget(self.sleep_spin)
        sleep.addStretch(1)
        birth = QHBoxLayout()
        self.birthday_box = QCheckBox(tr("生日祝福"))
        self.birth_month = QSpinBox()
        self.birth_month.setRange(1, 12)
        self.birth_month.setSuffix(tr(" 月"))
        self.birth_month.setPrefix("" if not english() else tr("月 "))
        self.birth_day = QSpinBox()
        self.birth_day.setRange(1, 31)
        self.birth_day.setSuffix(tr(" 日"))
        self.birth_day.setPrefix("" if not english() else tr("日 "))
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
            self.bedtime_combo.addItem(tr(BEDTIME_LABELS[mode]), mode)
        self.bedtime_combo.currentIndexChanged.connect(
            lambda _i: self._apply(lambda: self.ctrl.set_bedtime_reminder(self.bedtime_combo.currentData())))
        self.night_combo = QComboBox()
        for hour in NIGHT_STARTS:
            self.night_combo.addItem(f"{hour}:00", hour)
        self.night_combo.currentIndexChanged.connect(
            lambda _i: self._apply(lambda: self.ctrl.set_night_start(self.night_combo.currentData())))
        night.addWidget(QLabel(tr("深夜提醒休息")))
        night.addWidget(self.bedtime_combo)
        night.addWidget(QLabel(tr("几点算深夜")))
        night.addWidget(self.night_combo)
        night.addStretch(1)
        memory_row = QHBoxLayout()
        memory_row.addWidget(self.memory_box, 1)
        memory_row.addWidget(forget)
        summary = QHBoxLayout()
        self.summary_combo = QComboBox()
        for hour in SUMMARY_HOURS:
            self.summary_combo.addItem(tr("{0}:00 以后", hour) if hour else tr("关闭"), hour)
        self.summary_combo.currentIndexChanged.connect(
            lambda _i: self._apply(lambda: self.ctrl.set_daily_summary(self.summary_combo.currentData())))
        summary.addWidget(QLabel(tr("每日小结")))
        summary.addWidget(self.summary_combo)
        summary.addWidget(_hint(tr("（说说今天各类活动花了多久、完成了几个番茄，一天一次；活动时长需要陪伴记忆）")))
        summary.addStretch(1)
        focus = QHBoxLayout()
        self.focus_spin = QSpinBox()
        self.focus_spin.setRange(*FOCUS_RANGE)
        self.break_spin = QSpinBox()
        self.break_spin.setRange(*BREAK_RANGE)
        for spin in (self.focus_spin, self.break_spin):
            spin.setSuffix(tr(" 分钟"))
            spin.setKeyboardTracking(False)
        self.focus_spin.valueChanged.connect(lambda v: self._apply(lambda: self.ctrl.set_focus_minutes(v)))
        self.break_spin.valueChanged.connect(lambda v: self._apply(lambda: self.ctrl.set_break_minutes(v)))
        focus.addWidget(QLabel(tr("番茄钟：专注")))
        focus.addWidget(self.focus_spin)
        focus.addWidget(QLabel(tr("，放松")))
        focus.addWidget(self.break_spin)
        focus.addWidget(_hint(tr("（右键菜单「番茄钟与提醒」开始；也可以在那里添加提醒）")))
        focus.addStretch(1)
        layout.addWidget(self.self_talk_box)
        layout.addLayout(talk)
        layout.addLayout(focus)
        layout.addLayout(memory_row)
        layout.addLayout(summary)
        layout.addWidget(self.link_box)
        layout.addLayout(sleep)
        layout.addLayout(night)
        layout.addLayout(birth)
        layout.addWidget(_hint(tr("每天第一次见到主人时她会打个招呼；节日和主人生日那天会换成祝福。")))
        layout.addWidget(_hint(tr("深夜指从这个时间到早上 5 点。看屏幕的评论和自言自语共用这个次数，提过一次就等下一晚（或 2 小时后）。")))
        layout.addStretch(1)
        return page

    def _appearance(self) -> QWidget:
        page, layout = _page(tr("外观"))
        size = QHBoxLayout()
        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(100, 600)  # the same limits the config enforces
        self.size_slider.setSingleStep(10)
        self.size_slider.setPageStep(20)
        self.size_value = QLabel()
        self.size_slider.valueChanged.connect(lambda v: self.size_value.setText(tr("{0} 像素", v)))
        self.size_slider.sliderReleased.connect(lambda: self._apply(lambda: self.ctrl.set_sprite_height(self.size_slider.value())))
        self.size_slider.actionTriggered.connect(lambda _a: None if self.size_slider.isSliderDown() else self._apply(
            lambda: self.ctrl.set_sprite_height(self.size_slider.sliderPosition())))
        size.addWidget(QLabel(tr("她的身高")))
        size.addWidget(self.size_slider, 1)
        size.addWidget(self.size_value)
        layout.addLayout(size)
        layout.addWidget(_hint(tr("调整后立即生效，她的脚站在原来的位置。也可以把鼠标放在她身上，按住 Ctrl 滚动滚轮来调。")))
        face = QHBoxLayout()
        self.blink_combo = QComboBox()
        for rate in BLINK_CHOICES:
            self.blink_combo.addItem(tr(BLINK_LABELS[rate]), rate)
        self.blink_combo.currentIndexChanged.connect(
            lambda _i: self._apply(lambda: self.ctrl.set_blink(self.blink_combo.currentData())))
        self.mouth_box = QCheckBox(tr("说话时动嘴"))
        self.mouth_box.toggled.connect(lambda on: self._apply(lambda: self.ctrl.set_talk_mouth(on)))
        face.addWidget(QLabel(tr("眨眼")))
        face.addWidget(self.blink_combo)
        face.addSpacing(16)
        face.addWidget(self.mouth_box)
        self.head_box = QCheckBox(tr("头部小动作"))
        self.head_box.toggled.connect(lambda on: self._apply(lambda: self.ctrl.set_head_motion(on)))
        face.addSpacing(16)
        face.addWidget(self.head_box)
        self.body_box = QCheckBox(tr("身体小动作"))
        self.body_box.setToolTip(tr("被拎起来时轻轻摆动，落地时压扁再弹回，开心、生气、慌张、难过时身体动一下。"))
        self.body_box.toggled.connect(lambda on: self._apply(lambda: self.ctrl.set_body_motion(on)))
        face.addSpacing(16)
        face.addWidget(self.body_box)
        face.addStretch(1)
        layout.addLayout(face)
        sound = QHBoxLayout()
        self.voice_box = QCheckBox(tr("说话声音（动物语）"))
        self.voice_box.toggled.connect(lambda on: self._apply(lambda: self.ctrl.set_voice(on)))
        self.voice_combo = QComboBox()
        for style in VOICE_STYLES:
            self.voice_combo.addItem(tr(VOICE_STYLE_NAMES[style]), style)
        self.voice_combo.currentIndexChanged.connect(
            lambda _i: self._apply(lambda: self.ctrl.set_voice_style(self.voice_combo.currentData())))
        self.voice_volume = QSlider(Qt.Orientation.Horizontal)
        self.voice_volume.setRange(0, 100)
        self.voice_volume.setFixedWidth(140)
        self.voice_volume.sliderReleased.connect(lambda: self._apply(lambda: self.ctrl.set_voice_volume(self.voice_volume.value())))
        self.voice_volume.actionTriggered.connect(lambda _a: None if self.voice_volume.isSliderDown() else self._apply(
            lambda: self.ctrl.set_voice_volume(self.voice_volume.sliderPosition())))
        preview = QPushButton(tr("试听"))
        preview.setObjectName("quiet")
        preview.clicked.connect(self.ctrl.preview_voice)
        sound.addWidget(self.voice_box)
        sound.addWidget(self.voice_combo)
        sound.addWidget(QLabel(tr("音量")))
        sound.addWidget(self.voice_volume)
        sound.addWidget(preview)
        sound.addStretch(1)
        layout.addLayout(sound)
        layout.addWidget(_hint(tr("她说话时，每个字配一声程序合成的「嘟噜」小音节，像动物森友会里的角色（不是真的语音，不联网）；摸头、拎起来、落地和睡着时也有个小声音。全屏免打扰时不出声。")))
        self.walking_box = QCheckBox(tr("沿屏幕底部溜达"))
        self.walking_box.toggled.connect(lambda on: self._apply(lambda: self.ctrl.set_walking(on)))
        layout.addWidget(self.walking_box)
        layout.addWidget(_hint(tr("站在屏幕最下面（任务栏上方）时，她隔一会儿会左右走几步。说话、睡觉、全屏免打扰或暂停时不走；开着时从任何高度松手她都会掉到底部；想把她放在屏幕别处，先关掉溜达。")))
        layout.addStretch(1)
        return page

    def _about(self) -> QWidget:
        page, layout = _page(tr("关于"))
        self.about_label = text = QLabel()
        text.setWordWrap(True)
        text.setOpenExternalLinks(True)
        text.setTextFormat(Qt.TextFormat.RichText)
        updates_row = QHBoxLayout()
        self.updates_box = QCheckBox(tr("自动检查更新"))
        self.updates_box.toggled.connect(lambda on: self._apply(lambda: self.ctrl.set_check_updates(on)))
        self.check_now = QPushButton(tr("现在检查"))
        self.check_now.setObjectName("quiet")
        self.check_now.clicked.connect(self.ctrl.check_updates_now)
        updates_row.addWidget(self.updates_box)
        updates_row.addWidget(self.check_now)
        self.update_button = QPushButton(tr("下载并更新"))
        self.update_button.clicked.connect(self.ctrl.update_action)
        updates_row.addWidget(self.update_button)
        updates_row.addStretch(1)
        self.update_label = QLabel()
        self.update_label.setWordWrap(True)
        self.update_label.setOpenExternalLinks(True)
        self.update_label.setTextFormat(Qt.TextFormat.RichText)
        logs = QPushButton(tr("打开日志文件夹"))
        logs.setObjectName("quiet")
        logs.clicked.connect(self.ctrl.open_log_folder)
        row = QHBoxLayout()
        row.addWidget(logs)
        row.addStretch(1)
        layout.addWidget(text)
        layout.addLayout(updates_row)
        layout.addWidget(self.update_label)
        layout.addWidget(_hint(tr("每天最多查一次：只读取 GitHub 上公开的最新版本号，不发送你的任何数据，也不会自动下载。")))
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
        self._theme()
        self._syncing = True
        try:
            self.character_combo.setCurrentIndex(max(0, self.character_combo.findData(cfg.character)))
            if not self.address_edit.hasFocus():
                self.address_edit.setText(cfg.address)
            self._show_persona()
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
                self.key_status.setText(tr("{0} API Key：", provider.company) + (tr("已保存（在 Windows 凭据管理器里）") if saved else tr("还没有保存")))
                self.key_link.setText(self._link(tr("<a style='color:#B5531F' href='{0}'>去哪里申请 Key</a>",
                                                    provider.key_page)))
            else:
                self.key_status.setText(tr("这个方式用订阅登录，不需要 API Key。"))
                self.key_link.setText("")
            self.set_key_button.setEnabled(provider.needs_key)
            self.clear_key_button.setEnabled(provider.needs_key)
            custom = cfg.custom_models.get(provider.id, "")
            if not self.custom_model.hasFocus() or self.custom_model.text() == custom:
                self.custom_model.setText(custom)
            presets = tr("、").join(m for m in dict.fromkeys(provider.presets.values()) if m) or tr("账号默认模型")
            self.custom_model.setPlaceholderText(tr("留空使用预设：{0}", presets))
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
            self._show_value(self.focus_spin, cfg.focus_min)
            self._show_value(self.break_spin, cfg.break_min)
            self.summary_combo.setCurrentIndex(max(0, self.summary_combo.findData(cfg.daily_summary_hour)))
            self.link_box.setChecked(cfg.claude_link)
            self.link_box.setText(tr(LINK_LABEL) + (tr("（hook 未找到或 settings.json 异常）") if self.ctrl.claude_link_broken() else ""))
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
            self.body_box.setChecked(cfg.body_motion)
            self.voice_box.setChecked(cfg.voice)
            self.voice_combo.setCurrentIndex(max(0, self.voice_combo.findData(cfg.voice_style)))
            if not self.voice_volume.isSliderDown():
                self.voice_volume.setValue(cfg.voice_volume)
            self.updates_box.setChecked(cfg.check_updates)
            self.language_combo.setCurrentIndex(max(0, self.language_combo.findData(cfg.language)))
            self.check_now.setEnabled(not self.ctrl.update_checking)
            status = html.escape(self.ctrl.update_status)
            if self.ctrl.update_available:
                status += self._link(tr(" · <a style='color:#B5531F' href='{0}'>打开下载页</a>", RELEASES_PAGE))
            if self.ctrl.download_text:
                status += "<br>" + html.escape(self.ctrl.download_text)
            self.update_label.setText(status)
            self.update_button.setVisible(self.ctrl.can_self_update)
            self.update_button.setText(tr(UPDATE_BUTTON.get(self.ctrl.download_state, N_("下载并更新"))))
            if not self.size_slider.isSliderDown():  # a drag in progress is the user's, not the config's
                self.size_slider.setValue(cfg.sprite_height)
                self.size_value.setText(tr("{0} 像素", cfg.sprite_height))
        finally:
            self._syncing = False
