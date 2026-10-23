"""Is a newer Desk Sister out? One GET of the public GitHub release; nothing is sent.

Only when 主人 clicks 「下载并更新」 is the new exe downloaded: from this repository's release only, checked against
the size and SHA-256 GitHub gives for it, and swapped in by a small script once this copy has quit.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import __version__

log = logging.getLogger(__name__)

LATEST_URL = "https://api.github.com/repos/leto0309/desk-sister/releases/latest"
RELEASES_PAGE = "https://github.com/leto0309/desk-sister/releases/latest"
DOWNLOAD_PREFIX = "https://github.com/leto0309/desk-sister/releases/download/"
ASSET_NAME = "desk-sister.exe"  # the single-file exe
SETUP_NAME = "DeskSister-Setup.exe"  # the installer (one-folder build)
CHECK_EVERY_SEC = 24 * 3600
RETRY_SEC = 3600  # after a failed check (offline at start, say)
TIMEOUT_SEC = 10
DOWNLOAD_TIMEOUT_SEC = 60  # per read: a stalled download gives up
MAX_BYTES = 1 << 20
MAX_EXE_BYTES = 300 << 20
CHUNK = 1 << 16
PART_PREFIX, PART_SUFFIX = "desk-sister.update.", ".part"  # a random name in between
UPDATE_NAME = "desk-sister.update.exe"
OLD_NAME = "desk-sister.old.exe"  # the previous exe, kept until the new one has started
SETUP_UPDATE_NAME = "DeskSister-Setup.update.exe"  # a downloaded installer, checked, waiting to run
RESULT_NAME = "desk-sister.update.result"  # what the last swap did: updated, restored or failed
_VERSION = re.compile(r"v?(\d{1,6}(?:\.\d{1,6}){1,3})")
_SHA256 = re.compile(r"sha256:([0-9a-f]{64})")
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
_DETACHED = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
_HEADERS = {"User-Agent": f"desk-sister/{__version__}"}
_ERRORS = (OSError, ValueError, http.client.HTTPException)


class Cancelled(Exception):
    pass


@dataclass(frozen=True)
class Asset:
    version: str
    url: str
    size: int
    sha256: str


def parse_version(text: object) -> tuple[int, ...] | None:
    match = _VERSION.fullmatch(text) if isinstance(text, str) else None
    return tuple(int(part) for part in match.group(1).split(".")) if match else None


def is_newer(candidate: str, current: str = __version__) -> bool:
    new, old = parse_version(candidate), parse_version(current)
    if new is None or old is None:
        return False
    width = max(len(new), len(old))
    return new + (0,) * (width - len(new)) > old + (0,) * (width - len(old))


def _read_release(opener) -> dict | None:
    """The latest published release as GitHub describes it, or None (logged) when it cannot be read."""
    request = urllib.request.Request(LATEST_URL, headers={"Accept": "application/vnd.github+json", **_HEADERS})
    try:
        with opener(request, timeout=TIMEOUT_SEC) as response:
            body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise ValueError("release answer too large")
        data = json.loads(body.decode("utf-8"))
    except _ERRORS as exc:  # offline, rate limits, broken answers
        log.info("update check failed: %s", exc)
        return None
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    if parse_version(data.get("tag_name")) is None:
        return None
    return data


def fetch_latest(opener=urllib.request.urlopen) -> str | None:
    """The version of the latest published release ("0.1.12"), or None when it cannot be read."""
    data = _read_release(opener)
    return ".".join(map(str, parse_version(data["tag_name"]))) if data else None


def one_folder(exe: Path, meipass: str | None) -> bool:
    """The one-folder build: its files are in <exe folder>\\_internal. (A single-file exe unpacks to a _MEIxxxx folder,
    which may well sit next to the exe, say both in %TEMP%: only the exact _internal folder counts.)"""
    if not meipass:
        return False
    try:
        return Path(meipass).resolve() == (exe.parent / "_internal").resolve()
    except OSError:
        return False


def uses_installer(exe: Path, meipass: str | None, local_appdata: str | None) -> bool:
    """Whether this copy updates through the installer: the one-folder build (only the installer ships it),
    or the single-file exe sitting where the installer installs, which the installer then takes over."""
    if one_folder(exe, meipass):
        return True
    if not local_appdata:
        return False
    try:
        return exe.parent.resolve() == (Path(local_appdata) / "Programs" / "DeskSister").resolve()
    except OSError:
        return False


def fetch_asset(opener=urllib.request.urlopen, name: str = ASSET_NAME) -> Asset | None:
    """The latest release's file `name` (the exe or the installer): its download address (this repository's
    release only), size and SHA-256."""
    data = _read_release(opener)
    if data is None:
        return None
    tag = data["tag_name"]
    assets = data.get("assets")
    for item in assets if isinstance(assets, list) else ():
        if not isinstance(item, dict) or item.get("name") != name:
            continue
        url, size = item.get("browser_download_url"), item.get("size")
        digest = _SHA256.fullmatch(item.get("digest") or "") if isinstance(item.get("digest"), str) else None
        if url != f"{DOWNLOAD_PREFIX}{tag}/{name}" or digest is None:
            log.warning("release asset refused: %r", url)
            return None
        if not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= MAX_EXE_BYTES:
            return None
        return Asset(".".join(map(str, parse_version(tag))), url, size, digest.group(1))
    return None


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(asset: Asset, folder: Path, cancelled: Callable[[], bool], progress: Callable[[int, int], None],
             opener=urllib.request.urlopen, final_name: str = UPDATE_NAME) -> Path:
    """Fetch the exe into `folder` as UPDATE_NAME once its size and SHA-256 match; raises on anything else
    (Cancelled, OSError when the folder is not writable or the network fails, ValueError on a mismatch).

    The part file gets a fresh random name, created exclusively: nothing already there (a link someone placed)
    is ever opened or written through."""
    final = folder / final_name
    handle, name = tempfile.mkstemp(prefix=PART_PREFIX, suffix=PART_SUFFIX, dir=folder)
    part = Path(name)
    digest, got = hashlib.sha256(), 0
    try:
        with os.fdopen(handle, "wb") as out:
            request = urllib.request.Request(asset.url, headers=_HEADERS)
            with opener(request, timeout=DOWNLOAD_TIMEOUT_SEC) as response:
                while True:
                    if cancelled():
                        raise Cancelled
                    chunk = response.read(CHUNK)
                    if not chunk:
                        break
                    got += len(chunk)
                    if got > asset.size:
                        raise ValueError("the download is larger than the release says")
                    digest.update(chunk)
                    out.write(chunk)
                    progress(got, asset.size)
        if got != asset.size:
            raise ValueError(f"the download stopped at {got} of {asset.size} bytes")
        if digest.hexdigest() != asset.sha256:
            raise ValueError("the download does not match the release's SHA-256")
        if cancelled():  # cancelled while the last read was coming in
            raise Cancelled
        os.replace(part, final)  # replaces a name: never writes through whatever was there
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return final


def remove_leftovers(folder: Path) -> str:
    """Delete half downloads, an unused download, the previous exe kept by the last swap and its result note.
    Returns what the last swap did ("updated", "restored", "failed") or "" when there was none. A file that cannot
    be deleted now (held open by a virus scan, say) is left for the next start."""
    try:
        result = (folder / RESULT_NAME).read_text(encoding="ascii").strip()
    except (OSError, ValueError):
        result = ""
    if result not in ("updated", "restored", "failed"):
        result = ""
    if not result and ((folder / UPDATE_NAME).exists() or (folder / SETUP_UPDATE_NAME).exists()):
        result = "restored"  # a download that never went in: this is still the old exe
    remove_note(folder)
    for path in [*folder.glob(f"{PART_PREFIX}*{PART_SUFFIX}"), folder / UPDATE_NAME, folder / SETUP_UPDATE_NAME]:
        _remove(path)
    return result


def _remove(path: Path) -> bool:
    try:
        path.unlink(missing_ok=True)
        return True
    except OSError:
        log.warning("could not remove %s; tried again later", path.name)
        return False


KEPT_NAMES = ("desk-sister.exe.previous", "_internal.previous")  # the installer's kept version (see SETUP_SCRIPT)


def remove_note(folder: Path) -> bool:
    """Take the restart helper's note, then the backups it may still need; True once the note is gone.
    Downloads are left alone: one may be waiting for its restart."""
    if not _remove(folder / RESULT_NAME):
        return False
    _remove(folder / OLD_NAME)
    for name in KEPT_NAMES:
        path = folder / name
        if path.is_dir() and not path.is_symlink():
            try:
                shutil.rmtree(path)
            except OSError:
                log.warning("could not remove %s; tried again at the next start", name)
        else:
            _remove(path)
    return True


# Run hidden once this copy quits: wait for it (and the one-file launcher above it), keep the old exe aside,
# move the new one in and check the file now in place against the release's SHA-256. Each step is retried on its
# own. The exe is started only if it is the checked new one or the old one put back; otherwise nothing starts and
# the backup stays. The outcome note is written before the start: the new copy deletes it as it starts, which is
# how the script knows it came up. If the new exe will not start, or quits before that, the old one goes back.
# Paths come in environment variables, never inside the command.
RESTART_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
function Retry([scriptblock]$Step, [int]$Times) {
    for ($i = 0; $i -lt $Times; $i++) { try { & $Step; return $true } catch { Start-Sleep -Seconds 1 } }
    return $false
}
# Handles, taken now while they still run (a gone process is simply not waited for); no time limit.
$waiting = foreach ($id in ($env:DS_WAIT -split ',')) { if ($id) { try { Get-Process -Id ([int]$id) } catch {} } }
foreach ($process in $waiting) { $process.WaitForExit() }
function Start-Exe {
    Retry { $state.proc = Start-Process -FilePath $env:DS_EXE -WorkingDirectory (Split-Path -LiteralPath $env:DS_EXE) -PassThru } 5
}
function Start-Checked {  # true once the new copy has taken the note; false if it never starts or quits first
    if (-not (Start-Exe)) { return $false }
    while ($true) {
        if (-not (Test-Path -LiteralPath $env:DS_RESULT)) { return $true }
        if ($state.proc.HasExited) { return $false }
        Start-Sleep -Milliseconds 500
    }
}
function Remove-New {  # done once the file in place is gone, also when something else took it away (quarantine)
    Retry { if (Test-Path -LiteralPath $env:DS_EXE) { Remove-Item -LiteralPath $env:DS_EXE } } 10
}
function Write-Result([string]$Text) {
    try { Set-Content -LiteralPath $env:DS_RESULT -Value $Text -Encoding Ascii; return $true } catch { return $false }
}
function Put-Back {  # the old exe back in place of the new one; never removes the new one without a backup
    (Test-Path -LiteralPath $env:DS_OLD) -and
        (Remove-New) -and
        (Retry { Move-Item -LiteralPath $env:DS_OLD -Destination $env:DS_EXE } 10)
}
$state = @{ hash = ''; proc = $null }
$aside = Retry { Move-Item -LiteralPath $env:DS_EXE -Destination $env:DS_OLD } 30
$start = -not $aside  # never moved aside: the old exe is still in place
if ($aside) {
    $placed = Retry { Move-Item -LiteralPath $env:DS_NEW -Destination $env:DS_EXE } 10
    $good = $false
    if ($placed) {
        $null = Retry { $state.hash = (Get-FileHash -LiteralPath $env:DS_EXE -Algorithm SHA256).Hash } 10
        $good = $state.hash -eq $env:DS_SHA
        if (-not $good) { $placed = -not (Remove-New) }
    }
    if ($good) { $start = $true }
    elseif (-not $placed) { $start = Retry { Move-Item -LiteralPath $env:DS_OLD -Destination $env:DS_EXE } 10 }
}
if (-not $start) { $null = Write-Result 'failed' }
elseif ($good) {
    # The note goes down before the start: the new copy takes it as it comes up. Without it there is no telling
    # whether the new one came up, so the old one goes back instead.
    if (-not ((Write-Result 'updated') -and (Start-Checked))) {
        $null = Write-Result 'failed'
        if ($state.proc -and -not $state.proc.HasExited) { $null = $state.proc.WaitForExit(10000) }
        if (Put-Back) {
            $null = Write-Result 'restored'
            $null = Start-Exe
        }
    }
}
else {
    $null = Write-Result 'restored'
    $null = Start-Exe
}
"""


