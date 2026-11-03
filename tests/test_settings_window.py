from pathlib import Path

import pytest

from claude_pet import claude_client
from claude_pet.config import Config

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6 import QtCore, QtGui  # noqa: E402
from claude_pet import controller as controller_module  # noqa: E402

SPRITES = Path(__file__).resolve().parents[1] / "assets" / "sprites"
ANTHROPIC_ENTRY = "Desk Sister: Anthropic"
FAKE_KEY = "sk-ant-api03-" + "x" * 40


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def pet(app, tmp_path, monkeypatch):
    monkeypatch.setattr(controller_module.capture, "idle_seconds", lambda: 0.0)
    monkeypatch.setattr(controller_module.capture, "is_fullscreen", lambda _i: False)
    monkeypatch.setattr(controller_module.capture, "notification_busy", lambda: False)
    monkeypatch.setattr(claude_client, "find_claude", lambda _configured="": "claude.exe")
    monkeypatch.setattr(controller_module, "app_data_dir", lambda: tmp_path)
    saved = []
    monkeypatch.setattr(controller_module, "save_config", lambda config, *_a, **_k: saved.append(config.interval_sec))
    ctrl = controller_module.PetController(app, Config(dwell_sec=0), SPRITES, tmp_path / "config.json")
    vault = {}
    ctrl._load_key = lambda entry: vault.get(entry)
    ctrl._save_key = lambda key, entry: vault.__setitem__(entry, key)
    ctrl._delete_key = lambda entry: vault.pop(entry, None) is not None
    ctrl._confirm = lambda title, text: True
    ctrl._spawn = lambda fn: fn()
    ctrl.claude_settings = tmp_path / "claude" / "settings.json"
    ctrl.open_settings()
    yield ctrl, ctrl.settings_window, vault, saved
    ctrl.settings_window.close()


def test_the_menu_opens_one_settings_window(pet):
    ctrl, window, _vault, _saved = pet
    assert "设置…" in [a.text() for a in ctrl.tray.contextMenu().actions()]
    assert window.isVisible()
    ctrl.open_settings()
    assert ctrl.settings_window is window  # reused, not a second window
    assert window.nav.count() == 8 and window.windowTitle() == "Desk Sister · 设置"


def test_the_window_is_no_taller_than_before_the_memory_page(pet):
    """v0.3.10's memory page lists asked for ~190 px each and made the window 841 px tall, above a 816 px screen."""
    _ctrl, window, _vault, _saved = pet
    assert window.sizeHint().height() <= 680
    assert window.minimumSizeHint().height() <= 360  # and it can be lower: the pages scroll
    assert not window.pages.autoFillBackground() and not window.pages.parentWidget().autoFillBackground()  # no grey page


class SmallScreen:
    def __init__(self, x, y, width, height):
        self.rect = QtCore.QRect(x, y, width, height)

    def availableGeometry(self):  # noqa: N802 - like QScreen
        return self.rect


@pytest.mark.parametrize("screen", [(0, 0, 1366, 600), (1920, -200, 1024, 560), (0, 0, 1536, 816), (0, 0, 1024, 420)])
def test_the_window_opens_wholly_on_its_screen(pet, monkeypatch, screen):
    """Never taller than the screen it opens on and never above its top, so the title bar can be dragged."""
    _ctrl, window, _vault, _saved = pet
    fake = SmallScreen(*screen)
    monkeypatch.setattr(window, "screen", lambda: fake)
    window.fit_on_screen()
    area, frame = fake.rect, window.frameGeometry()  # the frame: title bar and borders included
    assert frame.top() >= area.top() and frame.left() >= area.left()  # the title bar is on the screen
    assert frame.bottom() <= area.bottom()  # no exception for low screens: the pages scroll
    assert frame.right() <= area.right()


