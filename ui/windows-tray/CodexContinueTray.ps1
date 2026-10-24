# Codex Auto Continue - Windows tray app (PowerShell + WinForms, no dependencies)
# Run: powershell -NoProfile -ExecutionPolicy Bypass -File CodexContinueTray.ps1
param([string]$Cli = "")

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..\..")).Path
# Honor CODEX_AUTO_CONTINUE_HOME the same way src/codex_auto_continue/paths.py does, so the
# tray log and "open run log" follow an isolated data dir instead of always using %APPDATA%.
if ($env:CODEX_AUTO_CONTINUE_HOME) {
    $dataDir = $env:CODEX_AUTO_CONTINUE_HOME
} else {
    $dataDir = Join-Path $env:APPDATA "codex-auto-continue"
}
$logFile = Join-Path $dataDir "tray.log"
if (-not (Test-Path $dataDir)) { New-Item -ItemType Directory -Path $dataDir -Force | Out-Null }

if (-not $Cli) {
    $candidate = Join-Path $repoRoot "bin\codex-continue.cmd"
    if (Test-Path $candidate) { $Cli = $candidate } else { $Cli = "codex-continue" }
}

function Write-Log([string]$Message) {
    try { Add-Content -Path $logFile -Value ("[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message) -Encoding UTF8 } catch {}
}

function Invoke-Cli([string[]]$Arguments) {
    # Windows PowerShell 5.1 turns a native command's stderr into a terminating error while
    # $ErrorActionPreference is "Stop"; keep the CLI's warnings off the JSON stream instead of
    # letting them abort the call.
    $previous = $ErrorActionPreference
    $errFile = [System.IO.Path]::GetTempFileName()
    try {
        $ErrorActionPreference = "Continue"
        $text = (& $Cli @Arguments 2> $errFile | Out-String)
        $code = $LASTEXITCODE
        $errText = (Get-Content -Path $errFile -Raw -ErrorAction SilentlyContinue)
        if ($errText) { $errText = $errText.Trim() }
        if ($code -ne 0) {
            Write-Log ("cli exit {0}: {1}" -f $code, $errText)
            if (-not $text.Trim() -and $errText) { $text = $errText }
        }
        return [pscustomobject]@{ Text = $text; Code = $code }
    } catch {
        Write-Log "cli error: $_"
        return [pscustomobject]@{ Text = "$_"; Code = -1 }
    } finally {
        $ErrorActionPreference = $previous
        Remove-Item -Path $errFile -Force -ErrorAction SilentlyContinue
    }
}

function Get-CliJson([string[]]$Arguments) {
    $result = Invoke-Cli $Arguments
    if (-not $result -or $result.Code -ne 0) { return $null }
    try { return ($result.Text | ConvertFrom-Json) } catch {
        Write-Log ("bad json: " + $result.Text.Substring(0, [Math]::Min(200, $result.Text.Length)))
        return $null
    }
}

function Format-Time([string]$Iso) {
    if (-not $Iso) { return "" }
    try { return ([DateTime]::Parse($Iso)).ToLocalTime().ToString("HH:mm") } catch { return "" }
}

# ---- single instance -------------------------------------------------
$mutex = New-Object System.Threading.Mutex($false, "CodexContinueTray")
$owned = $false
try {
    $owned = $mutex.WaitOne(0)
} catch [System.Threading.AbandonedMutexException] {
    # A previous tray died while holding the mutex; we now own it.
    $owned = $true
}
if (-not $owned) { exit 0 }
Write-Log ("tray started (pid {0}, PowerShell {1})" -f $PID, $PSVersionTable.PSVersion)

# ---- state -----------------------------------------------------------
$script:Status = $null
$script:Scan = $null
$script:Refreshing = $false
$script:PendingRebuild = $false

$script:DefaultMessage = "上一轮因 usage limit 中断。请从中断处继续未完成的工作，完成后简要汇报结果和未完成项；不要重复已完成的部分。"

# ---- tray icon -------------------------------------------------------
$menu = New-Object System.Windows.Forms.ContextMenuStrip
$menu.ShowImageMargin = $false

$iconPath = Join-Path $scriptDir "assets\CodexContinue.ico"
$icon = if (Test-Path $iconPath) { New-Object System.Drawing.Icon($iconPath) } else { [System.Drawing.SystemIcons]::Application }
$notify = New-Object System.Windows.Forms.NotifyIcon
$notify.Icon = $icon
$notify.Text = "Codex Auto Continue"
$notify.Visible = $true
$notify.ContextMenuStrip = $menu

function Show-Balloon([string]$Title, [string]$Text) {
    $notify.BalloonTipTitle = $Title
    $notify.BalloonTipText = $Text
    $notify.ShowBalloonTip(4000)
}

function Get-Pending { @($script:Status.threads | Where-Object { $_.status -in @("armed", "running", "failed") }) }
function Get-Interrupted { if ($script:Scan -and $script:Scan.interrupted) { @($script:Scan.interrupted) } else { @() } }

function Show-InputDialog([string]$DefaultText) {
    $form = New-Object System.Windows.Forms.Form
    $form.Text = "续跑消息"
    $form.Size = New-Object System.Drawing.Size(560, 320)
    $form.StartPosition = "CenterScreen"
    $form.TopMost = $true
    $form.MinimizeBox = $false
    $label = New-Object System.Windows.Forms.Label
    $label.Text = "额度重置后会发送这段文字："
    $label.SetBounds(12, 10, 520, 20)
    $box = New-Object System.Windows.Forms.TextBox
    $box.Multiline = $true
    $box.ScrollBars = "Vertical"
    $box.SetBounds(12, 34, 520, 180)
    $box.Text = $DefaultText
    $ok = New-Object System.Windows.Forms.Button
    $ok.Text = "安排续跑"
    $ok.SetBounds(360, 228, 90, 30)
    $ok.DialogResult = [System.Windows.Forms.DialogResult]::OK
    $cancel = New-Object System.Windows.Forms.Button
    $cancel.Text = "取消"
    $cancel.SetBounds(456, 228, 76, 30)
    $cancel.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
    $form.Controls.AddRange(@($label, $box, $ok, $cancel))
    $form.AcceptButton = $ok
    $form.CancelButton = $cancel
    if ($form.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
        $text = $box.Text.Trim()
        if ($text) { return $text }
    }
    return $null
}

function Invoke-Arm($Tag) {
    $arguments = @("arm", $Tag.Id, "--json")
    if ($Tag.Prompt) {
        $message = Show-InputDialog $script:DefaultMessage
        if (-not $message) { return }
        $arguments = @("arm", $Tag.Id, "--message", $message, "--json")
    }
    $result = Invoke-Cli $arguments
    if (-not $result -or $result.Code -ne 0) {
        Show-Balloon "续跑安排失败" ("审查输出：" + $result.Text)
        Write-Log ("arm failed: " + $result.Text)
        return
    }
    Show-Balloon "已安排续跑" ("线程 " + $Tag.Id)
    Update-Data
}

function Invoke-MessageEdit($Tag) {
    $status = $script:Status
    $current = $script:DefaultMessage
    if ($status -and $status.threads) {
        $match = $status.threads | Where-Object { $_.thread_id -eq $Tag.Id } | Select-Object -First 1
        if ($match -and $match.message) { $current = $match.message }
    }
    $message = Show-InputDialog $current
    if (-not $message) { return }
    $result = Invoke-Cli @("message", $Tag.Id, "--message", $message, "--json")
    if (-not $result -or $result.Code -ne 0) {
        Show-Balloon "更新消息失败" ("审查输出：" + $result.Text)
        return
    }
    Show-Balloon "已更新续跑消息" ("线程 " + $Tag.Id)
    Update-Data
}

function Invoke-Disarm($Tag) {
    $result = Invoke-Cli @("disarm", $Tag.Id)
    if (-not $result -or $result.Code -ne 0) {
        Show-Balloon "取消失败" ("审查输出：" + $result.Text)
        return
    }
    Show-Balloon "已取消续跑" ("线程 " + $Tag.Id)
    Update-Data
}

function Get-StartupShortcut { Join-Path ([Environment]::GetFolderPath("Startup")) "CodexAutoContinue.lnk" }
function Test-Startup { Test-Path (Get-StartupShortcut) }
function Set-Startup([bool]$Enabled) {
    $link = Get-StartupShortcut
    try {
        if ($Enabled) {
            $shell = New-Object -ComObject WScript.Shell
            $shortcut = $shell.CreateShortcut($link)
            $shortcut.TargetPath = "powershell.exe"
            $shortcut.Arguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $PSCommandPath + '"'
            $shortcut.WorkingDirectory = $repoRoot
            $shortcut.Save()
            [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($shell)
            Show-Balloon "已启用开机自启" "Codex Auto Continue"
        } else {
            if (Test-Path $link) { Remove-Item $link -Force -ErrorAction Stop }
            Show-Balloon "已关闭开机自启" "Codex Auto Continue"
        }
    } catch {
        # Don't let a failed shortcut write kill the tray's UI thread silently.
        Write-Log ("startup toggle failed (enabled=" + $Enabled + "): " + $_.Exception.Message)
        Show-Balloon "开机自启设置失败" ("无法更新启动文件夹：" + $_.Exception.Message)
        return
    }
    Update-Data
}

function New-MenuItem([string]$Text, $Tag = $null) {
    $item = New-Object System.Windows.Forms.ToolStripMenuItem($Text)
    $item.Tag = $Tag
    return $item
}

function Add-Disabled([string]$Text) {
    $item = New-MenuItem $Text
    $item.Enabled = $false
    [void]$menu.Items.Add($item)
}

function Build-Menu {
    $menu.Items.Clear()

    $quotaText = "额度：未知"
    if ($script:Status -and $script:Status.quota -and $script:Status.quota.windows) {
        $parts = @()
        foreach ($window in $script:Status.quota.windows) {
            $kind = if ($window.kind -eq "primary") { "5h" } else { "周" }
            $part = ("{0} {1}%" -f $kind, [int]$window.used_percent)
            if ($window.resets_at) { $part += "→" + (Format-Time $window.resets_at) }
            $parts += $part
        }
        $quotaText = "额度：" + ($parts -join "  ")
    } elseif ($script:Refreshing -and -not $script:Status) {
        $quotaText = "额度：刷新中…"
    }
    Add-Disabled $quotaText

    $pending = @(Get-Pending)
    if ($script:Refreshing -and -not $script:Status) {
        Add-Disabled "待续跑：刷新中…"
    } elseif ($pending.Count -gt 0) {
        $first = $pending | Select-Object -First 1
        $when = if ($first.fire_at) { Format-Time $first.fire_at } else { "—" }
        Add-Disabled ("待续跑：{0} 个 · 下次 {1}" -f $pending.Count, $when)
    } else {
        Add-Disabled "待续跑：0"
    }
    if ($script:Status -and $script:Status.scheduler) { Add-Disabled ("调度器：" + $script:Status.scheduler) }
    [void]$menu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator))

    $interrupted = @(Get-Interrupted)
    Add-Disabled ("因额度中断：{0}" -f $interrupted.Count)
    if ($interrupted.Count -eq 0) { Add-Disabled "  无" }
    foreach ($thread in ($interrupted | Select-Object -First 8)) {
        $label = if ($thread.title) { $thread.title } else { $thread.cwd }
        $item = New-MenuItem ("  " + $label)
        $sub = New-Object System.Windows.Forms.ContextMenuStrip
        $armDefault = New-MenuItem "用默认消息续跑" @{ Id = $thread.thread_id; Prompt = $false }
        $armDefault.add_Click({ param($sender, $eventArgs) Invoke-Arm $sender.Tag })
        [void]$sub.Items.Add($armDefault)
        $armCustom = New-MenuItem "自定义消息…" @{ Id = $thread.thread_id; Prompt = $true }
        $armCustom.add_Click({ param($sender, $eventArgs) Invoke-Arm $sender.Tag })
        [void]$sub.Items.Add($armCustom)
        $item.DropDown = $sub
        [void]$menu.Items.Add($item)
    }

    if ($pending.Count -gt 0) {
        [void]$menu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator))
        Add-Disabled ("已安排：{0}" -f $pending.Count)
        foreach ($thread in $pending) {
            $statusText = switch ($thread.status) {
                "armed" { "已安排" }
                "running" { "续跑中" }
                "failed" { "失败" }
                default { $thread.status }
            }
            $fire = if ($thread.fire_at) { Format-Time $thread.fire_at } else { "—" }
            $label = if ($thread.title) { $thread.title } else { $thread.thread_id.ToString().Substring(0, [Math]::Min(8, $thread.thread_id.Length)) }
            $item = New-MenuItem ("  {0} · {1} · {2}" -f $statusText, $fire, $label)
            $sub = New-Object System.Windows.Forms.ContextMenuStrip
            $edit = New-MenuItem "编辑消息…" @{ Id = $thread.thread_id }
            $edit.add_Click({ param($sender, $eventArgs) Invoke-MessageEdit $sender.Tag })
            [void]$sub.Items.Add($edit)
            $cancel = New-MenuItem "取消续跑" @{ Id = $thread.thread_id }
            $cancel.add_Click({ param($sender, $eventArgs) Invoke-Disarm $sender.Tag })
            [void]$sub.Items.Add($cancel)
            $item.DropDown = $sub
            [void]$menu.Items.Add($item)
        }
    }

    [void]$menu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator))
    $refresh = New-MenuItem "刷新"
    $refresh.add_Click({ param($sender, $eventArgs) Update-Data })
    [void]$menu.Items.Add($refresh)

    $log = New-MenuItem "打开运行日志"
    $log.add_Click({
        param($sender, $eventArgs)
        $dir = $dataDir
        if ($script:Status -and $script:Status.data_dir) { $dir = $script:Status.data_dir }
        $path = Join-Path $dir "run.log"
        try {
            if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
            if (-not (Test-Path $path)) { New-Item -ItemType File -Path $path -Force | Out-Null }
            Start-Process notepad.exe $path
        } catch {
            Write-Log ("open run.log failed: " + $_.Exception.Message)
            Show-Balloon "打开运行日志失败" ("无法打开：" + $path)
        }
    })
    [void]$menu.Items.Add($log)

    $codex = New-MenuItem "打开 Codex（网页）"
    $codex.add_Click({ param($sender, $eventArgs) Start-Process "https://chatgpt.com/codex" })
    [void]$menu.Items.Add($codex)

    $startup = New-MenuItem "开机自动启动"
    $startup.Checked = Test-Startup
    $startup.add_Click({ param($sender, $eventArgs) Set-Startup (-not (Test-Startup)) })
    [void]$menu.Items.Add($startup)

    [void]$menu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator))
    $quit = New-MenuItem "退出 Codex Auto Continue"
    $quit.add_Click({
        param($sender, $eventArgs)
        try { if ($script:RefreshTimer) { $script:RefreshTimer.Stop() } } catch {}
        try {
            if ($script:RefreshJob) {
                Stop-Job -Job $script:RefreshJob -ErrorAction SilentlyContinue
                Remove-Job -Job $script:RefreshJob -Force -ErrorAction SilentlyContinue
                $script:RefreshJob = $null
            }
        } catch {}
        $notify.Visible = $false
        $notify.Dispose()
        [System.Windows.Forms.Application]::Exit()
    })
    [void]$menu.Items.Add($quit)
}

