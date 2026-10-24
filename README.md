# codex-auto-continue

在 Codex 额度重置后，自动继续被 usage limit 打断的会话。

它不会猜测时间：先读取账号真实的额度窗口（Codex app-server 或 CodexBar 缓存），算出“所有已耗尽窗口都重置”的时刻，再用系统调度器（macOS launchd）在那一刻唤醒；到点后把续跑消息交给 Codex App（`codex queue`，App 内可见、走自动审核），并用 rollout 文件校验新回合确实开始了。

```
scan ──► arm <thread> ──► launchd (resetsAt + grace) ──► run
                                     │
                          quota ok? ─┴─ no ─► 重新排期
                                     │
                                  yes
                                     ▼
                    codex queue --thread <id> --message "…"
                                     │
                          校验 rollout 出现新回合
                                     │
                         done / notify / 失败重试
```

## 环境要求

- Python 3.9+
- 已登录的 Codex CLI / Codex App（同一个 `~/.codex`）
- macOS：完整支持（launchd 调度）。
- Windows 10/11：CLI + Task Scheduler 调度 + 托盘 UI（见下文「Windows」）。
- Linux：CLI 可用，systemd 调度适配器尚未实现。

## 安装

```bash
git clone https://github.com/bitqyh/codex-auto-continue ~/Projects/gptwork/codex-auto-continue
cd ~/Projects/gptwork/codex-auto-continue

# 方式 A：安装成命令（可选）
python3 -m pip install -e .        # 或 pipx install .
codex-continue --version

# 方式 B：不安装，直接用仓库内的启动器
./bin/codex-continue --version
```

`bin/codex-continue` 会自动把仓库的 `src/` 加入 `PYTHONPATH`，不依赖 pip。

> 说明：Codex 插件方向已放弃（2026-10-24 决定），仓库不再提供 marketplace / 插件；三个入口中的插件入口已移除，保留 CLI 与 macOS 菜单栏。

## 快速开始

macOS 用 `codex-continue`（或 `./bin/codex-continue`）；Windows 用 `bin\codex-continue.cmd`。

```bash
# 1. 看看哪些会话因额度中断
codex-continue scan

# 2. 查看额度窗口与重置时间
codex-continue usage

# 3. 把最近一个中断线程加入自动续跑（自动排到重置后 3 分钟）
codex-continue arm --last
#   或显式指定线程 / 强制时间 / 自定义消息
codex-continue arm 01a1621c-44dc-70a3-9842-b5409a150aaf
codex-continue arm --last --at 00:20 --message "继续未完成的工作，完成后汇报"
codex-continue arm --last --edit                 # 用 $EDITOR 编辑消息
codex-continue template set --cwd ~/Projects/myapp --message "继续 myapp 的剩余任务"
codex-continue template list

# 4. 查看状态与调度器
codex-continue status

# 5. 取消
codex-continue disarm --all
```

`arm` 之后不需要保持终端或 Codex App 打开；任务由 launchd 托管，Mac 睡眠时会在唤醒后补跑。

## 命令

| 命令 | 作用 |
| --- | --- |
| `scan [--days 7] [--json]` | 扫描 rollout，找出最后回合因 usage limit 中断的线程 |
| `usage [--json]` | 读取额度窗口（primary 5h / secondary 周窗口）与重置时间 |
| `arm [thread_id] [--last] [--message TEXT] [--edit] [--at 时间] [--force]` | 登记线程并安装定时任务；交互式终端会询问消息 |
| `template list / set --cwd DIR [--message TEXT] [--edit] / remove --cwd DIR` | 按项目保存续跑消息模板（最长目录前缀匹配） |
| `message <thread_id> [--message TEXT] [--edit]` | 修改已安排线程的续跑消息（不改触发时间） |
| `disarm [thread_id] [--all]` | 取消登记 |
| `status [--json]` | 已登记线程、额度、调度器状态 |
| `run [--dry-run] [--json]` | 执行一次续跑；`--dry-run` 只读预览，不写状态、日志、缓存或调度 |
| `install` / `uninstall` | 按当前状态安装/移除平台定时任务 |
| `config [--set key=value]` | 查看/修改配置 |
| `notify-test` | 测试本地通知 |