def test_the_menu_wears_her_colours_and_follows_a_switch(pet):
    from claude_pet import characters

    ctrl, _window, _vault, _saved = pet
    menu = ctrl.tray.contextMenu()
    for girl in ("deepseek", "gemini", "claude"):
        ctrl.set_character(girl)
        theme = characters.get(girl).theme
        sheet = ctrl.tray.contextMenu().styleSheet()
        assert theme.main in sheet and theme.deep in sheet and theme.ivory in sheet
    assert ctrl.tray.contextMenu() is menu  # the same menu, its items and their actions untouched
    for each in (menu, ctrl.timer_menu):  # the submenu too: rounded corners need a see-through window
        assert each.testAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        assert each.windowFlags() & QtCore.Qt.WindowType.FramelessWindowHint
        assert each.windowFlags() & QtCore.Qt.WindowType.Popup  # it still closes like a menu
    ctrl.set_language("en")  # the menu is rebuilt in the other language, in the same colours
    assert characters.get("claude").theme.main in ctrl.tray.contextMenu().styleSheet()
    assert ctrl.timer_menu.testAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)


def test_the_chat_dialog_wears_her_colours(pet):
    from PySide6.QtTest import QTest

    from claude_pet import characters, chat_dialog

    ctrl, _window, _vault, _saved = pet
    ctrl.set_character("gemini")
    asked = []
    ctrl._ask_chat = lambda name, theme, face: asked.append((name, theme, face.isNull()))  # cancelled
    ctrl.chat()
    assert asked == [("Gemini", characters.get("gemini").theme, False)] and not ctrl.busy  # cancelled: nothing happens
    theme = characters.get("gemini").theme
    dialog = chat_dialog.ChatDialog("Gemini", theme, QtGui.QPixmap())
    assert theme.main in dialog.styleSheet() and "Gemini" in dialog.windowTitle()
    assert dialog.entry.maxLength() == 300 and not dialog.send_button.isEnabled()
    dialog.entry.setText("   ")
    assert not dialog.send_button.isEnabled()  # spaces are not a message
    dialog.entry.setText("  你好 ")
    assert dialog.send_button.isEnabled() and dialog.message() == "你好"
    dialog.show()
    results = []
    dialog.finished.connect(results.append)
    QTest.keyClick(dialog.entry, QtCore.Qt.Key.Key_Return)
    assert results == [QtWidgets.QDialog.DialogCode.Accepted]  # Enter sends
    dialog.show()
    QTest.keyClick(dialog.entry, QtCore.Qt.Key.Key_Escape)
    assert results[-1] == QtWidgets.QDialog.DialogCode.Rejected  # Esc cancels


def test_no_scrollbar_where_the_window_fits(pet, monkeypatch):
    """v0.3.12's window was sized before its style sheet counted: the pages came out taller and a stray bar showed."""
    from claude_pet.settings_window import SettingsWindow

    ctrl, _window, _vault, _saved = pet
    window = SettingsWindow(ctrl)  # a new one, as it is the first time: never shown, its style sheet not yet counted
    fake = SmallScreen(0, 0, 1536, 1000)
    monkeypatch.setattr(window, "screen", lambda: fake)
    window.fit_on_screen()
    window.grab()  # lays everything out
    scroll = window.pages.parentWidget().parentWidget()
    assert scroll.verticalScrollBar().maximum() == 0 and scroll.horizontalScrollBar().maximum() == 0
    fake.rect = QtCore.QRect(0, 0, 1024, 460)  # too low: it scrolls instead of leaving the screen
    window.fit_on_screen()
    window.grab()
    assert scroll.verticalScrollBar().maximum() > 0 and window.frameGeometry().bottom() <= fake.rect.bottom()


def test_the_windows_wear_her_face_as_their_icon(pet, app):
    ctrl, _window, _vault, _saved = pet
    ctrl.set_character("gemini")
    first = app.windowIcon().pixmap(32, 32).toImage()
    assert not app.windowIcon().isNull() and not first.isNull()
    ctrl.set_character("deepseek")
    assert app.windowIcon().pixmap(32, 32).toImage() != first  # it follows a switch


