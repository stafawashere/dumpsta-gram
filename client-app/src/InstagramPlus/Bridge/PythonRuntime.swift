import Darwin
import Foundation
import os
@preconcurrency import PythonKit

// Starts the embedded interpreter, once and before any other PythonKit use, following
// docs/bridge/overview.md. Only PythonBridge calls it, which the isolated parameter enforces.
//
// PythonKit leaves the GIL with whichever thread initialised the interpreter. The bridge's
// queue may run on a different thread each time, and the engine's own loop thread needs the
// GIL between calls, so bootstrap releases it and every later touch goes through withGIL.
enum PythonRuntime {
   struct Failure: Error, CustomStringConvertible {
      let description: String
   }

   struct Report: Sendable {
      let pythonVersion: String
      let runtimeRoot: String
      let engineSource: String
      let engineModulePath: String
      let siteHookLoaded: Bool
   }

   private typealias GILEnsure = @convention(c) () -> Int32
   private typealias GILRelease = @convention(c) (Int32) -> Void
   private typealias SaveThread = @convention(c) () -> UnsafeMutableRawPointer?

   private struct GILFunctions: @unchecked Sendable {
      let ensure: GILEnsure
      let release: GILRelease
   }

   private enum State {
      case notStarted
      case ready(Report, GILFunctions)
      case failed(Failure)
   }

   private static let state = OSAllocatedUnfairLock<State>(initialState: .notStarted)
   private static let logger = Logger(subsystem: "io.github.stafawashere.instagramplus", category: "python")

   static var architectureDirectory: String {
      #if arch(arm64)
      "aarch64"
      #elseif arch(x86_64)
      "x86_64"
      #else
      #error("Runtime/<arch> has no directory for this architecture")
      #endif
   }

   static func bootstrap(on bridge: isolated PythonBridge) throws(Failure) -> Report {
      let current = state.withLock { $0 }

      switch current {
         case .ready(let report, _):
            return report

         case .failed(let failure):
            throw failure

         case .notStarted:
            break
      }

      do {
         let (report, functions) = try start()
         state.withLock { $0 = .ready(report, functions) }
         logger.log("python bootstrap ok, \(report.pythonVersion, privacy: .public), runtime \(report.runtimeRoot, privacy: .public)")
         return report
      } catch {
         state.withLock { $0 = .failed(error) }
         logger.error("python bootstrap failed, \(error.description, privacy: .public)")
         throw error
      }
   }

   // Every PythonObject is created and released inside one of these blocks. The body is
   // synchronous, so the acquire and the release happen on the same thread.
   // The body cannot throw and its result must be Sendable, so no Python exception and no
   // PythonObject can leave the block and be released after the GIL is given back.
   static func withGIL<Value: Sendable>(on bridge: isolated PythonBridge, _ body: () -> Value) -> Value {
      guard case .ready(_, let functions) = state.withLock({ $0 }) else {
         preconditionFailure("PythonRuntime.withGIL before a successful bootstrap")
      }

      let gilState = functions.ensure()
      defer { functions.release(gilState) }

      return body()
   }

