"""The game's own Chinese names for cards, blinds and poker hands, read from the copy of Balatro on this PC.

The mod reports English names. The translations stay in the game's files, which are only ever read (never run or
changed), and are the very names 主人 sees in the game. Without them everything simply keeps its English name.
"""
from __future__ import annotations

import logging
import re
import zipfile
import zlib
from pathlib import Path

log = logging.getLogger(__name__)

ENGLISH_FILE = "localization/en-us.lua"
CHINESE_FILE = "localization/zh_CN.lua"
FILE_MAX = 2_000_000  # bytes of a language file; anything bigger is not what we think it is
NAME_MAX = 30  # characters of a name

_ENTRY = re.compile(r'\b([a-z]+_[a-z0-9_]+)\s*=\s*\{\s*name\s*=\s*"([^"\n]*)"')
_HANDS = re.compile(r'\bpoker_hands\s*=\s*\{(.*?)\}', re.DOTALL)
_HAND = re.compile(r'''(?:\[["']([^"'\n]+)["']\]|\b([A-Za-z]+))\s*=\s*["']([^"'\n]*)["']''')
_LIBRARY = re.compile(r'"path"\s+"([^"\n]+)"')


def _entries(text: str) -> dict[str, str]:
    """key -> name for every card and blind, and hand -> name for the poker hands (those are keyed by the English name)."""
    found = dict(_ENTRY.findall(text))
    block = _HANDS.search(text)
    if block:
        found.update((quoted or bare, name) for quoted, bare, name in _HAND.findall(block.group(1)))
    return found


def _read(archive: zipfile.ZipFile, name: str) -> str:
    if archive.getinfo(name).file_size > FILE_MAX:
        raise ValueError(f"{name} is too big")
    return archive.read(name).decode("utf-8")


def read_names(game: Path) -> dict[str, str]:
    """Chinese names by key (j_joker) and by English name: the mod reports a blind or a poker hand by its English name
    only, and a card's reported name does not always match the language file (Riff-raff, Riff-Raff), so a card goes by
    its key. The game's .exe is also a zip of its files. Nothing readable gives {}."""
    try:
        with zipfile.ZipFile(game) as archive:
            english, chinese = _entries(_read(archive, ENGLISH_FILE)), _entries(_read(archive, CHINESE_FILE))
    except (OSError, KeyError, ValueError, EOFError, RuntimeError, NotImplementedError, zlib.error, zipfile.BadZipFile) as exc:
        # (RuntimeError: an encrypted entry; NotImplementedError: a compression zipfile does not know)
        log.info("no Chinese names from the game: %s", type(exc).__name__)
        return {}
    names = {}
    for key, name in english.items():
        translated = " ".join(chinese.get(key, "").split())
        if name and translated and len(translated) <= NAME_MAX:
            names[key] = names[name] = translated
    return names


def steam_game() -> Path | None:
    """Balatro.exe in any of Steam's libraries."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            steam = Path(winreg.QueryValueEx(key, "SteamPath")[0])
        libraries = _LIBRARY.findall((steam / "steamapps" / "libraryfolders.vdf").read_text(encoding="utf-8", errors="replace"))
    except (ImportError, OSError):
        return None
    for library in [str(steam), *libraries]:
        game = Path(library.replace("\\\\", "\\")) / "steamapps" / "common" / "Balatro" / "Balatro.exe"
        if game.is_file():
            return game
    return None


def load() -> dict[str, str]:
    game = steam_game()
    return read_names(game) if game else {}
