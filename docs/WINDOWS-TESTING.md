# Windows 真机验收清单（交给 Windows 上的 DSH / Agent）

版本基线：`v0.4.3`（Windows 真机验收轮，工作树）。macOS 侧已完整验证；Windows 侧代码已完成、CI 在 `windows-latest` 跑通单元测试。本清单用于在真实 Windows + 真实 Codex 上端到端验证；2026-10-24 已在 Windows 11 22631 实机执行一轮，结果见 §8。

工作目录：`C:\path\to\codex-auto-continue`（下文用 `%REPO%` 表示）
日志目录：`%APPDATA%\codex-auto-continue\`

## 0. 环境检查

```powershell
$PSVersionTable.PSVersion
python --version
git --version
where.exe codex
codex --version
git -C %REPO% log -1 --oneline
```

预期：Python ≥ 3.9、codex 可执行且在 PATH、仓库在 `v0.4.3` 或更新。

## 1. CLI 冒烟（不触发续跑）

```powershell
cd %REPO%
bin\codex-continue.cmd --version      # 0.4.3
bin\codex-continue.cmd usage          # 输出额度窗口；若 Windows 无 CodexBar，会走 app-server
bin\codex-continue.cmd scan --days 14 # 列出因额度中断的会话
bin\codex-continue.cmd status         # 数据目录、额度、调度器
```

记录：`usage` 是否成功拿到额度（来源 app-server）、`scan` 是否能读到 `%USERPROFILE%\.codex\sessions`。

## 2. 用一条真实线程测试 arm + Task Scheduler

先找一条因额度中断的线程（`scan` 里 `interrupted: true`）。若没有，可以让 Codex 开会话到额度用完，或临时用 `--force` 指定任意线程做机制验证：

```powershell
bin\codex-continue.cmd arm --last --message "继续未完成的工作" --json
bin\codex-continue.cmd status --json
schtasks /Query /TN CodexAutoContinue /V /FO LIST
```

预期：
- `status --json` 里 `threads[].fire_at` 有值，`scheduler` 显示 `task-scheduler: installed (...)`
- `schtasks` 能看到 `CodexAutoContinue`，状态为 Ready，下次运行时间正确
- 任务 XML 存放在 `%APPDATA%\codex-auto-continue\task-scheduler.xml`，包含 `WakeToRun`、`StartWhenAvailable`

### 不等时间，立刻触发一次

```powershell
schtasks /Run /TN CodexAutoContinue
Start-Sleep -Seconds 30
Get-Content "$env:APPDATA\codex-auto-continue\run.log" -Tail 20
```

预期日志出现 `queue accepted and a new turn started`，并且 Codex App 里对应会话出现新回合。
（如果出现 `queue failed` / `active writer` / 找不到 codex，记录完整输出。）

## 3. 托盘界面

先前台运行看报错：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File ui\windows-tray\CodexContinueTray.ps1
```

预期：托盘出现图标，右键菜单包含额度、待续跑、因额度中断的会话、已安排任务、刷新、打开运行日志、开机自启、退出。

逐项验证：
1. 菜单能打开、数据与 `status`/`scan` 一致
2. 「用默认消息续跑」能安排任务
3. 「自定义消息…」弹窗能编辑并保存
4. 「编辑消息…」能修改已安排线程的消息且不改变触发时间
5. 「取消续跑」后 `schtasks /Query` 不再显示任务
6. 「开机自动启动」能创建/删除启动文件夹快捷方式
7. 关闭后双击 `CodexContinueTray.vbs` 能无窗口启动

托盘自身日志：`%APPDATA%\codex-auto-continue\tray.log`

## 4. 睡眠 / 唤醒（可选但重要）

```powershell
bin\codex-continue.cmd arm --last --at (Get-Date).AddMinutes(3).ToString("HH:mm")
# 让机器睡眠，等待到点
```

预期：`WakeToRun` 能唤醒机器并在唤醒后执行（或至少 `StartWhenAvailable` 在唤醒后补跑）；查看 `run.log` 时间戳与 `powercfg /lastwake`。
若失败，记录：`powercfg /a`、电源计划是否允许唤醒计时器、`schtasks` 的“条件”页。

