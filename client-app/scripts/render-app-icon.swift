// Renders the Instagram glyph into AppIcon.appiconset at every macOS icon size.
// Usage: swift scripts/render-app-icon.swift src/InstagramPlus/Resources/Assets.xcassets/AppIcon.appiconset

import AppKit

let canvasSide: CGFloat = 1024
let tileInset: CGFloat = 100
let tileSide = canvasSide - tileInset * 2
let tileCornerRadius: CGFloat = 185

let gradientStops: [(location: CGFloat, hex: UInt32)] = [
   (0.00, 0xFDF497),
   (0.05, 0xFDF497),
   (0.45, 0xFD5949),
   (0.60, 0xD6249F),
   (0.90, 0x285AEB),
]

func cgColor(hex: UInt32, alpha: CGFloat = 1) -> CGColor {
   let red = CGFloat((hex >> 16) & 0xFF) / 255
   let green = CGFloat((hex >> 8) & 0xFF) / 255
   let blue = CGFloat(hex & 0xFF) / 255
   return CGColor(srgbRed: red, green: green, blue: blue, alpha: alpha)
}

func drawIcon(in context: CGContext) {
   let tileRect = CGRect(x: tileInset, y: tileInset, width: tileSide, height: tileSide)
   let tilePath = CGPath(roundedRect: tileRect, cornerWidth: tileCornerRadius, cornerHeight: tileCornerRadius, transform: nil)

   context.saveGState()
   context.setShadow(offset: CGSize(width: 0, height: -10), blur: 24, color: cgColor(hex: 0x000000, alpha: 0.28))
   context.addPath(tilePath)
   context.setFillColor(cgColor(hex: 0xD6249F))
   context.fillPath()
   context.restoreGState()

   // CSS places the gradient centre at 30% across and 107% down, measured from the top.
   // Core Graphics measures from the bottom, so 107% down becomes 7% below the tile.
   let gradientCenter = CGPoint(x: tileRect.minX + tileSide * 0.30, y: tileRect.minY - tileSide * 0.07)
   let farthestCorner = CGPoint(x: tileRect.maxX, y: tileRect.maxY)
   let gradientRadius = hypot(farthestCorner.x - gradientCenter.x, farthestCorner.y - gradientCenter.y)
   let colors = gradientStops.map { cgColor(hex: $0.hex) } as CFArray
   let locations = gradientStops.map { $0.location }
   let gradient = CGGradient(colorsSpace: CGColorSpace(name: CGColorSpace.sRGB), colors: colors, locations: locations)!

   context.saveGState()
   context.addPath(tilePath)
   context.clip()
   context.drawRadialGradient(gradient, startCenter: gradientCenter, startRadius: 0, endCenter: gradientCenter, endRadius: gradientRadius, options: [.drawsAfterEndLocation])
   context.restoreGState()

   let strokeWidth = tileSide * 0.07
   let frameSide = tileSide * 0.62
   let frameOrigin = tileRect.minX + (tileSide - frameSide) / 2
   let frameRect = CGRect(x: frameOrigin, y: tileRect.minY + (tileSide - frameSide) / 2, width: frameSide, height: frameSide)
   let frameCornerRadius = tileSide * 0.18

   context.setStrokeColor(cgColor(hex: 0xFFFFFF))
   context.setLineWidth(strokeWidth)
   context.addPath(CGPath(roundedRect: frameRect, cornerWidth: frameCornerRadius, cornerHeight: frameCornerRadius, transform: nil))
   context.strokePath()

   let lensDiameter = tileSide * 0.30
   let lensRect = CGRect(x: tileRect.midX - lensDiameter / 2, y: tileRect.midY - lensDiameter / 2, width: lensDiameter, height: lensDiameter)
   context.strokeEllipse(in: lensRect)

   let flashDiameter = tileSide * 0.075
   let flashCenter = CGPoint(x: tileRect.minX + tileSide * 0.685, y: tileRect.minY + tileSide * 0.685)
   context.setFillColor(cgColor(hex: 0xFFFFFF))
   context.fillEllipse(in: CGRect(x: flashCenter.x - flashDiameter / 2, y: flashCenter.y - flashDiameter / 2, width: flashDiameter, height: flashDiameter))
}

func renderPNG(pixelSide: Int) -> Data {
   let bitmap = NSBitmapImageRep(
      bitmapDataPlanes: nil,
      pixelsWide: pixelSide,
      pixelsHigh: pixelSide,
      bitsPerSample: 8,
      samplesPerPixel: 4,
      hasAlpha: true,
      isPlanar: false,
      colorSpaceName: .deviceRGB,
      bytesPerRow: 0,
      bitsPerPixel: 0
   )!

   let graphicsContext = NSGraphicsContext(bitmapImageRep: bitmap)!
   let context = graphicsContext.cgContext
   let scale = CGFloat(pixelSide) / canvasSide
   context.scaleBy(x: scale, y: scale)
   drawIcon(in: context)
   context.flush()

   return bitmap.representation(using: .png, properties: [:])!
}

let arguments = CommandLine.arguments
guard arguments.count == 2 else {
   FileHandle.standardError.write("usage: swift render-app-icon.swift <AppIcon.appiconset>\n".data(using: .utf8)!)
   exit(2)
}

let outputDirectory = URL(fileURLWithPath: arguments[1], isDirectory: true)
try FileManager.default.createDirectory(at: outputDirectory, withIntermediateDirectories: true)

let pointSizes = [16, 32, 128, 256, 512]
var imageEntries: [[String: String]] = []

for pointSize in pointSizes {
   for scale in [1, 2] {
      let suffix = scale == 1 ? "" : "@2x"
      let filename = "icon_\(pointSize)x\(pointSize)\(suffix).png"
      let pngData = renderPNG(pixelSide: pointSize * scale)
      try pngData.write(to: outputDirectory.appendingPathComponent(filename))

      imageEntries.append([
         "filename": filename,
         "idiom": "mac",
         "scale": "\(scale)x",
         "size": "\(pointSize)x\(pointSize)",
      ])
   }
}

let contents: [String: Any] = [
   "images": imageEntries,
   "info": ["author": "xcode", "version": 1],
]
let contentsData = try JSONSerialization.data(withJSONObject: contents, options: [.prettyPrinted, .sortedKeys])
try contentsData.write(to: outputDirectory.appendingPathComponent("Contents.json"))

print("wrote \(imageEntries.count) icons to \(outputDirectory.path)")