function Update-Tray {
    $pending = @(Get-Pending).Count
    $interrupted = @(Get-Interrupted).Count
    # Chinese tooltip, matching ui/windows-tray/README.md and the macOS menu bar app.
    $text = "Codex Auto Continue"
    if ($pending -gt 0) {
        $next = @(Get-Pending) | Select-Object -First 1
        if ($next -and $next.fire_at) {
            $text = "已安排 {0} 个 · 下次 {1}" -f $pending, (Format-Time $next.fire_at)
        } else {
            $text = "已安排 {0} 个" -f $pending
        }
    } elseif ($interrupted -gt 0) {
        $text = "{0} 个中断" -f $interrupted
    }
    if ($text.Length -gt 63) { $text = $text.Substring(0, 63) }
    $notify.Text = $text
    # Never rebuild the item list under an open drop-down; defer it to the next Opening.
    if ($script:RefreshTimer -and $menu.Visible) {
        $script:PendingRebuild = $true
        return
    }
    $script:PendingRebuild = $false
    Build-Menu
}

# ---- asynchronous data refresh ---------------------------------------
# status/scan can take many seconds (quota lookup starts the Codex app-server, up to 30s),
# so they must never run on the WinForms UI thread: the menu would freeze while opening.
# Start-Job runs them in a child PowerShell process; a 750ms UI timer picks the result up
# and rebuilds the menu on the UI thread from the cached snapshot meanwhile.
$script:RefreshJob = $null
$script:RefreshTimer = $null
$script:LastRefreshError = $null

