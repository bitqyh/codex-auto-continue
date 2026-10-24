---
name: codex-auto-continue
description: Arm and manage automatic continuation of interrupted Codex sessions after usage limits reset. Use when the user says things like 额度用完/额度重置后继续/自动续跑/把这个任务排到额度恢复后继续, asks which Codex sessions were interrupted by usage limits, or wants a task resumed automatically when the account quota resets.
---

# Codex Auto Continue

Arms an interrupted Codex session and schedules it to continue the moment the
account's quota window resets. The CLI is bundled with this plugin; do not
install anything else.

## Locate the bundled CLI

Resolve this skill's directory to an absolute path, then use:

- macOS / Linux: `<skill_dir>/../../bin/codex-continue`
- Windows: `<skill_dir>\..\..\bin\codex-continue.cmd`

If `codex-continue` is already on `PATH`, prefer it (it may be newer).
`scan`, `usage`, `arm`, `status` and `run` accept `--json`; prefer it when you need to parse output.

## Prerequisites to check first

1. `python3 --version` (or `python --version` on Windows) — Python 3.9+.
2. Codex CLI is logged in (`codex login status` or an existing `~/.codex/auth.json`).
3. The Codex app is running (recommended): its `codex queue` path runs the turn
   inside the app with the user's normal auto-review permissions and shows it
   in the conversation.

## Workflow

1. **Find interrupted sessions**
   Run `codex-continue scan --json`. Each entry has `thread_id`, `cwd`,
   `reset_hint`, `last_user_text` and the usage-limit `error_message`.
   Present candidates to the user; do not arm anything yet.

2. **Confirm the message before arming**
   Ask the user what to send at reset time (default is a generic "continue from
   where you stopped" message). Pass it explicitly with `--message`.
   Never arm silently and never invent a thread the user did not choose.

3. **Arm**
   - most recent interrupted session: `arm --last --message "<text>"`
   - specific thread: `arm <thread_id> --message "<text>"`
   - user wants a persistent message for a project:
     `template set --cwd <project-dir> --message "<text>"`
   - explicit trigger time (otherwise reset + 3 min): `--at "00:20"` or
     `--at "2026-10-24 00:20"`.

   Arming writes a scheduler job (macOS: `~/Library/LaunchAgents`) and may
   trigger an OS permission prompt. That is expected.

4. **Report status**
   Run `codex-continue status --json` and tell the user the next fire time,
   the resolved message, and the quota windows. Explain that quitening the app
   is fine, sleeping is fine (it runs after wake), but a powered-off machine
   will miss the run.

5. **Adjust or cancel**
   - change the message of an already armed session without moving its schedule:
     `message <thread_id> --message "<text>"` (or `--edit`)
   - cancel: `codex-continue disarm --all` (or a specific `thread_id`).

## Guardrails

- Only resume sessions the user explicitly asks to resume. The tool is
  delete-by-default: never scan-and-arm everything.
- Show the exact message before arming; the user can edit it with `--edit`
  when a terminal is available.
- Do not `codex queue` or `codex exec resume` manually to "test" the flow; use
  `codex-continue run --dry-run` to preview, or just let the scheduler run.
- Quota checks are read-only (Codex app-server RPC); they do not spend quota.
  The actual continuation turn spends quota normally.
- macOS is fully supported (launchd). Linux and Windows scheduler adapters are
  not implemented yet: `arm` reports a clear error there; use
  `codex-continue run --scheduled` from cron/Task Scheduler manually.
- macOS users may prefer the optional menu bar app: `open -a CodexContinue`
  (built from `ui/menubar`; shows quota, interrupted sessions, one-click arm,
  and lets them edit the message of an already scheduled session).
- Keep credentials out of the conversation: no auth tokens, no `auth.json`
  contents. The tool relies on the existing Codex login.
