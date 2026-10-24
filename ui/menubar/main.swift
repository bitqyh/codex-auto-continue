import AppKit
import Darwin
import Foundation

// MARK: - Data model

struct QuotaWindow {
    let kind: String
    let minutes: Int
    let usedPercent: Double
    let resetsAt: Date?
}

struct InterruptedThread {
    let threadID: String
    let title: String?
    let cwd: String
    let lastUserText: String
    let resetHint: String?
    let ageText: String
}

struct RegisteredThread {
    let threadID: String
    let title: String?
    let status: String
    let fireAt: Date?
    let attempts: Int
    let lastError: String?
    let message: String
}

struct Snapshot {
    var pendingCount = 0
    var nextFire: Date?
    var quotaText = "额度：读取中…"
    var schedulerText = "调度器：—"
    var dataDir: String = ""
    var interrupted: [InterruptedThread] = []
    var registered: [RegisteredThread] = []
    var error: String?
}

// MARK: - CLI bridge

final class CLI {
    static func discover() -> String? {
        if let override = UserDefaults.standard.string(forKey: "cliPath"), FileManager.default.isExecutableFile(atPath: override) {
            return override
        }
        if let bundled = Bundle.main.object(forInfoDictionaryKey: "CLIPath") as? String,
           FileManager.default.isExecutableFile(atPath: bundled) {
            return bundled
        }
        let home = FileManager.default.homeDirectoryForCurrentUser
        let direct = home.appendingPathComponent("Projects/gptwork/codex-auto-continue/bin/codex-continue").path
        if FileManager.default.isExecutableFile(atPath: direct) {
            return direct
        }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/sh")
        process.arguments = ["-c", "command -v codex-continue"]
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = Pipe()
        do {
            try process.run()
            process.waitUntilExit()
            if process.terminationStatus == 0 {
                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                if let path = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines), !path.isEmpty {
                    return path
                }
            }
        } catch {}
        return nil
    }

    static func runSync(_ path: String, _ args: [String]) -> (String, String, Int32) {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: path)
        process.arguments = args
        let out = Pipe()
        let err = Pipe()
        process.standardOutput = out
        process.standardError = err
        do {
            try process.run()
            process.waitUntilExit()
            let outData = out.fileHandleForReading.readDataToEndOfFile()
            let errData = err.fileHandleForReading.readDataToEndOfFile()
            return (
                String(data: outData, encoding: .utf8) ?? "",
                String(data: errData, encoding: .utf8) ?? "",
                process.terminationStatus
            )
        } catch {
            return ("", error.localizedDescription, -1)
        }
    }

    static func run(_ path: String, _ args: [String], completion: @escaping (String?, String?) -> Void) {
        DispatchQueue.global(qos: .userInitiated).async {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: path)
            process.arguments = args
            let out = Pipe()
            let err = Pipe()
            process.standardOutput = out
            process.standardError = err
            do {
                try process.run()
                process.waitUntilExit()
                let outData = out.fileHandleForReading.readDataToEndOfFile()
                let errData = err.fileHandleForReading.readDataToEndOfFile()
                let stdout = String(data: outData, encoding: .utf8) ?? ""
                let stderr = String(data: errData, encoding: .utf8) ?? ""
                DispatchQueue.main.async {
                    if process.terminationStatus == 0 {
                        completion(stdout, nil)
                    } else {
                        completion(stdout, stderr.isEmpty ? "exit \(process.terminationStatus)" : stderr)
                    }
                }
            } catch {
                DispatchQueue.main.async { completion(nil, error.localizedDescription) }
            }
        }
    }
}

// MARK: - App delegate

