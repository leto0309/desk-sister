"""Companion memory: what the user was doing, by program name and activity category only.

Idea from dsh-pet-indesktop's proactive memory (MIT; no code copied). Window titles are used
locally to classify (a browser on bilibili is "看视频") but never stored or logged. Everything
lives in one local JSON file; refused (blocked / unlisted) windows are never recorded.
"""
from __future__ import annotations

import json
import math
import os
import time
from collections.abc import Callable
from pathlib import Path

ACTIVITIES = ("写代码", "和 AI 一起干活", "看视频", "办公/看文档", "打游戏", "聊天", "听音乐", "上网", "在电脑前")
MAX_LOOKS = 20
MAX_TS = 4102444800.0  # 2100-01-01: anything later in the file is corrupt

_CODE = ("code.exe", "cursor.exe", "devenv.exe", "pycharm", "idea64.exe", "clion", "webstorm", "goland",
         "rider", "sublime_text.exe", "notepad++.exe", "windowsterminal.exe", "wezterm", "nvim", "vim")
_VIDEO_PROCS = ("potplayer", "vlc.exe", "mpv.exe", "bilibili.exe", "qqlive", "iqiyi", "youku")
_VIDEO_TITLES = ("bilibili", "哔哩哔哩", "youtube", "爱奇艺", "腾讯视频", "优酷", "netflix", "twitch", "斗鱼", "虎牙")
_OFFICE = ("winword.exe", "excel.exe", "powerpnt.exe", "wps.exe", "wpp.exe", "et.exe", "onenote.exe",
           "acrobat.exe", "acrord32.exe", "foxitpdfreader.exe", "sumatrapdf.exe", "obsidian.exe", "notion.exe")
_OFFICE_TITLES = (".pdf", ".docx", ".xlsx", ".pptx", "google docs", "腾讯文档", "飞书文档")
_GAMES = ("steam.exe", "epicgameslauncher.exe", "leagueclient.exe", "genshinimpact.exe", "starrail.exe",
          "yuanshen.exe", "valorant", "r5apex.exe", "cs2.exe", "minecraft", "javaw.exe", "rainbowsix")
_CHAT = ("wechat.exe", "weixin.exe", "qq.exe", "telegram.exe", "discord.exe", "line.exe", "dingtalk.exe",
         "feishu.exe", "lark.exe", "slack.exe", "kook.exe", "whatsapp.exe")
_MUSIC = ("spotify.exe", "cloudmusic.exe", "qqmusic.exe", "kugou.exe", "foobar2000.exe")
# AI assistants as desktop apps (process name) and as sites in a browser (window title, matched locally only).
_AI_PROCS = ("claude.exe", "chatgpt.exe", "codex.exe", "copilot.exe", "deepseek", "kimi", "doubao", "qianwen",
             "tongyi", "yuanbao", "perplexity", "gemini")
_AI_TITLES = ("claude", "chatgpt", "gemini", "deepseek", "kimi", "豆包", "通义", "千问", "元宝", "文心一言",
              "perplexity", "copilot", "poe")
_BROWSERS = ("chrome.exe", "msedge.exe", "firefox.exe", "opera.exe", "brave.exe", "vivaldi.exe", "quark.exe")


def classify_activity(process_name: str, title: str = "") -> str:
    """Local keyword rules; no network, no model call."""
    proc = (process_name or "").strip().casefold()
    text = (title or "").strip().casefold()
    if not proc:
        return "在电脑前"
    if any(k in proc for k in _CODE) or "visual studio" in text:
        return "写代码"
    if any(k in proc for k in _AI_PROCS):
        return "和 AI 一起干活"
    if any(k in proc for k in _GAMES):
        return "打游戏"
    if any(k in proc for k in _VIDEO_PROCS) or any(k in text for k in _VIDEO_TITLES):
        return "看视频"
    if any(k in proc for k in _OFFICE) or any(k in text for k in _OFFICE_TITLES):
        return "办公/看文档"
    if any(k in proc for k in _CHAT):
        return "聊天"
    if any(k in proc for k in _MUSIC):
        return "听音乐"
    if any(k in proc for k in _BROWSERS):
        # Video and documents were matched above, so a video *about* ChatGPT is still a video.
        return "和 AI 一起干活" if any(k in text for k in _AI_TITLES) else "上网"
    return "在电脑前"


