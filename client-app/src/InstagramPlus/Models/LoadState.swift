enum LoadState: Equatable, Sendable {
   case idle
   case loading
   case loaded
   case notFound
   case failed(String)

   var isLoading: Bool {
      self == .loading
   }

   var hasLoaded: Bool {
      self == .loaded
   }
}
