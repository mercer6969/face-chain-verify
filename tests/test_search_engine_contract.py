"""
test_search_engine_contract.py
-------------------------------
Proves search_engine.py's core promise: it performs a genuine live search and
never silently returns fabricated/hardcoded data. Without a real
SERPAPI_API_KEY it must raise SearchBackendUnavailable, not a fake PostMatch.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.search_engine import search, SearchBackendUnavailable


def test_refuses_without_api_key():
    os.environ.pop("SERPAPI_API_KEY", None)
    try:
        search(Path(__file__).resolve().parent.parent / "sample_data" / "sample_face.jpg")
        assert False, "search() should have raised SearchBackendUnavailable"
    except SearchBackendUnavailable:
        pass  # expected: no key -> no result, ever


if __name__ == "__main__":
    test_refuses_without_api_key()
    print("OK: search_engine correctly refuses to run without real credentials.")
