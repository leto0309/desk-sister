# 架构

代码、测试和脚本分离；统一 verify/build/package 接口，技术栈由 .ai-factory.json 选择。

```
QTimer(间隔) / 戳一下 / 和她说话
        │   （UI 线程只复制状态、派发 Job、启动看门狗；可能阻塞的步骤都在工作线程）
controller.PetController ──► [工作线程] capture：前台窗口 → 进程/黑名单 → PrintWindow → 复核 → 指纹 → JPEG
        │                                                    (未变化则跳过 / 久未变化入睡)
        ├─ [工作线程] ClaudeCall 会话：auth status（订阅确认）► claude -p --input-format stream-json
        │              （每个子进程挂起启动 → 放入 kill-on-close Job Object → 恢复；取消/超时终止整个 Job）
        │              （图片在消息里，--tools "" --safe-mode，无 API Key 环境变量）
        ◄─ Signal(Outcome + generation) ── 过期结果丢弃 → persona.parse_reply → 表情|台词
        │
pet_window.PetWindow：透明置顶窗口，立绘 + 打字机气泡；托盘/右键菜单；WM_HOTKEY
```

| 模块 | 职责 |
|---|---|
| src/claude_pet/config.py | %APPDATA%/ClaudePet/config.json 读写、默认黑名单、数值夹紧 |
| src/claude_pet/persona.py | 人设系统提示、每轮提示、回复解析、兜底台词 |
| src/claude_pet/claude_client.py | 查找 claude.exe、订阅确认、构造参数与 stream-json 消息、可取消的子进程调用（超时/取消结束进程树）与输出解析 |
| src/claude_pet/capture.py | Win32 前台窗口信息、PrintWindow 窗口内容截图（线程级 DPI 感知）、隐私黑名单、画面变化检测 |
| src/claude_pet/pet_window.py | 窗口绘制、拖动/点击、全局热键消息 |
| src/claude_pet/api_client.py | 可选 API Key 模式：官方 anthropic SDK 调用、错误映射、可取消 |
| src/claude_pet/credstore.py | Windows 凭据管理器读写 API Key |
| src/claude_pet/controller.py | 调度、节流、睡眠、菜单、配置保存 |
| devtools/process_sprites.py | 把 assets/raw 生成图处理成统一裁剪的 assets/sprites |

立绘：参考 ZipZipPipe 的原设（原图不入库，见 ASSETS-LICENSE.md）；assets/raw/（不入库）由 Codex 的 gpt-image 生成；
assets/sprites/ 为处理后的 8 个表情。缺图时程序绘制占位图。
