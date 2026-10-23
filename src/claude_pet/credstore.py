"""Secrets live in Windows Credential Manager (per user, protected by Windows), never in config.json or logs."""
from __future__ import annotations

import sys
from .i18n import tr

VAULT_ENTRY = "Desk Sister: Anthropic"  # the entry name in Windows Credential Manager
MAX_SECRET_BYTES = 2560  # CRED_MAX_CREDENTIAL_BLOB_SIZE
_ERROR_NOT_FOUND = 1168


class CredentialError(OSError):
    pass


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
        if not _CredWriteW(ctypes.byref(cred), 0):
            raise CredentialError(ctypes.get_last_error(), tr("写入 Windows 凭据失败"))

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