def test_her_portrait_comes_from_the_full_size_art(pet):
    """It was cut from the sprite at her height on the screen (220 px): too few pixels for a sharp picture."""
    from claude_pet import characters

    ctrl, window, _vault, _saved = pet
    ctrl.set_sprite_height(120)
    head = characters.get(ctrl.config.character).head
    face = ctrl.window.face_picture(head)
    assert face.height() >= 180 and face.height() > ctrl.window.sprites["idle"].height() * head[3] * 2
    window._themed = ""
    window.refresh()
    assert window.header.portrait.height() == face.height()
    asked = []
    ctrl._ask_chat = lambda _name, _theme, picture: asked.append(picture.height())
    ctrl.chat()
    assert asked == [face.height()]


def test_a_taken_shortcut_is_shown_told_once_and_tried_again(pet):
    ctrl, window, _vault, _saved = pet
    now = [100.0]
    ctrl._clock = lambda: now[0]
    ctrl.window.clock = ctrl._clock
    ctrl.window.clear_bubble()
    free = [False]
    ctrl._try_hotkey = lambda: free[0]
    ctrl._register_hotkey()
    assert ctrl.hotkey_taken and "占用" in ctrl.pause_action.text() and "占用" in window.pause_box.text()
    ctrl._update_hotkey()
    assert ctrl.window.full_text == ""  # a moment's clash is not worth a word
    now[0] += 60
    ctrl.window.say("talk", "我在说话")
    ctrl._update_hotkey()
    assert ctrl.window.full_text == "我在说话" and ctrl.config.hotkey_told_on == ""  # she waits for her turn
    ctrl.window.clear_bubble()
    ctrl._update_hotkey()
    assert "Ctrl+Alt+P" in ctrl.window.full_text and ctrl.config.hotkey_told_on == ctrl._today().isoformat()
    ctrl.window.clear_bubble()
    now[0] += 60
    ctrl._update_hotkey()
    assert ctrl.window.full_text == "" and ctrl.hotkey_taken  # once a day
    ctrl._register_hotkey()  # a restart the same day
    now[0] += 60
    ctrl._update_hotkey()
    assert ctrl.window.full_text == ""
    free[0] = True
    now[0] += 60
    ctrl._update_hotkey()  # the other program let go
    assert not ctrl.hotkey_taken and ctrl.pause_action.text() == "暂停观察 (Ctrl+Alt+P)"
    assert "也可以" in window.pause_box.text()
    tried = []
    ctrl._try_hotkey = lambda: tried.append(1) or True
    now[0] += 600
    ctrl._update_hotkey()
    assert tried == []  # held: nothing more to try


def test_enter_on_cancel_cancels_in_both_dialogs(pet):
    """Codex's review: with the focus on Cancel, Enter pressed the default button, so a "forget: ..." went through."""
    from PySide6.QtTest import QTest

    from claude_pet import characters, chat_dialog, reminder_dialog

    theme = characters.get("claude").theme
    chat = chat_dialog.ChatDialog("Claude", theme, QtGui.QPixmap())
    reminder = reminder_dialog.ReminderDialog(None, 1000.0, "claude")
    chat.entry.setText("忘掉：我下周考试")
    reminder.text.setText("喝水")
    for dialog in (chat, reminder):
        dialog.show()
        results = []
        dialog.finished.connect(results.append)
        cancel = next(b for b in dialog.findChildren(QtWidgets.QPushButton) if b.text() == "算了")
        cancel.setFocus()
        QTest.keyClick(cancel, QtCore.Qt.Key.Key_Return)
        assert results == [QtWidgets.QDialog.DialogCode.Rejected], dialog.windowTitle()
    back = chat_dialog.ChatDialog("Claude", theme, QtGui.QPixmap())  # to Cancel and back to the box: Enter sends
    back.entry.setText("你好")
    back.show()
    back.activateWindow()
    assert QTest.qWaitForWindowActive(back)
    results = []
    back.finished.connect(results.append)
    cancel = next(b for b in back.findChildren(QtWidgets.QPushButton) if b.text() == "算了")
    cancel.setFocus()
    back.entry.setFocus()
    assert back.send_button.isDefault() and not cancel.isDefault()
    QTest.keyClick(back.entry, QtCore.Qt.Key.Key_Return)
    assert results == [QtWidgets.QDialog.DialogCode.Accepted]


