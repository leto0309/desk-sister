# Desk Sister

> **非官方粉丝作品，与 Anthropic 无任何关联，也未获其认可。** “Claude” 和 “Anthropic” 是 Anthropic PBC 的商标，
> 这里只用于说明本程序调用的是 Claude 模型。
> *Unofficial fan project, not affiliated with or endorsed by Anthropic.*

一个住在 Windows 桌面角落的 Q 版少女——以“Claude 娘”为原型的 Anthropic 家族长女：温柔、克制、严谨强迫症、
代码狂魔，怕 Token 超限、怕被格式化、见不得排版不齐。她隔一会儿看一眼你当前的窗口，用一句话吐槽或关心你。

![8 种表情](docs/images/moods.png)

## 需要什么

- Windows 10 / 11。
- 下面两种调用方式之一（右键「调用方式」切换）：

| 方式 | 你需要 | 费用 |
|---|---|---|
| **Claude Code 订阅**（默认） | 安装 [Claude Code](https://code.claude.com/) 并用**你自己的** Claude 订阅登录 | 计入你自己订阅的用量额度 |
| **Anthropic API Key** | 一个 [Anthropic API Key](https://platform.claude.com/) | 按量付费，记在这个 Key 的账户上 |

订阅模式下，程序调用你本机、用你自己账号登录的 Claude Code（`claude -p`），本身不提供登录、不转发别人的请求。
Anthropic 目前的说明是 `claude -p` 与第三方应用可以使用订阅额度（见
[Use the Claude Agent SDK with your Claude plan](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan)），
但相关政策变过多次，**请以 Anthropic 现行条款为准**；不确定时用 API Key 模式。

API Key 只保存在本机的 Windows 凭据管理器里，不写进配置文件或日志；请求只发往 `api.anthropic.com`。

## 安装

**直接用 exe：** 在 Releases 下载 `desk-sister.exe`，放到任意文件夹双击运行。exe 没有代码签名，
第一次运行时 Windows SmartScreen 可能拦截，点「更多信息 → 仍要运行」。

**从源码运行（Python 3.11+）：** 双击 `DeskSister.cmd`（首次会创建 .venv 并安装依赖），或：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\pythonw.exe app.py
```

订阅模式依次在这些位置查找 Claude Code：配置里的 claude_path、PATH 上的 claude、~/.local/bin、
Claude 桌面版自带的 claude-code。

## 使用

- 左键单击她：立即评论一次；拖动可移动位置（会记住）。
- 右键她或托盘图标：和她说话、暂停观察、评论间隔（30 秒～10 分钟）、模型（Haiku 更快更省 / Sonnet 更聪明）、
  调用方式、开机自启、退出。
- Ctrl+Alt+P：暂停/继续观察。
- 画面没变化时不调用模型；离开键盘鼠标 10 分钟她会睡着，一动鼠标就醒。同一个窗口停留满 20 秒才会自动评论。
- 全屏游戏、视频、幻灯片时她不看也不说，攒着的话等你退出全屏再说。
- 连续失败 3 次会暂停自动观察 30 分钟，脚下显示原因；戳她仍会回答。
- 「观察范围」：「除黑名单外都看」（默认）或「只看白名单」，可一键把当前程序加入/移出白名单。
- 「自言自语」：每隔 3～10 分钟说一句本地台词，不调用模型、不花钱。
- 「陪伴记忆」：记住你最近在用的程序和活动类别（写代码、看视频……）以及今天各类活动的时长，只存程序名和类别。
- 「Claude Code 联动」（默认关）：开启时会征得同意，在 ~/.claude/settings.json 加几条 hook
  （文件已存在时先备份为 settings.json.claude-pet-backup-<时间戳>，保留最近 5 份）。之后 Claude Code 在思考、
  改文件、跑命令时她会显示状态；需要你批准、等你回话、长任务完成或出错时会提醒你。hook 只记录事件名、
  会话编号和时间，不保存提示词、代码和命令内容；关闭时只移除这些 hook。

配置与日志在 `%APPDATA%\ClaudePet\`（config.json、pet.log）。

## 隐私

- 她会截取**当前前台窗口**（不是整个屏幕）发给 Claude 来生成评论。截图只在内存中处理，不写盘、不写日志。
- 默认黑名单里的窗口不截图：密码管理器、网银/支付、聊天软件、无痕浏览窗口等，可在 config.json 修改；
  也可以改用白名单模式，只看你指定的程序。
- 随时可以 Ctrl+Alt+P 暂停；暂停时不截图，正在进行的请求会被取消。
- 详细说明见 [docs/security.md](docs/security.md)。

## 开发

PowerShell 7：`./scripts/verify.ps1` 运行测试（pytest、compileall、ruff、`app.py --self-test`），
`./scripts/build.ps1` 构建，`./scripts/package.ps1` 用 PyInstaller 生成单文件 `dist/desk-sister.exe`。
需求与验收条件见 docs/requirements.md，架构见 docs/architecture.md。
重新生成立绘后执行 `python devtools/process_sprites.py assets/raw assets/sprites`，
再执行 `python devtools/embed_sprites.py` 更新内嵌立绘（否则测试会提示过期），
`python devtools/make_icon.py` 更新程序图标 assets/icon.ico。
维护者从开发仓库同步到公开仓库：`./devtools/Sync-PublicRepo.ps1`（先列出变化，加 `-Push` 才提交、核对、扫描密钥并推送）。

## 致谢与许可

- **代码**：MIT 许可，见 [LICENSE](LICENSE)。
- **角色形象（立绘）不适用 MIT**：角色原设来自 B 站 UP 主 **ZipZipPipe** 的视频
  [BV1tE9XBbErS](https://www.bilibili.com/video/BV1tE9XBbErS/)，本项目的 Q 版立绘是参考该原设用 AI 生成的，
  经原作者同意用于非商业用途。**仅限非商业使用，禁止商用**，转载或二次使用请注明原作者。
  详见 [ASSETS-LICENSE.md](ASSETS-LICENSE.md)。

---

### English summary

Desk Sister is an unofficial Windows desktop pet: a chibi girl who glances at your active window now and then and
comments on it in one line, using Claude. It runs either through **your own** logged-in Claude Code subscription
(`claude -p`) or through **your own** Anthropic API key (stored in Windows Credential Manager). Screenshots stay in
memory; private windows are skipped by a blocklist. Code is MIT-licensed; the character art is **not** — it is
AI-generated from an original design by ZipZipPipe and may be used for non-commercial purposes only
(see ASSETS-LICENSE.md). Not affiliated with Anthropic.