## 5. 诊断信息收集

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows-diagnostics.ps1
```

会生成一个诊断文本（路径会打印出来），包含：系统/PowerShell/Python/codex 版本、仓库版本、任务状态与 XML、run.log/tray.log 尾部、数据目录列表。把这个文件和截图一起反馈。

## 6. 允许的修复范围

- 修 `src/codex_auto_continue/scheduler/windows.py`（XML、schtasks 调用、路径/编码）
- 修 `bin/codex-continue.cmd` / `bin/codex-continue-hidden.vbs`
- 修 `ui/windows-tray/CodexContinueTray.ps1`（语法、编码、事件、图标、启动项）
- 修 Windows 相关内核适配（`config._pid_alive`、`runner._hold_awake`、`runner._run_codex` 的 `.cmd` 处理、`messages._split_editor`）
- 补 Windows 专属单元测试；保持 `python -m unittest discover -s tests` 全绿（当前 54 个）
- 更新 `README.md` 的 Windows 章节与 `PROJECT_STATE.md`

不要改 macOS 侧行为；不要把插件方向加回来；不要提交凭据/日志。

## 7. 验收标准

- `bin\codex-continue.cmd usage/scan/status` 正常
- `arm` 创建任务，`status` 能读出下次触发时间
- 手动 `schtasks /Run` 后真实续跑成功（Codex 会话出现新回合，run.log 有 `queue accepted...`）
- 托盘 7 项功能全部可用
- 单元测试在 Windows 上全绿
- 把修复提交并推送（或输出 patch）

## 8. 本轮真机验收结果（2026-10-24，Windows 11 22631）

### 8.1 结果总览

| 清单项 | 结果 | 证据 |
| --- | --- | --- |
| CLI `--version` | ✅ `codex-continue 0.4.3` | `bin\codex-continue.cmd --version` |
| CLI `scan` | ✅ 读到 2 个真实 rollout（均非额度中断） | `scan --days 3650 --json` |
| CLI `status` | ✅ 数据目录/额度/调度器正常输出 | `status --json` |
| CLI `usage` | ⚠️ app-server RPC 已能启动，但账号 refresh token 失效 → `quota: null` | `usage --json`；见 §8.3 |
| `arm` 创建任务 | ✅ `CodexAutoContinue`，XML/注册表均含 `WakeToRun`/`StartWhenAvailable` | `schtasks /Query /V`、`Get-ScheduledTask`、`task-scheduler.xml` |
| `status` 读出下次触发 | ✅ `task-scheduler: installed (CodexAutoContinue) · next run ...` | `status --json` |
| `schtasks /Run` 手动触发 | ✅ 真实执行 runner，`run.log` 有记录，任务按状态清理 | `%APPDATA%\codex-auto-continue\run.log` |
| 到点自动触发（非手点） | ✅ 到点由 Task Scheduler 自动执行并写 run.log，随后删除任务 | run.log 中 `23:16:27` 那轮 |
| 真实续跑（queue accepted + Codex 新回合） | ❌ 被本机 Codex 登录失效阻塞；链路已到网络/鉴权层 | 见 §8.3 |
| 托盘 7 项功能 | ✅/⚠️ 见 §8.4（实机运行 + 修复，逐项结果） | `evidence/tray/` |
| 睡眠/唤醒 | ⚠️ 未实际睡眠；`WakeToRun/StartWhenAvailable` 已验证为 true | XML + `Get-ScheduledTask`；`powercfg /waketimers` 需管理员 |
| 单元测试 | ✅ 68 passed / 2 skipped（Windows 实机，Python 3.12.6） | `python -m unittest discover -s tests` |
| 诊断脚本 | ✅ 实机跑通，生成 `%TEMP%\codex-auto-continue-diag-*.txt` | `scripts\windows-diagnostics.ps1` |

### 8.2 本轮修复（v0.4.3）

1. `bin/codex-continue-hidden.vbs`：`WScript.Shell.Run` 直接执行 `.cmd` 会走 ShellExecute，
   在 Task Scheduler 环境弹出「打开文件 - 安全警告」并**永久挂起**任务（真机复现）。改为显式
   `cmd.exe /d /c` 启动后，计划任务正常无窗口运行。
2. `usage.find_codex`：增加 Windows 探测（`%USERPROFILE%\.codex\.sandbox-bin\codex.exe`、
   `%APPDATA%\npm\codex.cmd`、`%LOCALAPPDATA%\Programs\Codex\codex.exe` 等）。Codex App 的
   CLI 不在 PATH 是本机 `usage/status/run` 全部失败的首要原因。
3. `usage`：当前 CLI（0.119）不接受 `app-server --stdio`（exit 2）；先探测
   `app-server --help`，自动选择 `app-server` 或 `app-server --stdio`。
4. `runner`：新增 queue 能力探测（`codex queue --help` 是否含 `--thread/--message`）；纯 CLI
   没有 queue 时跳过并直接回退 resume；resume 按 CLI 版本选 `--sandbox workspace-write`
   或旧版 `--approve-for-me`（0.119 对 `--approve-for-me` 报 exit 2）。
5. `runner`：`codex CLI not found`、quota 不可用等失败路径写入 `run.log`，避免计划任务"看起来没跑"。
6. `scheduler/windows.py`：`schtasks` 输出按系统代码页解码；`describe` 兼容中文
   「下次运行时间」并用任务 XML 兜底。
7. `threads.py`：兼容没有 `name` 列的 `state_*.sqlite`（0.119 只有 `title`），恢复会话标题显示。
8. `scripts/windows-diagnostics.ps1`：修复 PowerShell 5.1 语法、UTF-16 XML / UTF-8 日志读取、
   codex 定位、任务 XML 与 `powercfg` 信息收集。
9. `ui/windows-tray/CodexContinueTray.ps1` / `CodexContinueTray.vbs`：
   - `CodexContinueTray.vbs` 原为 UTF-8 with BOM，WSH 在 (1,1) 报「无效字符」，静默启动必失败；
     改为 ASCII/no-BOM 后 `cscript`/双击均正常。
   - 托盘日志目录支持 `CODEX_AUTO_CONTINUE_HOME`；「打开运行日志」不再写到 `%APPDATA%`。
   - PowerShell 5.1 下 CLI stderr 不再中断 JSON 解析（`2>&1` + `ErrorActionPreference=Stop` 会把
     native stderr 当终止错误）；单实例 mutex 处理 abandoned；开机自启快捷方式读写失败不再静默。
   - 数据刷新改为异步：`status/scan` 用 `Start-Job` 后台执行，750ms WinForms Timer 回填缓存并重建菜单，
     UI 线程不再被 app-server 额度查询阻塞。真机计时：菜单打开 **23.66s → 0.13s**，「刷新中…」占位后
     数据在后台到达。
   - tooltip/菜单文案中文化与事件异常处理修正。

**已知限制（本轮未修）**：Windows PowerShell 5.1 的原生参数引号规则会破坏自定义续跑消息中的 ASCII
双引号（默认中文消息不受影响）；如需要可改用 `--message-file` 之类的 CLI 扩展。

### 8.3 真实续跑：根因已定位并解除（2026-10-25 第二轮）

原先记为「refresh token 失效」，真实错误链是两层：

1. **地区限制**：Windows 直连（无代理）时 `codex` 报
   `403 unsupported_country_region_territory`；Clash 全局节点为香港时同样 403（OpenAI 不支持香港）。
2. **token 已失效**：换美国节点后报
   `401 refresh_token_reused — Your refresh token has already been used ... Please try signing in again.`

处理过程与结果：

- Mihomo Party 切到**美国洛杉矶**节点（出口 `23.237.196.226`，FDCservers）；
  注意 `curl https://chatgpt.com` 仍 403 是 **Cloudflare 人机挑战**（`Cf-Mitigated: challenge`），
  不代表地区问题，验证地区应看 `http://ip-api.com/json`。