function Start-Refresh {
    if ($script:Refreshing) { return }
    $script:Refreshing = $true
    $script:LastRefreshError = $null
    $statusArgs = @("status", "--json")
    $scanArgs = @("scan", "--days", "14", "--json")
    try {
        $script:RefreshJob = Start-Job -ArgumentList $Cli, $statusArgs, $scanArgs -ScriptBlock {
            param($cli, $statusArgs, $scanArgs)
            $statusText = ""
            $scanText = ""
            try { $statusText = (& $cli @statusArgs 2> $null | Out-String) } catch { $statusText = "" }
            try { $scanText = (& $cli @scanArgs 2> $null | Out-String) } catch { $scanText = "" }
            [pscustomobject]@{ Status = $statusText; Scan = $scanText }
        }
    } catch {
        Write-Log "refresh start failed: $_"
        $script:Refreshing = $false
        return
    }
    if ($script:RefreshTimer) { $script:RefreshTimer.Start() }
}

function Complete-Refresh {
    if (-not $script:RefreshJob) { $script:Refreshing = $false; return }
    if ($script:RefreshTimer) { $script:RefreshTimer.Stop() }
    $result = $null
    try {
        $result = Receive-Job -Job $script:RefreshJob -ErrorAction SilentlyContinue
    } catch {
        Write-Log "refresh receive failed: $($_.Exception.Message)"
    }
    $script:RefreshJob | Remove-Job -Force -ErrorAction SilentlyContinue
    $script:RefreshJob = $null

    $first = @($result) | Select-Object -First 1
    if ($first -and $first.Status) {
        try {
            $script:Status = $first.Status | ConvertFrom-Json
        } catch {
            $script:LastRefreshError = "status json"
            Write-Log ("bad status json: " + $_.Exception.Message)
        }
        try {
            if ($first.Scan) { $script:Scan = $first.Scan | ConvertFrom-Json }
        } catch {
            $script:LastRefreshError = "scan json"
            Write-Log ("bad scan json: " + $_.Exception.Message)
        }
    } else {
        $script:LastRefreshError = "no data"
        Write-Log "refresh job produced no data"
    }
    $script:Refreshing = $false
    Update-Tray
}

