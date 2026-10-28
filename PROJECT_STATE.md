# PROJECT_STATE · codex-auto-continue

> 交接记录（供接手对话核对与继续）。创建：2026-10-24 14:20 CST。
> 交接编号：**HO-2026-10-24-01**

## 1. 任务与版本

- **目标**：Codex 账号额度（usage limit）重置后，自动让被中断的会话继续。
- **交付形态**：跨平台 CLI（核心，Python 标准库）＋ macOS 原生菜单栏 app ＋ Windows Task Scheduler 调度与 PowerShell 托盘。Codex 插件方向已放弃（2026-10-24 决定），marketplace/插件文件已从仓库移除。
- **当前版本**：`0.6.0`（`src/codex_auto_continue/__init__.py`）。
- **权威工作目录**：`/Users/qyh/Projects/gptwork/codex-auto-continue`（已部署，菜单栏 app 由此构建）。
- **开发镜像**：`/Users/qyh/Documents/deepseek-harness/default-workspace/codex-auto-continue`（由权威目录 rsync 同步，排除 `.git` 与构建目录）。
- **版本控制**：git 仓库，tag `v0.6.0`，已推送 GitHub：https://github.com/bitqyh/codex-auto-continue
- **更新时间**：2026-10-28 10:50 CST。Windows 真机验收已完整通过（2026-10-25 23:41，真实新回合成功）；发布流水线已实现（Windows Inno 安装器未签名、macOS universal app + ad-hoc dmg、Release 自动构建与校验和）；当前版本 0.5.1。SignPath Foundation 申请未通过，项目回到不签名方案。

## 2. 权威资料

| 资料 | 路径 | 用途 |
| --- | --- | --- |
| 用户说明 | `README.md` | 安装、命令、配置、资源占用 |
| 实现 | `src/codex_auto_continue/` | 全部逻辑（唯一源码权威） |
| 仓库内 CLI 启动器 | `bin/codex-continue`（POSIX）、`bin/codex-continue.cmd`（Windows）、`bin/codex-continue-hidden.vbs`（无窗口） | 把 `src/` 加入 PYTHONPATH 后运行 CLI |
| Windows 调度 | `src/codex_auto_continue/scheduler/windows.py` | Task Scheduler XML（WakeToRun/StartWhenAvailable） |
| Windows 托盘 | `ui/windows-tray/` | PowerShell + WinForms 托盘、图标、启动脚本 |
| CI | `.github/workflows/test.yml` | Ubuntu/macOS/Windows 三平台跑测试 |
| 验收测试 | `tests/` | 48 个 unittest 用例（原 41 + 本轮 7 个回归） |
| 菜单栏源码 | `ui/menubar/main.swift`、`ui/menubar/build.sh` | 原生 AppKit app |
| 运行时数据 | `~/Library/Application Support/codex-auto-continue/` | `state.json`、`run.log`、`quota-cache.json` |
| 菜单栏安装位置 | `~/Applications/CodexContinue.app` | 已安装并在运行 |
| Codex 会话名来源 | `~/.codex/state_*.sqlite` 的 `threads.name` | 菜单/CLI 显示名 |

说明：`src/` 是唯一源码权威；菜单栏 app 通过 `bin/codex-continue` 调用 CLI。

## 3. 决定与限制

### 用户已确认

1. ~~最终做 Codex 插件、win/mac 通用~~ → **2026-10-24 用户决定放弃 Codex 插件方向**，保留 CLI + macOS 菜单栏；跨平台只保留 CLI 侧。
1. **Windows 方向**：用户 2026-10-24 决定调度适配器 + 托盘一起做，已有实体/云 Windows 可做真机验收；Linux systemd 暂缓。
2. **只续显式 arm 的线程**，不自动扫描全量。
3. 基础版 **只做本地通知**；邮件作为可选 webhook 方式写在 README，不内置任何凭据。
4. **不做关机补跑**；只处理睡眠（唤醒后 launchd 补跑 + 执行期间 `caffeinate`）。
5. 可视化做 **macOS 菜单栏**（已完成），Windows 托盘之后再做。
6. 菜单栏支持**编辑已安排任务的消息**（已实现）。
7. **图标由本轮接手 Agent 重新设计并接入**。用户明确选择“交给你，按推荐直接完成”：石墨黑＋薄荷绿、环形重置箭头＋播放键、配套单色菜单栏图标；替代此前“图标由用户另行设计”的限制（见 §6）。

