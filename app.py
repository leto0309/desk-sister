"""Desk Sister (a desktop pet) entry point. `--self-test` checks the non-GUI pipeline without a display or network."""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from claude_pet import api_client, claude_client, codex_client, openai_client, persona, providers  # noqa: E402
from claude_pet.config import app_data_dir, load_config  # noqa: E402


def resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def self_test() -> int:
    reply = persona.parse_reply("happy|主人的缩进好整齐！")
    assert reply == persona.Reply("happy", "主人的缩进好整齐！"), reply
    args = claude_client.build_args("claude", "haiku", persona.system_prompt())
    assert args[args.index("--tools") + 1] == "" and "--safe-mode" in args
    assert not any("dangerously" in a or a == "bypassPermissions" for a in args)
    stream = '{"type":"result","subtype":"success","is_error":false,"result":"talk|你好"}\n'
    assert claude_client.parse_stream(stream).text == "talk|你好"
    # API Key mode: the SDK must be importable here too (in the exe this proves it was bundled).
    assert api_client.API_MODELS["haiku"] and api_client.build_content("hi", b"x")[0]["type"] == "image"
    assert api_client.anthropic.Anthropic is not None
    # Other providers: the OpenAI SDK must be bundled as well; the Codex helpers must import.
    messages = openai_client.build_messages("s", "hi", b"x")
    assert messages[1]["content"][0]["type"] == "image_url" and openai_client.openai.OpenAI is not None
    assert codex_client.parse_features("shell_tool  stable  true\n") == {"shell_tool"}
    assert set(providers.BACKENDS) >= {"subscription", "api", "openai", "deepseek", "gemini", "codex"}
    # The embedded art must decode here too: in a one-file exe this proves Pillow's WebP support was bundled.
    from claude_pet import sprite_data
    from claude_pet.sprites import decode_embedded

    for mood in persona.MOODS:
        image = decode_embedded(sprite_data.SPRITES[mood], sprite_data.CHECKSUMS[mood])  # raises if damaged
        assert image.mode == "RGBA" and image.width > 100, mood
    # Every girl with art carries it in the exe (each module is imported by name, so the build must include it).
    from claude_pet.sprites import sprite_module

    for girl in ("deepseek", "gpt", "gemini", "qwen", "glm"):
        module = sprite_module(girl)
        assert module is not None, f"{girl}'s art is not in this build"
        assert decode_embedded(module.SPRITES["idle"], module.CHECKSUMS["idle"]).width > 100, girl
        assert persona.girl_lines(girl) is not None, f"{girl}'s lines are not in this build"
    assert persona.system_prompt("glm").count("表情|台词") == 1  # each girl's persona and the fixed rules
    print("desk-sister self-test passed")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()

    from PySide6.QtCore import QLockFile
    from PySide6.QtWidgets import QApplication

    from claude_pet.autostart import Autostart, current_launch
    from claude_pet.controller import PetController
    from claude_pet.memory import CompanionMemory

    data = app_data_dir()
    data.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(data / "pet.log", maxBytes=512_000, backupCount=1, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(levelname)s %(message)s")

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    lock = QLockFile(str(data / "pet.lock"))
    if not lock.tryLock(100):
        print("Desk Sister is already running.")
        return 0
    # Written first, so a log without this line means logging itself is broken in that process.
    from claude_pet import __version__

    logging.getLogger("claude_pet").info(
        "Desk Sister %s started (pid %d, %s)", __version__, os.getpid(), "exe" if getattr(sys, "frozen", False) else "source",
    )
    # The exe carries its own icon; a source run points the startup shortcut at the same picture.
    icon = None if getattr(sys, "frozen", False) else Path(__file__).resolve().parent / "assets" / "icon.ico"
    autostart = Autostart(current_launch(Path(__file__).resolve(), icon))
    controller = PetController(app, load_config(), resource_root() / "assets" / "sprites", autostart=autostart,
                               memory=CompanionMemory(data / "memory.json"))
    controller.start()
    app.aboutToQuit.connect(controller.shutdown)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
