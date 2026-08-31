"""
face_engine.py
--------------
Step 1 of the pipeline: face detection + encoding.

Detects a face in an input image, crops it, and produces a numeric encoding
(feature vector) that downstream steps can use.

Detector : OpenCV's bundled Haar Cascade classifier. Ships with opencv-python,
           needs no model download and no network access, so it runs anywhere.
Encoder  : A HOG (Histogram of Oriented Gradients) feature vector computed on
           the aligned, normalized face crop. This is a real, classical
           computer-vision descriptor (not a stub) and needs no extra
           dependencies or downloads.

This module is intentionally pluggable: `FaceEngine` exposes `detect()` and
`encode()` as separate steps. For higher-accuracy production use, swap
`_build_encoding()` for a deep embedding (e.g. `face_recognition.face_encodings`
or `deepface.DeepFace.represent`) -- the rest of the pipeline only depends on
getting back a fixed-length numeric vector and a cropped face image, so no
other file needs to change.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np


class NoFaceDetectedError(Exception):
    """Raised when no face can be found in the supplied image."""


@dataclass
class FaceResult:
    """Container for everything downstream steps need about the detected face."""

    bbox: tuple[int, int, int, int]  # (x, y, w, h) in the original image
    face_crop_bgr: np.ndarray        # cropped face, original color, original size
    encoding: np.ndarray             # fixed-length float32 feature vector
    crop_path: Path = field(default=None)  # set once saved to disk

    @property
    def encoding_hex(self) -> str:
        """A short, stable hex fingerprint of the encoding (for logging/CLI)."""
        return hashlib.sha256(self.encoding.tobytes()).hexdigest()[:16]


class FaceEngine:
    """Detects a face and computes a feature-vector encoding for it."""

    CASCADE_PATH = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    ENCODING_SIZE = (96, 96)  # normalized crop size used before HOG

    def __init__(self) -> None:
        self._detector = cv2.CascadeClassifier(self.CASCADE_PATH)
        if self._detector.empty():
            raise RuntimeError(
                f"Could not load Haar cascade from {self.CASCADE_PATH}. "
                "Check your OpenCV installation."
            )
        # Standard HOG descriptor tuned for a small, fixed-size face crop.
        self._hog = cv2.HOGDescriptor(
            _winSize=self.ENCODING_SIZE,
            _blockSize=(16, 16),
            _blockStride=(8, 8),
            _cellSize=(8, 8),
            _nbins=9,
        )

    def detect(self, image_path: str | Path) -> FaceResult:
        """Detect the largest face in `image_path` and compute its encoding."""
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Input image not found: {image_path}")

        img = cv2.imread(str(image_path))
        if img is None:
            raise ValueError(f"Could not read image (unsupported format?): {image_path}")

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)

        faces = self._detector.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40)
        )
        if len(faces) == 0:
            raise NoFaceDetectedError(f"No face detected in {image_path}")

        # If multiple faces are found, use the largest bounding box (closest/primary subject).
        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
        face_crop = img[y : y + h, x : x + w]

        encoding = self._build_encoding(face_crop)

        return FaceResult(bbox=(int(x), int(y), int(w), int(h)), face_crop_bgr=face_crop, encoding=encoding)

    def _build_encoding(self, face_crop_bgr: np.ndarray) -> np.ndarray:
        """Compute a fixed-length HOG feature vector for a face crop.

        Swap this method's body for `face_recognition.face_encodings(...)[0]`
        or `DeepFace.represent(...)` to get a production-grade 128/512-d
        embedding -- everything else in the pipeline is agnostic to how the
        vector was produced.
        """
        gray = cv2.cvtColor(face_crop_bgr, cv2.COLOR_BGR2GRAY)
        resized = cv2.resize(gray, self.ENCODING_SIZE, interpolation=cv2.INTER_AREA)
        resized = cv2.equalizeHist(resized)
        vec = self._hog.compute(resized)
        return vec.flatten().astype(np.float32)

    @staticmethod
    def save_crop(result: FaceResult, out_dir: str | Path) -> Path:
        """Save the cropped face to disk and record the path on the result."""
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"face_{result.encoding_hex}.jpg"
        cv2.imwrite(str(out_path), result.face_crop_bgr)
        result.crop_path = out_path
        return out_path

    @staticmethod
    def compare(enc_a: np.ndarray, enc_b: np.ndarray) -> float:
        """Cosine similarity between two encodings (1.0 = identical direction)."""
        a, b = enc_a.astype(np.float64), enc_b.astype(np.float64)
        denom = (np.linalg.norm(a) * np.linalg.norm(b)) or 1e-9
        return float(np.dot(a, b) / denom)


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: python face_engine.py <image_path>")
        sys.exit(1)

    engine = FaceEngine()
    result = engine.detect(sys.argv[1])
    path = engine.save_crop(result, "sample_data/crops")
    print(f"Face detected at bbox={result.bbox}")
    print(f"Encoding fingerprint: {result.encoding_hex} (dim={result.encoding.shape[0]})")
    print(f"Crop saved to: {path}")
