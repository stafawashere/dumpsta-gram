import Foundation

// Which engine the app runs on, and how a real client is made for each account.
//
// Selecting the engine, first match wins:
//    launch argument   --engine real   or   --engine dummy
//    environment       INSTAGRAMPLUS_ENGINE=real   or   INSTAGRAMPLUS_ENGINE=dummy
//    settings          the developer section's choice for the next launch, stored under
//                      EngineSelection.nextLaunchKey
// The default is real. --exercise and --snapshot-dir always run on the dummy, because their
// seed ids and scripted replies exist only in the dummy's world. When the embedded runtime is
// missing or will not start, the app shows that state and names scripts/build-runtime.command.
//
// With the real engine, each saved session under
// ~/Library/Application Support/io.github.stafawashere.instagramplus/Sessions becomes one
// account, opened with SyncClient.from_session_file so the write budget and write stop persist
// in the ledger beside it. Each account has its own file, session-<ds_user_id>.json, written by
// the engine's Session.save and never shared. The engine's default Behavior, PARITY, is used.
//
// Developer fallbacks, read at launch only:
//    INSTAGRAMPLUS_COOKIE_FILE=<path>   a KEY=value file (the same shape the dumpsta CLI reads,
//                                       IG_SESSIONID, IG_DS_USER_ID, IG_CSRFTOKEN, optional
//                                       IG_MID). Adopted through the bridge and saved as above.
//                                       Values stay in memory and in the owner-only session
//                                       file. Nothing prints or logs them.
//    INSTAGRAMPLUS_ENGINE_CAPABILITIES=profile,feed,comments,media-writes,social-writes,
//                                       inbox,messages,message-requests,unread-counts,notes,
//                                       direct-writes,events
//                                       which wired capabilities may reach Instagram. Unset
//                                       means all of them. A live check sets it to spend only
//                                       the requests it means to.
enum EngineSelection: String, Sendable {
   case dummy
   case real

   static let nextLaunchKey = "engineForNextLaunch"

   static func resolve(arguments: [String], environment: [String: String], storedChoice: String? = nil) -> EngineSelection {
      let isProbeRun = arguments.contains("--exercise") || arguments.contains("--snapshot-dir")

      if isProbeRun {
         return .dummy
      }

      if let flagIndex = arguments.firstIndex(of: "--engine"), arguments.indices.contains(flagIndex + 1) {
         return EngineSelection(rawValue: arguments[flagIndex + 1]) ?? .real
      }

      if let fromEnvironment = environment["INSTAGRAMPLUS_ENGINE"].flatMap(EngineSelection.init(rawValue:)) {
         return fromEnvironment
      }

      return storedChoice.flatMap(EngineSelection.init(rawValue:)) ?? .real
   }
}

struct RealEngineLaunch: Sendable {
   let engines: [PythonEngine]
   let problem: String?
   let bootstrap: PythonRuntime.Report?
   var enabled: Set<PythonEngine.Capability> = []
}

enum PythonEngineFactory {
   // Under --exercise the dummy's accounts get session files too, so removing one can be
   // checked. They live in INSTAGRAMPLUS_SESSIONS_DIR or a temporary directory, never in
   // Application Support.
   static var sessionsDirectory: URL {
      let process = ProcessInfo.processInfo

      if process.arguments.contains("--exercise") {
         let exerciseDirectory = process.environment["INSTAGRAMPLUS_SESSIONS_DIR"]
         let fallback = FileManager.default.temporaryDirectory.appendingPathComponent("instagramplus-exercise-sessions")
         return exerciseDirectory.map { URL(fileURLWithPath: $0, isDirectory: true) } ?? fallback
      }

      let applicationSupport = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
      return applicationSupport
         .appendingPathComponent("io.github.stafawashere.instagramplus")
         .appendingPathComponent("Sessions")
   }

   static func sessionFile(for userID: String) -> URL {
      sessionsDirectory.appendingPathComponent("session-\(userID).json")
   }