### Agent 选择（接手可改，但需说明理由）

- 额度源：优先 `codex app-server --stdio` 的 `account/rateLimits/read`，失败回退 CodexBar 缓存；结果缓存 300 秒（`quota_cache_seconds`）。关键执行时刻（runner）强制刷新。
- 续跑执行：优先 `codex queue --thread <id> --message`（App 内可见、走 App 自动审核、可访问 Documents）；失败回退 `codex exec --approve-for-me … resume`（App 持有 writer 时会失败）。
- 调度：launchd 单次 `StartCalendarInterval`，每次重排用新代号 `local.codex-auto-continue.gN`，先装新任务/落盘状态、再删旧 plist/bootout；锁用 PID 存活检测回收。
- 触发时间 = 所有“已耗尽窗口”中最后重置者 + `grace_seconds`(180s)。
- 会话名读 Codex 状态库 `threads.name`，回退首条消息标题、再回退目录名。
- 菜单栏 60 秒刷新；额度缓存避免频繁拉起 app-server。

### 限制与已知坑

- 自动调度：macOS launchd 已完整验证；Windows Task Scheduler 已真机验证（v0.4.3）；Linux systemd 仍是明确报错的占位（`scheduler/systemd.py`）。
- **Windows 真机适配（本轮发现）**：
  - `codex queue` 只有 Codex App 提供，纯 CLI（codex-cli 0.119）没有；runner 自动检测（`codex queue --help` 是否含 `--thread/--message`），不支持时跳过 queue 直接回退 `codex exec ... resume`；新版 CLI 用 `--sandbox workspace-write`，旧版仍用 `--approve-for-me`。
  - Codex App 的 CLI 不在 PATH（本机在 `%USERPROFILE%\.codex\.sandbox-bin\codex.exe`）；`usage.find_codex` 增加 Windows 候选路径探测，仍可用 `config --set codex_path=...` 覆盖。
  - 当前 CLI 的 app-server 不接受 `--stdio`（exit 2），`usage` 改为先探测帮助再选择 `app-server` 或 `app-server --stdio`。
  - 计划任务经 `bin\codex-continue-hidden.vbs` 无窗口启动；VBS 必须显式用 `cmd.exe /d /c` 启动 `.cmd`，否则 Task Scheduler 环境会弹「打开文件 - 安全警告」并永久挂起计划任务（本轮真机复现并修复）。
  - 本机 Codex 登录 refresh token 已失效（401 `refresh_token_reused`），`usage`/`resume` 都会在鉴权层失败；需要用户重新 `codex login`。直连 OpenAI 被 DNS 污染，代理（如 `127.0.0.1:7890`）需写入用户环境变量 `HTTPS_PROXY/HTTP_PROXY` 后重新登录，计划任务才能继承。
  - Windows `state_*.sqlite` 的 `threads` 表没有 `name` 列时（0.119 只有 `title`），标题解析改为按实际列自适应。
  - `schtasks` 输出本地化（中文「下次运行时间」）与代码页问题：`describe` 兼容中英文标签并用任务 XML 兜底，`schtasks` 输出按系统代码页解码。
- 需要 **Python 3.9+**；菜单栏重编译需要 Xcode 命令行工具（`swiftc`）。
- 关机/断电期间错过的任务**不会**在下次开机补跑（用户明确不要）。
- macOS TCC：launchd 任务不能访问 `~/Documents`；脚本与数据必须在 `~/Library/Application Support`。
- Codex App 运行中会持有会话 writer，`codex exec resume` 会被拒；此时只能用 `codex queue`。
- app-server 冷启动 5–12 秒（临时进程 ~125 MB），靠 300 秒额度缓存摊薄。
- 本地通知可能需要在 系统设置 → 通知 中允许对应 App。

## 4. 进展与运行状态

### 已完成并验证

