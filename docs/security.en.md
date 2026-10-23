# Security

**English** · [中文](security.md)

No credentials are stored in the repository, no files are overwritten, nothing is merged automatically; APIs and
production deployments need authorisation. Secrets are configured only in GitHub.

## Screenshots and privacy

- Screenshots are handled in memory only and never logged; nothing is written to disk except in Codex mode. In Codex
  mode the screenshot is briefly written to a temp folder private to the current user and deleted in the background
  after the call; if the file is held open it stays until it can be deleted (see "Codex mode" below). PrintWindow
  renders only the target window's own content, so notifications, topmost windows and the pet herself on top of it never
  get into the screenshot; a window that cannot be rendered (all black) is skipped.
- No screenshot when the window's process cannot be identified; after the capture the window title and process are
  read again, and if the window has become a blocklisted one meanwhile, the screenshot is thrown away.
- Screenshots go only to the one company chosen in Settings: by default through the local Claude Code CLI to Anthropic
  (the user's own Claude subscription); in Anthropic API-key mode through the official anthropic Python SDK straight to
  https://api.anthropic.com (see "API-key mode" below); in Codex mode through the local Codex CLI to OpenAI (the user's
  own ChatGPT subscription); in OpenAI / DeepSeek / Gemini API-key mode through the official openai Python SDK to each
  one's official address (see "OpenAI-compatible mode" below). A window whose title or process name is on the
  blocklist is never captured. The blocklist is changed in blocklist in %APPDATA%/ClaudePet/config.json.
- Ctrl+Alt+P or the menu pauses her at any time; while paused nothing is captured and a call in progress is cancelled
  (the subscription check and the model call share one cancellable session that ends the whole process tree in a Job
  Object), and a late reply is dropped; quitting does the same.
- Capturing runs on a worker thread and checks before every step whether she was paused; if the target window hangs, the
  interface, the hotkey and pausing keep working, and a watchdog gives up the task after a timeout. At most one capture
  runs at a time, a stuck capture is never started twice, and threads and GDI resources do not pile up.
- The child process environment drops every ANTHROPIC_*, CLAUDE_CODE_USE_*, CLAUDE_CODE_SKIP_* and
  AWS_BEARER_TOKEN_BEDROCK, ruling out API keys, Bedrock / Vertex / Foundry and custom endpoints; before sending,
  `claude auth status` must confirm a claude.ai subscription login (firstParty), otherwise nothing is sent. The result
  is cached for 30 minutes.
- Start with Windows writes only to the current user's Startup folder and needs no administrator rights; the .lnk is
  created with PowerShell's WScript.Shell, with paths passed in environment variables, never inside the script text;
  only shortcuts that point at this program are deleted. Re-enabling clears this shortcut's disabled flag in the current
  user's StartupApproved and touches no other startup item.
- In allowlist mode (watch_mode=allowlist) only allowlisted programs' windows are captured, poking her included; the
  blocklist still applies on top. Allowlist rules match the process name by default; matching the window title needs an
  explicit title: prefix; a damaged allowlist counts as empty (no window is captured).
- The companion memory (%APPDATA%/ClaudePet/memory.json) keeps only process names, kinds of activity, timestamps and
  today's time per kind; window titles are used only to classify locally and are never written to the file or the log;
  windows refused by the blocklist or the allowlist are neither recorded nor timed. A summary of the memory goes to the
  model as context with comment requests; switch it off or clear it under Settings → Companion.
- The Claude Code link is off by default; turning it on needs confirming in a dialog. It changes the user's Claude Code
  settings.json (backing it up first); the hooks it adds run only powershell.exe: they read the hook's event JSON in
  memory, parse out only the top-level session ID (letters and digits; if parsing fails, only a leading session_id is
  accepted), and write "fixed event name + session ID + start time of the hook process" to
  %APPDATA%/ClaudePet/agent-events/claude.log; prompts, code, commands and file contents are written nowhere; they run
  async and never block Claude Code. The script contains no double quotes, so command-line escaping cannot change its
  meaning. When settings.json is changed, the version replaced is backed up as
  `settings.json.claude-pet-backup-<20-digit timestamp>` (the last 5 are kept); concurrent changes are checked before
  writing, and if another write slipped in after the replacement, the change is redone on top of that version or the
  error is reported honestly with the backup paths; when the file is newly created and someone else created it first,
  the change is redone. Uninstalling removes only hooks exactly as Desk Sister wrote them; an invalid or oddly shaped
  settings.json is not written. The event file is rotated by renaming once it passes 256 KB.
- A blocklist of the wrong type in the config falls back to the default blocklist and never silently becomes empty; an
  explicit empty list counts as the user's choice.
- The CLI runs with `--tools ""`, `--safe-mode`, empty setting sources and `--strict-mcp-config`: the model cannot run
  commands, read or write files, or call MCP; no option that skips permissions is ever used.

## Codex mode (ChatGPT subscription, optional, off by default)

- Before switching, a dialog explains: a ChatGPT subscription login only, all tools off, screenshots briefly written to
  disk. Before every call (never cached) `codex login status` must say "Logged in using ChatGPT", otherwise nothing is
  sent; the child process environment drops OPENAI_*, AZURE_OPENAI_* and CODEX_API_KEY, so it can never fall back to
  API-key billing.
- `codex exec --ephemeral --ignore-user-config --skip-git-repo-check -s read-only`, with an empty temp folder as the
  working directory; `codex features list` first reads the features this CLI knows, and every one that acts or reaches
  outside (shell, unified_exec, browser, computer use, plugins, apps, image generation, web search and so on) is passed
  to `--disable` (unknown names are not passed, so a different CLI version does not fail).
