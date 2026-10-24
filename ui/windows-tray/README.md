# Windows 托盘界面

与 macOS 菜单栏 app 对应的 Windows 图形入口，纯 PowerShell + WinForms，无第三方依赖。

## 启动

双击 `CodexContinueTray.vbs`（无控制台窗口），或：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File CodexContinueTray.ps1
```

## 前置条件

- Windows 10/11，已安装 Python 3.9+（`python` 或 `py`）
- 已安装并登录 Codex（Windows 版）
- 仓库已 clone，且 `bin\codex-continue.cmd` 可用

## 功能

- 托盘图标：`已安排 N 个` / `N 个中断` / 空闲
- 菜单：额度窗口、待续跑、因额度中断的会话（用默认消息续跑 / 自定义消息…）、已安排任务（编辑消息… / 取消续跑）、刷新、打开运行日志、开机自启、退出
- 所有操作调用同一个 CLI（`bin\codex-continue.cmd`），与命令行共享状态
- 每 60 秒刷新，打开菜单时也刷新

## 日志与状态

- 托盘日志：`%APPDATA%\codex-auto-continue\tray.log`
- 运行日志：`%APPDATA%\codex-auto-continue\run.log`
- 任务计划：`schtasks /Query /TN CodexAutoContinue`

## 开机自启

托盘菜单「开机自动启动」会在当前用户启动文件夹创建快捷方式（无需管理员权限），再点一次关闭。

## 已知限制（v0.4.0）

- 计划任务仅在用户登录时运行（`InteractiveToken`，不保存密码）；关机后错过的任务不补跑
- 托盘脚本未做代码签名；如被 SmartScreen 拦截，选择「仍要运行」