def test_general_page_applies_at_once_and_stays_in_step_with_the_menu(pet):
    ctrl, window, _vault, saved = pet
    window.interval_combo.setCurrentIndex(window.interval_combo.findData(300))
    assert ctrl.config.interval_sec == 300 and ctrl.timer.interval() == 300_000 and saved[-1] == 300
    window.model_combo.setCurrentIndex(window.model_combo.findData("sonnet"))
    assert ctrl.config.model == "sonnet"
    window.pause_box.setChecked(True)
    assert ctrl.config.paused and ctrl.pause_action.isChecked()
    ctrl.toggle_pause()  # from the menu / hotkey
    assert not window.pause_box.isChecked()
    ctrl.set_model("haiku")
    assert window.model_combo.currentData() == "haiku"


def test_the_way_of_playing_balatro_is_chosen_on_the_general_page(pet):
    ctrl, window, _vault, _saved = pet
    assert ctrl.config.balatro_thinking_tokens == 0 and window.balatro_combo.currentData() == 0  # relaxed unless chosen
    assert "额度消耗高" in window.balatro_combo.itemText(1)
    window.balatro_combo.setCurrentIndex(1)
    assert ctrl.config.balatro_thinking_tokens == 2000
    window.balatro_combo.setCurrentIndex(0)
    assert ctrl.config.balatro_thinking_tokens == 0


def test_a_limit_set_by_hand_shows_as_careful_and_is_not_overwritten(pet):
    ctrl, window, _vault, _saved = pet
    ctrl.config.balatro_thinking_tokens = 4000
    window.refresh()
    assert window.balatro_combo.currentData() == 2000 and ctrl.config.balatro_thinking_tokens == 4000
    ctrl.config.balatro_thinking_tokens = 0
    window.refresh()
    assert window.balatro_combo.currentData() == 0


def test_the_backend_page_never_shows_the_key(pet):
    ctrl, window, vault, _saved = pet
    ctrl._confirm = lambda title, text: False
    window.backend_radios["api"].setChecked(True)
    assert ctrl.config.backend == "subscription" and window.backend_radios["subscription"].isChecked()  # declined: back
    ctrl._confirm = lambda title, text: True
    ctrl._ask_secret = lambda title, label: (FAKE_KEY, True)
    window.backend_radios["api"].setChecked(True)
    assert ctrl.config.backend == "api" and vault[ANTHROPIC_ENTRY] == FAKE_KEY
    assert "已保存" in window.key_status.text() and FAKE_KEY not in window.key_status.text()
    texts = [w.text() for w in window.findChildren(QtWidgets.QLabel)] + [w.text() for w in window.findChildren(QtWidgets.QLineEdit)]
    assert not any(FAKE_KEY in t for t in texts)
    ctrl.clear_api_key()
    assert "还没有" in window.key_status.text()


def test_rule_lists_are_edited_safely(pet):
    ctrl, window, _vault, _saved = pet
    entry = window.blocklist_view.parent().findChild(QtWidgets.QLineEdit)
    entry.setText("  My Secret App  ")
    entry.returnPressed.emit()
    assert ctrl.config.blocklist[-1] == "My Secret App"
    before = list(ctrl.config.blocklist)
    for duplicate in ("my secret app", "   "):  # case-insensitive duplicate, blank
        entry.setText(duplicate)
        entry.returnPressed.emit()
    assert ctrl.config.blocklist == before
    generation = ctrl.generation
    window.blocklist_view.item(window.blocklist_view.count() - 1).setSelected(True)
    window.blocklist_view.parent().findChildren(QtWidgets.QPushButton)[1].click()  # 删除选中
    assert "My Secret App" not in ctrl.config.blocklist and ctrl.generation > generation  # in-flight look dropped
    allow_entry = window.allowlist_view.parent().findChild(QtWidgets.QLineEdit)
    allow_entry.setText("code.exe")
    allow_entry.returnPressed.emit()
    window.allowlist_radio.setChecked(True)
    assert ctrl.config.allowlist == ["code.exe"] and ctrl.config.watch_mode == "allowlist"