- CLI 全部命令：`scan / usage / arm / message / disarm / status / run / install / uninstall / template / config / notify-test`。
- **48 个测试通过**（`PYTHONPATH=src python3 -m unittest discover -s tests`；本轮在权威目录重跑通过，Python 3.9.6）。
- **dry-run 真正只读**：预览在创建调度器、运行锁与 caffeinate 前返回；不写状态、日志、额度缓存，不启动 app-server，不发送消息；单线程预览复制输入对象。只读取新鲜本地额度缓存，缺少缓存则明确额度未知；正式执行仍强制刷新。
- **额度缓存时间修复**：CodexBar 的 `updatedAt` 缺失或无效时，使用文件修改时间，避免把旧缓存当作刚更新。
- **独立代码审查**：发现缓存时间问题，新增回归观察失败后修复；最终 48/48。
- 菜单栏 app：本轮重新编译、安装到 `~/Applications/CodexContinue.app` 并打开；包含 AppIcon.icns 与 18pt template 图片。空闲／中断／已安排／错误四种状态均以假 CLI 完成原生 `--ui-selftest`，`ui-visible: true`、`ui-icon: true template: true`，数量、时间、菜单动作保持正常。
- **真实续跑验证（用户已确认“测试成功”）**：2026-10-24 00:19:22 对线程 `01a1621c-44dc-70a3-9842-b5409a150aaf`（会话名「构建 PROJECT ALIBI 原型」）成功 `queue`，App 开始新回合；证据在 `run.log`：
  - `queue accepted and a new turn started (App visible)`
  - `all armed threads finished; removing scheduler job`
- 当前无已安排任务：`~/Library/LaunchAgents` 无 `codex-auto-continue*`；`state.json` 中唯一线程状态 `done`。
- **Windows（v0.4.3，真机验证完成）**：`scheduler/windows.py` 用 `schtasks /Create /XML` 注册 `CodexAutoContinue` 任务（`WakeToRun`、`StartWhenAvailable`、`InteractiveToken`）；托盘为 PowerShell + WinForms（`ui/windows-tray`），功能对齐 macOS 菜单栏；`bin/codex-continue.cmd` 为 Windows 启动器；Windows PID 存活检测、`.cmd` codex 路径、PowerShell Toast 已加；CI 增加三平台矩阵。**已在实体 Windows 11 上跑通，详见下方本轮验收条目**。
- 原交接时记录有 2 个因额度中断、**未安排**的会话（本轮未重新扫描，不能当作实时列表）：`分析题目解法思路`、`查找隔空手势操作电脑的方法`（随时可用 `arm`）。

- **Windows 真机验收（2026-10-24，Windows 11 22631 实机，v0.4.3 工作树）**：
  - 环境：Python 3.12.6（PATH 另有 Anaconda）、未安装 PowerShell 7（使用 Windows PowerShell 5.1）、codex-cli 0.119.0-alpha.11（位于 `%USERPROFILE%\.codex\.sandbox-bin\codex.exe`，不在 PATH）、无 Codex App。
  - CLI：`bin\codex-continue.cmd --version` → 0.4.3；`scan --days 3650` 读到 2 个真实 rollout（均非中断）；`status` 正常；`usage` 在修复 app-server 参数后能启动 RPC，但因账号 refresh token 失效返回 quota null（预期失败）。
  - Task Scheduler：`arm --force <thread> --at HH:mm` 成功创建 `CodexAutoContinue`；注册 XML 含 `WakeToRun`/`StartWhenAvailable`；CIM 读取确认 `WakeToRun=True`、`StartWhenAvailable=True`、Run As User=当前用户、InteractiveToken、LeastPrivilege；`status --json` 显示下次触发时间；`schtasks /Run` 与**到点自动触发**都实际执行 runner，`run.log` 出现 `quota unavailable ... continuing without quota gate`、线程 superseded、`all armed threads finished; removing scheduler job`，任务随后自动删除。
  - VBS：修复「打开文件 - 安全警告」挂起后，计划任务真实运行并写下 run.log。
  - 续跑链路：构造临时 `CODEX_HOME`（真实 rollout 副本 + 在用的登录态）验证 queue 不支持→跳过→`codex exec --sandbox workspace-write --skip-git-repo-check -o ... resume` 调用真实 CLI，到达网络/鉴权层后因 `401 refresh_token_reused` 失败；`attempts=1`、`last_error` 完整写入 state 与 run.log。真实新回合未能产生，原因是账号登录失效，不是代码。
  - 诊断脚本：`scripts\windows-diagnostics.ps1` 实机跑通；修复了 PS 5.1 解析、UTF-16 XML/UTF-8 日志读取、codex 定位等问题。
  - 单元测试：Windows 上 `python -m unittest discover -s tests` → **68 个通过（2 skipped）**，新增 Windows 回归用例 14 个。
  - 托盘：13 项菜单实机观测（真实 %APPDATA% + 隔离数据）；`CodexContinueTray.vbs` 的 UTF-8 BOM 导致 WSH「无效字符」→ 改 ASCII 后静默启动通过；开机自启快捷方式创建/删除通过；PS 5.1 下 CLI stderr 中断 JSON、mutex abandoned、日志目录/「打开运行日志」路径、中文 tooltip 均修复；数据刷新改异步（`Start-Job` + 750ms Timer），菜单打开 **23.66s → 0.13s**；arm/自定义消息/编辑/取消未逐项点击（本机无法真实续跑，沙箱内子菜单不可稳定展开）。