## 配置

配置与状态位于（可用 `CODEX_AUTO_CONTINUE_HOME` 覆盖）：

- macOS：`~/Library/Application Support/codex-auto-continue/`
- Linux：`~/.local/share/codex-auto-continue/`
- Windows：`%APPDATA%\codex-auto-continue\`

`config.json` 常用项：

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `message_template` | 续跑中文模板 | 支持 `{thread_id}` 占位 |
| `grace_seconds` | 180 | 重置后再等多久触发 |
| `max_attempts` | 6 | 单线程最多尝试次数 |
| `retry_seconds` | 600 | 额度仍不可用时的重试间隔 |
| `queue_verify_seconds` | 120 | 等待 App 出现新回合的上限 |
| `quota_cache_seconds` | 300 | 额度查询缓存秒数（`status/usage` 默认走缓存，`--refresh` 强制刷新） |
| `notifications.local` | true | macOS / Windows / Linux 本地通知 |
| `notifications.email` | false | 启用 webhook 通知（见下） |
| `webhook_url` | null | 通用 webhook 地址，POST JSON |
| `codex_path` | null | 自定义 codex 可执行文件路径 |
| `project_templates` | {} | 按项目目录保存的续跑消息模板，由 `template` 命令维护 |

消息优先级：`--message` > 项目模板（最长目录前缀）> `message_template`；`{thread_id}` 会被替换。

## 通知与邮件（可选）

默认只发本地通知，不依赖任何服务。想要邮件/手机通知时，把 `config --set notify_email=true --set webhook_url=https://...` 指向任意接收 JSON 的端点即可，runner 会 POST：

```json
{"event": "thread-result", "thread_id": "…", "ok": true, "detail": "…"}
```

常见的三种落地方式：

1. **Cloudflare Worker + 邮件 API**（本仓库作者使用的方案）：Worker 校验固定共享密钥后调用邮件服务，客户端只 POST 事件 JSON。适合长期常驻的服务器。
2. **ntfy / Telegram Bot / Bark**：把 `webhook_url` 指向对应 HTTP API，事件 JSON 会被原样转发。
3. **邮件客户端脚本**：本地用 `msmtp`/`sendmail` 包装一个 HTTP 服务，或直接用 `launchd` 定时跑 `mail`。

基础版故意不内置 SMTP 配置：把邮件服务凭据留在用户自己的部署里，仓库里不保存任何密钥。

## 工作原理与边界

- **只续显式 arm 的线程**。默认不扫描全量自动续跑，避免无人值守时动到不该动的会话。
- 触发前会重新校验：线程如果已经出现新的用户消息（说明你自己继续过），直接标记 `superseded` 跳过。
- 续跑优先 `codex queue`：消息进入 Codex App，由 App 自己的自动审核执行，能访问受保护目录（macOS TCC），界面可见。
- App 未运行时回退 `codex exec --approve-for-me … resume`；若 App 仍持有该线程写锁，会如实记录失败，不静默吞掉。
- 额度判断取“所有已耗尽窗口都重置”的时刻；额度查询优先 app-server（跨平台），macOS 上回退读 CodexBar 的缓存快照。
- macOS 上定时脚本与数据必须放在 `~/Library/Application Support`，不能放 `~/Documents`（TCC 会拒绝 launchd 执行）。

## 菜单栏界面（macOS）

除 CLI 外，仓库还带一个原生 AppKit 菜单栏 app（`ui/menubar/`）：

```bash
cd ui/menubar
./build.sh --install      # 编译并安装到 ~/Applications，自动打开
```

