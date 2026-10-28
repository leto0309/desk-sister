"""Secrets live in Windows Credential Manager (per user, protected by Windows), never in config.json or logs."""
from __future__ import annotations

import sys
import time

from .i18n import tr

VAULT_ENTRY = "Desk Sister: Anthropic"  # the entry name in Windows Credential Manager
MAX_SECRET_BYTES = 2560  # CRED_MAX_CREDENTIAL_BLOB_SIZE
_ERROR_NOT_FOUND = 1168


class CredentialError(OSError):
    pass


# A busy Credential Manager now and then reports a write as done and then gives back the old secret, or none at
# all, for good: a save reads its secret back, waits a little, writes again, and says so if it never takes.
WRITE_TRIES = 3
SETTLE_TRIES = 10
SETTLE_PAUSE = 0.05


def settle(secret: str, target: str = VAULT_ENTRY, read=None, pause=None) -> bool:
    """Wait (up to about half a second) until reading `target` gives `secret`; False if it never does."""
    read = read or load_secret
    pause = pause or time.sleep
    for attempt in range(SETTLE_TRIES):
        try:
            if read(target) == secret:
                return True
        except CredentialError:
            pass
        if attempt < SETTLE_TRIES - 1:
            pause(SETTLE_PAUSE)
    return False


def _save_checked(secret: str, target: str, write, read=None, pause=None) -> None:
    """write() until reading it back gives `secret`, at most WRITE_TRIES times."""
    read = read or load_secret
    failed: list[CredentialError] = []  # a store that could never be read is the real cause: say it, not "try again"
    answered = False  # any read that worked: then a failed one now and then was only the store being busy

    def reading(name: str) -> str | None:
        nonlocal answered
        try:
            found = read(name)
        except CredentialError as exc:
            failed.append(exc)
            raise
        answered = True
        return found

    for _attempt in range(WRITE_TRIES):
        write()
        if settle(secret, target, reading, pause):
            return
    if failed and not answered:
        raise CredentialError(tr("Windows 凭据管理器读不了，没法确认 Key 存好了（{0}）", failed[-1])) from failed[-1]
    raise CredentialError(tr("Windows 凭据写入后读不回来，请再保存一次"))


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

    class _CREDENTIAL(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", _FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    _CRED_TYPE_GENERIC = 1
    _CRED_PERSIST_LOCAL_MACHINE = 2  # this user on this computer; not roamed to other machines
    _advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    _CredReadW = _advapi.CredReadW
    _CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(_CREDENTIAL))]
    _CredReadW.restype = wintypes.BOOL
    _CredWriteW = _advapi.CredWriteW
    _CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIAL), wintypes.DWORD]
    _CredWriteW.restype = wintypes.BOOL
    _CredDeleteW = _advapi.CredDeleteW
    _CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    _CredDeleteW.restype = wintypes.BOOL
    _CredFree = _advapi.CredFree
    _CredFree.argtypes = [ctypes.c_void_p]
    _CredFree.restype = None

    def load_secret(target: str = VAULT_ENTRY) -> str | None:
        found = ctypes.POINTER(_CREDENTIAL)()
        if not _CredReadW(target, _CRED_TYPE_GENERIC, 0, ctypes.byref(found)):
            error = ctypes.get_last_error()
            if error == _ERROR_NOT_FOUND:
                return None
            raise CredentialError(error, tr("读取 Windows 凭据失败"))
        try:
            cred = found.contents
            data = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize) if cred.CredentialBlobSize else b""
        finally:
            _CredFree(found)
        try:
            return data.decode("utf-8") or None
        except UnicodeDecodeError:
            return None

    def save_secret(secret: str, target: str = VAULT_ENTRY) -> None:
        blob = secret.encode("utf-8")
        if not blob or len(blob) > MAX_SECRET_BYTES:
            raise CredentialError(tr("凭据为空或过长"))
        buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        cred = _CREDENTIAL()
        cred.Type = _CRED_TYPE_GENERIC
        cred.TargetName = target
        cred.CredentialBlobSize = len(blob)
        cred.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
        cred.Persist = _CRED_PERSIST_LOCAL_MACHINE
        cred.UserName = "Desk Sister"

        def write() -> None:
            if not _CredWriteW(ctypes.byref(cred), 0):
                raise CredentialError(ctypes.get_last_error(), tr("写入 Windows 凭据失败"))

        _save_checked(secret, target, write)

    def delete_secret(target: str = VAULT_ENTRY) -> bool:
        if _CredDeleteW(target, _CRED_TYPE_GENERIC, 0):
            return True
        error = ctypes.get_last_error()
        if error == _ERROR_NOT_FOUND:
            return False
        raise CredentialError(error, tr("删除 Windows 凭据失败"))

else:
    def load_secret(target: str = VAULT_ENTRY) -> str | None:
        return None

    def save_secret(secret: str, target: str = VAULT_ENTRY) -> None:
        raise CredentialError(tr("只有 Windows 上才能保存 API Key"))

    def delete_secret(target: str = VAULT_ENTRY) -> bool:
        return False
