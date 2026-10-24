# Windows 真机验收清单（交给 Windows 上的 DSH / Agent）

版本基线：`v0.4.1`（GitHub 已发布）。macOS 侧已完整验证；Windows 侧代码已完成、CI 在 `windows-latest` 跑通 54 个单元测试，但**尚未在真实 Windows + 真实 Codex 上端到端验证**。本清单的目标就是补上这一步，并修掉发现的问题。

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

预期：Python ≥ 3.9、codex 可执行且在 PATH、仓库在 `v0.4.1` 或更新。

## 1. CLI 冒烟（不触发续跑）

```powershell
cd %REPO%
bin\codex-continue.cmd --version      # 0.4.1
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
