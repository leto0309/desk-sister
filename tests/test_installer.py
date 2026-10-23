"""The installer script, its build script and the release workflow agree with the program's updater."""
import re
from pathlib import Path

from claude_pet import updates

ROOT = Path(__file__).resolve().parents[1]
ISS = (ROOT / "installer" / "desk-sister.iss").read_text(encoding="utf-8")
RELEASE = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")


def setting(name):
    match = re.search(rf"^{name}=(.*)$", ISS, re.MULTILINE)
    assert match, name
    return match.group(1).strip()


def test_the_installer_is_what_the_updater_downloads():
    assert setting("OutputBaseFilename") + ".exe" == updates.SETUP_NAME
    assert setting("OutputDir") == r"..\dist"


def test_it_installs_per_user_where_the_updater_looks():
    assert setting("PrivilegesRequired") == "lowest"
    assert setting("DefaultDirName") == r"{localappdata}\Programs\DeskSister"
    local = Path("C:/Users/x/AppData/Local")
    assert updates.uses_installer(local / "Programs" / "DeskSister" / "desk-sister.exe", None, str(local))


def test_a_stable_app_id():
    assert re.fullmatch(r'"\{\{[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}\}"',
                        re.search(r'#define AppIdValue (.*)', ISS).group(1))


def test_uninstall_removes_the_updater_s_leftovers_and_keeps_her_data():
    uninstall = ISS[ISS.index("[UninstallDelete]"):ISS.index("[Code]")]
    for name in (updates.OLD_NAME, "desk-sister.update*", "DeskSister-Setup.update*", "_internal"):
        assert name in uninstall, name
    assert "ClaudePet" not in uninstall and "{userappdata}" not in uninstall  # config and memory stay


def test_both_languages():
    assert 'MessagesFile: "compiler:Default.isl"' in ISS and 'MessagesFile: "ChineseSimplified.isl"' in ISS
    assert (ROOT / "installer" / "ChineseSimplified.isl").read_text(encoding="utf-8").count("LanguageID=$0804") == 1


def test_the_release_builds_the_installer_with_a_pinned_checked_inno_setup():
    assert "./scripts/package.ps1" in RELEASE and "./devtools/build_installer.ps1" in RELEASE
    assert RELEASE.index("./scripts/package.ps1") < RELEASE.index("./devtools/build_installer.ps1")
    assert re.search(r"releases/download/is-6_7_3/innosetup-6\.7\.3\.exe", RELEASE)
    assert re.search(r"\$sha = '[0-9A-F]{64}'", RELEASE) and "Get-FileHash" in RELEASE



def test_prerelease_versions_build_too():
    script = (ROOT / "devtools" / "build_installer.ps1").read_text(encoding="utf-8")
    pattern = re.search(r"-notmatch '(.+?)'", script).group(1)
    for version in ("0.1.16", "0.1.17-rc.1", "1.2.3-beta"):
        assert re.match(pattern, version), version
    assert not re.match(pattern, "0.1")
    workflow = re.search(r"-notmatch '(.+?)'", RELEASE).group(1)
    for version in ("0.1.16", "0.1.17-rc.1"):
        assert re.match(workflow, version) and re.match(pattern, version)
    assert "VersionInfoVersion={#NumericVersion}" in ISS


def test_the_previous_version_is_set_aside_not_deleted_up_front():
    assert "[InstallDelete]" not in ISS
    code = ISS[ISS.index("[Code]"):]
    assert "SetAside('_internal')" in code and "PutBack('_internal', LibAside)" in code and "DeinitializeSetup" in code


def test_uninstall_closes_her_only_once_confirmed():
    code = ISS[ISS.index("[Code]"):]
    assert "InitializeUninstall" not in code
    assert "if CurUninstallStep = usUninstall then\n    CloseRunningCopies();" in code


def test_the_install_closes_her_before_setting_her_files_aside():
    code = ISS[ISS.index("procedure CurStepChanged"):]
    assert code.index("CloseRunningCopies();") < code.index("SetAside('_internal');")
    assert ISS.index("procedure CloseRunningCopies") < ISS.index("procedure CurStepChanged")  # declared before use



def test_closing_her_passes_the_folder_in_the_environment_not_in_the_command():
    code = ISS[ISS.index("procedure CloseRunningCopies"):ISS.index("// The previous version is set aside")]
    assert "SetEnvironmentVariable('DESK_SISTER_APP'" in code and "$env:DESK_SISTER_APP" in code
    assert "StringChangeEx" not in code and "AppDir" not in code


def test_only_what_this_run_set_aside_is_put_back():
    assert "PutBack('_internal', LibAside);" in ISS and "PutBack('desk-sister.exe', ExeAside);" in ISS
    assert "if not Aside or" in ISS


def test_an_earlier_backup_is_kept_when_nothing_is_there_to_replace_it():
    code = ISS[ISS.index("function SetAside"):ISS.index("procedure PutBack")]
    assert code.index("exit;") < code.index("DelTree(Previous(Name)")  # nothing current: the backup stays
