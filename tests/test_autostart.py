import sys
from pathlib import Path

import pytest

from claude_pet import autostart
from claude_pet.autostart import (
    SHORTCUT_NAME, Autostart, AutostartError, Launch, current_launch, flag_means_disabled, points_to_us, read_shortcut,
)

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows shortcuts")


@pytest.fixture
def app_file(tmp_path):
    folder = tmp_path / "pet app"  # a space, like real user paths
    folder.mkdir()
    file = folder / "app.py"
    file.write_text("")
    return file


def ours(app_file):
    return Launch(sys.executable, f'"{app_file}"', str(app_file.parent))


def test_current_launch_uses_windowed_python_and_absolute_app(app_file):
    launch = current_launch(app_file)
    assert Path(launch.target).parent == Path(sys.executable).parent
    assert launch.arguments == f'"{app_file}"' and launch.workdir == str(app_file.parent)


def test_enable_creates_our_shortcut_and_disable_removes_it(tmp_path, app_file):
    pet = Autostart(ours(app_file), folder=tmp_path / "Startup", task_manager=False)
    assert not pet.is_enabled()
    pet.enable()
    assert pet.shortcut.name == SHORTCUT_NAME and pet.is_enabled()
    target, workdir, arguments = read_shortcut(pet.shortcut)
    assert Path(target) == Path(sys.executable) and Path(workdir) == app_file.parent
    assert points_to_us(pet.shortcut, pet.launch)
    pet.enable()  # idempotent: re-creating our own shortcut is fine
    pet.disable()
    assert not pet.shortcut.exists() and not pet.is_enabled()
    pet.disable()  # already off: no error


def test_foreign_shortcut_is_never_overwritten_or_deleted(tmp_path, app_file):
    folder = tmp_path / "Startup"
    notepad = Launch(r"C:\Windows\System32\notepad.exe", "", r"C:\Windows")
    Autostart(notepad, folder=folder, task_manager=False).enable()
    pet = Autostart(ours(app_file), folder=folder, task_manager=False)
    with pytest.raises(AutostartError):
        pet.disable()
    with pytest.raises(AutostartError):
        pet.enable()
    assert read_shortcut(pet.shortcut)[0].lower().endswith("notepad.exe")


def test_legacy_shortcut_with_relative_app_py_counts_as_ours(tmp_path, app_file):
    folder = tmp_path / "Startup"
    legacy = Launch(sys.executable, "app.py", str(app_file.parent))  # how the first autostart link was made
    Autostart(legacy, folder=folder, task_manager=False).enable()
    pet = Autostart(ours(app_file), folder=folder, task_manager=False)
    assert points_to_us(pet.shortcut, pet.launch)
    pet.disable()
    assert not pet.shortcut.exists()


def test_task_manager_disabled_flag(monkeypatch, tmp_path, app_file):
    assert flag_means_disabled(b"\x03" + b"\x00" * 11)
    assert flag_means_disabled(b"\x07" + b"\x00" * 11)
    assert not flag_means_disabled(b"\x02" + b"\x00" * 11)
    assert not flag_means_disabled(b"") and not flag_means_disabled(None)
    pet = Autostart(ours(app_file), folder=tmp_path / "Startup", task_manager=True)
    cleared = []
    monkeypatch.setattr(autostart, "clear_task_manager_flag", lambda name=SHORTCUT_NAME: cleared.append(name))
    monkeypatch.setattr(autostart, "disabled_in_task_manager", lambda name=SHORTCUT_NAME: True)
    pet.enable()
    assert cleared == [SHORTCUT_NAME]  # turning it on again re-enables a Task Manager-disabled entry
    assert not pet.is_enabled()  # while Task Manager says disabled, the menu shows it off
    pet.disable()


def test_frozen_exe_does_not_claim_a_foreign_python_shortcut(tmp_path):
    folder = tmp_path / "Startup"
    apps = tmp_path / "Apps"
    apps.mkdir()
    (apps / "python.exe").write_text("")
    Autostart(Launch(str(apps / "python.exe"), "", str(apps)), folder=folder, task_manager=False).enable()
    frozen = Autostart(Launch(str(apps / "ClaudePet.exe"), "", str(apps)), folder=folder, task_manager=False)
    assert not points_to_us(frozen.shortcut, frozen.launch)
    assert frozen.state() == autostart.FOREIGN
    with pytest.raises(AutostartError):
        frozen.disable()
    with pytest.raises(AutostartError):
        frozen.enable()
    assert frozen.shortcut.exists()


def test_state_reports_foreign_shortcut_instead_of_on(tmp_path, app_file):
    folder = tmp_path / "Startup"
    Autostart(Launch(r"C:\Windows\System32\notepad.exe", "", r"C:\Windows"), folder=folder, task_manager=False).enable()
    pet = Autostart(ours(app_file), folder=folder, task_manager=False)
    assert pet.state() == autostart.FOREIGN and not pet.is_enabled()


