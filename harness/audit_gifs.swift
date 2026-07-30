#!/usr/bin/env swift

import CoreGraphics
import Foundation
import ImageIO
import Vision

var rules = [
    "/users/", ".claude/hooks/", "welcome back", "gmail.com", "@gmail",
]
if let privateTerms = ProcessInfo.processInfo.environment["GIF_PRIVACY_TERMS"] {
    rules += privateTerms.split(separator: ",").map {
        String($0).lowercased().filter { !$0.isWhitespace }
    }.filter { !$0.isEmpty }
}

func gifPaths(_ arguments: [String]) throws -> [String] {
    let inputs = arguments.isEmpty ? ["docs/images"] : arguments
    var paths: [String] = []
    for input in inputs {
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: input, isDirectory: &isDirectory) else {
            throw NSError(domain: "gif-audit", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "missing path: \(input)"])
        }
        if isDirectory.boolValue {
            let names = try FileManager.default.contentsOfDirectory(atPath: input)
            paths += names.filter { $0.lowercased().hasSuffix(".gif") }
                .map { URL(fileURLWithPath: input).appendingPathComponent($0).path }
        } else if input.lowercased().hasSuffix(".gif") {
            paths.append(input)
        }
    }
    return paths.sorted()
}

func recognizedText(_ image: CGImage) throws -> String {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = false
    let handler = VNImageRequestHandler(cgImage: image, options: [:])
    try handler.perform([request])
    return (request.results ?? []).compactMap { observation in
        observation.topCandidates(1).first?.string
    }.joined(separator: "\n")
}

do {
    let paths = try gifPaths(Array(CommandLine.arguments.dropFirst()))
    guard !paths.isEmpty else {
        throw NSError(domain: "gif-audit", code: 2,
                      userInfo: [NSLocalizedDescriptionKey: "no GIF files found"])
    }
    var findings = 0
    var frames = 0
    for path in paths {
        let url = URL(fileURLWithPath: path) as CFURL
        guard let source = CGImageSourceCreateWithURL(url, nil) else {
            throw NSError(domain: "gif-audit", code: 3,
                          userInfo: [NSLocalizedDescriptionKey: "cannot read GIF: \(path)"])
        }
        for index in 0..<CGImageSourceGetCount(source) {
            guard let image = CGImageSourceCreateImageAtIndex(source, index, nil) else {
                continue
            }
            frames += 1
            let text = try recognizedText(image).lowercased()
            let compact = text.filter { !$0.isWhitespace }
            for rule in rules {
                let compactRule = rule.filter { !$0.isWhitespace }
                guard compact.contains(compactRule) else { continue }
                findings += 1
                print("FAIL \((path as NSString).lastPathComponent) frame \(index): matched privacy rule")
            }
        }
    }
    if findings > 0 {
        print("GIF privacy audit failed: \(findings) matches across \(frames) frames")
        exit(1)
    }
    print("GIF privacy audit passed: \(paths.count) files, \(frames) frames")
} catch {
    fputs("GIF privacy audit error: \(error.localizedDescription)\n", stderr)
    exit(2)
}