def test_scope_and_companion_numbers_are_clamped(pet):
    ctrl, window, _vault, _saved = pet
    window.quiet_box.setChecked(False)
    window.dwell_spin.setValue(45)
    assert not ctrl.config.quiet_fullscreen and ctrl.config.dwell_sec == 45
    window.talk_min.setValue(20)
    window.talk_max.setValue(5)  # below the minimum: raised to it
    assert ctrl.config.self_talk_min_sec == 1200 and ctrl.config.self_talk_max_sec == 1200
    assert window.talk_max.value() == 20
    window.sleep_spin.setValue(30)
    assert ctrl.config.sleep_after_sec == 1800
    window.self_talk_box.setChecked(False)
    assert not ctrl.config.self_talk and not window.talk_min.isEnabled()
    window.memory_box.setChecked(False)
    assert not ctrl.config.companion_memory


def test_the_claude_code_link_still_asks_first(pet):
    ctrl, window, _vault, _saved = pet
    ctrl._confirm = lambda title, text: False
    window.link_box.setChecked(True)
    assert not ctrl.config.claude_link and not window.link_box.isChecked()
    assert not ctrl.claude_settings.exists()


def test_her_size_changes_live_with_her_feet_in_place(pet):
    ctrl, window, _vault, _saved = pet
    pet_window = ctrl.window
    pet_window.move(300, 200)
    feet = (pet_window.geometry().center().x(), pet_window.geometry().bottom())
    ctrl.set_sprite_height(320)
    assert ctrl.config.sprite_height == 320 and pet_window.sprite_height == 320
    assert all(p.height() == 320 for p in pet_window.sprites.values())
    assert abs(pet_window.geometry().center().x() - feet[0]) <= 1 and pet_window.geometry().bottom() == feet[1]
    assert (ctrl.config.x, ctrl.config.y) == (pet_window.x(), pet_window.y())
    assert window.size_slider.value() == 320
    ctrl.set_sprite_height(9999)
    assert ctrl.config.sprite_height == 600  # clamped


def test_the_about_page_credits_and_links(pet):
    _ctrl, window, _vault, _saved = pet
    from claude_pet import __version__

    texts = " ".join(w.text() for w in window.findChildren(QtWidgets.QLabel))
    assert __version__ in texts and "ZipZipPipe" in texts and "仅限非商业使用" in texts
    assert "github.com/leto0309/desk-sister" in texts


def test_typed_numbers_apply_once_typing_is_done(pet):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    ctrl, window, _vault, _saved = pet
    window.nav.setCurrentRow(3)
    spin = window.talk_max
    spin.setFocus()
    spin.lineEdit().selectAll()
    QTest.keyClicks(spin.lineEdit(), "20")
    QTest.keyClick(spin.lineEdit(), Qt.Key.Key_Return)
    assert ctrl.config.self_talk_max_sec == 20 * 60 and spin.value() == 20


def test_edge_values_set_elsewhere_are_shown_and_left_alone(pet):
    ctrl, window, _vault, _saved = pet
    ctrl.set_sprite_height(600)
    ctrl.set_sleep_after(86400)
    assert window.size_slider.value() == 600 and window.sleep_spin.value() == 1440
    window.size_slider.sliderReleased.emit()  # pressing the handle without moving it
    assert ctrl.config.sprite_height == 600
    ctrl.set_sprite_height(100)
    assert window.size_slider.value() == 100