   static func enabledCapabilities(environment: [String: String]) -> Set<PythonEngine.Capability> {
      guard let listed = environment["INSTAGRAMPLUS_ENGINE_CAPABILITIES"] else {
         return Set(PythonEngine.Capability.allCases)
      }

      let names = listed.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }
      return Set(names.compactMap(PythonEngine.Capability.init(rawValue:)))
   }

   // App.init is synchronous and every account needs its viewer id before its stores exist, so
   // the launch waits here once. The work runs on the bridge's own queue, never the main thread.
   static func launchBlocking(environment: [String: String]) -> RealEngineLaunch {
      let box = LaunchBox()
      let finished = DispatchSemaphore(value: 0)

      Task.detached {
         box.value = await launch(environment: environment)
         finished.signal()
      }

      finished.wait()
      return box.value ?? RealEngineLaunch(engines: [], problem: "the engine launch did not finish", bootstrap: nil)
   }

   static func launch(environment: [String: String]) async -> RealEngineLaunch {
      let bridge = PythonBridge.shared
      let startedAt = Date()
      let report: PythonRuntime.Report

      do {
         report = try await bridge.bootstrap()
      } catch {
         let problem = "Python bootstrap failed: \(error.description)"
         print("[engine] \(problem)")
         return RealEngineLaunch(engines: [], problem: problem, bootstrap: nil)
      }

      let elapsed = Int(Date().timeIntervalSince(startedAt) * 1000)
      print("[engine] python bootstrap ok, python \(report.pythonVersion), runtime \(report.runtimeRoot), dumpstagram \(report.engineModulePath), sitecustomize loaded \(report.siteHookLoaded), \(elapsed) ms")

      let enabled = enabledCapabilities(environment: environment)
      print("[engine] capabilities allowed to reach Instagram: \(enabled.map(\.rawValue).sorted().joined(separator: ","))")

      do {
         try prepareSessionsDirectory()
      } catch {
         return RealEngineLaunch(engines: [], problem: "could not create \(sessionsDirectory.path)", bootstrap: report, enabled: enabled)
      }

      var engines: [PythonEngine] = []
      var adoptedFile: URL?

      if let cookiePath = environment["INSTAGRAMPLUS_COOKIE_FILE"] {
         let adopted: Adoption = switch readCookieFile(URL(fileURLWithPath: cookiePath)) {
            case .success(let material): await adopt(material, enabled: enabled)
            case .failure(let problem): .failed(problem)
         }

         switch adopted {
            case .adopted(let engine):
               engines.append(engine)
               adoptedFile = sessionFile(for: engine.viewerID)

            case .checkpoint:
               let problem = "The session in the cookie file is in a checkpoint. Confirm it in a browser first."
               return RealEngineLaunch(engines: [], problem: problem, bootstrap: report, enabled: enabled)

            case .revoked:
               let problem = "The engine refused the session in the cookie file."
               return RealEngineLaunch(engines: [], problem: problem, bootstrap: report, enabled: enabled)

            case .failed(let problem):
               print("[engine] \(problem.description)")
               return RealEngineLaunch(engines: [], problem: problem.description, bootstrap: report, enabled: enabled)
         }
      }

      for sessionFile in savedSessionFiles() where sessionFile != adoptedFile {
         do throws(EngineError) {
            switch try await bridge.open(sessionFile: sessionFile) {
               case .value(let opened):
                  engines.append(PythonEngine(bridge: bridge, opened: opened, sessionFile: sessionFile, enabled: enabled))

               case .checkpoint:
                  print("[engine] \(sessionFile.lastPathComponent) is in a checkpoint, not opened")
            }
         } catch {
            print("[engine] \(sessionFile.lastPathComponent) did not open: \(error)")
         }
      }

      print("[engine] \(engines.count) account session(s) open")

      let problem = engines.isEmpty ? "No saved session. Connect a browser session to use the real engine." : nil
      return RealEngineLaunch(engines: engines, problem: problem, bootstrap: report, enabled: enabled)
   }

   struct Problem: Error, CustomStringConvertible {
      let description: String
   }

   // What adopting cookie material produced. A checkpoint and a refused session are states for a
   // person to resolve, the same ones a later call can produce, and neither is retried.
   enum Adoption: Sendable {
      case adopted(PythonEngine)
      case checkpoint(PythonEngine, Checkpoint)
      case revoked
      case failed(Problem)
   }

   // Adoption from cookie material, the path the session setup screen and the developer cookie
   // file both take. The result is saved and reopened by the next launch as well.
   static func adopt(_ material: PythonBridge.CookieMaterial, enabled: Set<PythonEngine.Capability>) async -> Adoption {
      let bridge = PythonBridge.shared
      let isUsableFileName = !material.userID.isEmpty && material.userID.allSatisfy { $0.isLetter || $0.isNumber }

      guard isUsableFileName else {
         return .failed(Problem(description: "ds_user_id may hold letters and digits only"))
      }

      let sessionFile = sessionFile(for: material.userID)

      do {
         try prepareSessionsDirectory()
      } catch {
         return .failed(Problem(description: "could not create \(sessionsDirectory.path)"))
      }

      do throws(EngineError) {
         switch try await bridge.adopt(material, savingTo: sessionFile) {
            case .value(let opened):
               print("[engine] adopted a browser session into \(sessionFile.lastPathComponent)")
               return .adopted(PythonEngine(bridge: bridge, opened: opened, sessionFile: sessionFile, enabled: enabled))

            case .checkpoint(let checkpoint):
               print("[engine] the adopted session is in a checkpoint")
               let savedFile = FileManager.default.fileExists(atPath: sessionFile.path) ? sessionFile : nil
               let engine = PythonEngine(bridge: bridge, opened: nil, sessionFile: savedFile, enabled: enabled, viewerID: material.userID)
               return .checkpoint(engine, checkpoint)
         }
      } catch {
         if error == .authenticationFailed {
            print("[engine] the engine refused the adopted session")
            return .revoked
         }

         return .failed(Problem(description: "adopting the session failed: \(error)"))
      }
   }

   static func readCookieFile(_ url: URL) -> Result<PythonBridge.CookieMaterial, Problem> {
      guard let contents = try? String(contentsOf: url, encoding: .utf8) else {
         return .failure(Problem(description: "could not read the cookie file at \(url.path)"))
      }

      var values: [String: String] = [:]

      for rawLine in contents.split(whereSeparator: \.isNewline) {
         let line = rawLine.trimmingCharacters(in: .whitespaces)
         let isComment = line.hasPrefix("#")

         guard !line.isEmpty, !isComment, let separator = line.firstIndex(of: "=") else {
            continue
         }

         let key = line[..<separator].trimmingCharacters(in: .whitespaces)
         let value = line[line.index(after: separator)...]
            .trimmingCharacters(in: .whitespaces)
            .trimmingCharacters(in: CharacterSet(charactersIn: "\"'"))
         values[key] = value
      }

      let requiredKeys = ["IG_SESSIONID", "IG_DS_USER_ID", "IG_CSRFTOKEN"]
      let missingKeys = requiredKeys.filter { (values[$0] ?? "").isEmpty }

      guard missingKeys.isEmpty else {
         return .failure(Problem(description: "the cookie file lacks \(missingKeys.joined(separator: ", "))"))
      }

      var extraCookies: [String: String] = [:]

      if let mid = values["IG_MID"], !mid.isEmpty {
         extraCookies["mid"] = mid
      }

      let material = PythonBridge.CookieMaterial(
         sessionID: values["IG_SESSIONID"] ?? "",
         userID: values["IG_DS_USER_ID"] ?? "",
         csrfToken: values["IG_CSRFTOKEN"] ?? "",
         extraCookies: extraCookies
      )

      return .success(material)
   }

   private static func prepareSessionsDirectory() throws {
      try FileManager.default.createDirectory(
         at: sessionsDirectory,
         withIntermediateDirectories: true,
         attributes: [.posixPermissions: 0o700]
      )
   }

   private static func savedSessionFiles() -> [URL] {
      let listed = (try? FileManager.default.contentsOfDirectory(
         at: sessionsDirectory,
         includingPropertiesForKeys: [.contentModificationDateKey]
      )) ?? []

      let sessionFiles = listed.filter { $0.lastPathComponent.hasPrefix("session-") && $0.pathExtension == "json" }

      return sessionFiles.sorted { first, second in
         let firstDate = (try? first.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
         let secondDate = (try? second.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
         return firstDate > secondDate
      }
   }
}

private final class LaunchBox: @unchecked Sendable {
   var value: RealEngineLaunch?
}