function Update-Data {
    # kept as an alias: refresh is always asynchronous now
    Start-Refresh
}

$script:RefreshTimer = New-Object System.Windows.Forms.Timer
$script:RefreshTimer.Interval = 750
$script:RefreshTimer.add_Tick({
    if (-not $script:RefreshJob) { $script:RefreshTimer.Stop(); $script:Refreshing = $false; return }
    if ($script:RefreshJob.State -eq "Running" -or $script:RefreshJob.State -eq "NotStarted") { return }
    try { Complete-Refresh } catch { Write-Log "refresh tick error: $_" }
})

$menu.add_Opening({
    # Rebuild immediately from the cached snapshot; refresh runs in the background.
    try { Update-Tray } catch { Write-Log "menu opening error: $_" }
    try { Start-Refresh } catch { Write-Log "menu refresh error: $_" }
})

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 60000
$timer.add_Tick({ try { Start-Refresh } catch { Write-Log "timer error: $_" } })
$timer.Start()

$initial = New-Object System.Windows.Forms.Timer
$initial.Interval = 1000
$initial.add_Tick({
    $initial.Stop()
    try { Update-Tray } catch { Write-Log "initial refresh error: $_" }
    try { Start-Refresh } catch { Write-Log "initial refresh error: $_" }
})
$initial.Start()

[System.Windows.Forms.Application]::Run()