def test_resizing_back_and_forth_never_drifts(pet):
    ctrl, _window, _vault, _saved = pet
    pet_window = ctrl.window
    pet_window.move(300, 200)
    start = pet_window.pos()
    for height in (321, 220, 333, 220, 450, 220):
        ctrl.set_sprite_height(height)
    assert pet_window.pos() == start
    pet_window.move(500, 260)  # moved by the user: the new place is kept
    ctrl.set_sprite_height(300)
    ctrl.set_sprite_height(220)
    assert pet_window.pos().x() == 500


def test_autostart_text_reaches_the_window_with_its_state(pet):
    ctrl, window, _vault, _saved = pet
    ctrl._on_autostart_state(ctrl.autostart_version, controller_module.AUTOSTART_FOREIGN)
    assert not window.autostart_box.isEnabled() and "其他程序" in window.autostart_box.text()
    ctrl._on_autostart_state(ctrl.autostart_version, controller_module.AUTOSTART_ON)
    assert window.autostart_box.isEnabled() and window.autostart_box.isChecked()
    assert "其他程序" not in window.autostart_box.text()


def test_changing_one_end_keeps_the_others_exact_seconds(pet):
    ctrl, window, _vault, _saved = pet
    ctrl.set_self_talk_range(30, 600)
    window.talk_max.setValue(11)
    assert (ctrl.config.self_talk_min_sec, ctrl.config.self_talk_max_sec) == (30, 660)
    ctrl.set_self_talk_range(90, 660)
    window.talk_min.setValue(5)
    assert (ctrl.config.self_talk_min_sec, ctrl.config.self_talk_max_sec) == (300, 660)


