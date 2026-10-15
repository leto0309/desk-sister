# 安全

不存储凭据、不覆盖文件、不自动合并；API 和生产部署需授权。Secrets 只配置于 GitHub。

## 截图与隐私

- 截图只在内存中处理，不写盘、不写日志；用 PrintWindow 只渲染目标窗口自身的内容，
  盖在上面的通知、置顶窗口和桌宠本身不会进入截图；窗口无法渲染（全黑）时跳过。
- 无法识别窗口所属进程时不截图；截图后重新读取窗口标题和进程，期间变成黑名单窗口则丢弃截图。
- 截图会发送给 Claude：默认经本机 Claude Code CLI 与用户自己的 Claude 订阅；用户切换到 API Key 模式后，
  经官方 anthropic Python SDK 直接发往 https://api.anthropic.com（见下方“API Key 模式”）。窗口标题/进程名命中黑名单时不截图。
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
  发给 Claude；右键菜单可关闭或清空。
- Claude Code 联动默认关闭；开启需在弹窗中确认。它修改用户的 Claude Code settings.json（先备份），添加的 hook
  只执行 powershell.exe：在内存中读取 hook 的事件 JSON，只解析出顶层的会话编号（字母数字，解析失败时仅认开头的 session_id），把“固定事件名 + 会话编号 + hook 进程启动时间”
  写入 %APPDATA%/ClaudePet/agent-events/claude.log；提示词、代码、命令和文件内容不写入任何地方；async 运行，不阻塞
  Claude Code。脚本不含双引号，避免命令行转义改变其含义。修改 settings.json 时把被替换的版本备份为 settings.json.claude-pet-backup-<20 位时间戳>（保留最近 5 份），
  写前检查并发改动，替换后若发现插队写入则在其版本上重做或如实报错并给出备份路径；新建文件时若被他人抢先创建则重做；
  卸载只移除与桌宠写入完全一致的 hook；settings.json 无效或结构异常时不写入。事件文件超过 256 KB 时改名轮换。
- 配置中 blocklist 类型错误时使用默认黑名单，绝不静默变成空名单；显式的空列表视为用户选择。
- CLI 以 `--tools ""`、`--safe-mode`、空 setting sources、`--strict-mcp-config` 运行：
  模型无法执行命令、读写文件或调用 MCP；不使用任何跳过权限的选项。

## API Key 模式（可选，默认关）

- 切换前弹窗说明按量计费；用户确认并输入 Key 后才生效。Key 只保存在当前用户的 Windows 凭据管理器
  （通用凭据 “Desk Sister: Anthropic”），不写入 config.json、日志、错误信息或界面；右键可清除。
- 输入的 Key 先做格式检查（长度、只含字母数字和 - _），不合格不保存。
- SDK 客户端显式传入 Key 与 base_url=https://api.anthropic.com，不读取任何 ANTHROPIC_* 环境变量，
  环境变量既不能替换 Key，也不能把 Key 发到其他主机。最多重试 1 次，超时与订阅模式相同。
- 请求不带任何工具，只有系统提示、截图（可选）和文字；模型为 claude-haiku-5-5 或 claude-sonnet-5-5，effort=low。
  Sonnet 请求启用服务端拒答回退（server-side-fallback-2026-07-01, fallbacks="default"）。
- 暂停、退出或切换调用方式时取消进行中的请求（关闭客户端），迟到的回复被丢弃。
- 401/403、429、超时、网络错误和拒答都显示为明确原因，计入连续失败熔断。