def _valid_look(item: object) -> dict | None:
    """A stored look, or None if any field is corrupt (inf/NaN/huge timestamps included)."""
    if not isinstance(item, dict) or item.get("activity") not in ACTIVITIES or not isinstance(item.get("process"), str):
        return None
    raw = item.get("ts")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    try:
        ts = float(raw)
        if not math.isfinite(ts) or not 0 <= ts <= MAX_TS:
            return None
        time.localtime(ts)  # must be formattable on this platform
    except (OverflowError, ValueError, OSError):
        return None
    return {"ts": ts, "process": item["process"], "activity": item["activity"]}


def _hours(seconds: float) -> str:
    return f"{seconds / 3600:.1f} 小时" if seconds >= 3600 else f"{max(1, round(seconds / 60))} 分钟"


class CompanionMemory:
    """Recent looks and today's time per activity. path=None keeps everything in memory only."""

    def __init__(self, path: Path | None = None, now: Callable[[], float] = time.time) -> None:
        self.path = path
        self.now = now
        self.looks: list[dict] = []          # {"ts", "process", "activity"}
        self.day = self._today()
        self.seconds: dict[str, float] = {}  # activity -> seconds today
        self.dirty = False
        self._load()

    # ---- persistence -------------------------------------------------------
    def _today(self) -> str:
        return time.strftime("%Y-%m-%d", time.localtime(self.now()))

    def _load(self) -> None:
        if self.path is None:
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return  # missing or corrupt: start fresh
        if not isinstance(data, dict):
            return
        looks = data.get("looks")
        if isinstance(looks, list):
            self.looks = [look for look in map(_valid_look, looks[-MAX_LOOKS:]) if look is not None]
        seconds = data.get("seconds")
        if data.get("day") == self.day and isinstance(seconds, dict):
            self.seconds = {
                k: float(v) for k, v in seconds.items()
                # range first: a 400-digit int would overflow inside isfinite(); inf/NaN fail the range too
                if k in ACTIVITIES and isinstance(v, (int, float)) and not isinstance(v, bool)
                and 0 <= v <= 86400 and math.isfinite(v)
            }

    def flush(self) -> None:
        if self.path is None or not self.dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        payload = {"day": self.day, "seconds": self.seconds, "looks": self.looks}
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(temp, self.path)
        self.dirty = False

    def clear(self) -> None:
        """Forget everything; raises OSError if the file could not be rewritten (it stays dirty for a retry)."""
        self.looks, self.seconds, self.day = [], {}, self._today()
        self.dirty = True
        self.flush()

    # ---- recording ---------------------------------------------------------
    def _roll_day(self) -> None:
        today = self._today()
        if today != self.day:
            self.day, self.seconds = today, {}
            self.dirty = True

    def add_time(self, activity: str, seconds: float) -> None:
        if activity not in ACTIVITIES or seconds <= 0:
            return
        self._roll_day()
        self.seconds[activity] = min(86400.0, self.seconds.get(activity, 0.0) + seconds)
        self.dirty = True

    def record_look(self, process_name: str, activity: str) -> None:
        if activity not in ACTIVITIES:
            return
        self.looks = (self.looks + [{"ts": self.now(), "process": process_name, "activity": activity}])[-MAX_LOOKS:]
        self.dirty = True

    # ---- reading -----------------------------------------------------------
    def top_today(self, minimum_seconds: float = 0) -> tuple[str, float] | None:
        self._roll_day()
        ranked = sorted(self.seconds.items(), key=lambda item: item[1], reverse=True)
        if ranked and ranked[0][1] >= minimum_seconds:
            return ranked[0]
        return None

    def context(self, current_activity: str | None) -> str:
        """A short line for the prompt: what changed since the last look, and today's main activities."""
        self._roll_day()
        parts = []
        if self.looks:
            last = self.looks[-1]
            when = time.strftime("%H:%M", time.localtime(last["ts"]))
            if current_activity and current_activity != last["activity"]:
                parts.append(f"上次（{when}）看到主人在{last['activity']}（{last['process']}），现在在{current_activity}。")
            elif current_activity:
                parts.append(f"上次（{when}）看到主人也在{current_activity}。")
        ranked = sorted(((a, s) for a, s in self.seconds.items() if s >= 300), key=lambda item: item[1], reverse=True)
        if ranked:
            parts.append("今天：" + "、".join(f"{a}约 {_hours(s)}" for a, s in ranked[:3]) + "。")
        return "".join(parts)
