#!/usr/bin/env swift
// Editable vector geometry shared by the plugin, application and menu bar icons.
// Run: swift scripts/build_icons.swift (then iconutil, as described in README).
import AppKit

let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
let plugin = root.appendingPathComponent("plugins/codex-auto-continue/assets")
let assets = root.appendingPathComponent("ui/menubar/assets")
let iconset = assets.appendingPathComponent("AppIcon.iconset")
let fm = FileManager.default
for dir in [plugin, assets, iconset] { try fm.createDirectory(at: dir, withIntermediateDirectories: true) }

let ring = "M372.438 353.704 A152 152 0 1 1 392.612 189.367"
let arrow = "M354 195 L414 160 Q420 156 419 164 L411 230 Q410 237 406 232 Z"
let play = "M224 201 Q216 196 216 205 L216 307 Q216 316 224 311 L307 264 Q320 256 307 248 Z"

func markSVG(_ ink: String, playInk: String? = nil) -> String {
    """
    <path d="\(ring)" fill="none" stroke="\(ink)" stroke-width="38" stroke-linecap="round"/>
    <path d="\(arrow)" fill="\(ink)"/>
    <path d="\(play)" fill="\(playInk ?? ink)"/>
    """
}

func svg(_ body: String, side: Int = 512) -> String {
    """
    <svg xmlns="http://www.w3.org/2000/svg" width="\(side)" height="\(side)" viewBox="0 0 512 512" role="img" aria-label="Codex Auto Continue">
    <title>Codex Auto Continue</title>
    \(body)
    </svg>

    """
}

let backgroundSVG = """
<defs><linearGradient id="tile" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#263A37"/><stop offset="1" stop-color="#101A1B"/></linearGradient></defs>
<rect x="32" y="32" width="448" height="448" rx="102" fill="url(#tile)"/>
<rect x="33" y="33" width="446" height="446" rx="101" fill="none" stroke="#FFFFFF" stroke-opacity=".12" stroke-width="2"/>
"""
try svg(backgroundSVG + markSVG("#7EECC0", playInk: "#EDFFF6")).write(to: plugin.appendingPathComponent("logo.svg"), atomically: true, encoding: .utf8)
try svg(markSVG("currentColor"), side: 24).write(to: plugin.appendingPathComponent("composerIcon.svg"), atomically: true, encoding: .utf8)
try svg("<g transform=\"translate(256 256) scale(1.35) translate(-256 -256)\">" + markSVG("#000000") + "</g>", side: 18).write(to: assets.appendingPathComponent("statusTemplate.svg"), atomically: true, encoding: .utf8)
try svg(backgroundSVG + markSVG("#7EECC0", playInk: "#EDFFF6"), side: 1024).write(to: assets.appendingPathComponent("AppIcon.svg"), atomically: true, encoding: .utf8)

func color(_ r: CGFloat, _ g: CGFloat, _ b: CGFloat) -> CGColor {
    CGColor(srgbRed: r / 255, green: g / 255, blue: b / 255, alpha: 1)
}
let mint = color(126, 236, 192)
let white = color(237, 255, 246)

func drawMark(_ context: CGContext, monochrome: Bool) {
    let ink = monochrome ? CGColor(gray: 0, alpha: 1) : mint
    context.setStrokeColor(ink)
    context.setLineWidth(38)
    context.setLineCap(.round)
    context.addArc(center: CGPoint(x: 256, y: 256), radius: 152,
                   startAngle: 40 * .pi / 180, endAngle: 334 * .pi / 180, clockwise: false)
    context.strokePath()
    context.setFillColor(ink)
    context.move(to: CGPoint(x: 354, y: 195))
    context.addLine(to: CGPoint(x: 414, y: 160))
    context.addQuadCurve(to: CGPoint(x: 419, y: 164), control: CGPoint(x: 420, y: 156))
    context.addLine(to: CGPoint(x: 411, y: 230))
    context.addQuadCurve(to: CGPoint(x: 406, y: 232), control: CGPoint(x: 410, y: 237))
    context.closePath()
    context.fillPath()
    context.setFillColor(monochrome ? ink : white)
    context.move(to: CGPoint(x: 224, y: 201))
    context.addQuadCurve(to: CGPoint(x: 216, y: 205), control: CGPoint(x: 216, y: 196))
    context.addLine(to: CGPoint(x: 216, y: 307))
    context.addQuadCurve(to: CGPoint(x: 224, y: 311), control: CGPoint(x: 216, y: 316))
    context.addLine(to: CGPoint(x: 307, y: 264))
    context.addQuadCurve(to: CGPoint(x: 307, y: 248), control: CGPoint(x: 320, y: 256))
    context.closePath()
    context.fillPath()
}

func render(side: Int, monochrome: Bool = false) -> NSBitmapImageRep {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: side, pixelsHigh: side,
                              bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true,
                              isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    let context = NSGraphicsContext(bitmapImageRep: rep)!.cgContext
    context.scaleBy(x: CGFloat(side) / 512, y: CGFloat(side) / 512)
    context.translateBy(x: 0, y: 512)
    context.scaleBy(x: 1, y: -1)
    if !monochrome {
        let tile = CGPath(roundedRect: CGRect(x: 32, y: 32, width: 448, height: 448), cornerWidth: 102, cornerHeight: 102, transform: nil)
        context.saveGState()
        context.addPath(tile)
        context.clip()
        let colors = [color(38, 58, 55), color(16, 26, 27)] as CFArray
        let gradient = CGGradient(colorsSpace: CGColorSpace(name: CGColorSpace.sRGB)!, colors: colors, locations: [0, 1])!
        context.drawLinearGradient(gradient, start: CGPoint(x: 32, y: 32), end: CGPoint(x: 480, y: 480), options: [])
        context.restoreGState()
        context.setStrokeColor(CGColor(gray: 1, alpha: 0.12))
        context.setLineWidth(2)
        context.addPath(CGPath(roundedRect: CGRect(x: 33, y: 33, width: 446, height: 446), cornerWidth: 101, cornerHeight: 101, transform: nil))
        context.strokePath()
    } else {
        // Use the entire 18pt canvas, rather than the application's padded tile.
        context.translateBy(x: 256, y: 256)
        context.scaleBy(x: 1.35, y: 1.35)
        context.translateBy(x: -256, y: -256)
    }
    drawMark(context, monochrome: monochrome)
    return rep
}

func save(_ rep: NSBitmapImageRep, _ target: URL) throws {
    try rep.representation(using: .png, properties: [:])!.write(to: target)
}
try save(render(side: 512), plugin.appendingPathComponent("logo.png"))
try save(render(side: 1024), assets.appendingPathComponent("AppIcon.png"))
for size in [16, 32, 128, 256, 512] {
    try save(render(side: size), iconset.appendingPathComponent("icon_\(size)x\(size).png"))
    try save(render(side: size * 2), iconset.appendingPathComponent("icon_\(size)x\(size)@2x.png"))
}
for scale in [1, 2, 3] {
    let suffix = scale == 1 ? "" : "@\(scale)x"
    try save(render(side: 18 * scale, monochrome: true), assets.appendingPathComponent("statusTemplate\(suffix).png"))
}
print("Generated SVG, PNG and iconset assets in \(assets.path)")