def restart_env(base: dict[str, str], exe: Path, new: Path, sha256: str, wait: list[int]) -> dict[str, str]:
    """The helper's environment: none of this one-file process's own PyInstaller variables, which would make
    the restarted exe think it is a child of this one, and no PSModulePath: one inherited from PowerShell 7
    (she was started from a pwsh terminal) makes Windows PowerShell load modules that break Get-FileHash."""
    env = {k: v for k, v in base.items()
           if not k.upper().startswith(("_PYI_", "_MEI")) and k.upper() != "PSMODULEPATH"}
    env.update(PYINSTALLER_RESET_ENVIRONMENT="1", DS_EXE=str(exe), DS_NEW=str(new), DS_OLD=str(exe.with_name(OLD_NAME)),
               DS_RESULT=str(exe.with_name(RESULT_NAME)),
               DS_SHA=sha256.upper(), DS_WAIT=",".join(str(pid) for pid in wait))
    return env


# The installer's turn: wait for her to quit, check the downloaded installer and run it silently into the same folder,
# telling it to keep the previous version aside (it closes anything still holding her files and rolls itself back if it
# fails). Then start the new version and wait until it is up (it takes the outcome note as it starts): the kept version
# is deleted then. If the new version will not start, or quits before it is up, it is taken out and the kept version
# put back and started. Without a whole kept version, the new one is never removed.
SETUP_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
function Retry([scriptblock]$Step, [int]$Times) {
    for ($i = 0; $i -lt $Times; $i++) { try { & $Step; return $true } catch { Start-Sleep -Seconds 1 } }
    return $false
}
function Write-Result([string]$Text) {
    try { Set-Content -LiteralPath $env:DS_RESULT -Value $Text -Encoding Ascii; return $true } catch { return $false }
}
$state = @{ proc = $null; wasFolder = $false }
function Start-Exe {
    Retry { $state.proc = Start-Process -FilePath $env:DS_EXE -WorkingDirectory (Split-Path -LiteralPath $env:DS_EXE) -PassThru } 5
}
function Start-Checked {  # true once the new copy has taken the note; false if it never starts or quits first
    if (-not (Start-Exe)) { return $false }
    while ($true) {
        if (-not (Test-Path -LiteralPath $env:DS_RESULT)) { return $true }
        if ($state.proc.HasExited) { return $false }
        Start-Sleep -Milliseconds 500
    }
}
$dir = Split-Path -LiteralPath $env:DS_EXE
$lib = Join-Path $dir '_internal'
$oldExe = $env:DS_EXE + '.previous'
$oldLib = $lib + '.previous'
function Remove-Gone([string]$Path) {  # done once it is gone, also when something else took it away
    Retry { if (Test-Path -LiteralPath $Path) { Remove-Item -LiteralPath $Path -Recurse -Force } } 10
}
function Put-Back {  # the kept version in place of the new one; nothing is removed unless the whole of it is kept
    if (-not (Test-Path -LiteralPath $oldExe)) { return $false }
    if ($state.wasFolder -and -not (Test-Path -LiteralPath $oldLib)) { return $false }  # its libraries are gone
    if (-not (Remove-Gone $env:DS_EXE)) { return $false }
    if (-not (Retry { Move-Item -LiteralPath $oldExe -Destination $env:DS_EXE } 10)) { return $false }
    if (Test-Path -LiteralPath $oldLib) {
        if (-not ((Remove-Gone $lib) -and (Retry { Move-Item -LiteralPath $oldLib -Destination $lib } 10))) { return $false }
    } else {
        $null = Remove-Gone $lib  # it was the single-file exe before: the new libraries are not its
    }
    return $true
}
function Forget-Kept {
    $null = Remove-Gone $oldExe
    $null = Remove-Gone $oldLib
}
$waiting = foreach ($id in ($env:DS_WAIT -split ',')) { if ($id) { try { Get-Process -Id ([int]$id) } catch {} } }
foreach ($process in $waiting) { $process.WaitForExit() }
$state.wasFolder = Test-Path -LiteralPath $lib  # the one-folder build: putting it back needs its libraries too
$installed = $false
try {
    if ((Get-FileHash -LiteralPath $env:DS_NEW -Algorithm SHA256).Hash -eq $env:DS_SHA) {
        $setup = Start-Process -FilePath $env:DS_NEW -Wait -PassThru -ArgumentList `
            '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', '/KEEPPREVIOUS=1', ('/DIR="' + $dir + '"')
        $installed = $setup.ExitCode -eq 0
    }
} catch {}
try { Remove-Item -LiteralPath $env:DS_NEW } catch {}
if (-not $installed) {  # the installer rolled itself back: this is still the old version
    $null = Write-Result 'restored'
    $null = Start-Exe
} elseif ((Write-Result 'updated') -and (Start-Checked)) {
    Forget-Kept
} else {  # the new version will not start (blocked?) or quit before it was up
    $null = Write-Result 'failed'
    if ($state.proc -and -not $state.proc.HasExited) { $null = $state.proc.WaitForExit(10000) }
    if (Put-Back) {
        $null = Write-Result 'restored'
        $null = Start-Exe
    }
}
"""


def launch_restart(env: dict[str, str], script: str = RESTART_SCRIPT) -> None:
    subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
         "-Command", script],
        env=env, creationflags=_NO_WINDOW | _DETACHED, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, close_fds=True,
    )
