"""English for the interface: every tr() / N_() text in the program, keyed by its Chinese (a test checks)."""

TEXT = {
    # ---- Claude Code link ------------------------------------------------------------------------------
    "Claude Code 在改文件…": "Claude Code is editing files…",
    "Claude Code 在跑命令…": "Claude Code is running a command…",
    "Claude Code 在读代码…": "Claude Code is reading code…",
    "Claude Code 在查资料…": "Claude Code is looking things up…",
    "Claude Code 派出了子代理…": "Claude Code sent out a subagent…",
    "Claude Code 在用工具…": "Claude Code is using a tool…",
    "主人主人，Claude Code 妹妹在等你批准操作！": "Hey, hey! My little sister Claude Code is waiting for your approval!",
    "Claude Code 妹妹在等你回话哦～": "Claude Code is waiting for your reply~",
    "Claude Code 妹妹那边做完啦，去看看吧～": "Claude Code has finished. Go and take a look~",
    "Claude Code 妹妹那边好像出错了……去看一眼吧。": "Something seems to have gone wrong for Claude Code... take a look.",
    "{0} {1}，没有修改它": "{0} {1}; it was left unchanged",
    "的内容不是 JSON 对象": "does not hold a JSON object",
    "里的 hooks 格式不是预期的样子": "has hooks in an unexpected format",
    "{0} 已被桌宠改动，但读不了被替换的版本（{1}）；它保存在 {2}，请检查":
        "{0} was changed by Desk Sister, but the version it replaced could not be read ({1}); it is saved at {2}, please check",
    "{0} 一直在被其他程序修改，没有改动它，稍后再试": "{0} keeps being changed by another program; left unchanged, try again later",
    "Claude Code 在思考…": "Claude Code is thinking…",
    "Claude Code 在等你批准": "Claude Code is waiting for your approval",
    "Claude Code 在等你回话": "Claude Code is waiting for your reply",
    "不是有效的 JSON（{0}）": "is not valid JSON ({0})",
    "读不了 {0}：{1}": "Cannot read {0}: {1}",
    "又有程序保存了一次，那次的版本在 {0}": "Another program saved it again; that version is at {0}",
    "Claude Code 在干活…": "Claude Code is working…",
    "文件又被改动了": "the file changed again",
    "{0} 已被桌宠改动，但同时有其他程序保存了它，未能把两边合并（{1}）。那个程序保存的版本在 {2}，请对照检查。":
        "{0} was changed by Desk Sister while another program saved it too, and the two could not be merged ({1}). "
        "The other program's version is at {2}; please compare them.",
    "文件被删除后又被重新创建": "the file was deleted and created again",
    # ---- thinking and its errors -------------------------------------------------------------------
    "[已隐藏]": "[hidden]",
    "还没有设置 API Key": "No API key set yet",
    "模型拒绝了这次请求": "The model declined this request",
    "API 返回了空回复（{0}）": "The API returned an empty reply ({0})",
    "读取 API Key 失败：{0}": "Could not read the API key: {0}",
    "API Key 无效（401）": "Invalid API key (401)",
    "API Key 没有权限（403）": "The API key has no permission (403)",
    "API 请求太频繁（429），稍后再试": "Too many API requests (429); try again later",
    "API 错误 {0}：{1}": "API error {0}: {1}",
    "连不上 Anthropic API：{0}": "Cannot reach the Anthropic API: {0}",
    "{0} API 返回了空回复": "The {0} API returned an empty reply",
    "{0} API 返回了空回复（{1}）": "The {0} API returned an empty reply ({1})",
    "{0} API Key 无效（401）": "Invalid {0} API key (401)",
    "{0} API Key 没有权限（403）": "The {0} API key has no permission (403)",
    "{0} API 错误 400：{1}": "{0} API error 400: {1}",
    "{0} 请求太频繁或额度不足（429）：{1}": "{0}: too many requests or not enough credit (429): {1}",
    "{0} API 错误 {1}：{2}": "{0} API error {1}: {2}",
    "连不上 {0} API：{1}": "Cannot reach the {0} API: {1}",
    "{0} API Key 无效（400）": "Invalid {0} API key (400)",
    "（附图是主人当前窗口的截图。不要调用任何工具，只按上面的输出格式回答一行。）":
        "(The attached image is a screenshot of the user's current window. Do not call any tools; answer with one "
        "line in the output format above, in English.)",
    "不是 ChatGPT 订阅登录（{0}）": "Not signed in with a ChatGPT subscription ({0})",
    "未登录": "not signed in",
    "读不到 Codex 的功能清单，无法确认能关闭它的工具，这次先不调用":
        "Could not read Codex's feature list, so its tools cannot be confirmed off; not calling it this time",
    "codex 没有给出回答": "codex gave no answer",
    "超时（{0} 秒内没有回复）": "Timed out (no reply within {0} seconds)",
    "还没有设置 API Key（设置里的「调用方式」页）": "No API key set yet (Settings, \"How she thinks\" page)",
    "不是订阅登录：{0}": "Not a subscription login: {0}",
    "任务卡住，已放弃": "The task got stuck and was dropped",
    "未知错误": "Unknown error",
    # ---- autostart and credentials -------------------------------------------------------------------
    "{0} 已存在且指向其他程序，未覆盖": "{0} already exists and points at another program; not overwritten",
    "{0} 指向其他程序，未删除": "{0} points at another program; not deleted",
    "创建启动快捷方式失败：": "Could not create the startup shortcut: ",
    "删不掉旧的启动快捷方式 {0}：{1}": "Cannot delete the old startup shortcut {0}: {1}",
    "无法解除任务管理器中的禁用：{0}": "Cannot undo the Task Manager's disable: {0}",
    "删除 Windows 凭据失败": "Could not delete the Windows credential",
    "只有 Windows 上才能保存 API Key": "API keys can only be saved on Windows",
    "读取 Windows 凭据失败": "Could not read the Windows credential",
    "凭据为空或过长": "The credential is empty or too long",
    "写入 Windows 凭据失败": "Could not write the Windows credential",
    "开机自启": "Start with Windows",
    "（同名快捷方式属于其他程序）": " (a shortcut of that name belongs to another program)",
    "好的，以后开机我就会自动来陪主人啦～": "All right, I'll come and keep you company whenever Windows starts~",
    "好的，开机时我就不自己跑出来了。": "All right, I won't pop up by myself when Windows starts.",
    "呜…开机自启没设置成功：{0}": "Uh... starting with Windows could not be set: {0}",
    "等我把开机自启设置好就走～": "Let me finish setting up the start with Windows, then I'll go~",
    # ---- bedtime --------------------------------------------------------------------------------------
    "关闭": "Off",
    "一晚一次": "Once a night",
    "每 2 小时一次": "Every 2 hours",
    # ---- updates --------------------------------------------------------------------------------------
    "已更新到 {version}。": "Updated to {version}.",
    "上次下载的新版没能换上，现在用的还是原来的版本（{version}），可以再试一次。":
        "The downloaded version could not be put in place, so this is still the old version ({version}). You can try again.",
    "上次的更新没有完成，请到下载页手动下载新版。": "The last update did not finish. Please download the new version from the download page.",
    "正在检查…": "Checking…",
    "正在下载 {0}%（{1:.1f} / {2:.1f} MB）": "Downloading {0}% ({1:.1f} / {2:.1f} MB)",
    "v{0} 已下载并校验好。": "v{0} is downloaded and checked.",
    "检查失败（网络不通或 GitHub 暂时连不上），过一会儿会再试。":
        "The check failed (no network, or GitHub cannot be reached right now); trying again in a while.",
    "有新版本 v{0}": "New version v{0}",
    "点「下载并更新」就能换上": "click \"Download and update\" to get it",
    "可以打开下载页": "you can open the download page",
    "主人，我有新版本 v{0} 啦～在设置 → 关于里{1}。": "There's a new version of me, v{0}~ In Settings → About, {1}.",
    "正在准备下载…": "Preparing the download…",
    "已取消下载。": "Download cancelled.",
    "更新 Desk Sister": "Update Desk Sister",
    "新版已下载并校验好。现在重启换成新版吗？\n她会先退出，几秒后自己回来。":
        "The new version is downloaded and checked. Restart into it now?\nShe will quit first and come back by herself "
        "in a few seconds.",
    "新版已下载好，点「重启并更新」就会换上。": "The new version is downloaded; click \"Restart and update\" to put it in place.",
    "已是最新版（{0}）": "Up to date ({0})",
    "已是最新版（{0}）。": "Up to date ({0}).",
    "下载的文件不见了或被改动过，请重新下载。": "The downloaded file is gone or was changed; please download it again.",
    "没能启动更新程序，请到下载页手动下载。": "The updater could not start; please download from the download page.",
    "已取消下载（下载的文件暂时删不掉，下次启动时会清理）。":
        "Download cancelled (the file cannot be deleted right now; it is cleaned up at the next start).",
    "读不到新版的下载信息，请稍后再试，或到下载页手动下载。":
        "Cannot read the new version's download details; try again later, or download from the download page.",
    "exe 所在的文件夹不能写入，请到下载页手动下载。": "The exe's folder is not writable; please download from the download page.",
    "下载的文件和 GitHub 公布的大小或校验值不一致，已删除。":
        "The download did not match the size or checksum GitHub gives, so it was deleted.",
    "下载失败（网络中断？），请稍后再试。": "The download failed (network dropped?); please try again later.",
    # ---- intervals and units ---------------------------------------------------------------------------
    "30 秒": "30 seconds",
    "1 分钟": "1 minute",
    "90 秒": "90 seconds",
    "2 分钟": "2 minutes",
    "5 分钟": "5 minutes",
    "10 分钟": "10 minutes",
    " 秒": " s",
    " 分钟": " min",
    " 月": "",
    " 日": "",
    "月 ": "Month ",
    "日 ": "Day ",
    "{0} 像素": "{0} px",
    "{0}:00 以后": "after {0}:00",
    "、": ", ",
    "{0}（{1}）": "{0} ({1})",
    # ---- menu, dialogs, bubbles -----------------------------------------------------------------------
    "和 Claude 说话": "Talk to Claude",
    "想对她说什么？": "What would you like to say to her?",
    "戳她一下（立即评论）": "Poke her (comment now)",
    "和她说话…": "Talk to her…",
    "设置…": "Settings…",
    "暂停观察 (Ctrl+Alt+P)": "Pause watching (Ctrl+Alt+P)",
    "把当前程序加入白名单": "Add the current program to the allowlist",
    "退出": "Quit",
    "把当前程序加入白名单（没有可加入的窗口）": "Add the current program to the allowlist (no window to add)",
    "从白名单移除「{0}」": "Remove \"{0}\" from the allowlist",
    "「{0}」已被白名单规则匹配（在 config.json 修改）": "\"{0}\" is matched by an allowlist rule (change it in config.json)",
    "把「{0}」加入白名单": "Add \"{0}\" to the allowlist",
    "要开启 Claude Code 联动吗？\n\n这会修改 {0}：添加几条 hook。如果文件已存在，会先备份为 settings.json.claude-pet-backup-<时间戳>（保留最近 5 份）。\n\nhook 只从 Claude Code 的事件数据里取出会话编号，往本地文件写“事件名 + 会话编号 + 时间”（例如“在改文件”“等你批准”）；你的提示词、代码和命令内容不会被保存。\n\n关闭联动时，只移除这些 hook。":
        "Turn on the Claude Code link?\n\nThis changes {0}: it adds a few hooks. If the file exists, it is first backed "
        "up as settings.json.claude-pet-backup-<timestamp> (the last 5 are kept).\n\nThe hooks take only the session ID "
        "from Claude Code's event data and write \"event + session ID + time\" to a local file (such as \"editing files\" "
        "or \"waiting for your approval\"); your prompts, code and commands are never saved.\n\nTurning the link off "
        "removes only these hooks.",
    "Claude Code 联动": "Claude Code link",
    "好的，联动关掉了，hook 也移除了。": "All right, the link is off and the hooks are removed.",
    "原来的设置备份在 {0}。": "Your original settings are backed up in {0}.",
    "联动开启啦！Claude Code 妹妹在忙什么我都会知道～{0}（已经开着的会话可能要重开才生效）":
        "The link is on! I'll know whatever my little sister Claude Code is up to~ {0} (sessions already open may need "
        "a restart)",
    "我不再看联动了，但没能从 settings.json 移除 hook：{0}": "I stopped watching the link, but could not remove the hooks from settings.json: {0}",
    "没能开启联动：事件文件写不进去（{0}）": "Could not turn on the link: the event file cannot be written ({0})",
    "没能开启联动：{0}": "Could not turn on the link: {0}",
    "好的，陪伴记忆都清空啦……（翻到新的一页）": "All right, my companion memory is cleared... (turns to a fresh page)",
    "记忆在我这儿清空了，但 memory.json 没能改写（{0}），我稍后会再试。":
        "My memory is cleared, but memory.json could not be rewritten ({0}); I'll try again later.",
    "主人好～我是 Claude。我会安静待在这里，偶尔看看你在忙什么。": "Hello~ I'm Claude. I'll stay quietly here and now and then see what you're up to.",
    "我现在闭着眼睛呢，没在看哦～（Ctrl+Alt+P 恢复）": "My eyes are closed right now, I'm not looking~ (Ctrl+Alt+P to resume)",
    "等一下下，我还在想上一句……": "Just a moment, I'm still thinking about the last one...",
    "主人现在好像没有打开什么窗口呢……": "Looks like you don't have any window open right now...",
    "好的，我先闭上眼睛，不偷看了。需要我的时候再叫我～": "All right, I'll close my eyes and not peek. Call me when you need me~",
    "我回来啦！继续陪着主人～": "I'm back! Keeping you company again~",
    "白名单还是空的哦～打开想让我看的程序，右键选「把它加入白名单」，或在设置的「观察范围」页添加吧。":
        "The allowlist is still empty~ Open a program you want me to watch and right-click \"Add to the allowlist\", "
        "or add it on the \"Watching\" page in Settings.",
    "（切到「只看白名单」后生效）": " (takes effect in \"only the allowlist\" mode)",
    "记住啦，「{0}」加入白名单～{1}": "Got it, \"{0}\" is on the allowlist~{1}",
    "好的，以后我只看白名单里的 {0} 项～": "All right, from now on I only watch the {0} items on the allowlist~",
    "好的，除了黑名单里的窗口，我都会看看～": "All right, I'll watch every window except those on the blocklist~",
    "移掉了「{0}」这一条，但规则 {1} 仍然匹配它，要在 config.json 里改哦。":
        "I removed \"{0}\", but the rules {1} still match it; change those in config.json.",
    "好的，「{0}」移出白名单了。": "All right, \"{0}\" is off the allowlist.",
    "要改用你自己的 {0} API Key 吗？\n\nAPI 按用量收费，费用记在这个 Key 所属的 {1} 账户上。她每次看屏幕或回答都会调用一次 API，截图会发给这家公司；评论间隔越短、选「更聪明」的模型，花费越多。\n\nKey 只保存在本机的 Windows 凭据管理器里，不会写进配置文件或日志。":
        "Switch to your own {0} API key?\n\nThe API is billed by use, to the {1} account the key belongs to. Every look "
        "or answer is one API call, and the screenshot is sent to that company; shorter comment intervals and the "
        "\"Smarter\" model cost more.\n\nThe key is kept only in this computer's Windows Credential Manager, never in "
        "the config file or the log.",
    "切换到 {0}": "Switch to {0}",
    "要改用 Codex（你自己的 ChatGPT 订阅）吗？\n\n她会通过本机已登录的 Codex CLI 思考，只接受 ChatGPT 订阅登录，不会改用 API Key 计费。Codex 的命令、浏览器、电脑操作等工具都会被关闭。\n\n注意：Codex CLI 只能从文件读取图片，所以每次看屏幕时，截图会短暂写入你自己的临时文件夹，调用结束（包括失败或取消）后删除；若文件正被别的程序占用，会保留到能删时为止，桌宠每秒、退出和启动时都会重试。其他调用方式的截图只在内存里。\n\n用订阅额度运行第三方程序以 OpenAI 现行条款为准。":
        "Switch to Codex (your own ChatGPT subscription)?\n\nShe will think through the Codex CLI signed in on this "
        "computer, with a ChatGPT subscription login only, never falling back to API-key billing. Codex's commands, "
        "browser, computer use and other tools are all switched off.\n\nNote: the Codex CLI can only read images from "
        "files, so for each look the screenshot is briefly written to your own temp folder and deleted when the call "
        "ends (including failure or cancel); if another program holds the file, it stays until it can be deleted, "
        "retried every second, at quit and at start. With every other way of thinking, screenshots stay in memory "
        "only.\n\nUsing a subscription with a third-party program is subject to OpenAI's current terms.",
    "切换到 Codex（ChatGPT 订阅）": "Switch to Codex (ChatGPT subscription)",
    "好的，之后我用主人的 {0} API Key 来思考～（按量计费，记得留意用量哦）": "All right, I'll think with your {0} API key from now on~ (billed by use, keep an eye on it)",
    "好的，之后我借 Codex 的 ChatGPT 订阅来思考～": "All right, I'll think through Codex on your ChatGPT subscription from now on~",
    "好的，之后我用 Claude Code 的订阅登录来思考～": "All right, I'll think with Claude Code's subscription login from now on~",
    "这个模型名看起来不对呢……（只能有字母、数字和 . _ - : / @）我没有改。":
        "That model name doesn't look right... (letters, digits and . _ - : / @ only) I left it unchanged.",
    "设置 {0} API Key": "Set the {0} API key",
    "粘贴你的 {0} API Key（只保存在本机 Windows 凭据管理器）：": "Paste your {0} API key (kept only in this computer's Windows Credential Manager):",
    "现在的调用方式用的是订阅登录，不需要 API Key 哦。": "The current way of thinking uses a subscription login; no API key needed.",
    "这串看起来不像 API Key 呢……（不能有空格或中文）我没有保存。": "That doesn't look like an API key... (no spaces or Chinese) I didn't save it.",
    "没能保存 API Key：{0}": "Could not save the API key: {0}",
    "API Key 收好啦，锁在 Windows 凭据管理器里～": "API key stored, locked away in the Windows Credential Manager~",
    "现在的调用方式用的是订阅登录，没有保存 API Key。": "The current way of thinking uses a subscription login; no API key is saved.",
    "没能清除 API Key：{0}": "Could not clear the API key: {0}",
    "（现在正用它，要再设置一个 Key 才能继续看屏幕）": " (it is in use now; set another key so I can keep watching)",
    "已经清除保存的 API Key。": "The saved API key is cleared.",
    "本来就没有保存 API Key 哦。": "There was no saved API key anyway.",
    "打不开日志文件夹：{0}": "Cannot open the log folder: {0}",
    # ---- status under her feet ----------------------------------------------------------------------
    "身高 {0} 像素": "Height {0} px",
    "已暂停": "Paused",
    "思考中…": "Thinking…",
    "全屏中，先不打扰": "Full screen, not disturbing",
    "（攒了一句）": " (one line saved)",
    "｜原因：{0}": " | reason: {0}",
    "连续失败 {0} 次，{1} 前不自动看{2}": "{0} failures in a row; no automatic looks until {1}{2}",
    "原因：": "Reason: ",
    "睡着了…动一下鼠标叫醒她": "Asleep… move the mouse to wake her",
    # ---- ways of thinking -----------------------------------------------------------------------------
    "快速省钱": "Fast and cheap",
    "更聪明": "Smarter",
    "Claude Code 订阅（默认）": "Claude Code subscription (default)",
    "Codex（ChatGPT 订阅）": "Codex (ChatGPT subscription)",
    "账号默认模型": "the account's default model",
    "账号默认模型，低推理强度": "the account's default model, low reasoning effort",
    "账号默认模型，中等推理强度": "the account's default model, medium reasoning effort",
    # ---- settings window -----------------------------------------------------------------------------
    "Claude Code 联动（会先征得同意，再修改 ~/.claude/settings.json）": "Claude Code link (asks first, then changes ~/.claude/settings.json)",
    "少": "Few",
    "正常": "Normal",
    "多": "Often",
    "取消下载": "Cancel download",
    "重启并更新": "Restart and update",
    "常规": "General",
    "调用方式": "How she thinks",
    "观察范围": "Watching",
    "陪伴": "Companion",
    "外观": "Appearance",
    "关于": "About",
    "用你自己的 {0} API Key，按量计费，截图会发给 {1}；截图只在内存里。":
        "Uses your own {0} API key, billed by use; screenshots are sent to {1} and otherwise stay in memory.",
    "Desk Sister · 设置": "Desk Sister · Settings",
    "Anthropic 家族的长女，为主人整理一切": "The eldest daughter of the Anthropic family, keeping everything in order for you",
    "暂停观察（Ctrl+Alt+P 也可以）": "Pause watching (Ctrl+Alt+P works too)",
    "设置 API Key…": "Set API key…",
    "清除已保存的 Key": "Clear the saved key",
    "使用这个模型": "Use this model",
    "用本机已登录 ChatGPT 的 Codex CLI，不花 API 费用；Codex 的命令、浏览器等工具都会被关闭。截图会短暂写入你自己的临时文件夹，调用结束后删除（被占用时会反复重试，直到删掉）。":
        "Uses the Codex CLI signed in with ChatGPT on this computer, no API cost; Codex's commands, browser and other "
        "tools are switched off. Screenshots are briefly written to your own temp folder and deleted after the call "
        "(retried until they are gone if held open).",
    "用本机已登录 Claude 订阅的 Claude Code，不花 API 费用；截图只在内存里。":
        "Uses Claude Code signed in with your Claude subscription on this computer, no API cost; screenshots stay in memory.",
    "添加": "Add",
    "删除选中": "Delete selected",
    "除黑名单外都看（默认）": "Everything except the blocklist (default)",
    "只看白名单里的程序": "Only the programs on the allowlist",
    "关键词": "Keyword",
    "程序名": "Program name",
    "黑名单关键词同时匹配窗口标题和程序名，如 bank、微信。白名单默认按程序名匹配，如 code.exe；想按窗口标题匹配，写 title:*关键词*。":
        "Blocklist keywords match both window titles and program names, such as bank or wechat. The allowlist matches "
        "program names, such as code.exe; to match a window title, write title:*keyword*.",
    "全屏游戏、视频、幻灯片时不看也不说": "Neither look nor talk during full-screen games, videos and slideshows",
    "自言自语（本地台词，不调用模型、不花钱）": "Self-talk (local lines, no model calls, free)",
    "陪伴记忆：记住主人在用的程序和活动类别（不存窗口标题和截图）":
        "Companion memory (program names and kinds of activity only)",
    "清空陪伴记忆": "Clear companion memory",
    "生日祝福": "Birthday wish",
    "说话时动嘴": "Move her mouth while talking",
    "头部小动作": "Small head movements",
    "沿屏幕底部溜达": "Stroll along the bottom of the screen",
    "<p style='font-size:12pt'><b>Desk Sister</b> {0}</p><p>非官方粉丝作品，与 Anthropic 无任何关联。</p><p>代码：MIT 许可。角色立绘与图标：参考 B 站 UP 主 <b>ZipZipPipe</b> 的原设（BV1tE9XBbErS）用 AI 生成，经原作者同意<b>仅限非商业使用</b>。人设参考 leto0309/ai-girl-desktop-pet-prompts 中的 Claude 角色卡。</p><p>隐私：她只看当前前台窗口，截图不写日志；黑名单里的窗口不截图；Ctrl+Alt+P 随时暂停。截图只在内存中处理——唯一的例外是 Codex 模式：Codex CLI 只能从文件读图，截图会短暂写入你自己的临时文件夹，调用结束后删除（文件被占用时稍后重试）。</p><p><a style='color:#B5531F' href='https://github.com/leto0309/desk-sister'>github.com/leto0309/desk-sister</a></p>":
        "<p style='font-size:12pt'><b>Desk Sister</b> {0}</p><p>An unofficial fan work, not affiliated with Anthropic "
        "in any way.</p><p>Code: MIT licence. Character art and icon: AI-generated after the original design by "
        "Bilibili creator <b>ZipZipPipe</b> (BV1tE9XBbErS), with the artist's permission, <b>for non-commercial use "
        "only</b>. Persona based on the Claude character card in leto0309/ai-girl-desktop-pet-prompts.</p>"
        "<p>Privacy: she looks only at the window in front, and screenshots are never logged; windows on the "
        "blocklist are never captured; Ctrl+Alt+P pauses her at any time. Screenshots are handled in memory only, "
        "with one exception, Codex mode: the Codex CLI can only read images from files, so the screenshot is briefly "
        "written to your own temp folder and deleted after the call (retried later if the file is held open).</p>"
        "<p><a style='color:#B5531F' href='https://github.com/leto0309/desk-sister'>github.com/leto0309/desk-sister</a></p>",
    "自动检查更新": "Check for updates automatically",
    "现在检查": "Check now",
    "下载并更新": "Download and update",
    "打开日志文件夹": "Open the log folder",
    "评论间隔": "Comment interval",
    "模型": "Model",
    "跟随系统": "Follow Windows",
    "语言 / Language": "Language / 语言",
    "评论间隔越短、选 Sonnet，消耗的额度越多。开机自启写在你自己的「启动」文件夹里，也可以在任务管理器里管理。":
        "Shorter intervals and the Sonnet model use more of your allowance. Start with Windows is a shortcut in your "
        "own Startup folder; the Task Manager can manage it too.",
    "自定义模型名": "Custom model name",
    "留空就用「常规」页选的「快速省钱 / 更聪明」预设。模型改名或下线时，在这里填新的名字即可。":
        "Leave empty to use the \"Fast and cheap / Smarter\" preset chosen on the General page. If a model is renamed "
        "or retired, enter the new name here.",
    "Key 只保存在本机的 Windows 凭据管理器里，不会写进配置文件、日志或这个窗口。用订阅额度运行第三方程序，以 Anthropic / OpenAI 的现行条款为准。":
        "Keys are kept only in this computer's Windows Credential Manager, never in the config file, the log or this "
        "window. Using a subscription with a third-party program is subject to Anthropic's / OpenAI's current terms.",
    "黑名单（命中就不截图，任何模式下都生效）": "Blocklist (never captured, in every mode)",
    "白名单": "Allowlist",
    "同一个窗口停留多久后才自动评论": "Stay on one window this long before an automatic comment",
    "每隔": "Every",
    "到": "to",
    "说一句": "one line",
    "主人离开键盘鼠标多久后她会睡着": "She falls asleep after you leave the keyboard and mouse for",
    "深夜提醒休息": "Late-night rest reminder",
    "几点算深夜": "Night starts at",
    "每日小结": "Daily summary",
    "（需要陪伴记忆：说说今天各类活动花了多久，一天一次）": "(needs companion memory: how long today went on each activity, once a day)",
    "每天第一次见到主人时她会打个招呼；节日和主人生日那天会换成祝福。":
        "She says hello the first time she sees you each day; on festivals and your birthday it becomes a wish.",
    "深夜指从这个时间到早上 5 点。看屏幕的评论和自言自语共用这个次数，提过一次就等下一晚（或 2 小时后）。":
        "Night runs from this time to 5 in the morning. Screen comments and self-talk share the reminder: once given, "
        "the next comes the next night (or 2 hours later).",
    "她的身高": "Her height",
    "调整后立即生效，她的脚站在原来的位置。也可以把鼠标放在她身上，按住 Ctrl 滚动滚轮来调。":
        "Takes effect at once, her feet stay where they are. You can also hold Ctrl and scroll the wheel over her.",
    "眨眼": "Blinking",
    "站在屏幕最下面（任务栏上方）时，她隔一会儿会左右走几步。说话、睡觉、全屏免打扰或暂停时不走；开着时从任何高度松手她都会掉到底部；想把她放在屏幕别处，先关掉溜达。":
        "When she stands at the very bottom of the screen (above the taskbar), she takes a few steps now and then. "
        "Not while talking, asleep, in full-screen quiet or paused; while on, she drops to the bottom from any height "
        "when let go. To keep her elsewhere on the screen, switch strolling off first.",
    "每天最多查一次：只读取 GitHub 上公开的最新版本号，不发送你的任何数据，也不会自动下载。":
        "At most once a day: reads only the public latest version number on GitHub, sends none of your data, and "
        "never downloads by itself.",
    "留空使用预设：{0}": "Empty uses the preset: {0}",
    " · <a style='color:#B5531F' href='{0}'>打开下载页</a>": " · <a style='color:#B5531F' href='{0}'>Open the download page</a>",
    "<a style='color:#B5531F' href='{0}'>去哪里申请 Key</a>": "<a style='color:#B5531F' href='{0}'>Where to get a key</a>",
    "这个方式用订阅登录，不需要 API Key。": "This way uses a subscription login; no API key needed.",
    "（按量付费）": " (billed by use)",
    "{0} API Key：": "{0} API key: ",
    "（hook 未找到或 settings.json 异常）": " (hooks not found, or settings.json is not as expected)",
    "已保存（在 Windows 凭据管理器里）": "saved (in the Windows Credential Manager)",
    "还没有保存": "not saved yet",
    # ---- activities (companion memory) ---------------------------------------------------------------
    "写代码": "coding",
    "和 AI 一起干活": "working with AI",
    "看视频": "watching videos",
    "办公/看文档": "office work and documents",
    "打游戏": "gaming",
    "聊天": "chatting",
    "听音乐": "listening to music",
    "上网": "browsing",
    "在电脑前": "at the computer",
}