def test_registry_errors_other_than_missing_flag_fail_enable(monkeypatch, tmp_path, app_file):
    import winreg

    class Key:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    monkeypatch.setattr(winreg, "OpenKey", lambda *a, **k: Key())
    monkeypatch.setattr(winreg, "DeleteValue", lambda *a: (_ for _ in ()).throw(FileNotFoundError()))
    autostart.clear_task_manager_flag()  # nothing to clear: fine
    monkeypatch.setattr(winreg, "DeleteValue", lambda *a: (_ for _ in ()).throw(PermissionError("denied")))
    with pytest.raises(PermissionError):
        autostart.clear_task_manager_flag()
    pet = Autostart(ours(app_file), folder=tmp_path / "Startup", task_manager=True)
    monkeypatch.setattr(autostart, "disabled_in_task_manager", lambda name=SHORTCUT_NAME: True)
    with pytest.raises(AutostartError):
        pet.enable()  # the entry would stay disabled, so this must not look like success
    pet.task_manager = False
    pet.disable()


def test_an_older_versions_shortcut_is_adopted_and_replaced(tmp_path, app_file, monkeypatch):
    folder = tmp_path / "Startup"
    pet = Autostart(ours(app_file), folder=folder, task_manager=False)
    pet.enable()
    legacy = folder / autostart.LEGACY_NAMES[0]
    pet.shortcut.rename(legacy)  # what an older version left behind
    assert pet.state() == "on"  # still starts with Windows: shown as on
    pet.enable()
    assert pet.shortcut.exists() and not legacy.exists()  # one entry, under the new name
    pet.shortcut.rename(legacy)
    pet.disable()
    assert not legacy.exists() and pet.state() == "off"


def test_an_older_shortcut_of_another_program_is_left_alone(tmp_path, app_file):
    folder = tmp_path / "Startup"
    other = Autostart(Launch(sys.executable, f"\"{tmp_path / 'other.py'}\"", str(tmp_path)), folder=folder, task_manager=False)
    other.enable()
    legacy = folder / autostart.LEGACY_NAMES[0]
    other.shortcut.rename(legacy)
    pet = Autostart(ours(app_file), folder=folder, task_manager=False)
    assert pet.state() == "off"
    pet.enable()
    pet.disable()
    assert legacy.exists()


def test_a_legacy_shortcut_disabled_in_task_manager_counts_as_off(tmp_path, app_file, monkeypatch):
    folder = tmp_path / "Startup"
    pet = Autostart(ours(app_file), folder=folder, task_manager=True)
    monkeypatch.setattr(autostart, "clear_task_manager_flag", lambda name=SHORTCUT_NAME: None)
    pet.enable()
    legacy = folder / autostart.LEGACY_NAMES[0]
    pet.shortcut.rename(legacy)
    checked = []
    monkeypatch.setattr(autostart, "disabled_in_task_manager", lambda name=SHORTCUT_NAME: checked.append(name) or True)
    assert pet.state() == "off" and checked == [legacy.name]


def test_both_shortcuts_count_when_only_the_new_one_is_disabled(tmp_path, app_file, monkeypatch):
    folder = tmp_path / "Startup"
    pet = Autostart(ours(app_file), folder=folder, task_manager=True)
    monkeypatch.setattr(autostart, "clear_task_manager_flag", lambda name=SHORTCUT_NAME: None)
    monkeypatch.setattr(autostart, "LEGACY_NAMES", ())  # create both side by side first
    pet.enable()
    legacy = folder / "Claude 桌宠.lnk"
    legacy.write_bytes(pet.shortcut.read_bytes())
    monkeypatch.setattr(autostart, "LEGACY_NAMES", (legacy.name,))
    monkeypatch.setattr(autostart, "disabled_in_task_manager", lambda name=SHORTCUT_NAME: name == SHORTCUT_NAME)
    assert pet.state() == "on"  # the old one still starts it with Windows


def test_a_legacy_shortcut_that_cannot_be_removed_is_reported(tmp_path, app_file, monkeypatch):
    folder = tmp_path / "Startup"
    pet = Autostart(ours(app_file), folder=folder, task_manager=False)
    pet.enable()
    legacy = folder / autostart.LEGACY_NAMES[0]
    pet.shortcut.rename(legacy)
    real_unlink = Path.unlink

    def locked(self, *args, **kwargs):
        if self.name == legacy.name:
            raise PermissionError("in use")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", locked)
    with pytest.raises(AutostartError):
        pet.enable()
    with pytest.raises(AutostartError):
        pet.disable()
    assert pet.state() == "on"

