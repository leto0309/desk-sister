# claude-pet 开发规范

本项目由 AI Dev Factory 生成，是独立的软件仓库。开始前阅读 docs/requirements.md、docs/architecture.md 和 docs/security.md。
用户指定的 Agent 负责开发；需要独立审查时，由另一个 Agent 或会话只读检查差异，自检不能代替独立审查。
功能修改使用功能分支和独立 Git Worktree（scripts/New-AgentWorktree.ps1）；不得直接向 main/master 提交功能更新。
同一目录只能有一个写入 Agent，不覆盖其他 Agent 未提交的修改。
把需求整理成可验证的验收条件，记录在 docs/requirements.md；为行为变化写真实测试。
运行 scripts/verify.ps1 和 scripts/build.ps1，修复失败并重新运行；禁止删除测试、忽略异常、伪造成功或绕过权限。
提交前检查 git status、差异和敏感信息（scripts/Scan-Secrets.ps1）。推送、PR、合并和发布需要用户授权。
不使用绕过全部权限的运行选项，不记录、输出或提交密钥。
