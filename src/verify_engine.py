"""
verify_engine.py
-----------------
Step 5 of the pipeline: automated re-verification + tamper detection.

Given the locally saved evidence record (post metadata + image bytes) and a
deployed EvidenceRegistry contract, this module:
  1. Recomputes the hash from the local files and confirms it matches the
     on-chain record (isValid == True).
  2. Simulates tampering (flips one character of the post text, and
     separately one byte of the image) and proves the recomputed hash no
     longer verifies on-chain (isValid == False) -- demonstrating that the
     on-chain record is tamper-evident.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from src.blockchain_engine import EvidenceRegistryClient, compute_hash


def _load_evidence(evidence_dir: Path) -> tuple[dict, bytes]:
    meta = json.loads((evidence_dir / "post_metadata.json").read_text())
    image_bytes = (evidence_dir / "post_image.jpg").read_bytes()
    return meta, image_bytes


def _tamper_text(meta: dict) -> dict:
    """Flip a single character in post_text to simulate content tampering."""
    tampered = copy.deepcopy(meta)
    text = tampered.get("post_text", "")
    if not text:
        text = "x"
    chars = list(text)
    chars[0] = "Z" if chars[0] != "Z" else "Y"  # guarantee an actual change
    tampered["post_text"] = "".join(chars)
    return tampered


def _tamper_image(image_bytes: bytes) -> bytes:
    """Flip a single byte to simulate image tampering."""
    b = bytearray(image_bytes)
    if not b:
        return bytes([0x01])
    b[0] = b[0] ^ 0xFF  # flip all bits of the first byte -> guaranteed change
    return bytes(b)


def run_full_verification(evidence_dir: str | Path, client: EvidenceRegistryClient) -> dict:
    """Runs the genuine + both tamper checks and returns a summary dict."""
    evidence_dir = Path(evidence_dir)
    meta, image_bytes = _load_evidence(evidence_dir)

    report = {}

    # 1. Genuine re-verification.
    real_hash = compute_hash(meta, image_bytes)
    real_result = client.verify_record(real_hash)
    report["genuine"] = {
        "hash": real_hash.hex(),
        **real_result,
        "expected_valid": True,
        "passed": real_result["is_valid"] is True,
    }

    # 2. Tamper the text by one character.
    tampered_meta = _tamper_text(meta)
    tampered_text_hash = compute_hash(tampered_meta, image_bytes)
    tampered_text_result = client.verify_record(tampered_text_hash)
    report["tampered_text"] = {
        "hash": tampered_text_hash.hex(),
        **tampered_text_result,
        "expected_valid": False,
        "passed": tampered_text_result["is_valid"] is False,
    }

    # 3. Tamper the image by one byte.
    tampered_image_bytes = _tamper_image(image_bytes)
    tampered_image_hash = compute_hash(meta, tampered_image_bytes)
    tampered_image_result = client.verify_record(tampered_image_hash)
    report["tampered_image"] = {
        "hash": tampered_image_hash.hex(),
        **tampered_image_result,
        "expected_valid": False,
        "passed": tampered_image_result["is_valid"] is False,
    }

    report["all_checks_passed"] = all(
        report[k]["passed"] for k in ("genuine", "tampered_text", "tampered_image")
    )
    return report


def print_report(report: dict) -> None:
    def line(label, r):
        mark = "PASS" if r["passed"] else "FAIL"
        print(f"[{mark}] {label:<15} isValid={r['is_valid']!s:<6} "
              f"(expected {r['expected_valid']})  hash=0x{r['hash'][:16]}...")

    print("\n=== Re-verification & Tamper Detection Report ===")
    line("Genuine record", report["genuine"])
    line("Tampered text", report["tampered_text"])
    line("Tampered image", report["tampered_image"])
    print("---")
    print("ALL CHECKS PASSED" if report["all_checks_passed"] else "SOME CHECKS FAILED")
