import Foundation
import Vision
import ImageIO

// Local OCR only. The image and recognized text never leave this computer.
let url = URL(fileURLWithPath: CommandLine.arguments[1])
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = false
try VNImageRequestHandler(url: url).perform([request])
let lines = (request.results ?? []).compactMap { observation -> [String: Any]? in
    guard let text = observation.topCandidates(1).first?.string else { return nil }
    return ["text": text, "x": observation.boundingBox.minX,
            "y": 1 - observation.boundingBox.maxY]
}
let data = try JSONSerialization.data(withJSONObject: lines)
FileHandle.standardOutput.write(data)
