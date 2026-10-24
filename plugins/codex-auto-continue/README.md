# Codex Auto Continue (plugin)

Codex 插件包：额度重置后自动继续被 usage limit 打断的会话。

- CLI 本体（Python 3.9+，标准库）已随插件打包在 `lib/codex_auto_continue`
- 启动脚本：`bin/codex-continue`（macOS/Linux）、`bin/codex-continue.cmd`（Windows）
- 技能指令：`skills/codex-auto-continue/SKILL.md`

## 安装

在 Codex 里添加本仓库为 marketplace，然后安装插件：

```bash
# 本地路径
codex plugin marketplace add /path/to/codex-auto-continue

# 或 GitHub 仓库（owner/repo）
codex plugin marketplace add your-name/codex-auto-continue
codex plugin add codex-auto-continue@qyh-tools
```

安装后重启 Codex，技能会被自动加载；对话里说「额度重置后继续这个任务」即可。

## 使用

插件通过技能调用内置 CLI；常用命令也可手动执行：

```bash
bin/codex-continue scan            # 找因额度中断的会话
bin/codex-continue arm --last --message "继续未完成的工作"
bin/codex-continue status
bin/codex-continue disarm --all
```

## 平台支持

- macOS：完整支持（launchd 调度）
- Linux / Windows：核心命令可用（扫描、额度、queue）；自动调度适配器尚未实现，
  会给出明确报错，可先用 cron / Task Scheduler 调 `run --scheduled`

## 权限

不需要管理员权限；macOS 安装会写 `~/Library/LaunchAgents` 并可能询问一次
「允许在后台运行」。不需要全盘访问/辅助功能。

## License

MIT
