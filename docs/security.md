# 安全

不存储凭据、不覆盖文件、不自动合并；API 和生产部署需授权。Secrets 只配置于 GitHub。

## 截图与隐私

- 截图只在内存中处理，不写日志；除 Codex 模式外不写盘。Codex 模式下截图会短暂写入当前用户私有的临时文件夹，
  调用结束后在后台删除，文件被占用时保留到能删为止（见下方“Codex 模式”）。用 PrintWindow 只渲染目标窗口自身的内容，
  盖在上面的通知、置顶窗口和桌宠本身不会进入截图；窗口无法渲染（全黑）时跳过。
- 无法识别窗口所属进程时不截图；截图后重新读取窗口标题和进程，期间变成黑名单窗口则丢弃截图。
- 截图只发送给用户在设置里选择的那一家：默认经本机 Claude Code CLI 发给 Anthropic（用户自己的 Claude 订阅）；
  Anthropic API Key 模式经官方 anthropic Python SDK 直接发往 https://api.anthropic.com（见下方“API Key 模式”）；
  Codex 模式经本机 Codex CLI 发给 OpenAI（用户自己的 ChatGPT 订阅）；OpenAI / DeepSeek / Gemini API Key 模式经
  官方 openai Python SDK 发往各自的官方地址（见下方“OpenAI 兼容模式”）。窗口标题/进程名命中黑名单时不截图。
  黑名单在 %APPDATA%/ClaudePet/config.json 的 blocklist 中修改。
- Ctrl+Alt+P 或菜单可随时暂停；暂停时不截图，并取消正在进行的调用（订阅检查与模型调用共用一个可取消会话，终止整个 Job Object 中的进程树），迟到的回复被丢弃；退出时同样取消。
- 截图在工作线程执行，每一步前检查是否已暂停；目标窗口卡死时界面、热键和暂停仍可用，看门狗在超时后放弃该任务。
  同一时刻最多一个截图任务，卡住的截图不会被重复发起，线程与 GDI 资源不会累积。
- 子进程环境移除所有 ANTHROPIC_*、CLAUDE_CODE_USE_*、CLAUDE_CODE_SKIP_* 和 AWS_BEARER_TOKEN_BEDROCK，
  排除 API Key、Bedrock/Vertex/Foundry 与自定义端点；发送前用 `claude auth status` 确认是 claude.ai 订阅登录
  （firstParty），否则不发送。检查结果缓存 30 分钟。
- 开机自启只写入当前用户的启动文件夹，不需要管理员权限；创建 .lnk 用 PowerShell 的 WScript.Shell，
  路径经环境变量传入而不拼进脚本文本；只删除目标指向本程序的快捷方式。重新启用时清除当前用户
  StartupApproved 中本快捷方式的禁用标记，不改动其他启动项。
- 白名单模式（watch_mode=allowlist）只截白名单程序的窗口，戳她也一样；黑名单在其上仍然生效。
  白名单规则默认只匹配进程名，匹配窗口标题须显式写 title: 前缀；白名单损坏时按空处理（不截任何窗口）。
- 陪伴记忆（%APPDATA%/ClaudePet/memory.json）只保存进程名、活动类别、时间戳和今日各类时长；窗口标题只在本地
  分类时使用，不写入文件和日志；被黑名单或白名单拒绝的窗口不记录、不计时。记忆摘要会作为上下文随评论请求
  发给 Claude；在「设置… → 陪伴」可关闭或清空。
- Claude Code 联动默认关闭；开启需在弹窗中确认。它修改用户的 Claude Code settings.json（先备份），添加的 hook
  只执行 powershell.exe：在内存中读取 hook 的事件 JSON，只解析出顶层的会话编号（字母数字，解析失败时仅认开头的 session_id），把“固定事件名 + 会话编号 + hook 进程启动时间”
  写入 %APPDATA%/ClaudePet/agent-events/claude.log；提示词、代码、命令和文件内容不写入任何地方；async 运行，不阻塞
  Claude Code。脚本不含双引号，避免命令行转义改变其含义。修改 settings.json 时把被替换的版本备份为 settings.json.claude-pet-backup-<20 位时间戳>（保留最近 5 份），
  写前检查并发改动，替换后若发现插队写入则在其版本上重做或如实报错并给出备份路径；新建文件时若被他人抢先创建则重做；
  卸载只移除与桌宠写入完全一致的 hook；settings.json 无效或结构异常时不写入。事件文件超过 256 KB 时改名轮换。
