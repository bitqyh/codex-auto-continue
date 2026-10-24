"""Command line interface: scan, usage, arm, disarm, status, run, install."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from . import __version__, config as cfg, messages, paths, plan, rollouts, threads, usage
from . import runner
from .notify import local_notify
from .scheduler import SchedulerError, for_platform


def _json_dump(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _short(text: str | None, limit: int = 70) -> str:
    if not text:
        return "-"
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _format_age(timestamp: float) -> str:
    delta = dt.datetime.now().timestamp() - timestamp
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"
    return f"{int(delta // 86400)}d ago"


def cmd_scan(args: argparse.Namespace) -> int:
    infos = rollouts.scan(days=args.days, include_subagents=args.include_subagents)
    interrupted = [info for info in infos if info.interrupted]
    if args.json:
        _json_dump({"scanned": len(infos), "interrupted": [info.to_dict() for info in interrupted]})
        return 0
    if not interrupted:
        print(f"扫描了 {len(infos)} 个会话（最近 {args.days} 天），没有因额度中断的。")
        return 0
    print(f"扫描了 {len(infos)} 个会话，找到 {len(interrupted)} 个因额度中断：\n")
    for info in interrupted:
        reset = plan.format_local(plan.aware(cfg.parse_iso(info.reset_hint))) if info.reset_hint else "未知"
        print(f"  {info.title or info.thread_id}  ({_format_age(info.mtime)})")
        print(f"    id:    {info.thread_id}")
        print(f"    cwd:   {info.cwd or '-'}")
        print(f"    重置:  {reset}")
        print(f"    最后:  {_short(info.last_user_text or info.last_assistant_text)}")
        print(f"    错误:  {_short(info.error_message)}")
        print(f"    路径:  {info.path}")
        print()
    print("用 `codex-continue arm <thread_id>` 或 `codex-continue arm --last` 加入自动续跑。")
    return 0


def cmd_usage(args: argparse.Namespace) -> int:
    config = cfg.load_config()
    snapshot = usage.snapshot(
        config.codex_path,
        max_age=config.quota_cache_seconds,
        force=getattr(args, "refresh", False),
    )
    if snapshot is None:
        if args.json:
            _json_dump({"quota": None})
        else:
            print("无法读取额度（app-server 与 CodexBar 缓存都不可用）。")
        return 1
    if args.json:
        _json_dump(snapshot.to_dict())
        return 0
    print(plan.describe_quota(snapshot))
    print(f"account: {snapshot.account_email or '-'}")
    for window in snapshot.windows:
        if window.resets_at:
            print(
                f"  {window.kind}: used {window.used_percent:g}% / {window.window_minutes}m, "
                f"resets {plan.format_local(window.resets_at)}"
            )
    print(f"now: {plan.format_local(dt.datetime.now(dt.timezone.utc))}")
    return 0


def _resolve_thread(target: str | None, use_last: bool, days: int) -> rollouts.RolloutInfo | None:
    if use_last:
        candidates = rollouts.interrupted(days=days)
        return candidates[0] if candidates else None
    if not target:
        return None
    path = rollouts.find_rollout(target)
    if path is None:
        return None
    return rollouts.parse_rollout(path)


def _parse_at(value: str) -> dt.datetime:
    now = dt.datetime.now().astimezone()
    formats = ["%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%m-%d %H:%M", "%H:%M"]
    for fmt in formats:
        try:
            parsed = dt.datetime.strptime(value, fmt)
        except ValueError:
            continue
        if fmt == "%H:%M":
            parsed = now.replace(hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0)
            if parsed <= now:
                parsed += dt.timedelta(days=1)
        elif fmt == "%m-%d %H:%M":
            parsed = parsed.replace(year=now.year)
        else:
            parsed = parsed.replace(tzinfo=now.tzinfo)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=now.tzinfo)
        return parsed
    raise ValueError(f"无法解析时间: {value}")


def _arm_message(config: cfg.Config, info: rollouts.RolloutInfo, args: argparse.Namespace) -> str:
    message = messages.resolve_message(config, info.cwd, args.message, info.thread_id)
    if args.edit:
        edited = messages.edit_message(message)
        if edited:
            return edited
        print("未找到可用的 $EDITOR/$VISUAL，继续使用当前消息。", file=sys.stderr)
        return message
    if args.message or not sys.stdin.isatty():
        return message
    print("本次续跑将发送的消息：")
    print(f"  {message}\n")
    try:
        answer = input("回车使用默认；直接输入自定义内容；输入 :e 用编辑器编辑：").strip()
    except EOFError:
        return message
    if answer == ":e":
        return messages.edit_message(message) or message
    return answer or message


def cmd_arm(args: argparse.Namespace) -> int:
    config = cfg.load_config()
    state = cfg.load_state()
    info = _resolve_thread(args.thread_id, args.last, args.days)
    if info is None:
        print("找不到对应会话；用 `codex-continue scan` 查看可用线程。", file=sys.stderr)
        return 2
    if not info.interrupted and not args.force:
        print(
            f"线程 {info.thread_id} 当前并不是「额度中断」状态（最后错误：{_short(info.error_message)}）。"
            "如仍要续跑，加 --force。",
            file=sys.stderr,
        )
        return 2
    message = _arm_message(config, info, args)
    thread = cfg.ArmedThread(
        thread_id=info.thread_id,
        rollout_path=str(info.path),
        cwd=info.cwd,
        message=message,
        armed_at=cfg.iso(dt.datetime.now(dt.timezone.utc)),
        status=cfg.STATUS_ARMED,
        baseline_lines=info.lines,
        reset_hint=info.reset_hint,
    )
    state.threads[info.thread_id] = thread
    snapshot = usage.snapshot(config.codex_path, max_age=config.quota_cache_seconds)

    if args.at:
        try:
            run_at = _parse_at(args.at)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        thread.fire_at = cfg.iso(run_at)
        for pending in state.threads.values():
            if pending.is_pending:
                pending.fire_at = cfg.iso(run_at)
        scheduler = for_platform()
        argv, env, workdir = runner._schedule_parts()
        scheduler.install_calendar(run_at, argv, env, workdir)
        cleanup = getattr(scheduler, "cleanup_stale", None)
        if callable(cleanup):
            cleanup()
        fire_at = run_at
    else:
        scheduler = for_platform()
        fire_at = runner.refresh_schedule(state, config, snapshot, scheduler)

    cfg.save_state(state)
    cfg.append_log(f"armed {info.thread_id} (fire_at={plan.format_local(fire_at)})")
    if args.json:
        _json_dump(
            {
                "thread": thread.to_dict(),
                "fire_at": cfg.iso(fire_at),
                "quota": snapshot.to_dict() if snapshot else None,
                "scheduler": scheduler.describe(),
            }
        )
        return 0
    print(f"已加入自动续跑：{info.title or info.thread_id}")
    if fire_at is None:
        print("  下次触发：额度已可用，60 秒内自动续跑")
    else:
        print(f"  下次触发：{plan.format_local(fire_at)}")
    print(f"  额度：    {plan.describe_quota(snapshot)}")
    print(f"  调度器：  {scheduler.describe()}")
    print(f"  消息：    {_short(message, 90)}")
    if args.at is None:
        print("（额度不可用时会自动排到重置后重试；也可用 --at 指定时间。）")
    return 0


def cmd_message(args: argparse.Namespace) -> int:
    state = cfg.load_state()
    thread = state.threads.get(args.thread_id)
    if thread is None:
        print(f"没有已登记的线程：{args.thread_id}", file=sys.stderr)
        return 2
    text = args.message
    if args.edit or not text:
        edited = messages.edit_message(thread.message)
        if edited is None:
            print("没有可用的编辑器，或内容为空。请用 --message 指定。", file=sys.stderr)
            return 2
        text = edited
    cfg.set_thread_message(state, args.thread_id, text)
    cfg.save_state(state)
    cfg.append_log(f"updated message for {args.thread_id}")
    if args.json:
        _json_dump({"thread_id": args.thread_id, "message": text})
        return 0
    print(f"已更新续跑消息：{thread.thread_id}")
    print(f"  {_short(text, 120)}")
    return 0


def cmd_disarm(args: argparse.Namespace) -> int:
    state = cfg.load_state()
    removed = []
    for thread_id, thread in list(state.threads.items()):
        if args.all or thread_id == args.thread_id:
            if args.all:
                removed.append(thread_id)
                del state.threads[thread_id]
            else:
                thread.status = cfg.STATUS_DISARMED
                thread.fire_at = None
                removed.append(thread_id)
    if not removed:
        print("没有匹配的待续跑线程。", file=sys.stderr)
        return 2
    cfg.save_state(state)
    remaining = [thread for thread in state.threads.values() if thread.is_pending]
    scheduler = for_platform()
    if not remaining:
        scheduler.remove()
    else:
        config = cfg.load_config()
        snapshot = usage.snapshot(config.codex_path, max_age=config.quota_cache_seconds)
        runner.refresh_schedule(state, cfg.load_config(), snapshot, scheduler)
        cfg.save_state(state)
    cfg.append_log(f"disarmed {', '.join(removed)}")
    print(f"已取消续跑：{', '.join(removed)}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    config = cfg.load_config()
    state = cfg.load_state()
    pending = [thread for thread in state.threads.values() if thread.is_pending]
    snapshot = usage.snapshot(
        config.codex_path,
        max_age=config.quota_cache_seconds,
        force=getattr(args, "refresh", False),
    )
    scheduler = for_platform()
    titles = threads.load_thread_titles(list(state.threads.keys())) if state.threads else {}
    if args.json:
        _json_dump(
            {
                "data_dir": str(paths.data_dir()),
                "pending": [
                    {**thread.to_dict(), "title": titles.get(thread.thread_id)} for thread in pending
                ],
                "threads": [
                    {**thread.to_dict(), "title": titles.get(thread.thread_id)}
                    for thread in state.threads.values()
                ],
                "quota": snapshot.to_dict() if snapshot else None,
                "scheduler": scheduler.describe(),
            }
        )
        return 0
    print(f"数据目录: {paths.data_dir()}")
    print(f"额度:     {plan.describe_quota(snapshot)}")
    print(f"调度器:   {scheduler.describe()}")
    if not state.threads:
        print("没有已登记的线程。用 `codex-continue scan` 找到中断会话后 `arm`。")
        return 0
    print(f"\n已登记 {len(state.threads)} 个线程（待续跑 {len(pending)} 个）：")
    for thread in state.threads.values():
        fire = plan.format_local(plan.aware(cfg.parse_iso(thread.fire_at)))
        label = titles.get(thread.thread_id) or thread.thread_id
        print(f"  {label}  [{thread.status}]  fire={fire}  attempts={thread.attempts}")
        if thread.last_error:
            print(f"    last_error: {_short(thread.last_error, 100)}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    config = cfg.load_config()
    summary = runner.run(config, dry_run=args.dry_run, notify_results=not args.no_notify)
    if args.json:
        _json_dump(summary)
    else:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary.get("status") in ("error", "locked"):
        return 1
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    config = cfg.load_config()
    state = cfg.load_state()
    scheduler = for_platform()
    snapshot = usage.snapshot(config.codex_path, max_age=config.quota_cache_seconds)
    fire_at = runner.refresh_schedule(state, config, snapshot, scheduler)
    cfg.save_state(state)
    print(f"调度器：{scheduler.describe()}")
    if fire_at:
        print(f"下次触发：{plan.format_local(fire_at)}")
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    scheduler = for_platform()
    scheduler.remove()
    print("已移除定时任务（已登记的线程保留）。")
    return 0


def cmd_template(args: argparse.Namespace) -> int:
    config = cfg.load_config()
    if args.action == "list":
        if not config.project_templates:
            print("没有按项目保存的模板；`arm --edit` 或 `template set --cwd <目录> --message ...` 添加。")
            return 0
        for path, template in sorted(config.project_templates.items()):
            print(f"{path}\n    {_short(template, 120)}")
        return 0
    if not args.cwd:
        print("需要 --cwd <目录>", file=sys.stderr)
        return 2
    key = messages.normalize_cwd(args.cwd)
    if args.action == "remove":
        if key in config.project_templates:
            del config.project_templates[key]
            cfg.save_config(config)
            print(f"已删除项目模板：{key}")
            return 0
        print(f"没有该项目的模板：{key}", file=sys.stderr)
        return 2
    text = args.message
    if args.edit or not text:
        base = text or messages.resolve_message(config, key)
        edited = messages.edit_message(base)
        if edited is None:
            print("没有可用的编辑器，或内容为空。", file=sys.stderr)
            return 2
        text = edited
    config.project_templates[key] = text
    cfg.save_config(config)
    print(f"已保存项目模板：{key}\n    {_short(text, 120)}")
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    config = cfg.load_config()
    if args.set:
        key, _, value = args.set.partition("=")
        if not key:
            print("用法：--set key=value", file=sys.stderr)
            return 2
        if key == "webhook_url":
            config.webhook_url = value or None
        elif key == "message_template":
            config.message_template = value
        elif key in (
            "grace_seconds",
            "max_attempts",
            "retry_seconds",
            "queue_verify_seconds",
            "quota_cache_seconds",
        ):
            setattr(config, key, int(value))
        elif key == "notify_local":
            config.notify_local = value.lower() not in ("0", "false", "no")
        elif key == "notify_email":
            config.notify_email = value.lower() not in ("0", "false", "no")
        elif key == "codex_path":
            config.codex_path = value or None
        else:
            print(f"未知配置项: {key}", file=sys.stderr)
            return 2
        cfg.save_config(config)
        print(f"已保存：{key}={value}")
        return 0
    _json_dump(config.to_dict())
    return 0


def cmd_notify_test(args: argparse.Namespace) -> int:
    ok = local_notify("Codex Auto Continue", "本地通知测试成功 / local notification test OK")
    print("已发送本地测试通知。" if ok else "本地通知发送失败（可能需要在系统设置中允许通知）。")
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codex-continue",
        description="在 Codex 额度重置后自动继续被中断的会话。",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="扫描因额度中断的 Codex 会话")
    scan.add_argument("--days", type=int, default=7)
    scan.add_argument("--include-subagents", action="store_true")
    scan.add_argument("--json", action="store_true")
    scan.set_defaults(func=cmd_scan)

    usage_cmd = sub.add_parser("usage", help="查看当前额度窗口与重置时间")
    usage_cmd.add_argument("--json", action="store_true")
    usage_cmd.add_argument("--refresh", action="store_true", help="忽略额度缓存，强制查询")
    usage_cmd.set_defaults(func=cmd_usage)

    arm = sub.add_parser("arm", help="把线程加入自动续跑")
    arm.add_argument("thread_id", nargs="?")
    arm.add_argument("--last", action="store_true", help="选择最近一个中断线程")
    arm.add_argument("--days", type=int, default=7)
    arm.add_argument("--message", help="续跑时发送的消息（优先级最高）")
    arm.add_argument("--edit", action="store_true", help="用 $EDITOR/$VISUAL 编辑续跑消息")
    arm.add_argument("--at", help='强制触发时间，如 "00:20" 或 "2026-10-24 00:20"')
    arm.add_argument("--force", action="store_true", help="即使当前不是额度中断状态也续跑")
    arm.add_argument("--json", action="store_true")
    arm.set_defaults(func=cmd_arm)

    message_cmd = sub.add_parser("message", help="修改已安排线程的续跑消息（不改触发时间）")
    message_cmd.add_argument("thread_id")
    message_cmd.add_argument("--message")
    message_cmd.add_argument("--edit", action="store_true")
    message_cmd.add_argument("--json", action="store_true")
    message_cmd.set_defaults(func=cmd_message)

    disarm = sub.add_parser("disarm", help="取消自动续跑")
    disarm.add_argument("thread_id", nargs="?")
    disarm.add_argument("--all", action="store_true")
    disarm.set_defaults(func=cmd_disarm)

    status = sub.add_parser("status", help="查看已登记线程与调度状态")
    status.add_argument("--json", action="store_true")
    status.add_argument("--refresh", action="store_true", help="忽略额度缓存，强制查询")
    status.set_defaults(func=cmd_status)

    run = sub.add_parser("run", help="执行一次续跑（供调度器调用）")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--scheduled", action="store_true", help="由平台调度器调用时使用")
    run.add_argument("--no-notify", action="store_true")
    run.add_argument("--json", action="store_true")
    run.set_defaults(func=cmd_run)

    install = sub.add_parser("install", help="按当前状态安装/刷新平台定时任务")
    install.set_defaults(func=cmd_install)

    uninstall = sub.add_parser("uninstall", help="移除平台定时任务")
    uninstall.set_defaults(func=cmd_uninstall)

    template = sub.add_parser("template", help="管理按项目的续跑消息模板")
    template.add_argument("action", choices=["list", "set", "remove"])
    template.add_argument("--cwd", help="项目目录")
    template.add_argument("--message")
    template.add_argument("--edit", action="store_true")
    template.set_defaults(func=cmd_template)

    config_cmd = sub.add_parser("config", help="查看或修改配置")
    config_cmd.add_argument("--set", help="key=value")
    config_cmd.set_defaults(func=cmd_config)

    notify_cmd = sub.add_parser("notify-test", help="测试本地通知")
    notify_cmd.set_defaults(func=cmd_notify_test)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except SchedulerError as exc:
        print(f"调度器错误: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
