#!/usr/bin/env python3
"""
main.py
-------
Orchestrates the full pipeline:

  face scan image
      -> [face_engine]     detect + crop + encode face
      -> [search_engine]   genuine live reverse-image search for a matching post
      -> [blockchain_engine] hash post metadata+image, deploy/store on-chain
      -> [verify_engine]   re-verify against chain, prove tamper detection

Usage:
    python main.py --image path/to/face_scan.jpg

Requires a .env file (see .env.example) with at minimum SERPAPI_API_KEY for
the live search step, and optionally RPC_URL/PRIVATE_KEY if CHAIN_MODE=rpc.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.face_engine import FaceEngine, NoFaceDetectedError
from src.search_engine import search as reverse_image_search
from src.search_engine import SearchBackendUnavailable, NoMatchFoundError
from src.blockchain_engine import EvidenceRegistryClient, compute_hash, ARTIFACT_PATH
from src.verify_engine import run_full_verification, print_report

ROOT_DIR = Path(__file__).resolve().parent
EVIDENCE_DIR = ROOT_DIR / "sample_data" / "evidence"


def step(n: int, title: str) -> None:
    print(f"\n{'=' * 60}\nSTEP {n}: {title}\n{'=' * 60}")


def ensure_contract_compiled() -> None:
    if ARTIFACT_PATH.exists():
        return
    print("Contract artifact not found -- compiling EvidenceRegistry.sol ...")
    result = subprocess.run(
        ["node", "scripts/compile.js"], cwd=ROOT_DIR, capture_output=True, text=True
    )
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Face -> social search -> blockchain notarization pipeline")
    parser.add_argument("--image", required=True, help="Path to the input face scan image")
    args = parser.parse_args()

    load_dotenv()
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- #
    step(1, "Face detection & encoding")
    engine = FaceEngine()
    try:
        face_result = engine.detect(args.image)
    except NoFaceDetectedError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    crop_path = engine.save_crop(face_result, EVIDENCE_DIR)
    print(f"Face bbox: {face_result.bbox}")
    print(f"Encoding fingerprint: {face_result.encoding_hex} (dim={face_result.encoding.shape[0]})")
    print(f"Face crop saved to: {crop_path}")

    # ---------------------------------------------------------------- #
    step(2, "Dynamic web/social media reverse-image search")
    try:
        match = reverse_image_search(crop_path)
    except SearchBackendUnavailable as e:
        print(f"ERROR: {e}")
        print("\nSet SERPAPI_API_KEY in your .env to run the live search step.")
        sys.exit(1)
    except NoMatchFoundError as e:
        print(f"No match found: {e}")
        sys.exit(1)

    print(f"Matched post: {match.post_url}")
    print(f"Author:       {match.author}")
    print(f"Text:         {match.post_text[:120]}")
    print(f"Image URL:    {match.image_url}")
    print(f"Timestamp:    {match.timestamp or '(not provided by source)'}")

    # Download the matched post's image so we can hash real bytes, not just a URL string.
    import requests
    img_resp = requests.get(match.image_url, timeout=30)
    img_resp.raise_for_status()
    post_image_bytes = img_resp.content
    (EVIDENCE_DIR / "post_image.jpg").write_bytes(post_image_bytes)

    post_meta = match.to_dict()
    (EVIDENCE_DIR / "post_metadata.json").write_text(json.dumps(post_meta, indent=2))
    print(f"Evidence saved to: {EVIDENCE_DIR}/")

    # ---------------------------------------------------------------- #
    step(3, "Cryptographic hashing & payload packaging")
    post_hash = compute_hash(post_meta, post_image_bytes)
    print(f"keccak256(post metadata + image bytes) = 0x{post_hash.hex()}")

    # ---------------------------------------------------------------- #
    step(4, "Blockchain notarization")
    ensure_contract_compiled()
    client = EvidenceRegistryClient()
    address = client.deploy()
    print(f"EvidenceRegistry deployed at {address} (mode={client.config.mode})")

    receipt = client.store_record(post_hash, match.post_url)
    print(f"storeRecord() tx: {receipt['tx_hash']}  (block {receipt['block_number']}, status={receipt['status']})")

    # ---------------------------------------------------------------- #
    step(5, "Re-verification & tamper detection")
    report = run_full_verification(EVIDENCE_DIR, client)
    print_report(report)

    (EVIDENCE_DIR / "verification_report.json").write_text(json.dumps(report, indent=2))
    sys.exit(0 if report["all_checks_passed"] else 1)


if __name__ == "__main__":
    main()
