"""Which language she speaks: Chinese, or English for everyone else.

The interface wraps its Chinese text in tr(); the English for it is in i18n_en.TEXT, keyed by that same Chinese text
(a test checks every tr() literal has one). Her own lines live in persona (Chinese) and persona_en (English).
"""
from __future__ import annotations

import ctypes
import sys

CHOICES = ("", "zh", "en")  # "" follows the Windows display language
_current = "zh"


def system_language() -> str:
    """Chinese if Windows shows Chinese, else English."""
    if sys.platform != "win32":
        return "en"
    try:
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
    except (AttributeError, OSError):
        return "zh"
    return "zh" if lang_id & 0x3FF == 0x04 else "en"  # LANG_CHINESE, any region or script


def resolve(choice: str) -> str:
    return choice if choice in ("zh", "en") else system_language()


def set_language(choice: str) -> str:
    """Use `choice` ("" = the system's) from now on; returns the language in effect."""
    global _current
    _current = resolve(choice)
    return _current


def current() -> str:
    return _current


def english() -> bool:
    return _current == "en"


class Msg:
    """Text kept for showing later (an about-page status): translated when shown, so a language switch reaches it."""

    def __init__(self, text: str, *args, **values) -> None:
        self.text, self.args, self.values = text, args, values

    def __str__(self) -> str:
        return tr(self.text, *self.args, **self.values)


def N_(text: str) -> str:
    """Marks text kept in a table and shown later through tr(), so the translation check finds it."""
    return text


def tr(text: str, *args, **values) -> str:
    """`text` (the Chinese) in the current language, with its {0} / {name} fields filled in."""
    if _current == "en":
        from .i18n_en import TEXT

        text = TEXT.get(text, text)
    return text.format(*args, **values) if args or values else text