   private static func start() throws(Failure) -> (Report, GILFunctions) {
      let runtimeRoot = try resolveRuntimeRoot()
      let engineSource = try resolveEngineSource()
      let home = runtimeRoot.appendingPathComponent("python")
      let library = home.appendingPathComponent("lib/libpython3.12.dylib")
      let sitePackages = runtimeRoot.appendingPathComponent("site-packages")

      let requiredPaths = [home, library, sitePackages, engineSource.appendingPathComponent("dumpstagram")]
      let missingPaths = requiredPaths.filter { !FileManager.default.fileExists(atPath: $0.path) }

      guard missingPaths.isEmpty else {
         let listed = missingPaths.map(\.path).joined(separator: ", ")
         throw Failure(description: "the embedded runtime is incomplete, missing \(listed). Run client-app/scripts/build-runtime.command")
      }

      var searchPaths = [engineSource.path, sitePackages.path]

      #if DEBUG
      // A developer hook, such as engine/probes/cli_request_counter, loaded ahead of everything.
      if let prepended = ProcessInfo.processInfo.environment["INSTAGRAMPLUS_PYTHONPATH_PREPEND"], !prepended.isEmpty {
         searchPaths.insert(prepended, at: 0)
      }
      #endif

      setenv("PYTHONHOME", home.path, 1)
      setenv("PYTHONNOUSERSITE", "1", 1)
      setenv("PYTHONDONTWRITEBYTECODE", "1", 1)
      setenv("PYTHON_LIBRARY", library.path, 1)
      setenv("PYTHONPATH", searchPaths.joined(separator: ":"), 1)

      do {
         try PythonLibrary.loadLibrary()
      } catch {
         throw Failure(description: "could not load \(library.path): \(error)")
      }

      guard
         let ensure = symbol("PyGILState_Ensure", as: GILEnsure.self),
         let release = symbol("PyGILState_Release", as: GILRelease.self),
         let saveThread = symbol("PyEval_SaveThread", as: SaveThread.self)
      else {
         throw Failure(description: "\(library.path) does not export the GIL functions")
      }

      // The interpreter starts here and this thread holds the GIL until saveThread. Every
      // PythonObject lives inside importEngine, so none is released after the GIL goes.
      let imported = importEngine(searchPaths: searchPaths)
      _ = saveThread()

      switch imported {
         case .success(let (version, modulePath, siteHookLoaded)):
            let report = Report(
               pythonVersion: version,
               runtimeRoot: runtimeRoot.path,
               engineSource: engineSource.path,
               engineModulePath: modulePath,
               siteHookLoaded: siteHookLoaded
            )

            return (report, GILFunctions(ensure: ensure, release: release))

         case .failure(let reason):
            throw Failure(description: "import dumpstagram failed with the runtime at \(runtimeRoot.path) and the engine at \(engineSource.path): \(reason.description)")
      }
   }

   private static func importEngine(searchPaths: [String]) -> Result<(String, String, Bool), Failure> {
      let sys = Python.import("sys")
      let knownPaths = Set(Array(sys.path).compactMap { String($0) })

      for path in searchPaths.reversed() where !knownPaths.contains(path) {
         sys.path.insert(0, path)
      }

      let fullVersion = String(sys.version) ?? "unknown"
      let version = fullVersion.split(separator: " ").first.map(String.init) ?? fullVersion

      do {
         let dumpstagram = try Python.attemptImport("dumpstagram")
         let modulePath = String(dumpstagram.__file__) ?? "unknown"
         let siteHookLoaded = Bool(sys.modules.__contains__("sitecustomize")) ?? false
         return .success((version, modulePath, siteHookLoaded))
      } catch {
         return .failure(Failure(description: String(describing: error)))
      }
   }

   private static func symbol<Function>(_ name: String, as type: Function.Type) -> Function? {
      let defaultHandle = UnsafeMutableRawPointer(bitPattern: -2)

      guard let address = dlsym(defaultHandle, name) else {
         return nil
      }

      return unsafeBitCast(address, to: type)
   }

   private static func resolveRuntimeRoot() throws(Failure) -> URL {
      #if DEBUG
      try repositoryRoot().appendingPathComponent("Runtime").appendingPathComponent(architectureDirectory)
      #else
      try bundleResources().appendingPathComponent("Runtime").appendingPathComponent(architectureDirectory)
      #endif
   }

   private static func resolveEngineSource() throws(Failure) -> URL {
      #if DEBUG
      try repositoryRoot().appendingPathComponent("engine")
      #else
      try bundleResources().appendingPathComponent("engine")
      #endif
   }

   #if DEBUG
   // Injected by the DUMPSTA_REPOSITORY_ROOT build setting through config/InstagramPlus-Info.plist,
   // never derived from #filePath.
   private static func repositoryRoot() throws(Failure) -> URL {
      let configured = Bundle.main.object(forInfoDictionaryKey: "DumpstaRepositoryRoot") as? String ?? ""

      guard !configured.isEmpty else {
         throw Failure(description: "DumpstaRepositoryRoot is empty in Info.plist, so a debug build cannot find Runtime/ or engine/")
      }

      return URL(fileURLWithPath: configured).standardizedFileURL
   }
   #else
   private static func bundleResources() throws(Failure) -> URL {
      guard let resources = Bundle.main.resourceURL else {
         throw Failure(description: "the app bundle has no resource directory")
      }

      return resources
   }
   #endif
}