### 未做 / 未验证

- **Windows 真实新回合（未完成）**：本机 Codex 登录 refresh token 已失效（401 `refresh_token_reused`）；需用户 `codex login`（必要时先写入代理用户环境变量）后重跑 `arm` 才能产生真实新回合。代码链路已验证到鉴权层，queue 跳过/resume 参数/日志均正确。
- **Windows 睡眠/唤醒实机测试（未做）**：本机仅支持 S0 现代待机，`powercfg /waketimers` 需要管理员权限；已验证任务 XML 与 CIM 的 `WakeToRun=true`、`StartWhenAvailable=true`，但未实际让机器进入睡眠（避免打断当前会话）。需要时可按 docs/WINDOWS-TESTING.md §4 由用户手动睡眠验证。
- **Windows 托盘**：本轮已实机验证并修复（13 项菜单观测、VBS 静默启动、开机自启、异步刷新 23.66s→0.13s 等，见 §4）；`arm/自定义消息/编辑消息/取消续跑` 未逐项点击（本机无法真实续跑，沙箱内子菜单不可稳定展开）；已知限制：PS 5.1 原生参数引号会破坏含 ASCII 双引号的自定义消息（默认中文消息不受影响）。
- Linux systemd user timer 适配器。
- 自动扫描全部中断线程 + 项目白名单模式。
- `pmset schedule wake` 定时唤醒（可选，需 sudo）。
- 无新的图标待办；后续如需改变品牌方向再改 SVG／Swift 母版。
- ~~GitHub 仓库初始化与推送~~（已完成：https://github.com/bitqyh/codex-auto-continue）
- **Release 分系统产物（v0.5.0 已实现）**：tag 触发 `.github/workflows/release.yml`，产出 Windows Inno 安装器（内嵌 Python，**未签名**）、Windows 便携 zip、macOS universal dmg（ad-hoc）、SHA256SUMS。
- **签名状态（2026-10-26 更新）**：SignPath Foundation 申请未通过，项目回到**不签名**方案：Windows 安装器发布为 `-unsigned.exe`，macOS 保持 ad-hoc（未公证）。仓库已移除 `SIGNPATH_*` Secrets 要求和签名步骤；`SHA256SUMS` 仅做完整性校验。
- **Windows 真机验收结论（2026-10-24，已被 2026-10-25 完整通过取代）**：第一轮 68 tests / 2 skipped 通过，真实续跑被 Codex 账号 refresh token 失效阻塞；后续通过重登录 + model/proxy 配置完成真实新回合。
- **Windows 端到端验收通过（2026-10-25 23:41）**：计划任务自动触发 → queue 回退 → `codex exec resume` 成功，state done/attempts=1，rollout 68→86 行；关键配置 `codex_path` 指向 App 自带 CLI 0.164、`model=gpt-6.1-sol`、`proxy=http://127.0.0.1:7890`。修复提交 `cbce0b6`、`d52cf03`。
- **v0.5.0 Release（2026-10-25）**：https://github.com/bitqyh/codex-auto-continue/releases/tag/v0.5.0 （早于最终 Windows 修复，已被 v0.5.1 取代）
  - `CodexContinue-Setup-0.5.0-unsigned.exe`（11.1 MB，当时未签名）
  - `CodexContinue-0.5.0-win-x64.zip`（11.5 MB，内嵌 Python，pth 已含 `..\src`）
  - `CodexContinue-0.5.0-macOS.dmg`（1.6 MB，universal arm64+x86_64，ad-hoc 签名）
  - `SHA256SUMS`；release workflow 在 windows-latest 上通过了安装器静默安装 + `codex-continue --version` 冒烟
  - 三平台 tests 全绿；`release.yml` 仅在 tag 触发，Windows 安装器由 finalize 脚本改名为 `-unsigned.exe`
