"""
test_full_flow.py
------------------
Integration test for the full pipeline (Steps 1, 3, 4, 5).

NOTE ON STEP 2: This test substitutes a realistic PostMatch object in place of
a live search_engine.search() call, because this specific execution
environment's network egress is restricted to package registries (pypi/npm/
github) and cannot reach serpapi.com or general image hosts. search_engine.py
itself is fully live code -- see its module docstring and
tests/test_search_engine_contract.py for proof it refuses to fabricate
results without real credentials. Run `python main.py --image ...` with a
SERPAPI_API_KEY configured and internet access to exercise Step 2 for real.

This test proves everything else end-to-end: face detection -> hashing ->
on-chain deploy/store -> re-verification -> tamper detection (text + image).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.face_engine import FaceEngine
from src.blockchain_engine import EvidenceRegistryClient, compute_hash
from src.verify_engine import run_full_verification

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = ROOT / "sample_data" / "evidence_test"


def test_full_pipeline():
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    # --- Step 1: face detection (real) ---
    engine = FaceEngine()
    result = engine.detect(ROOT / "sample_data" / "sample_face.jpg")
    FaceEngine.save_crop(result, EVIDENCE_DIR)
    assert result.encoding.shape[0] > 0

    # --- Step 2 substitute: a realistic discovered-post payload ---
    # (structure matches exactly what search_engine.PostMatch.to_dict() returns)
    post_meta = {
        "post_url": "https://x.com/example_user/status/1234567890",
        "author": "example_user",
        "post_text": "Just landed in Goa for the hackathon!",
        "image_url": "https://pbs.twimg.com/media/example.jpg",
        "timestamp": "2026-08-30T10:15:00Z",
        "source_engine": "serpapi_google_lens",
    }
    post_image_bytes = (ROOT / "sample_data" / "sample_face.jpg").read_bytes()
    (EVIDENCE_DIR / "post_metadata.json").write_text(json.dumps(post_meta, indent=2))
    (EVIDENCE_DIR / "post_image.jpg").write_bytes(post_image_bytes)

    # --- Step 3: hashing ---
    post_hash = compute_hash(post_meta, post_image_bytes)
    assert len(post_hash) == 32  # bytes32

    # --- Step 4: blockchain notarization ---
    client = EvidenceRegistryClient()
    client.deploy()
    receipt = client.store_record(post_hash, post_meta["post_url"])
    assert receipt["status"] == 1

    # --- Step 5: re-verification + tamper detection ---
    report = run_full_verification(EVIDENCE_DIR, client)
    assert report["genuine"]["is_valid"] is True
    assert report["tampered_text"]["is_valid"] is False
    assert report["tampered_image"]["is_valid"] is False
    assert report["all_checks_passed"] is True

    print("\nFull pipeline (steps 1,3,4,5) verified OK.")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    test_full_pipeline()
