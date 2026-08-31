"""
search_engine.py
-----------------
Step 2 of the pipeline: dynamic reverse-image / web search.

Given a face crop, performs a genuine, live reverse-image search and returns
the first real social-media (or general web) post result it finds. This is a
live API call, not a lookup table -- the result depends entirely on what the
search engine currently indexes for the supplied image.

Primary backend : SerpApi's Google Lens engine (https://serpapi.com/google-lens-api)
                   -- returns "visual matches" for an uploaded/hosted image,
                   which frequently include social posts, profile pages, and
                   articles. Requires a free/paid SERPAPI_API_KEY.

Because Google Lens needs a URL it can fetch (it does not accept raw image
bytes in the request), the crop is first uploaded to a short-lived, public
image host (0x0.st) so SerpApi can retrieve it. No account or key is required
for that upload step -- only the search step needs SERPAPI_API_KEY.

If no key is configured, `search()` raises `SearchBackendUnavailable` rather
than silently returning a fabricated result -- the task requires a genuine
search, so this module never falls back to fake/hardcoded data.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import requests

SERPAPI_ENDPOINT = "https://serpapi.com/search"
IMAGE_HOST_ENDPOINT = "https://0x0.st"  # ephemeral anonymous file host, used only
                                          # to give the search API a fetchable URL


class SearchBackendUnavailable(Exception):
    """Raised when no working search backend/credentials are configured."""


class NoMatchFoundError(Exception):
    """Raised when the search backend responds but returns no usable post match."""


@dataclass
class PostMatch:
    """Normalized metadata for a discovered social media / web post."""

    post_url: str
    author: str
    post_text: str
    image_url: str
    timestamp: str  # ISO-8601 if the source provides one, else "" (unknown)
    source_engine: str = "serpapi_google_lens"

    def to_dict(self) -> dict:
        return {
            "post_url": self.post_url,
            "author": self.author,
            "post_text": self.post_text,
            "image_url": self.image_url,
            "timestamp": self.timestamp,
            "source_engine": self.source_engine,
        }


SOCIAL_DOMAINS = (
    "twitter.com", "x.com", "instagram.com", "linkedin.com",
    "reddit.com", "facebook.com", "tiktok.com", "pinterest.com",
)


def _upload_image_for_search(image_path: Path) -> str:
    """Upload a local image to a public host so the search API can fetch it by URL.

    Uses 0x0.st: no auth, no account, links expire automatically. Swap this for
    S3/Cloudinary/etc. in production if you need retention control or privacy
    guarantees beyond "public for a short time".
    """
    with open(image_path, "rb") as f:
        resp = requests.post(IMAGE_HOST_ENDPOINT, files={"file": f}, timeout=30)
    resp.raise_for_status()
    url = resp.text.strip()
    if not url.startswith("http"):
        raise SearchBackendUnavailable(f"Image host returned unexpected response: {url}")
    return url


def _query_serpapi_lens(image_url: str, api_key: str) -> dict:
    params = {
        "engine": "google_lens",
        "url": image_url,
        "api_key": api_key,
    }
    resp = requests.get(SERPAPI_ENDPOINT, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _pick_best_match(serpapi_json: dict) -> PostMatch:
    """Pick the first visual match that looks like a social-media post, else the
    first visual match at all. Raises NoMatchFoundError if nothing usable came back.
    """
    matches = serpapi_json.get("visual_matches", [])
    if not matches:
        raise NoMatchFoundError("Search backend returned zero visual matches for this face.")

    def is_social(m: dict) -> bool:
        link = m.get("link", "")
        return any(domain in link for domain in SOCIAL_DOMAINS)

    chosen = next((m for m in matches if is_social(m)), matches[0])

    return PostMatch(
        post_url=chosen.get("link", ""),
        author=chosen.get("source", chosen.get("title", "unknown")),
        post_text=chosen.get("title", ""),
        image_url=chosen.get("thumbnail", chosen.get("original", "")),
        timestamp=chosen.get("date", ""),  # SerpApi rarely provides this; often blank
    )


def search(face_crop_path: str | Path) -> PostMatch:
    """Run a genuine, live reverse-image search for the given face crop.

    Raises SearchBackendUnavailable if SERPAPI_API_KEY is not set, and
    NoMatchFoundError if the search runs but returns nothing usable.
    """
    api_key = os.getenv("SERPAPI_API_KEY")
    if not api_key:
        raise SearchBackendUnavailable(
            "SERPAPI_API_KEY is not set. Get a free key at https://serpapi.com/ "
            "and put it in your .env file to run a genuine live search."
        )

    face_crop_path = Path(face_crop_path)
    hosted_url = _upload_image_for_search(face_crop_path)
    result_json = _query_serpapi_lens(hosted_url, api_key)
    return _pick_best_match(result_json)


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) != 2:
        print("Usage: python search_engine.py <face_crop_image_path>")
        sys.exit(1)

    match = search(sys.argv[1])
    print(json.dumps(match.to_dict(), indent=2))