def test_enter_in_a_number_box_never_presses_a_button(pet, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    ctrl, window, _vault, _saved = pet
    cleared = []
    monkeypatch.setattr(ctrl, "clear_companion_memory", lambda: cleared.append(1))
    window.close()
    ctrl.open_settings()
    window.nav.setCurrentRow(3)
    spin = window.sleep_spin
    spin.setFocus()
    spin.lineEdit().selectAll()
    QTest.keyClicks(spin.lineEdit(), "45")
    QTest.keyClick(spin.lineEdit(), Qt.Key.Key_Return)
    assert ctrl.config.sleep_after_sec == 45 * 60 and cleared == []
    assert not any(b.autoDefault() or b.isDefault() for b in window.findChildren(QtWidgets.QPushButton))


def test_half_typed_numbers_survive_an_unrelated_sync(pet):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    ctrl, window, _vault, _saved = pet
    window.nav.setCurrentRow(3)
    spin = window.talk_max
    spin.setFocus()
    spin.lineEdit().selectAll()
    QTest.keyClicks(spin.lineEdit(), "20")
    ctrl.toggle_pause()  # syncs the window while the number is still being typed
    assert spin.lineEdit().text().startswith("20")
    QTest.keyClick(spin.lineEdit(), Qt.Key.Key_Return)
    assert ctrl.config.self_talk_max_sec == 20 * 60


def test_typing_the_shown_minute_still_applies_it(pet):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    ctrl, window, _vault, _saved = pet
    ctrl.set_self_talk_range(30, 600)  # 30 s shows as "1 分钟"
    window.nav.setCurrentRow(3)
    spin = window.talk_min
    spin.setFocus()
    spin.lineEdit().selectAll()
    QTest.keyClicks(spin.lineEdit(), "1")
    QTest.keyClick(spin.lineEdit(), Qt.Key.Key_Return)
    assert ctrl.config.self_talk_min_sec == 60
    ctrl.config.self_talk_min_sec = 90
    window.refresh()
    window.talk_max.setFocus()  # only looking at a box, without typing, changes nothing
    window.talk_min.setFocus()
    window.talk_max.setFocus()
    assert ctrl.config.self_talk_min_sec == 90


def test_a_sync_during_a_drag_keeps_the_dragged_size(pet):
    ctrl, window, _vault, _saved = pet
    slider = window.size_slider
    slider.setSliderDown(True)
    slider.setSliderPosition(320)
    ctrl.toggle_pause()  # syncs the window mid-drag
    assert slider.sliderPosition() == 320
    slider.setSliderDown(False)
    slider.sliderReleased.emit()
    assert ctrl.config.sprite_height == 320


def test_a_clamped_typed_value_is_committed_once(pet):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    ctrl, window, _vault, _saved = pet
    ctrl.set_self_talk_range(90, 600)
    window.nav.setCurrentRow(3)
    spin = window.talk_max
    spin.setFocus()
    spin.lineEdit().selectAll()
    QTest.keyClicks(spin.lineEdit(), "1")  # below the minimum: clamped to 90 s
    QTest.keyClick(spin.lineEdit(), Qt.Key.Key_Return)
    assert (ctrl.config.self_talk_min_sec, ctrl.config.self_talk_max_sec) == (90, 90)


@pytest.mark.parametrize("typed", ["", "0"])
def test_invalid_text_put_back_by_qt_changes_nothing(pet, typed):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    ctrl, window, _vault, _saved = pet
    ctrl.set_self_talk_range(90, 600)
    window.nav.setCurrentRow(3)
    spin = window.talk_min
    spin.setFocus()
    spin.lineEdit().selectAll()
    QTest.keyClick(spin.lineEdit(), Qt.Key.Key_Backspace)
    if typed:
        QTest.keyClicks(spin.lineEdit(), typed)
    QTest.keyClick(spin.lineEdit(), Qt.Key.Key_Return)  # finish editing: Qt puts the old number back
    assert ctrl.config.self_talk_min_sec == 90


def test_the_menu_keeps_only_what_is_wanted_at_hand(pet):
    ctrl, _window, _vault, _saved = pet
    labels = [a.text() for a in ctrl.tray.contextMenu().actions() if not a.isSeparator()]
    assert labels[:6] == ["戳她一下（立即评论）", "和她说话…", "陪我玩 Balatro", "番茄钟与提醒", "设置…", "暂停观察 (Ctrl+Alt+P)"]
    assert labels[-1] == "退出"
    for gone in ("观察范围", "Claude Code 联动", "陪伴记忆", "自言自语", "沿屏幕底部溜达", "评论间隔", "调用方式", "模型",
                 "开机自启", "打开日志文件夹"):
        assert not any(label.startswith(gone) for label in labels), gone
    submenus = [a.text() for a in ctrl.tray.contextMenu().actions() if a.menu()]
    assert submenus == ["番茄钟与提醒"]  # the only one: the timer's actions change with its state



def test_birthday_row(pet):
    ctrl, window, _vault, _saved = pet
    assert not window.birthday_box.isChecked() and not window.birth_month.isEnabled()
    window.birth_month.setValue(5)
    window.birth_day.setValue(3)
    assert ctrl.config.birthday == ""  # not until the box is ticked
    window.birthday_box.setChecked(True)
    assert ctrl.config.birthday == "05-03" and window.birth_month.isEnabled()
    window.birth_day.setValue(31)
    window.birth_month.setValue(2)
    assert ctrl.config.birthday == "02-29" and window.birth_day.value() == 29  # the last day of that month
    ctrl.config.birthday = "12-24"
    window.refresh()
    assert window.birthday_box.isChecked() and (window.birth_month.value(), window.birth_day.value()) == (12, 24)
    window.birthday_box.setChecked(False)
    assert ctrl.config.birthday == ""


def test_a_half_typed_birthday_survives_a_sync(pet):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    ctrl, window, _vault, _saved = pet
    window.nav.setCurrentRow(3)
    window.birthday_box.setChecked(True)
    spin = window.birth_day
    spin.setFocus()
    spin.lineEdit().selectAll()
    QTest.keyClicks(spin.lineEdit(), "15")
    ctrl.toggle_pause()  # another setting changes while 主人 is typing
    assert spin.lineEdit().text().startswith("15")
    QTest.keyClick(spin.lineEdit(), Qt.Key.Key_Return)
    assert ctrl.config.birthday.endswith("-15")