- 状态栏图标：单色“环形重置箭头＋播放键”；空闲时只显示图标，有中断会话时附数量，已安排时附下次触发时间；图像丢失时回退文字标识
- 菜单内容：额度窗口（5h / 周 + 重置时刻）、待续跑列表、**因额度中断的会话**（可「用默认消息续跑」或「自定义消息…」）、已安排任务（可「编辑消息…」或「取消续跑」）、刷新、打开运行日志、打开 Codex App、指定 CLI 路径、开机自动启动
- 会话名与 Codex 会话列表一致：读取 Codex 状态库 `threads.name`（改名后同步），退化时依次用首条消息标题、目录名
- 每 60 秒自动刷新，打开菜单时也会刷新；全部操作走同一套 CLI，不另存状态
- 权限：不需要管理员；不需要全盘访问/辅助功能；只有「开机自动启动」会写一个 `~/Library/LaunchAgents` 项
- 单实例保护：重复启动会被退出（`Application Support/codex-auto-continue/menubar.lock`），不会出现两个状态栏图标；打开「开机自动启动」只写登录项、不会当场再拉起一份

自检（无需看界面，验证菜单项能正常生成）：

```bash
./build/CodexContinue.app/Contents/MacOS/CodexContinue --ui-selftest
```

需要 Xcode 命令行工具（`swiftc`）编译；app 用 ad-hoc 签名，本地使用足够。

#### 图标不在菜单栏显示？

先确认图标已装上：

```bash
~/Applications/CodexContinue.app/Contents/MacOS/CodexContinue --ui-selftest | grep ui-icon
# 期望：ui-icon: true template: true
ls ~/Applications/CodexContinue.app/Contents/Resources/statusTemplate*
```

常见原因：

- **Bartender 等在管理菜单栏**：Bartender 6 会把未显式 Show 的第三方项挪到屏幕外（隐藏栏里也可能不列出）。若之前装过旧 bundle id 的版本，系统可能记住旧的屏幕外位置；换新 bundle id（v0.2 起为 `local.qyh.codex-auto-continue.menubar`）或临时退出 Bartender 后重启 app 即可恢复，然后在 Bartender 里拖到可见区。
- **菜单栏空间不足 / 刘海遮挡**：按住 ⌘ 拖动图标调整位置；本 app 用 `autosaveName` 记住位置。
- **app 没在运行**：`pgrep -fl CodexContinue`，或重新 `open ~/Applications/CodexContinue.app`。

### 图标资源

整套图标采用石墨黑（`#101A1B`）、薄荷绿（`#7EECC0`）与暖白：环形箭头表示额度重置，播放键表示继续任务。

- 应用：`ui/menubar/assets/AppIcon.icns`、1024px PNG 与 SVG 母版、完整 `AppIcon.iconset`。
- 菜单栏：18pt `statusTemplate.png` 及 @2x / @3x，由 AppKit template 模式适配深浅色。

重新生成（只需 macOS 原生工具，不增加 Python 依赖）：

```bash
swift scripts/build_icons.swift
iconutil -c icns ui/menubar/assets/AppIcon.iconset -o ui/menubar/assets/AppIcon.icns
ui/menubar/build.sh --install
```

`run --dry-run` 仅读取状态及新鲜的本地额度缓存，不启动 app-server，不发送消息、不获取运行锁、不防睡，也不改变文件和调度；没有新鲜缓存时会标记额度未知，正式执行仍强制刷新。

## 资源占用

| 项 | 占用 |
| --- | --- |
| 菜单栏 app `~/Applications/CodexContinue.app` | ~200 KB |
| Windows 托盘（PowerShell 脚本 + 图标） | ~50 KB，常驻 ~50 MB |
| 数据目录（状态/日志/额度缓存） | ~20 KB，日志按 256 KB × 3 滚动 |
| 菜单栏常驻 | RSS ~37 MB，自身 CPU 0%；每 60 秒刷新一次 |
| 暖刷新（默认） | ~0.05 秒：直接读额度缓存 |
| 每次刷新额外开销 | 扫描 rollout ~1.2 秒（python 子进程 ~30 MB），仅当菜单/定时需要时运行 |
| 冷刷新（每 5 分钟一次） | 5–12 秒，临时拉起 `codex app-server --stdio`（峰值 RSS ~125 MB），随即退出 |
| 综合 CPU 占用 | 菜单栏运行时约占单核 2–4%（清醒时），合计磁盘 ~0.3 MB |
| 定时任务 | 只在触发时刻运行一次 runner（python ~30 MB），续跑由 Codex App 执行；本工具没有常驻守护进程 |

