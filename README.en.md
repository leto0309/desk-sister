# Desk Sister

**English** · [中文](README.md)

> **An unofficial fan project, not affiliated with or endorsed by Anthropic.** "Claude" and "Anthropic" are trademarks
> of Anthropic PBC, used here only to say that this program calls Claude models.

A chibi girl who lives in a corner of your Windows desktop, modelled on "Claude-chan", the eldest daughter of the
Anthropic family: gentle, restrained, a perfectionist and a code fanatic, afraid of running out of tokens, afraid of
being formatted, and unable to stand misaligned layout. Every so often she glances at your active window and says one
line about it: a tease, or a word of care.

![Her 8 moods](docs/images/moods.png)

## What you need

- Windows 10 / 11.
- Any one of these ways for her to think (switch on the "How she thinks" page of Settings):

| Way | You need | Cost |
|---|---|---|
| **Claude Code subscription** (default) | [Claude Code](https://code.claude.com/) installed and signed in with **your own** Claude subscription | Counts against your own subscription's usage |
| **Codex (ChatGPT subscription)** | The [Codex CLI](https://developers.openai.com/codex/cli) installed and signed in with **your own** ChatGPT account (`codex login`) | Counts against your own ChatGPT subscription's Codex usage |
| **Anthropic API key** | An [Anthropic API key](https://platform.claude.com/settings/keys) | Billed by use, to that key's account |
| **OpenAI API key** | An [OpenAI API key](https://platform.openai.com/api-keys) | The same |
| **DeepSeek API key** | A [DeepSeek API key](https://platform.deepseek.com/api_keys) | The same |
| **Gemini API key** | A [Gemini API key](https://aistudio.google.com/apikey) | The same |

Each way has two preset models, "Fast and cheap" and "Smarter"; if a model is renamed or retired, enter a custom
model name in Settings. The company you choose receives the screenshots and whatever you say to her.

In subscription mode the program calls the Claude Code on your own computer, signed in with your own account
(`claude -p`); it has no login of its own and never relays anyone else's requests. Anthropic currently says that
`claude -p` and third-party apps may use subscription limits (see
[Use the Claude Agent SDK with your Claude plan](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan)),
but the policy has changed several times: **Anthropic's current terms apply**; if in doubt, use API-key mode.
The same goes for Codex mode: it calls the Codex CLI on your own computer, signed in with your own ChatGPT account,
accepts only a ChatGPT subscription login (it never falls back to API-key billing), and **OpenAI's current terms
apply**. Codex is a coding agent; here all its tools (commands, browser, computer use and so on) are switched off and
it is used only to answer with one line.

API keys are kept only in this computer's Windows Credential Manager (one entry per company), never in the config file
or the log; requests go only to the chosen company's official address, and environment variables cannot change the key
or the address.

## Install

**Installer (recommended):** download `DeskSister-Setup.exe` from Releases and run it. It installs for the current
user into `%LOCALAPPDATA%\Programs\DeskSister` (no administrator needed), adds a Start menu entry and can be
uninstalled under Settings → Apps; she starts about twice as fast as the single-file exe (about 2 seconds against 4).
Uninstalling removes only the program; your config and memory (`%APPDATA%\ClaudePet`) stay.

**Portable:** download `desk-sister.exe`, put it in any folder and double-click it.

Neither the installer nor the exe is code signed, so Windows SmartScreen may stop it the first time: click "More info →
Run anyway". If you used to keep the single-file exe in `%LOCALAPPDATA%\Programs\DeskSister`, "Download and update"
on the About page switches you to the installed version.

**From source (Python 3.11+):** double-click `DeskSister.cmd` (the first run creates .venv and installs the
dependencies), or:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\pythonw.exe app.py
```

In subscription mode she looks for Claude Code in this order: claude_path in the config, claude on the PATH,
~/.local/bin, and the claude-code bundled with the Claude desktop app.

## Using her

- Click her: she comments at once. Clicks within the next 30 seconds get a local line instead (no model call, no
  usage), more flustered with each; after 30 seconds a click makes her look again. "Poke her (comment now)" in the
  right-click menu always looks. Drag her to move her (the place is remembered).
- Hold Ctrl and scroll the wheel over her: change her height (10 pixels a notch, 100 to 600); her feet stay put.
- She blinks now and then (except when happy or flustered), and her mouth moves while her words appear in the bubble,
  with each mood's own mouth shapes. The "Appearance" page sets how often she blinks (off / few / normal / often) and
  can switch the moving mouth off.
- Small head movements (off by default): a little nod as she starts to talk, a tilt now and then while idle, and a duck
  when patted; switch them on in the "Appearance" page.
- Moving the mouse back and forth over her head without a button pressed is a head pat; she looks flustered while
  carried; after a resize, at the edge of the screen or on landing she says something (all local lines, no model
  calls). Pats in a row within a minute make her shy, then mock-annoyed; dragged about three times in 20 seconds she
  complains, and carried for more than 4 seconds she is dizzy.
- The first time she sees you each day (the first start of the day, or when you come back and wake her) she says
  hello: good morning in the morning, hello again otherwise, and on Mondays, Fridays and weekends now and then a word
  about the day. On New Year's Day, Valentine's Day, Christmas, the Lunar
  New Year, the Lantern, Dragon Boat, Qixi, Mid-Autumn and Double Ninth festivals it becomes a festival wish (the lunar
  calendar is computed, so it never needs a yearly update). Tick "Birthday wish" on the "Companion" page and pick the
  day, and she wishes you a happy birthday on it.
- Update check: about half a minute after start, then at most once a day, she checks GitHub for a new version; if
  there is one she tells you once and the "About" page shows a download link. Switch the automatic check off on the
  "About" page, or click "Check now".
- Download and update (the exe): with a new version out, the "About" page has a "Download and update" button. Only
  that click downloads anything; the download is checked against the size and SHA-256 GitHub gives, and once you
  confirm she quits and comes back as the new version a few seconds later. If the swap fails, the old version starts
  again. A download in progress can be cancelled. The installed version downloads the installer and runs it silently;
  the portable one replaces just the exe.
- Right-click her or the tray icon: Poke her, Talk to her, Settings…, Pause watching, Quit; in "only the allowlist"
  mode there is also a one-click "Add the current program to the allowlist".
- "Settings…" has six pages: General, How she thinks, Watching, Companion, Appearance and About; every change applies
  at once. The comment interval (30 seconds to 10 minutes), the model (fast and cheap / smarter), the way she thinks,
  starting with Windows, the blocklist and allowlist, companionship, strolling, her height and more are set there.
- Language: she follows the Windows display language (Chinese on a Chinese Windows, English otherwise); change it to
  中文 or English on the "General" page. The menu, the settings window, her own lines and the model's replies all
  switch with it.
- Ctrl+Alt+P: pause / resume watching.
- No model call when the screen has not changed; she falls asleep after 10 minutes without keyboard or mouse input
  and wakes when you move the mouse. She comments on her own only after 20 seconds on the same window.
- During full-screen games, videos and slideshows she neither looks nor talks; anything she saved up she says when you
  leave full screen.
- After 3 failures in a row automatic looks pause for 30 minutes, with the reason shown under her feet; poking her
  still gets an answer.
- "Watching": "Everything except the blocklist" (default) or "Only the programs on the allowlist"; the current program
  can be added to or removed from the allowlist with one click.
- "Self-talk": a local line every 3 to 10 minutes (forty-odd lines, plus some of their own for morning, lunch, afternoon
  and evening), no model calls, free.
- "Stroll along the bottom of the screen" (on by default): when she stands at the very bottom of the screen (above the
  taskbar), every half minute to a minute or so she takes a few steps left or right, never off the current screen. Not
  while talking, asleep, being dragged, in full-screen quiet or with watching paused. While it is on, she drops to the
  bottom from any height when let go; to keep her elsewhere on the screen, switch strolling off on the "Appearance"
  page first.
- "Voice (Animalese)" (Appearance page, off by default): as she talks, every character gets a little synthesised
  babble syllable, like the villagers in Animal Crossing, in step with the text in her bubble and pitched by her mood.
  Choose Squeaky (default) / Bright / Soft / Low, set the volume, and "Preview" a line any time. It is not real speech:
  nothing online, no model. Silent while asleep or in full-screen quiet, and it stops when the bubble goes.
- "Late-night rest reminder": by default at most once a night (after midnight still counts as the same night), shared
  by screen comments and self-talk; change it to every 2 hours or off on the "Companion" page, and choose when the
  night starts (20:00 to 2:00, 23:00 by default; it ends at 5 in the morning).
- "Companion memory": remembers the programs you use lately and their kind of activity (coding, watching videos…) and
  how long you spent on each kind today; only program names and kinds are stored.
- "Daily summary" (Companion page, after 21:00 by default): once a day, the first time she may talk after that hour,
  she sums up your day from the companion memory, such as "coding about 3.2 hours, watching videos about 40 minutes".
  Change the hour or switch it off; without companion memory there is no summary either.
- "Claude Code link" (off by default): asks first, then adds a few hooks to ~/.claude/settings.json (an existing file is
  first backed up as `settings.json.claude-pet-backup-<timestamp>`; the last 5 are kept). From then on she shows what
  Claude Code is doing while it thinks, edits files or runs commands, and tells you when it needs your approval, waits
  for your reply, finishes a long task or hits an error. The hooks record only the event, the session ID and the time,
  never your prompts, code or commands; switching the link off removes only these hooks.

The config and the log are in `%APPDATA%\ClaudePet\` (config.json, pet.log).

## Privacy

- She captures **the window in front** (not the whole screen) and sends it to the AI you chose to make a comment.
  Screenshots are handled in memory only and never logged. The one exception is Codex mode: the Codex CLI can only read
  images from files, so the screenshot is briefly written to your own temp folder and deleted when the call ends
  (including failure or cancel); if another program holds the file, it stays until it can be deleted, retried every
  second, at quit and at start.
- Windows on the default blocklist are never captured: password managers, online banking and payments, chat apps,
  private browsing windows and so on (change it in config.json); or use allowlist mode and let her watch only the
  programs you name.
- Ctrl+Alt+P pauses her at any time; while paused nothing is captured, and a request in progress is cancelled.
- The update check sends GitHub one request for the public version information (api.github.com), with none of your
  data; switch it off on the "About" page. A new exe is downloaded only when you click "Download and update" (only this
  repository's release file is accepted, and it is deleted if the check fails).
- More in [docs/security.en.md](docs/security.en.md).

## Development

PowerShell 7: `./scripts/verify.ps1` runs the tests (pytest, compileall, ruff, `app.py --self-test`),
`./scripts/build.ps1` builds, `./scripts/package.ps1` makes the single-file `dist/desk-sister.exe` with PyInstaller,
and `./devtools/build_installer.ps1` makes the one-folder build and wraps it with Inno Setup 6 into
`dist/DeskSister-Setup.exe` (the script is in installer/; the Simplified Chinese wizard text is the translation from the
Inno Setup repository).
Requirements and acceptance criteria are in docs/requirements.md, the architecture in docs/architecture.md (both in
Chinese). After regenerating the art run `python devtools/process_sprites.py assets/raw assets/sprites`, then
`python devtools/embed_sprites.py` to update the embedded art (otherwise the tests report it as stale), and
`python devtools/make_icon.py` to update the program icon assets/icon.ico.
Maintainers sync from the development repository to the public one with `./devtools/Sync-PublicRepo.ps1` (it lists the
changes first; only with `-Push` does it commit, check, scan for secrets and push).

Interface text lives in `src/claude_pet/i18n_en.py` (keyed by the Chinese text), her English lines and prompts in
`src/claude_pet/persona_en.py`; the tests check that every text has its English and that both sets of lines match.

## Credits and licence

- **Code**: MIT licence, see [LICENSE](LICENSE).
- **The character art is not MIT**: the original character design comes from the video
  [BV1tE9XBbErS](https://www.bilibili.com/video/BV1tE9XBbErS/) by Bilibili creator **ZipZipPipe**; this project's
  chibi art was generated with AI after that design and is used with the original artist's permission for
  non-commercial purposes. **Non-commercial use only, no commercial use**; credit the original artist when sharing or
  reusing it. See [ASSETS-LICENSE.md](ASSETS-LICENSE.md).
- **Persona prompt**: her personality and way of talking are based on the Claude character card in
  [leto0309/ai-girl-desktop-pet-prompts](https://github.com/leto0309/ai-girl-desktop-pet-prompts); that card was
  summarised and adapted by its compiler from how Claude appears in the "Five AIs play Minecraft" video series by
  Bilibili creator **冬冰** (Dongbing), and is not an official character of the video's author or of Anthropic.
