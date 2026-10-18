import AppKit
import Foundation

// Loads the images the engine hands over as https addresses. Bytes stay in memory, because the session
// is ephemeral, its URLCache has no disk capacity, and no cookie goes along with the request.
// Nothing here builds an address, retries a failed load or logs an address, since the engine's
// media addresses carry signed query strings.
@MainActor
final class MediaLoader {
   enum Outcome {
      case loaded(NSImage)
      case failed
   }

   static let shared = MediaLoader()

   private let session: URLSession
   private let images = NSCache<NSURL, NSImage>()
   private var failedURLs: Set<URL> = []
   private var inFlight: [URL: Task<NSImage?, Never>] = [:]

   private init() {
      let configuration = URLSessionConfiguration.ephemeral
      configuration.urlCache = URLCache(memoryCapacity: 64 * 1024 * 1024, diskCapacity: 0)
      configuration.requestCachePolicy = .returnCacheDataElseLoad
      configuration.httpShouldSetCookies = false
      configuration.httpCookieStorage = nil
      configuration.urlCredentialStorage = nil

      session = URLSession(configuration: configuration)
      images.totalCostLimit = 128 * 1024 * 1024
   }

   static func isRemote(_ url: URL?) -> Bool {
      url?.scheme?.lowercased() == "https"
   }

   func cachedImage(for url: URL) -> NSImage? {
      images.object(forKey: url as NSURL)
   }

   func hasFailed(_ url: URL) -> Bool {
      failedURLs.contains(url)
   }

   func image(for url: URL) async -> Outcome {
      guard Self.isRemote(url) else {
         return .failed
      }

      if let cached = cachedImage(for: url) {
         return .loaded(cached)
      }

      if hasFailed(url) {
         return .failed
      }

      let load = inFlight[url] ?? startLoad(url)
      inFlight[url] = load
      let image = await load.value
      inFlight[url] = nil

      guard let image else {
         failedURLs.insert(url)
         return .failed
      }

      let approximateCost = Int(image.size.width * image.size.height * 4)
      images.setObject(image, forKey: url as NSURL, cost: approximateCost)
      return .loaded(image)
   }

   private func startLoad(_ url: URL) -> Task<NSImage?, Never> {
      let session = session

      return Task {
         guard let (data, response) = try? await session.data(from: url) else {
            return nil
         }

         let statusCode = (response as? HTTPURLResponse)?.statusCode ?? 0
         let isSuccessStatus = (200..<300).contains(statusCode)

         guard isSuccessStatus else {
            return nil
         }

         return NSImage(data: data)
      }
   }
}
