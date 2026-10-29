# Desk Sister 进度

接手这个项目的人或 Agent 先读这里，再读 AGENTS.md 和 docs/requirements.md。完成任务时在同一个提交或 PR 里更新本文件，只写现在的状态。

## 当前版本

- 已发布：v0.3.9（2026-10-29），附件为 `desk-sister.exe` 和 `DeskSister-Setup.exe`。
- 自 v0.3.9 以来尚未发布的改动：
  - 发布流程会附上 `SHA256SUMS.txt`，并在建立 Release 前用 `sha256sum --check --strict` 核对；
  - README（中英）的设置窗口页数更正为七页。

## 进行中

- 无。

## 待办

- Gemini、通义千问、GLM 三位的「难过」表情还缺几张图，暂时不会动。
- 身体分层动画（腿、头发）需要手工分层或请画师；更高阶的动画素材怎么做还没决定。
- 一次时间扫描测试曾在没有 CPU 占用的情况下停住约 12 小时，之后无法重现，原因不明。如再出现，记下当时的时刻、种子和网络状况。
- 最近几个版本只经过 Gemini 4 Argon 审查；Codex 额度恢复后补做一次独立审查。

## 最近的决定

- 2026-10-29：Release 附 `SHA256SUMS.txt`，供手动下载的人和校验工具核对。程序内的更新本来就核对 GitHub 提供的附件哈希，不受影响。
- 2026-10-29：Codex 额度用完期间，由 Gemini 4 Argon 做独立审查。
- 2026-10-29：测试运行加上单次时限、卡住时打印调用栈、每次运行用独立临时目录（`devtools/run_tests_at_times.py`）。
- 公开仓库只接收文件树：用 `devtools/Sync-PublicRepo.ps1` 同步，提交身份是 GitHub noreply 邮箱，开发历史不公开。

## 发布流程要点

1. 在开发仓库更新版本号并合并。
2. 用 `devtools/Sync-PublicRepo.ps1` 预览，确认后加 `-Push` 同步到公开仓库。
3. 在公开仓库手动触发 `release.yml`，输入版本号。
4. 发布后核对附件哈希（`SHA256SUMS.txt` 与 GitHub 提供的哈希），并运行 `desk-sister.exe --self-test`，再补写 Release 说明。

## 历史

- v0.3.9：摘要用语与长时间活动提醒的措辞修正，台词检查更严格。
- v0.3.8：每位角色各自的常用回复。
- v0.3.0：六位可选的 AI 角色，各有立绘、性格、台词和主题。
