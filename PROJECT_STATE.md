# PROJECT_STATE · codex-auto-continue

> 交接记录（供接手对话核对与继续）。创建：2026-10-24 14:20 CST。
> 交接编号：**HO-2026-10-24-01**

## 1. 任务与版本

- **目标**：Codex 账号额度（usage limit）重置后，自动让被中断的会话继续。
- **交付形态**：跨平台 CLI（核心，Python 标准库）＋ macOS 原生菜单栏 app ＋ Windows Task Scheduler 调度与 PowerShell 托盘。Codex 插件方向已放弃（2026-10-24 决定），marketplace/插件文件已从仓库移除。
- **当前版本**：`0.4.2`（`src/codex_auto_continue/__init__.py`）。
- **权威工作目录**：`/Users/qyh/Projects/gptwork/codex-auto-continue`（已部署，菜单栏 app 由此构建）。
- **开发镜像**：`/Users/qyh/Documents/deepseek-harness/default-workspace/codex-auto-continue`（由权威目录 rsync 同步，排除 `.git` 与构建目录）。
- **版本控制**：git 仓库，tag `v0.4.2`，已推送 GitHub：https://github.com/bitqyh/codex-auto-continue
- **更新时间**：2026-10-24 16:05 CST。本轮实现 Windows 调度 + 托盘并发布 v0.4.2（菜单栏单实例 + 登录项重复启动修复）。

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

- 自动调度只有 macOS（launchd）；Linux/Windows 适配器是明确报错的占位（`scheduler/systemd.py`、`scheduler/windows.py`）。
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
- **Windows（v0.4.0，待真机验证）**：`scheduler/windows.py` 用 `schtasks /Create /XML` 注册 `CodexAutoContinue` 任务（`WakeToRun`、`StartWhenAvailable`、`InteractiveToken`）；托盘为 PowerShell + WinForms（`ui/windows-tray`），功能对齐 macOS 菜单栏；`bin/codex-continue.cmd` 为 Windows 启动器；Windows PID 存活检测、`.cmd` codex 路径、PowerShell Toast 已加；CI 增加三平台矩阵。**尚未在实体 Windows 上跑过**。
- 原交接时记录有 2 个因额度中断、**未安排**的会话（本轮未重新扫描，不能当作实时列表）：`分析题目解法思路`、`查找隔空手势操作电脑的方法`（随时可用 `arm`）。

### 未做 / 未验证

- **Windows 真机验证**：用户 2026-10-24 决定在 Windows 上装 DSH 自行调试；材料见仓库 `docs/WINDOWS-TESTING.md` 与 `scripts/windows-diagnostics.ps1`（登录 Codex → arm → 到点 queue → 托盘/通知 → 任务计划唤醒），由 Windows 侧会话执行并回改。
- Linux systemd user timer 适配器。
- 自动扫描全部中断线程 + 项目白名单模式。
- `pmset schedule wake` 定时唤醒（可选，需 sudo）。
- 无新的图标待办；后续如需改变品牌方向再改 SVG／Swift 母版。
- ~~GitHub 仓库初始化与推送~~（已完成：https://github.com/bitqyh/codex-auto-continue）

## 5. 接续动作

**下一步（按优先级）**：

1. Windows/macOS 通用化：按已确认的 win/mac 目标，先补 Task Scheduler 适配器，再做 Windows 托盘（复用 CLI 的 `--json` 接口）；Linux systemd 单独后续处理。本轮尚未实现。
2. Linux systemd user timer 适配器（可选）。
3. 可选：`pmset schedule wake` 精准唤醒（需 sudo，合盖/Apple Silicon 有限制）。

**前置条件**：Python 3.9+、已登录 Codex（同一 `~/.codex`）、可选 Xcode CLT。

**验收方法**：

```bash
cd /Users/qyh/Projects/gptwork/codex-auto-continue
PYTHONPATH=src python3 -m unittest discover -s tests          # 48 pass
PYTHONPATH=src python3 -m codex_auto_continue status --json    # 正常输出
PYTHONPATH=src python3 -m codex_auto_continue run --dry-run    # 无副作用
ui/menubar/build/CodexContinue.app/Contents/MacOS/CodexContinue --ui-selftest  # 菜单结构
```

**阻塞项**：无。已知无效路线：不要尝试用 `codex exec resume` 去接 App 正在持有的线程（会报 writer 冲突）。

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

# 同步开发镜像（权威目录 → 镜像）
rsync -a --delete --exclude '__pycache__' --exclude '*.pyc' --exclude '.git' \
  --exclude 'ui/menubar/build' \
  /Users/qyh/Projects/gptwork/codex-auto-continue/ \
  /Users/qyh/Documents/deepseek-harness/default-workspace/codex-auto-continue/

# 查看运行记录
tail -n 20 "$HOME/Library/Application Support/codex-auto-continue/run.log"
```