额度缓存可用 `codex-continue config --set quota_cache_seconds=300` 调大，或 `status --refresh` 强制刷新。

## Windows（Windows 10/11）

前置：Python 3.9+、已安装并登录 Codex（Windows 版）、仓库已 clone。

```bat
cd codex-auto-continue
bin\codex-continue.cmd usage
bin\codex-continue.cmd scan
bin\codex-continue.cmd arm --last --message "继续未完成的工作"
bin\codex-continue.cmd status
bin\codex-continue.cmd disarm --all
```

`arm` 会通过 `schtasks` 创建名为 `CodexAutoContinue` 的计划任务（任务带 `WakeToRun`、`StartWhenAvailable`，仅在当前用户登录时运行、不保存密码）；`status` 可查看任务状态，`uninstall` 会删除任务。

### 托盘界面

```bat
ui\windows-tray\CodexContinueTray.vbs
```

- 功能与 macOS 菜单栏一致：额度、待续跑、因额度中断的会话（默认/自定义消息续跑）、已安排任务（编辑消息/取消）、刷新、日志、开机自启
- 纯 PowerShell + WinForms，无第三方依赖；日志在 `%APPDATA%\codex-auto-continue\tray.log`
- 开机自启通过当前用户启动文件夹的快捷方式实现，不需要管理员权限

已知限制：计划任务只在用户登录时运行；关机期间错过的任务不会补跑（与 macOS 设计一致）。

真机验收清单与诊断脚本：`docs/WINDOWS-TESTING.md`、`scripts/windows-diagnostics.ps1`。

## 睡眠处理

- **睡眠不丢任务**：到点时机算任务是 launchd `StartCalendarInterval`，Mac 在睡时会等**唤醒后补跑**（可能晚于原定时间）。
- **执行期间防睡**：runner 用 `caffeinate -i`（macOS）在运行窗口内阻止空闲睡眠，跑完即释放。
- **关机/断电不补跑**（按设计不处理）：关机期间错过的定时不会在下次开机时自动补执行；需要补的话重新 `arm` 即可。
- 想精确到点（比如 00:19 准点而不是等自然醒）只能加上 `pmset schedule wake`，需要 sudo，且合盖/Apple Silicon 定时开机会受限，本项目未内置。

## 开发与测试

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

GitHub Actions 会在 Ubuntu / macOS / Windows 三平台跑同一套测试（Windows 上的 launchd 用例自动跳过）。

测试包含：rollout 解析、额度 JSON 解析、触发时间计算、状态/锁、以及用假 `codex` 可执行文件跑通的 queue 成功、queue 失败回退 resume、线程已继续等场景。

## 路线图

- [x] macOS launchd 调度器
- [ ] Linux systemd user timer 适配器
- [x] Windows Task Scheduler 适配器（`schtasks` + XML，WakeToRun/StartWhenAvailable）
- ~~Codex 插件方向~~：2026-10-24 决定放弃，已从仓库移除
- [ ] 可选的“自动扫描全部中断线程 + 项目白名单”模式
- [x] macOS 菜单栏 app（`ui/menubar`，原生 AppKit）
- [x] Windows 托盘 UI（PowerShell + WinForms，`ui/windows-tray`）
- [x] 续跑消息自定义：`arm` 交互输入 / `--edit`（$EDITOR）、`template` 按项目保存模板
- [x] 睡眠处理：launchd 唤醒补跑 + `caffeinate` 保护执行窗口
- [ ] 可选：陪跑模式（queue 后盯 rollout 期间保持唤醒）
- [ ] 可选：`pmset schedule wake` 定时唤醒（需 sudo；合盖与 Apple Silicon 定时开机会受限）

## License

MIT
