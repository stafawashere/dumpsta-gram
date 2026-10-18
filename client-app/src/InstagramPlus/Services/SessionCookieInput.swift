import Foundation

// What a person pasted from the browser's cookie list, checked for the mistakes a copy and
// paste makes before anything reaches the engine. This is input hygiene only: no value is
// interpreted, and Instagram decides whether a session is real. A value is never put in an
// error message, so a problem can be shown and logged without leaking a cookie.
struct SessionCookieInput: Sendable, Equatable {
   enum Field: String, CaseIterable, Sendable {
      case sessionID = "sessionid"
      case userID = "ds_user_id"
      case csrfToken = "csrftoken"
   }

   var sessionID: String
   var userID: String
   var csrfToken: String

   // The cleaned values, ready for the engine.
   struct Cleaned: Sendable, Equatable {
      let sessionID: String
      let userID: String
      let csrfToken: String
   }

   // One message per field that failed. Empty fields are not reported, so a form that is still
   // being filled shows no errors, and `isComplete` says whether Continue may be enabled.
   struct Report: Sendable, Equatable {
      let cleaned: Cleaned?
      let problems: [Field: String]
   }

   var isComplete: Bool {
      !Self.strip(sessionID).isEmpty && !Self.strip(userID).isEmpty && !Self.strip(csrfToken).isEmpty
   }

   func check() -> Report {
      var problems: [Field: String] = [:]

      let sessionID = Self.strip(sessionID)
      let userID = Self.strip(userID)
      let csrfToken = Self.strip(csrfToken)

      if !sessionID.isEmpty, let problem = Self.sessionIDProblem(sessionID) {
         problems[.sessionID] = problem
      }

      if !userID.isEmpty, let problem = Self.userIDProblem(userID) {
         problems[.userID] = problem
      }

      if !csrfToken.isEmpty, let problem = Self.csrfTokenProblem(csrfToken) {
         problems[.csrfToken] = problem
      }

      let isReady = isComplete && problems.isEmpty
      let cleaned = isReady ? Cleaned(sessionID: sessionID, userID: userID, csrfToken: csrfToken) : nil

      return Report(cleaned: cleaned, problems: problems)
   }

   // Surrounding whitespace, a trailing semicolon and one pair of quotes are what a copy from a
   // cookie table or a Cookie header carries along.
   static func strip(_ raw: String) -> String {
      var value = raw.trimmingCharacters(in: .whitespacesAndNewlines)

      while value.hasSuffix(";") {
         value.removeLast()
         value = value.trimmingCharacters(in: .whitespaces)
      }

      let quotes = CharacterSet(charactersIn: "\"'")
      value = value.trimmingCharacters(in: quotes)

      return value
   }

   // The name and equals sign of a pasted `sessionid=...` pair, which is the other common
   // mistake, are named so the message can say what to remove.
   private static func hasNamePrefix(_ value: String) -> Bool {
      Field.allCases.contains { value.lowercased().hasPrefix($0.rawValue + "=") }
   }

   private static let sessionIDCharacters = CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789%:._-")
   private static let tokenCharacters = CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")

   private static func sessionIDProblem(_ value: String) -> String? {
      if hasNamePrefix(value) {
         return "Paste only the value, without \"sessionid=\"."
      }

      if value.rangeOfCharacter(from: .whitespacesAndNewlines) != nil {
         return "The value has a space in it. Copy the whole value from the Value column, nothing else."
      }

      if value.rangeOfCharacter(from: sessionIDCharacters.inverted) != nil {
         return "The value has characters a sessionid never holds. Copy it again."
      }

      if value.count < 20 {
         return "The value is too short to be a sessionid. Copy the whole value."
      }

      return nil
   }

   private static func userIDProblem(_ value: String) -> String? {
      if hasNamePrefix(value) {
         return "Paste only the value, without \"ds_user_id=\"."
      }

      if value.rangeOfCharacter(from: CharacterSet.decimalDigits.inverted) != nil {
         return "ds_user_id is a number, digits only."
      }

      if value.count > 20 {
         return "ds_user_id is too long to be an account number. Copy the right row."
      }

      return nil
   }

   private static func csrfTokenProblem(_ value: String) -> String? {
      if hasNamePrefix(value) {
         return "Paste only the value, without \"csrftoken=\"."
      }

      if value.rangeOfCharacter(from: tokenCharacters.inverted) != nil {
         return "The value has characters a csrftoken never holds. Copy it again."
      }

      if value.count < 16 {
         return "The value is too short to be a csrftoken. Copy the whole value."
      }

      return nil
   }
}