- 系统代理已开启（`127.0.0.1:7890`），登录、`codex`、`codex-continue` 均可用；
  计划任务需要 `HTTPS_PROXY/HTTP_PROXY` 用户环境变量（登录前设置，或写进任务包装脚本）。
- 通过 `codex login` 重新登录成功（本地 1455 回调；SSH 会话会回收子进程，
  所以登录进程改挂在临时计划任务里执行，完成后删除）。登录后 `auth.json` 更新，`usage` 正常返回真实额度。
- 2026-10-25 16:52 实况：`primary 300m used=100% (resets 19:14:20)`、`secondary 10080m used=16%`，
  即账号当前处于真实的额度耗尽状态，`arm` 正确排到 **19:17:20**（reset + 180s grace），
  `schtasks` Ready、`WakeToRun/StartWhenAvailable=true`、任务动作为隐藏 vbs。
- **已验收（2026-10-25 23:41:53）**：计划任务自动触发（23:38:55）→ queue 路径 120s 未出回合
  （Codex App 未运行）→ 回退 `codex exec resume` → **`resume completed`**，
  `state.json` 中 `status=done attempts=1 last_error=null`，会话 rollout 从 68 行增至 86 行。
  即「到点自动触发 + 真实续跑 + 新回合」全链路通过。第 2 节「不等时间立即触发」等价于手动
  `schtasks /Run`，本轮另外验证了真实到点触发（无需手动）。