- **邮件通知接入（2026-10-28）**：复用 `codex-quota-email` 的 Cloudflare Worker，新增 `POST /auto-continue`（commit `2cb480f`，已部署到 `notify.qyhgroup.uk`，沿用同一 `AUTH_SECRET`/发件域名/固定收件人）；`codex-auto-continue` 新增 `notifications.email_endpoint`、`notifications.email_secret_file` 与 `notify-test --email`，每处理一个线程发一封（`event=thread-result`）。本机已配置并实测：本地通知 + 邮件中继均成功（2026-10-28），密钥文件 `~/Library/Application Support/CodexQuotaEmail/auth.secret`（0600）。
- **v0.6.0 Release（2026-10-28）**：https://github.com/bitqyh/codex-auto-continue/releases/tag/v0.6.0 — 包含邮件中继接入；Windows 安装器仍为 `-unsigned.exe`，macOS 为 ad-hoc dmg；SHA256SUMS 已校验。
- **v0.5.1 Release（2026-10-26）**：https://github.com/bitqyh/codex-auto-continue/releases/tag/v0.5.1 — 包含最终 Windows 修复（model/proxy、`--force` 等）；Windows 安装器未签名（`-unsigned.exe`），macOS 为 ad-hoc dmg。

## 5. 接续动作

**下一步（按优先级）**：

1. **Windows 收尾已完成**：2026-10-25 真实新回合验证通过；无需再 `codex login`/`arm`。剩余仅睡眠/唤醒实机测试（可选）。
2. Windows 睡眠/唤醒实机验证：按 docs/WINDOWS-TESTING.md §4 手动睡眠，确认 `WakeToRun` 唤醒或唤醒后 `StartWhenAvailable` 补跑（需管理员 `powercfg /waketimers` 辅助确认）。
3. Linux systemd user timer 适配器（可选）。
4. 可选：`pmset schedule wake` 精准唤醒（需 sudo，合盖/Apple Silicon 有限制）。
5. ~~Release 分系统产物~~（v0.5.0/v0.5.1 已实现）：Windows Setup.exe（不签名）+ 便携 zip、macOS dmg（ad-hoc）、SHA256SUMS；见 docs/RELEASING.md。

**前置条件**：Python 3.9+、Codex 登录有效（同一 `~/.codex`）、可选 Xcode CLT；Windows 建议 Windows 10/11 + 已登录的 Codex CLI/App。

**验收方法**：

```bash
cd /Users/qyh/Projects/gptwork/codex-auto-continue
PYTHONPATH=src python3 -m unittest discover -s tests          # 79 pass
PYTHONPATH=src python3 -m codex_auto_continue status --json    # 正常输出
PYTHONPATH=src python3 -m codex_auto_continue run --dry-run    # 无副作用
ui/menubar/build/CodexContinue.app/Contents/MacOS/CodexContinue --ui-selftest  # 菜单结构
```

```bat
cd C:\path\to\codex-auto-continue
bin\codex-continue.cmd --version
bin\codex-continue.cmd scan --days 3650
bin\codex-continue.cmd status
bin\codex-continue.cmd arm --last --message "继续未完成的工作"
schtasks /Query /TN CodexAutoContinue /V /FO LIST
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows-diagnostics.ps1
```