- The Codex CLI can only read images from files: the screenshot is written to a folder of its own under `%TEMP%` for this
  call (private to the current user) and, when the call ends, fails, times out or is cancelled, the two files (only the
  names are removed, nothing is overwritten, so a file a hard link points at is unaffected) and the folder are deleted;
  if another program opened the file in a way that forbids deleting, the delete fails and the screenshot stays as it is
  until it can be deleted: retried in the background on the pet's every-second heartbeat, at quit and at the next start
  (the call itself never waits for the cleanup). The folder is created with permissions for the current user and the
  system only (not inheriting %TEMP%'s); the Codex CLI is given the real path with every link resolved.
  From creation to deletion the pet holds a handle on the folder (nobody can rename or replace it); the screenshot can
  only be newly created, never written into an existing file, and reading the answer and deleting both go relative to
  that handle, so even if a parent folder is swapped for a junction nothing is read, written or deleted elsewhere; the
  scan at start cleans only folders left from before this start.
  Links, junctions and paths that cannot be checked are never touched. With every other way of thinking, screenshots
  stay in memory only.
- The same process control as in Claude Code mode: a Job Object ends the whole process tree; pausing, quitting or
  switching the way she thinks cancels; a late reply is dropped.

## OpenAI / DeepSeek / Gemini API-key mode (optional, off by default)

- The official openai Python SDK, connecting to https://api.openai.com/v1, https://api.deepseek.com and
  https://generativelanguage.googleapis.com/v1beta/openai/ respectively; the keys are kept in Windows credentials of
  their own ("Desk Sister: OpenAI / DeepSeek / Gemini") and never written to config.json, the log, error messages or
  the interface.
- While the client is built, every OPENAI_* environment variable is removed for the moment (the SDK reads
  OPENAI_BASE_URL, OPENAI_ORG_ID, OPENAI_CUSTOM_HEADERS and others), and the key and address are passed explicitly:
  environment variables can neither replace the key or send it to another host, nor attach an organisation or custom
  headers to DeepSeek / Google.
- The screenshot goes only in the user message, as a base64 data URI; keys in error messages (sk-…, AIza…) are always
  masked; 401/403 and Gemini's "invalid API key (400)" all say the key was refused.

## API-key mode (optional, off by default)

- Before switching, a dialog explains the per-use billing; it takes effect only after the user confirms and enters a
  key. The key is kept only in the current user's Windows Credential Manager (generic credential "Desk Sister:
  Anthropic"), never written to config.json, the log, error messages or the interface; clear it under Settings → How she
  thinks.
- An entered key is first checked for format (length; letters, digits, - and _ only); one that fails is not saved.
- The SDK client is given the key and base_url=https://api.anthropic.com explicitly and reads no ANTHROPIC_* environment
  variable, so environment variables can neither replace the key nor send it to another host. At most 1 retry; the same
  timeout as subscription mode.
- Requests carry no tools: only the system prompt, the screenshot (optional) and text; the model is claude-haiku-5-5 or
  claude-sonnet-5-5 with effort=low. Sonnet requests turn on the server-side refusal fallback
  (server-side-fallback-2026-07-01, fallbacks="default").
- Pausing, quitting or switching the way she thinks cancels a request in progress (closing the client), and a late reply
  is dropped.
- 401/403, 429, timeouts, network errors and refusals are all shown as clear reasons and count towards the
  consecutive-failure breaker.

## Update check (on by default, can be switched off under Settings → About)

- At most once a day (plus a "Check now" button), one GET to
  `https://api.github.com/repos/leto0309/desk-sister/releases/latest`, carrying only `Accept` and
  `User-Agent: desk-sister/<version>`: no screenshots, config, memory or any other local data.
- The automatic check reads only the version number in the answer (at most 1 MB is read; anything malformed is
  ignored) and downloads nothing. The download page link is a fixed GitHub address.
- "Download and update" (only in the packaged exe, only on a click): reads the latest release again and accepts only a
  file named desk-sister.exe whose address is exactly
  `https://github.com/leto0309/desk-sister/releases/download/<that version's tag>/desk-sister.exe`, at most 300 MB;
  it is downloaded into the exe's folder as an exclusively created, randomly named `desk-sister.update.<random>.part`
  (nothing already there, file or link, is ever opened or written through), and renamed to `desk-sister.update.exe`
  only when both its size and the SHA-256 digest GitHub gives match; otherwise it is deleted. A version no newer than the
  current one is not downloaded.
- On confirming the restart, the downloaded file's SHA-256 is computed again; if it differs from what was checked
  (changed or gone), it is deleted and not installed. Then a hidden Windows PowerShell script starts (its text is fixed
  in the program; paths, the checksum and the process IDs to wait for come in environment variables, never inside the
  command): it waits for this process (and the one-file exe's launcher process) to quit; renames the old exe to
  `desk-sister.old.exe` as a backup; moves the new file into place and computes the SHA-256 of the file in place once
  more; if that differs or the move fails, it deletes the new file and renames the backup back. Only a checked new
  version or the restored old one is started; if the new version will not start (blocked by security software, say) or
  quits before it is ready (ready means the new version took the result file as it started), the old one is put back
  and started too; if neither is possible, nothing is started and the backup is kept. The script writes the outcome
  (updated / restored / failed) to `desk-sister.update.result`, which the next start reads and reports on the About
  page before deleting it, the backup and any leftover download. The restart drops PyInstaller's internal environment
  variables and PSModulePath (a module path inherited from PowerShell 7 keeps Windows PowerShell from computing the
  checksum).
- Anyone who can write to the exe's folder could replace the exe directly anyway, so putting the download in that same
  folder adds no new risk; the default install location (%LOCALAPPDATA%\Programs\DeskSister) is writable only by the
  current user.
- Network failures, rate limits and malformed answers only write one line to the log; no pop-up.
