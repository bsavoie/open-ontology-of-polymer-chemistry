// The OOPC Mac app: a launcher that runs the bundled Python's `oopc inspect` on
// loopback and opens it in the default browser. Clicking the Dock icon opens the
// browser again; quitting the app stops the server and its running workers.
//
// The workspace (releases/ and private .oopc/) lives under
// ~/Library/Application Support/OOPC, or OOPC_ROOT when set. The bundle is never
// written: the bundled release is copied into the workspace the first time this
// app version runs. OOPC_APP_NO_BROWSER=1 skips opening the browser (for tests).
import AppKit
import Darwin

struct LaunchError: LocalizedError {
    let message: String
    init(_ message: String) { self.message = message }
    var errorDescription: String? { message }
}

final class Launcher: NSObject, NSApplicationDelegate {
    private let resources = Bundle.main.resourceURL!
    private let environment = ProcessInfo.processInfo.environment
    private var server: Process?
    private var url: URL?
    private var log: FileHandle?
    private var quitting = false
    private var failed = false

    private let workspace: URL = {
        if let root = ProcessInfo.processInfo.environment["OOPC_ROOT"], !root.isEmpty {
            return URL(fileURLWithPath: (root as NSString).expandingTildeInPath, isDirectory: true).standardizedFileURL
        }
        return FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("OOPC", isDirectory: true)
    }()
    private var logURL: URL { workspace.appendingPathComponent(".oopc/app.log") }