#### 续跑可用性的三个前置配置（2026-10-25 新增）

| 配置 | 值 | 作用 |
|---|---|---|
| `codex_path` | `%LOCALAPPDATA%\OpenAI\Codex\bin\<hash>\codex.exe`（0.164） | 旧 `.codex\.sandbox-bin\codex.exe`（0.119）不支持账号当前模型；App 自带 CLI 才有 `queue` 与 `gpt-6.1-sol` |
| `model` | `gpt-6.1-sol` | `~/.codex/config.toml` 里的 `gpt-5.4` 是 API 专用，ChatGPT 登录会 `model_not_found` |
| `proxy` | `http://127.0.0.1:7890` | 计划任务环境没有 `HTTPS_PROXY`；runner/usage 会把它注入子进程，否则 app-server 网络超时（`quota unavailable`） |

均可用 `codex-continue config --set <key>=<value>` 设置。

#### 遗留问题（低优先级）

1. 计划任务在自身运行中 `schtasks /Delete` 会被 Windows 拒绝，"自清理辅助任务"方案在实机未验证成功；
   当前表现为任务残留（`Next Run` 指向已过去的时刻，不会造成重复续跑）。
2. 计划任务环境首次读额度可能仍报 `quota unavailable`，但不影响后续 queue/resume。

### 8.3.1 本轮修复（Windows 侧，2026-10-25）

1. `arm --force` 在 arm 时放行、执行时又被 "session is no longer waiting on a usage limit"
   拦掉 → `forced` 持久化进 state，`continue_thread` 对 forced 线程跳过该判定。
2. `state.json` 解析失败会静默变空（实测 PowerShell 手改带 BOM 即触发，所有已安排任务无声消失）
   → 损坏文件改名 `state.json.corrupt-<ts>` 并写 `run.log`。
3. `failed` 状态仍算 pending → 失败线程每 `retry_seconds` 无限重试
   → `failed` 改为终态，不再参与调度。
4. 计划任务在自身运行中删不掉自己（Windows 限制）→ `remove()` 失败时创建一次性
   `CodexAutoContinueCleanup` 任务（+2 分钟）删除主任务与自身；该兜底尚未在实机复验成功，仍需跟进。
5. 回归测试：Mac/Windows 各 74 个测试通过（+4 个新用例：forced 终态、损坏 state、failed 非 pending、任务清理路径）。

### 8.4 托盘逐项结果（见 `ui/windows-tray/README.md`；本地记录在 `evidence/tray/`，不随仓库提交）

- 实机启动托盘、菜单结构（13 项）、单实例、开机自启快捷方式创建/删除、VBS 静默启动、`tray.log`
  均通过；「刷新」经 MSAA 调用成功；异步刷新后菜单打开耗时 23.66s → 0.13s。
- 未逐项点击验证：用默认消息续跑 / 自定义消息 / 编辑消息 / 取消续跑（本机无法真实续跑，且沙箱内
  无法稳定展开子菜单），以及「打开运行日志」「退出」仅代码审查；默认消息与其他菜单功能默认中文
  消息下不受引号限制。