final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate {
    private var statusItem: NSStatusItem!
    private var instanceLockFD: Int32 = -1
    private var snapshot = Snapshot()
    private var timer: Timer?
    private var refreshing = false
    private var menuOpen = false

    private let isoFormatters: [ISO8601DateFormatter] = {
        let withFraction = ISO8601DateFormatter()
        withFraction.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let plain = ISO8601DateFormatter()
        plain.formatOptions = [.withInternetDateTime]
        return [withFraction, plain]
    }()

    private func acquireInstanceLock() -> Bool {
        let directory = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/codex-auto-continue")
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let lockPath = directory.appendingPathComponent("menubar.lock").path
        let descriptor = open(lockPath, O_CREAT | O_RDWR, 0o644)
        if descriptor < 0 { return true }
        if flock(descriptor, LOCK_EX | LOCK_NB) != 0 {
            close(descriptor)
            return false
        }
        instanceLockFD = descriptor
        let owner = "\(ProcessInfo.processInfo.processIdentifier)\n"
        _ = ftruncate(descriptor, 0)
        _ = write(descriptor, owner, owner.utf8.count)
        return true
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        // --ui-selftest is a short-lived diagnostic instance; it must not fight
        // the running app for the single-instance lock.
        if !CommandLine.arguments.contains("--ui-selftest"), !acquireInstanceLock() {
            // Another CodexContinue instance already owns the menu bar item.
            NSApp.terminate(nil)
            return
        }
        NSApp.setActivationPolicy(.accessory)
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        let menu = NSMenu()
        menu.delegate = self
        statusItem.menu = menu
        if let icon = Bundle.main.image(forResource: "statusTemplate") {
            icon.size = NSSize(width: 18, height: 18)
            icon.isTemplate = true
            statusItem.button?.image = icon
            statusItem.button?.imagePosition = .imageLeading
        }
        statusItem.button?.title = statusItem.button?.image == nil ? "✓ codex" : ""
        refresh()
        timer = Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { [weak self] _ in
            self?.refresh()
        }
        if CommandLine.arguments.contains("--ui-selftest") {
            var attempts = 0
            func finishSelfTest() {
                attempts += 1
                let loaded = !self.refreshing && !self.snapshot.quotaText.contains("读取中")
                if !loaded && attempts < 20 {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { finishSelfTest() }
                    return
                }
                let button = self.statusItem.button
                print("ui-title: \(button?.title ?? "nil")")
                print("ui-tooltip: \(button?.toolTip ?? "nil")")
                print("ui-pending: \(self.snapshot.pendingCount) interrupted: \(self.snapshot.interrupted.count)")
                self.menuOpen = true
                self.buildMenu()
                let titles = (self.statusItem.menu?.items ?? []).map { item -> String in
                    if let submenu = item.submenu, !submenu.items.isEmpty {
                        let children = submenu.items.map { $0.title }.joined(separator: "/")
                        return "\(item.title.isEmpty ? "-" : item.title)[\(children)]"
                    }
                    return item.title.isEmpty ? "-" : item.title
                }
                print("ui-menu: \(titles.joined(separator: " | "))")
                print("ui-visible: \(String(describing: button?.window != nil))")
                print("ui-icon: \(button?.image != nil) template: \(button?.image?.isTemplate == true)")
                NSApp.terminate(nil)
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { finishSelfTest() }
        }
    }

    // MARK: data loading

    func refresh() {
        guard !refreshing else { return }
        refreshing = true
        guard let cli = CLI.discover() else {
            snapshot.error = "找不到 codex-continue CLI（可在菜单里指定）"
            render()
            refreshing = false
            return
        }
        let group = DispatchGroup()
        var statusOut: String?
        var scanOut: String?
        var cliError: String?

        group.enter()
        CLI.run(cli, ["status", "--json"]) { out, err in
            statusOut = out
            if let err = err { cliError = err }
            group.leave()
        }
        group.enter()
        CLI.run(cli, ["scan", "--days", "14", "--json"]) { out, _ in
            scanOut = out
            group.leave()
        }
        group.notify(queue: .main) {
            self.refreshing = false
            if let err = cliError {
                self.snapshot.error = err
                self.render()
                return
            }
            self.snapshot = self.parse(statusJSON: statusOut, scanJSON: scanOut)
            self.render()
        }
    }

    private func parse(statusJSON: String?, scanJSON: String?) -> Snapshot {
        var snap = Snapshot()
        if let data = statusJSON?.data(using: .utf8),
           let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            if let dir = root["data_dir"] as? String { snap.dataDir = dir }
            if let scheduler = root["scheduler"] as? String { snap.schedulerText = "调度器：" + scheduler }
            if let quota = root["quota"] as? [String: Any], let windows = quota["windows"] as? [[String: Any]] {
                var parts: [String] = []
                for window in windows {
                    let kind = (window["kind"] as? String) == "primary" ? "5h" : "周"
                    let used = window["used_percent"] as? Double ?? 0
                    var part = "\(kind) \(Int(used))%"
                    if let reset = window["resets_at"] as? String, let date = self.date(fromISO: reset) {
                        part += "→" + self.timeText(date)
                    }
                    parts.append(part)
                }
                snap.quotaText = "额度：" + (parts.isEmpty ? "未知" : parts.joined(separator: "  "))
            }
            if let threads = root["threads"] as? [[String: Any]] {
                for thread in threads {
                    let status = thread["status"] as? String ?? ""
                    guard ["armed", "running", "failed"].contains(status) else { continue }
                    snap.registered.append(
                        RegisteredThread(
                            threadID: thread["thread_id"] as? String ?? "",
                            title: thread["title"] as? String,
                            status: status,
                            fireAt: (thread["fire_at"] as? String).flatMap { self.date(fromISO: $0) },
                            attempts: thread["attempts"] as? Int ?? 0,
                            lastError: thread["last_error"] as? String,
                            message: thread["message"] as? String ?? ""
                        )
                    )
                }
            }
            snap.pendingCount = snap.registered.count
            snap.nextFire = snap.registered.compactMap { $0.fireAt }.min()
        }
        if let data = scanJSON?.data(using: .utf8),
           let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let interrupted = root["interrupted"] as? [[String: Any]] {
            for item in interrupted {
                let cwd = item["cwd"] as? String ?? ""
                let resetHint = item["reset_hint"] as? String
                let date = resetHint.flatMap { self.date(fromISO: $0) }
                snap.interrupted.append(
                    InterruptedThread(
                        threadID: item["thread_id"] as? String ?? "",
                        title: item["title"] as? String,
                        cwd: (cwd as NSString).lastPathComponent,
                        lastUserText: self.flatten(item["last_user_text"] as? String ?? ""),
                        resetHint: date.map { self.timeText($0) },
                        ageText: self.ageText((item["mtime"] as? Double) ?? 0)
                    )
                )
            }
        }
        return snap
    }

    // MARK: rendering

    private func render() {
        let hasIcon = statusItem.button?.image != nil
        if let error = snapshot.error {
            statusItem.button?.title = "⚠︎"
            statusItem.button?.toolTip = error
        } else if snapshot.pendingCount > 0, let fire = snapshot.nextFire {
            statusItem.button?.title = (hasIcon ? " " : "⏳ ") + timeText(fire)
            statusItem.button?.toolTip = "待续跑 \(snapshot.pendingCount) 个，下次 \(timeText(fire))"
        } else if !snapshot.interrupted.isEmpty {
            statusItem.button?.title = (hasIcon ? " " : "⏳") + "\(snapshot.interrupted.count)"
            statusItem.button?.toolTip = "\(snapshot.interrupted.count) 个会话因额度中断，尚未安排续跑"
        } else {
            statusItem.button?.title = hasIcon ? "" : "✓"
            statusItem.button?.toolTip = "没有待续跑任务"
        }
        if menuOpen { buildMenu() }
    }

    private func buildMenu() {
        guard let menu = statusItem.menu else { return }
        menu.removeAllItems()

        let quotaItem = NSMenuItem(title: snapshot.quotaText, action: nil, keyEquivalent: "")
        quotaItem.isEnabled = false
        menu.addItem(quotaItem)

        if snapshot.error == nil {
            let pendingTitle: String
            if snapshot.pendingCount == 0 {
                pendingTitle = "待续跑：0"
            } else if let fire = snapshot.nextFire {
                pendingTitle = "待续跑：\(snapshot.pendingCount) 个 · 下次 \(timeText(fire))"
            } else {
                pendingTitle = "待续跑：\(snapshot.pendingCount) 个"
            }
            let pendingItem = NSMenuItem(title: pendingTitle, action: nil, keyEquivalent: "")
            pendingItem.isEnabled = false
            menu.addItem(pendingItem)

            if !snapshot.schedulerText.isEmpty {
                let schedulerItem = NSMenuItem(title: snapshot.schedulerText, action: nil, keyEquivalent: "")
                schedulerItem.isEnabled = false
                menu.addItem(schedulerItem)
            }
            menu.addItem(.separator())

            // Interrupted sessions
            let interruptedHeader = NSMenuItem(
                title: "因额度中断：\(snapshot.interrupted.count)",
                action: nil,
                keyEquivalent: ""
            )
            interruptedHeader.isEnabled = false
            menu.addItem(interruptedHeader)
            if snapshot.interrupted.isEmpty {
                let empty = NSMenuItem(title: "  无", action: nil, keyEquivalent: "")
                empty.isEnabled = false
                menu.addItem(empty)
            }
            for thread in snapshot.interrupted.prefix(8) {
                let label = thread.title ?? thread.cwd
                let title = "  \(label) · \(thread.ageText)"
                let item = NSMenuItem(title: title, action: nil, keyEquivalent: "")
                item.toolTip = "\(thread.title ?? "")\n\(thread.cwd)\n最后一句：\(thread.lastUserText)\n线程：\(thread.threadID)"
                let submenu = NSMenu()
                let armDefault = NSMenuItem(
                    title: "用默认消息续跑",
                    action: #selector(armWithDefaultMessage(_:)),
                    keyEquivalent: ""
                )
                armDefault.target = self
                armDefault.representedObject = thread.threadID
                submenu.addItem(armDefault)
                let armCustom = NSMenuItem(
                    title: "自定义消息…",
                    action: #selector(armWithCustomMessage(_:)),
                    keyEquivalent: ""
                )
                armCustom.target = self
                armCustom.representedObject = thread.threadID
                submenu.addItem(armCustom)
                item.submenu = submenu
                menu.addItem(item)
            }

            // Registered
            if !snapshot.registered.isEmpty {
                menu.addItem(.separator())
                let registeredHeader = NSMenuItem(
                    title: "已安排：\(snapshot.registered.count)",
                    action: nil,
                    keyEquivalent: ""
                )
                registeredHeader.isEnabled = false
                menu.addItem(registeredHeader)
                for thread in snapshot.registered {
                    let fire = thread.fireAt.map { timeText($0) } ?? "—"
                    let statusText: String
                    switch thread.status {
                    case "armed": statusText = "已安排"
                    case "running": statusText = "续跑中"
                    case "failed": statusText = "失败"
                    default: statusText = thread.status
                    }
                    let label = thread.title ?? String(thread.threadID.prefix(8))
                    let item = NSMenuItem(
                        title: "  \(statusText) · \(fire) · \(label)",
                        action: nil,
                        keyEquivalent: ""
                    )
                    item.toolTip = "\(thread.title ?? "")\n线程：\(thread.threadID)\n\(thread.lastError ?? "")"
                    let submenu = NSMenu()
                    let editMessage = NSMenuItem(
                        title: "编辑消息…",
                        action: #selector(editScheduledMessage(_:)),
                        keyEquivalent: ""
                    )
                    editMessage.target = self
                    editMessage.representedObject = thread.threadID
                    submenu.addItem(editMessage)
                    let cancel = NSMenuItem(
                        title: "取消续跑",
                        action: #selector(disarm(_:)),
                        keyEquivalent: ""
                    )
                    cancel.target = self
                    cancel.representedObject = thread.threadID
                    submenu.addItem(cancel)
                    item.submenu = submenu
                    menu.addItem(item)
                }
            }

            menu.addItem(.separator())
            let refreshItem = NSMenuItem(title: "刷新", action: #selector(refreshNow), keyEquivalent: "r")
            refreshItem.target = self
            menu.addItem(refreshItem)

            let logItem = NSMenuItem(title: "打开运行日志", action: #selector(openLog), keyEquivalent: "l")
            logItem.target = self
            menu.addItem(logItem)

            let codexItem = NSMenuItem(title: "打开 Codex App", action: #selector(openCodex), keyEquivalent: "")
            codexItem.target = self
            menu.addItem(codexItem)

            let cliItem = NSMenuItem(title: "指定 CLI 路径…", action: #selector(chooseCLI), keyEquivalent: "")
            cliItem.target = self
            menu.addItem(cliItem)

            menu.addItem(.separator())
            let loginItem = NSMenuItem(
                title: "开机自动启动",
                action: #selector(toggleLaunchAtLogin(_:)),
                keyEquivalent: ""
            )
            loginItem.target = self
            loginItem.state = launchAtLogin() ? .on : .off
            menu.addItem(loginItem)
        }

        menu.addItem(.separator())
        let quitItem = NSMenuItem(title: "退出 Codex Auto Continue", action: #selector(quit), keyEquivalent: "q")
        quitItem.target = self
        menu.addItem(quitItem)
    }

    // MARK: actions

    @objc private func refreshNow() {
        refresh()
    }

    @objc private func armWithDefaultMessage(_ sender: NSMenuItem) {
        guard let threadID = sender.representedObject as? String, let cli = currentCLI() else { return }
        CLI.run(cli, ["arm", threadID, "--json"]) { _, error in
            self.showResult(error == nil, error ?? "已安排续跑")
            self.refresh()
        }
    }

    @objc private func armWithCustomMessage(_ sender: NSMenuItem) {
        guard let threadID = sender.representedObject as? String, let cli = currentCLI() else { return }
        guard let message = promptMessage(defaultText: "上一轮因 usage limit 中断。请从中断处继续未完成的工作，完成后简要汇报结果与未完成项；不要重复已完成的部分。") else {
            return
        }
        CLI.run(cli, ["arm", threadID, "--message", message, "--json"]) { _, error in
            self.showResult(error == nil, error ?? "已安排续跑")
            self.refresh()
        }
    }

    @objc private func editScheduledMessage(_ sender: NSMenuItem) {
        guard let threadID = sender.representedObject as? String, let cli = currentCLI() else { return }
        let current = snapshot.registered.first { $0.threadID == threadID }?.message ?? ""
        guard let message = promptMessage(defaultText: current) else { return }
        CLI.run(cli, ["message", threadID, "--message", message, "--json"]) { _, error in
            self.showResult(error == nil, error ?? "已更新消息")
            self.refresh()
        }
    }

    @objc private func disarm(_ sender: NSMenuItem) {
        guard let threadID = sender.representedObject as? String, let cli = currentCLI() else { return }
        CLI.run(cli, ["disarm", threadID]) { _, error in
            self.showResult(error == nil, error ?? "已取消续跑")
            self.refresh()
        }
    }

    @objc private func openLog() {
        let dir = snapshot.dataDir.isEmpty
            ? FileManager.default.homeDirectoryForCurrentUser
                .appendingPathComponent("Library/Application Support/codex-auto-continue").path
            : snapshot.dataDir
        let log = dir + "/run.log"
        if !FileManager.default.fileExists(atPath: log) {
            FileManager.default.createFile(atPath: log, contents: Data())
        }
        NSWorkspace.shared.open(URL(fileURLWithPath: log))
    }

    @objc private func openCodex() {
        if let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.openai.chatgpt")
            ?? NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.openai.codex") {
            NSWorkspace.shared.openApplication(at: url, configuration: NSWorkspace.OpenConfiguration())
        } else {
            let alert = NSAlert()
            alert.messageText = "没找到 Codex App"
            alert.runModal()
        }
    }

    @objc private func chooseCLI() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false
        panel.prompt = "选择 codex-continue"
        if panel.runModal() == .OK, let url = panel.url {
            UserDefaults.standard.set(url.path, forKey: "cliPath")
            refresh()
        }
    }

    @objc private func toggleLaunchAtLogin(_ sender: NSMenuItem) {
        let enabled = launchAtLogin()
        setLaunchAtLogin(!enabled)
        sender.state = enabled ? .off : .on
    }

    @objc private func quit() {
        NSApp.terminate(nil)
    }

    // MARK: helpers

    private func currentCLI() -> String? {
        if let cli = CLI.discover() { return cli }
        let alert = NSAlert()
        alert.messageText = "找不到 codex-continue CLI"
        alert.informativeText = "请在菜单里用「指定 CLI 路径…」选择脚手架里的 bin/codex-continue。"
        alert.runModal()
        return nil
    }

    private func showResult(_ ok: Bool, _ text: String) {
        if ok { return }
        let alert = NSAlert()
        alert.messageText = "操作失败"
        alert.informativeText = text
        alert.alertStyle = .warning
        alert.runModal()
    }

    private func promptMessage(defaultText: String) -> String? {
        let alert = NSAlert()
        alert.messageText = "续跑时发送的消息"
        alert.informativeText = "额度重置后会把这段文字发给该会话。"
        let scroll = NSScrollView(frame: NSRect(x: 0, y: 0, width: 420, height: 110))
        let textView = NSTextView(frame: scroll.bounds)
        textView.string = defaultText
        textView.isRichText = false
        textView.font = NSFont.systemFont(ofSize: 12)
        scroll.documentView = textView
        scroll.hasVerticalScroller = true
        scroll.borderType = .bezelBorder
        alert.accessoryView = scroll
        alert.addButton(withTitle: "安排续跑")
        alert.addButton(withTitle: "取消")
        guard alert.runModal() == .alertFirstButtonReturn else { return nil }
        let text = textView.string.trimmingCharacters(in: .whitespacesAndNewlines)
        return text.isEmpty ? defaultText : text
    }

    private func date(fromISO text: String) -> Date? {
        for formatter in isoFormatters {
            if let date = formatter.date(from: text) { return date }
        }
        return nil
    }

    private func timeText(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm"
        return formatter.string(from: date)
    }

    private func ageText(_ timestamp: Double) -> String {
        guard timestamp > 0 else { return "" }
        let seconds = Date().timeIntervalSince1970 - timestamp
        if seconds < 3600 { return "\(Int(seconds / 60)) 分钟前" }
        if seconds < 86400 { return "\(Int(seconds / 3600)) 小时前" }
        return "\(Int(seconds / 86400)) 天前"
    }

    private func flatten(_ text: String) -> String {
        text.replacingOccurrences(of: "\n", with: " ").prefix(90).description
    }

    // MARK: menu delegate

    func menuWillOpen(_ menu: NSMenu) {
        menuOpen = true
        buildMenu()
        refresh()
    }

    func menuDidClose(_ menu: NSMenu) {
        menuOpen = false
    }

    // MARK: launch at login

    private var loginPlistURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/LaunchAgents/local.qyh.codex-continue-menubar.plist")
    }

    private func launchAtLogin() -> Bool {
        FileManager.default.fileExists(atPath: loginPlistURL.path)
    }

    private func setLaunchAtLogin(_ enabled: Bool) {
        let fm = FileManager.default
        if enabled {
            let binary = Bundle.main.executablePath ?? CommandLine.arguments[0]
            let plist = """
            <?xml version="1.0" encoding="UTF-8"?>
            <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
            <plist version="1.0">
            <dict>
              <key>Label</key><string>local.qyh.codex-continue-menubar</string>
              <key>ProgramArguments</key><array><string>\(binary)</string></array>
              <key>RunAtLoad</key><true/>
              <key>ProcessType</key><string>Interactive</string>
            </dict>
            </plist>
            """
            try? fm.createDirectory(at: loginPlistURL.deletingLastPathComponent(), withIntermediateDirectories: true)
            try? plist.write(to: loginPlistURL, atomically: true, encoding: .utf8)
            // Do not bootstrap here: RunAtLoad would immediately start a second
            // instance. ~/Library/LaunchAgents is loaded automatically at login.
        } else {
            let uid = getuid()
            _ = shell("/bin/launchctl", ["bootout", "gui/\(uid)/local.qyh.codex-continue-menubar"])
            try? fm.removeItem(at: loginPlistURL)
        }
    }

    @discardableResult
    private func shell(_ path: String, _ args: [String]) -> Int32 {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: path)
        process.arguments = args
        process.standardOutput = Pipe()
        process.standardError = Pipe()
        do {
            try process.run()
            process.waitUntilExit()
            return process.terminationStatus
        } catch {
            return -1
        }
    }
}

// MARK: - main

if CommandLine.arguments.contains("--check") {
    if let cli = CLI.discover() {
        print("cli: \(cli)")
        let result = CLI.runSync(cli, ["status", "--json"])
        print(result.0)
        if !result.1.isEmpty { FileHandle.standardError.write(Data(result.1.utf8)) }
        exit(result.2 == 0 ? 0 : 1)
    } else {
        print("cli not found")
        exit(1)
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