    // MARK: Application

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.mainMenu = mainMenu()
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                try self.prepareWorkspace()
                let url = try self.startServer()
                DispatchQueue.main.async {
                    self.url = url
                    self.openBrowser()
                }
            } catch {
                DispatchQueue.main.async { self.fail("OOPC could not start", error.localizedDescription) }
            }
        }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        openBrowser()
        return false
    }

    func applicationDockMenu(_ sender: NSApplication) -> NSMenu? {
        let menu = NSMenu()
        menu.addItem(item("Open in Browser", #selector(openBrowser)))
        return menu
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        quitting = true
        guard let server = server, server.isRunning else { return .terminateNow }
        note("Stopping the server.")
        server.terminate()  // SIGTERM: the server stops its running workers before it exits.
        DispatchQueue.global().async {
            let deadline = Date().addingTimeInterval(10)
            while server.isRunning && Date() < deadline { Thread.sleep(forTimeInterval: 0.1) }
            if server.isRunning { kill(server.processIdentifier, SIGKILL) }
            DispatchQueue.main.async { sender.reply(toApplicationShouldTerminate: true) }
        }
        return .terminateLater
    }

    // MARK: Workspace

    private func prepareWorkspace() throws {
        let files = FileManager.default
        let releases = workspace.appendingPathComponent("releases", isDirectory: true)
        try files.createDirectory(at: workspace.appendingPathComponent(".oopc", isDirectory: true),
                                  withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        try files.createDirectory(at: releases, withIntermediateDirectories: true)
        openLog()
        let bundled = resources.appendingPathComponent("releases", isDirectory: true)
        let id = try releaseID(bundled.appendingPathComponent("current.json"))
        let target = releases.appendingPathComponent(id, isDirectory: true)
        let current = releases.appendingPathComponent("current.json")
        if !files.fileExists(atPath: target.path) {
            note("Installing release " + id + ".")
            let staging = releases.appendingPathComponent(".app-install-" + UUID().uuidString, isDirectory: true)
            defer { try? files.removeItem(at: staging) }
            try files.copyItem(at: bundled.appendingPathComponent(id, isDirectory: true), to: staging)
            try files.moveItem(at: staging, to: target)
            try writeCurrent(id, to: current)  // A release this app brings becomes the current one once.
        } else if !files.fileExists(atPath: current.path) {
            try writeCurrent(id, to: current)
        }
    }

    private func releaseID(_ path: URL) throws -> String {
        let value = try JSONSerialization.jsonObject(with: Data(contentsOf: path)) as? [String: Any]
        guard let id = value?["release_id"] as? String, id.hasPrefix("oopc-"),
              id.allSatisfy({ $0.isLetter || $0.isNumber || $0 == "-" }) else {
            throw LaunchError("The app's bundled release is missing or invalid.")
        }
        return id
    }

    private func writeCurrent(_ id: String, to path: URL) throws {
        try JSONSerialization.data(withJSONObject: ["release_id": id]).write(to: path, options: .atomic)
    }

    // MARK: Server

    private func startServer() throws -> URL {
        let port = choosePort()
        let process = Process()
        process.executableURL = resources.appendingPathComponent("python/bin/python3")
        process.arguments = ["-I", "-m", "oopc", "--root", workspace.path, "inspect", "--port", String(port)]
        process.currentDirectoryURL = workspace
        process.environment = serverEnvironment()
        process.standardInput = FileHandle.nullDevice
        if let log = log {
            process.standardOutput = log
            process.standardError = log
        }
        process.terminationHandler = { [weak self] stopped in
            DispatchQueue.main.async { self?.serverStopped(stopped.terminationStatus) }
        }
        try DispatchQueue.main.sync {
            if quitting { throw LaunchError("The app is quitting.") }
            note("Starting the server on port \(port).")
            try process.run()
            server = process
        }
        let deadline = Date().addingTimeInterval(120)
        while Date() < deadline {
            if !process.isRunning { throw LaunchError("The server stopped while starting.") }
            if listening(port) { return URL(string: "http://127.0.0.1:\(port)/")! }
            Thread.sleep(forTimeInterval: 0.2)
        }
        process.terminate()
        throw LaunchError("The server did not answer within two minutes.")
    }

    private func serverStopped(_ status: Int32) {
        note("The server exited with status \(status).")
        if !quitting { fail("OOPC stopped", "The server stopped unexpectedly (status \(status)).") }
    }

    /// The usual port, a few neighbours, then any free one.
    private func choosePort() -> UInt16 {
        for port in UInt16(8765)...UInt16(8774) where claim(port) != nil { return port }
        return claim(0) ?? 8765
    }

    private func loopback(_ port: UInt16) -> sockaddr_in {
        var address = sockaddr_in()
        address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        address.sin_family = sa_family_t(AF_INET)
        address.sin_port = port.bigEndian
        address.sin_addr.s_addr = inet_addr("127.0.0.1")
        return address
    }

    /// Binds and releases the port; the port actually bound, or nil when it is taken.
    private func claim(_ port: UInt16) -> UInt16? {
        let socket = Darwin.socket(AF_INET, SOCK_STREAM, 0)
        guard socket >= 0 else { return nil }
        defer { close(socket) }
        var address = loopback(port)
        var length = socklen_t(MemoryLayout<sockaddr_in>.size)
        let bound = withUnsafeMutablePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                Darwin.bind(socket, $0, length) == 0 && getsockname(socket, $0, &length) == 0
            }
        }
        return bound ? UInt16(bigEndian: address.sin_port) : nil
    }

    private func listening(_ port: UInt16) -> Bool {
        let socket = Darwin.socket(AF_INET, SOCK_STREAM, 0)
        guard socket >= 0 else { return false }
        defer { close(socket) }
        var address = loopback(port)
        return withUnsafePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                connect(socket, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) == 0
            }
        }
    }

    /// Finder starts apps with a bare PATH, which misses CLIs installed with Homebrew,
    /// npm or the Claude installer; take the login shell's PATH and add the usual places.
    private func serverEnvironment() -> [String: String] {
        var values = environment.filter { !$0.key.hasPrefix("PYTHON") }
        var parts = (loginShellPath() ?? "").split(separator: ":").map(String.init)
        parts += [NSHomeDirectory() + "/.local/bin", "/opt/homebrew/bin", "/usr/local/bin"]
        parts += (environment["PATH"] ?? "/usr/bin:/bin:/usr/sbin:/sbin").split(separator: ":").map(String.init)
        var seen = Set<String>()
        values["PATH"] = parts.filter { !$0.isEmpty && seen.insert($0).inserted }.joined(separator: ":")
        if values["LANG"] == nil { values["LANG"] = "en_US.UTF-8" }
        return values
    }

    private func loginShellPath() -> String? {
        let output = FileManager.default.temporaryDirectory.appendingPathComponent("oopc-path-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: output) }
        let shell = Process()
        shell.executableURL = URL(fileURLWithPath: environment["SHELL"] ?? "/bin/zsh")
        // A file, not a pipe: whatever the profile prints or leaves running cannot block the read.
        shell.arguments = ["-l", "-i", "-c", "printf '%s' \"$PATH\" > \"$1\"", "oopc", output.path]
        shell.standardInput = FileHandle.nullDevice
        shell.standardOutput = FileHandle.nullDevice
        shell.standardError = FileHandle.nullDevice
        let finished = DispatchSemaphore(value: 0)
        shell.terminationHandler = { _ in finished.signal() }
        do { try shell.run() } catch { return nil }
        if finished.wait(timeout: .now() + 10) == .timedOut {
            shell.terminate()
            note("The login shell did not report its PATH within 10 seconds.")
            return nil
        }
        return try? String(contentsOf: output, encoding: .utf8)
    }

    // MARK: Interface

    @objc private func openBrowser() {
        guard let url = url else { return }
        if environment["OOPC_APP_NO_BROWSER"] == "1" {
            note("Ready at " + url.absoluteString + " (browser not opened).")
        } else {
            NSWorkspace.shared.open(url)
        }
    }

    @objc private func showWorkspace() {
        NSWorkspace.shared.activateFileViewerSelecting([workspace])
    }

    @objc private func showLog() {
        NSWorkspace.shared.activateFileViewerSelecting([logURL])
    }

    private func mainMenu() -> NSMenu {
        let menu = NSMenu()
        let app = NSMenu()
        app.addItem(withTitle: "About OOPC", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        app.addItem(.separator())
        app.addItem(item("Open in Browser", #selector(openBrowser), "o"))
        app.addItem(item("Show Data Folder", #selector(showWorkspace)))
        app.addItem(item("Show Log", #selector(showLog)))
        app.addItem(.separator())
        app.addItem(withTitle: "Quit OOPC", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        let holder = NSMenuItem()
        holder.submenu = app
        menu.addItem(holder)
        return menu
    }

    private func item(_ title: String, _ action: Selector, _ key: String = "") -> NSMenuItem {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: key)
        item.target = self
        return item
    }

    private func fail(_ title: String, _ detail: String) {
        if failed { return }  // A failed start also ends the server; one alert is enough.
        failed = true
        note(title + ": " + detail)
        let alert = NSAlert()
        alert.messageText = title
        alert.informativeText = detail + "\n\nThe log is at " + logURL.path + "."
        alert.addButton(withTitle: "Quit")
        alert.addButton(withTitle: "Show Log")
        NSApp.activate(ignoringOtherApps: true)
        if alert.runModal() == .alertSecondButtonReturn { showLog() }
        quitting = true
        NSApp.terminate(nil)
    }

    // MARK: Log

    /// One log shared with the server's output, kept under the private .oopc folder.
    private func openLog() {
        let files = FileManager.default
        if let size = (try? files.attributesOfItem(atPath: logURL.path))?[.size] as? Int, size > 5_000_000 {
            let previous = logURL.appendingPathExtension("1")
            try? files.removeItem(at: previous)
            try? files.moveItem(at: logURL, to: previous)
        }
        if !files.fileExists(atPath: logURL.path) {
            files.createFile(atPath: logURL.path, contents: nil, attributes: [.posixPermissions: 0o600])
        }
        log = try? FileHandle(forWritingTo: logURL)
        log?.seekToEndOfFile()
        note("OOPC app " + (Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "") +
             " with workspace " + workspace.path + ".")
    }

    private func note(_ message: String) {
        let stamp = ISO8601DateFormatter().string(from: Date())
        log?.write(Data(("[app " + stamp + "] " + message + "\n").utf8))
    }
}

let application = NSApplication.shared
let launcher = Launcher()
application.delegate = launcher
application.setActivationPolicy(.regular)
application.run()
