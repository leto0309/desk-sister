from pathlib import Path

import pytest

from claude_pet import claude_client
from claude_pet.config import Config

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
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
    assert labels[:5] == ["戳她一下（立即评论）", "和她说话…", "番茄钟与提醒", "设置…", "暂停观察 (Ctrl+Alt+P)"]
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