**阻塞项**：Windows 真实新回合目前被本机 Codex 登录失效阻塞（`401 refresh_token_reused`），需用户重新登录后才能完成最终验收；其余 Windows 验收项已跑通。已知无效路线：不要尝试用 `codex exec resume` 去接 App 正在持有的线程（会报 writer 冲突）；纯 CLI 没有 `codex queue`（Codex App 专属）。

## 6. 图标已完成（本轮）

- 方向：环形重置箭头＋播放键；石墨黑 `#101A1B`、薄荷绿 `#7EECC0`、暖白。
- 应用：`ui/menubar/assets/AppIcon.icns`、`AppIcon.png`（1024px）、`AppIcon.svg`、完整 `AppIcon.iconset`；构建脚本拷入 Resources 并写 `CFBundleIconFile=AppIcon`。
- 菜单栏：`statusTemplate.svg`、18／36／54px PNG；AppKit `isTemplate=true` 适配深浅色；保留数量和触发时间，缺图回退文字。
- 可重复生成：`swift scripts/build_icons.swift`，再用 README 的 `iconutil` 命令打包；只用 macOS 原生工具，无新增 Python 依赖。
- 图标由代码原生矢量绘制；未调用图片生成 API、无额外图片生成费用。
- 本轮未触发真实 queue/resume、未修改任务登记或真实调度；原有真实续跑成功证据保留。
- 验证边界：未重新测试生产续跑／关机行为；未切换系统深浅外观，已检查两种颜色的渲染预览及原生 template 属性。

## 7. 交接区

| 字段 | 值 |
| --- | --- |
| 交接编号 | **HO-2026-10-24-01** |
| 源任务 | 本 DSH 会话（项目开发会话）；被续跑的 Codex 会话 `01a1621c-…` 是对象，不是本项目开发会话 |
| 用户确认范围 | 原范围为仅保存材料；本轮用户人工恢复并授权继续开发、重新设计整套图标，选择“交给你，按推荐直接完成”。未新建其他接手任务 |
| 接手任务编号 | 当前人工恢复对话（编号未核实；未另建任务） |
| 交接状态 | **已接手**；2026-10-24 15:45 CST 完成插件方向移除、v0.3.0 发布 |
| Windows 验收 | 2026-10-24 23:30 CST，Windows 11 22631 实机完成 CLI/Task Scheduler/托盘/诊断脚本验收并修复 6 个缺陷，版本 0.4.3；真实新回合待用户重新 `codex login`。证据见 `docs/WINDOWS-TESTING.md` §8 与 `scripts/windows-diagnostics.ps1` 生成的诊断文件。 |
| 恢复入口 | 新对话中调用 `$project-handoff`，项目根目录 `/Users/qyh/Projects/gptwork/codex-auto-continue`，交接编号 HO-2026-10-24-01 |

## 8. 常用命令速查

```bash
cd /Users/qyh/Projects/gptwork/codex-auto-continue

# 用源码运行
PYTHONPATH=src python3 -m codex_auto_continue scan --days 14
PYTHONPATH=src python3 -m codex_auto_continue arm --last --message "继续未完成的工作"
PYTHONPATH=src python3 -m codex_auto_continue status
PYTHONPATH=src python3 -m codex_auto_continue disarm --all

# 仓库内启动器（无需 PYTHONPATH）
./bin/codex-continue status

# 改完源码后
ui/menubar/build.sh --install

# 测试邮件中继（需先配置 email_endpoint/email_secret_file）
PYTHONPATH=src python3 -m codex_auto_continue notify-test --email

# 发版构建（不推送，仅本地校验）
python3 scripts/check_version.py --tag v0.5.0
./scripts/build_macos_release.sh
# Windows: pwsh ./scripts/build_windows_bundle.ps1 -Version 0.5.0
#          ISCC.exe /DAppVersion=0.5.0 installer\codex-auto-continue.iss

# 同步开发镜像（权威目录 → 镜像）
rsync -a --delete --exclude '__pycache__' --exclude '*.pyc' --exclude '.git' \
  --exclude 'ui/menubar/build' \
  /Users/qyh/Projects/gptwork/codex-auto-continue/ \
  /Users/qyh/Documents/deepseek-harness/default-workspace/codex-auto-continue/

# 查看运行记录
tail -n 20 "$HOME/Library/Application Support/codex-auto-continue/run.log"
```