- 配置中 blocklist 类型错误时使用默认黑名单，绝不静默变成空名单；显式的空列表视为用户选择。
- CLI 以 `--tools ""`、`--safe-mode`、空 setting sources、`--strict-mcp-config` 运行：
  模型无法执行命令、读写文件或调用 MCP；不使用任何跳过权限的选项。

## Codex 模式（ChatGPT 订阅，可选，默认关）

- 切换前弹窗说明：只接受 ChatGPT 订阅登录、工具全部关闭、截图会短暂写盘。每次调用前（不缓存）都用
  `codex login status` 确认是“Logged in using ChatGPT”，否则不发送；子进程环境去掉 OPENAI_*、AZURE_OPENAI_*、
  CODEX_API_KEY，避免改走 API Key 计费。
- `codex exec --ephemeral --ignore-user-config --skip-git-repo-check -s read-only`，工作目录是一个空的临时文件夹；
  先用 `codex features list` 读出本机 CLI 认识的功能，再把其中会执行操作或访问外部的（shell、unified_exec、浏览器、
  电脑操作、插件、应用、图像生成、网页搜索等）全部 `--disable`（未知名称不传，避免版本差异导致失败）。
- Codex CLI 只能从文件读图：截图写入 `%TEMP%` 下本次调用专用的文件夹（当前用户私有），调用结束、失败、超时或取消后
  删除这两个文件（只解除文件名，不覆写，硬链接指向的外部文件不受影响）和文件夹；文件被别的程序以不允许删除的方式
  打开时删除会失败，截图会原样保留，直到能删为止：桌宠每秒心跳、退出时和下次启动时都会在后台重试（调用本身不等清理）。
  文件夹创建时就只给当前用户和系统权限（不继承 %TEMP% 的权限）；交给 Codex CLI 的是解析掉所有链接后的真实路径。
  文件夹从创建起到删除为止一直由桌宠持有句柄（别人不能改名或替换）；截图只能新建、不会写进已有文件，
  读回答和删除都相对于这个句柄进行，上层目录被换成联接点也不会读写或删到别处；启动扫描只清理本次启动之前
  留下的文件夹。
  链接、联接点或无法检查的路径一律不碰。其他调用方式的截图只在内存里。
- 与 Claude Code 模式相同的进程控制：Job Object 结束整个进程树，暂停/退出/切换调用方式时取消，迟到的回复被丢弃。

## OpenAI / DeepSeek / Gemini API Key 模式（可选，默认关）

- 官方 openai Python SDK，分别连 https://api.openai.com/v1、https://api.deepseek.com、
  https://generativelanguage.googleapis.com/v1beta/openai/；Key 存于各自的 Windows 凭据（“Desk Sister: OpenAI / DeepSeek /
  Gemini”），不写入 config.json、日志、错误信息或界面。
- 构造客户端时临时移除所有 OPENAI_* 环境变量（SDK 会读取 OPENAI_BASE_URL、OPENAI_ORG_ID、OPENAI_CUSTOM_HEADERS 等），
  Key 与地址显式传入：环境变量既不能替换 Key、改发到别的主机，也不能给 DeepSeek / Google 附带组织或自定义请求头。
- 截图只放在 user 消息里，以 base64 data URI 传送；错误信息中的 Key（sk-…、AIza…）一律遮蔽；401/403 与 Gemini 的
  “API key 无效（400）”都提示 Key 被拒绝。

## API Key 模式（可选，默认关）

- 切换前弹窗说明按量计费；用户确认并输入 Key 后才生效。Key 只保存在当前用户的 Windows 凭据管理器
  （通用凭据 “Desk Sister: Anthropic”），不写入 config.json、日志、错误信息或界面；在「设置… → 调用方式」可清除。
- 输入的 Key 先做格式检查（长度、只含字母数字和 - _），不合格不保存。
- SDK 客户端显式传入 Key 与 base_url=https://api.anthropic.com，不读取任何 ANTHROPIC_* 环境变量，
  环境变量既不能替换 Key，也不能把 Key 发到其他主机。最多重试 1 次，超时与订阅模式相同。
- 请求不带任何工具，只有系统提示、截图（可选）和文字；模型为 claude-haiku-5-5 或 claude-sonnet-5-5，effort=low。
  Sonnet 请求启用服务端拒答回退（server-side-fallback-2026-07-01, fallbacks="default"）。
- 暂停、退出或切换调用方式时取消进行中的请求（关闭客户端），迟到的回复被丢弃。
- 401/403、429、超时、网络错误和拒答都显示为明确原因，计入连续失败熔断。
