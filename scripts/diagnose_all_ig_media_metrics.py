"""
Diagnostic script that tests Instagram Media-level insights metrics against the
live Graph API, grouped by media type.

Unlike Page Insights (which depend only on the page-level metric name), IG media
insights metrics have validity that depends on the media object's media_type.
This script therefore has two phases:

1. DISCOVERY: GET /{ig-user-id}/media to find one sample media ID per type
   (IMAGE, VIDEO, CAROUSEL_ALBUM, REELS, STORY), picking the most recent post
   of each type found in the last 50 items.

2. TEST: For each found media type, loop through that type's candidate metrics
   and call GET /{ig-media-id}/insights?metric={name}. Print SUCCESS/FAIL per
   metric. Continue past individual failures.

No period parameter is used -- IG media-level insights do not accept a period
grain; each metric is inherently scoped to the media object's lifetime.

Uses the existing config_loader pattern (IG_USER_ID, SYSTEM_USER_TOKEN).
Both token values are redacted from every line printed, including response bodies.
No writes or mutations to any IG data -- read-only GET requests only.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "extraction"))

from config_loader import load_config  # noqa: E402

GRAPH_API_VERSION = "v25.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

# Candidate metrics grouped by media type.
# Based on Meta's IG Media Insights doc and the ROADMAP's known per-type gotchas.
METRICS_BY_TYPE: Dict[str, List[str]] = {
    "IMAGE": [
        "reach",
        "saved",
        "likes",
        "comments",
        "shares",
        "total_interactions",
        "engagement",
        "impressions",
        "video_views",  # likely FAIL for IMAGE -- included for confirmation
        "views",        # confirmed working (2026-07-14)
    ],
    "VIDEO": [
        "reach",
        "saved",
        "likes",
        "comments",
        "shares",
        "total_interactions",
        "engagement",
        "impressions",
        "video_views",
        "views",        # confirmed working (2026-07-14)
    ],
    "CAROUSEL_ALBUM": [
        "reach",
        "saved",
        "likes",
        "comments",
        "shares",
        "total_interactions",
        "engagement",
        "impressions",
        "video_views",  # may FAIL for CAROUSEL_ALBUM -- included for confirmation
        "views",        # confirmed working (2026-07-14)
    ],
    "REELS": [
        "reach",
        "saved",
        "likes",
        "comments",
        "shares",
        "total_interactions",
        "plays",
        "ig_reels_avg_watch_time",
        "ig_reels_video_view_total_time",
        "clips_replays_count",
    ],
    "STORY": [
        "reach",
        "replies",
        "navigation",
        "taps_forward",
        "taps_back",
        "exits",
        "total_interactions",
    ],
}

# All known media types that could appear in the API response.
# STORY is included for completeness but will almost always be empty
# (Stories expire after 24h) -- noted in discovery output rather than skipped silently.
KNOWN_MEDIA_TYPES = ["IMAGE", "VIDEO", "CAROUSEL_ALBUM", "REELS", "STORY"]


def _redact(text: str, secrets: List[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***REDACTED***")
    return text


def _get(path: str, access_token: str, params: dict, secrets: List[str]) -> Optional[dict]:
    query = dict(params)
    query["access_token"] = access_token
    url = f"{GRAPH_API_BASE}/{path}?{urllib.parse.urlencode(query)}"

    try:
        with urllib.request.urlopen(url) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read()
    except urllib.error.URLError as exc:
        print(_redact(f"  <no response> ({exc.reason})", secrets))
        return None

    text = _redact(body.decode("utf-8", errors="replace"), secrets)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        print(f"  <unparseable response> {text}")
        return None


def discover_media_samples(
    ig_user_id: str, access_token: str, secrets: List[str]
) -> Dict[str, str]:
    """
    Fetch recent media for the IG user, group by media_type, and return a
    dict mapping media_type -> sample media ID (the most recent post of that type).

    Returns only types that actually have at least one post in the result set.
    """
    params: dict = {"fields": "id,media_type,timestamp", "limit": 50}
    all_media: Dict[str, List[dict]] = {t: [] for t in KNOWN_MEDIA_TYPES}

    print("=== Discovery Phase: fetching recent media ===")
    print()

    # Fetch up to 50 recent media items (single request -- ample for finding at
    # least one sample per media type, and pagination would require re-extracting
    # token from paging.next URL).
    parsed = _get(f"{ig_user_id}/media", access_token, params, secrets)
    if parsed is None:
        print("  <discovery failed: no response>")
        return {}

    if "error" in parsed:
        error = parsed["error"]
        print(
            f"  Discovery error code={error.get('code')} "
            f"subcode={error.get('error_subcode')} "
            f"msg={error.get('message')}"
        )
        return {}

    items = parsed.get("data", [])
    for item in items:
        mtype = item.get("media_type")
        if mtype in all_media:
            all_media[mtype].append(item)

    # Pick the most recent post of each found type
    samples: Dict[str, str] = {}
    for mtype in KNOWN_MEDIA_TYPES:
        posts = all_media.get(mtype, [])
        if posts:
            # The API returns most recent first, so the first item is the newest
            sample = posts[0]
            samples[mtype] = sample["id"]
            print(f"  {mtype}: found {len(posts)} post(s), using sample ID {sample['id']} "
                  f"(posted {sample.get('timestamp', 'unknown')})")
        else:
            note = ""
            if mtype == "STORY":
                note = " (STORY expires after 24h -- expected to be empty)"
            elif mtype == "REELS":
                note = " (no Reels found in recent media)"
            print(f"  {mtype}: not found{note}")

    print()
    print(f"  Discovered {len(samples)} media type(s) with recent content")
    print()
    return samples


def test_metrics_for_type(
    media_id: str,
    media_type: str,
    access_token: str,
    secrets: List[str],
) -> List[tuple]:
    """
    Test each candidate metric for the given media_type against
    /{media_id}/insights.

    Returns a list of (metric, status) tuples.
    """
    metrics = METRICS_BY_TYPE.get(media_type, [])
    if not metrics:
        print(f"  [{media_type}] No candidate metrics defined -- skipping")
        return []

    print(f"--- Testing {media_type} (media ID {media_id}) ---")
    results: List[tuple] = []
    for metric in metrics:
        parsed = _get(
            f"{media_id}/insights",
            access_token,
            {"metric": metric},
            secrets,
        )
        if parsed and "error" in parsed:
            error = parsed["error"]
            status = (
                f"FAIL code={error.get('code')} subcode={error.get('error_subcode')} "
                f"msg={error.get('message')}"
            )
        elif parsed and "data" in parsed:
            status = "SUCCESS"
        else:
            status = "UNKNOWN (no parseable JSON)"
        print(f"  {metric}: {status}")
        results.append((metric, status))
    print()
    return results


def main() -> None:
    config = load_config()
    system_token = config.system_user_token
    ig_user_id = config.ig_user_id
    secrets = [system_token]

    # Phase 1: Discover media types and get sample IDs
    samples = discover_media_samples(ig_user_id, system_token, secrets)

    if not samples:
        print("=== No media types found with recent content -- nothing to test ===")
        return

    # Phase 2: Test metrics per discovered type
    print("=== Test Phase: checking metric availability per media type ===")
    print()

    all_results: Dict[str, List[tuple]] = {}
    for media_type, media_id in samples.items():
        all_results[media_type] = test_metrics_for_type(
            media_id, media_type, system_token, secrets
        )

    # Summary per type
    total_success = 0
    total_fail = 0
    total_all = 0

    print("=== Summary ===")
    print()
    for media_type in sorted(samples.keys()):
        results = all_results.get(media_type, [])
        successes = [m for m, s in results if s == "SUCCESS"]
        failures = [m for m, s in results if s != "SUCCESS"]
        print(f"{media_type}: {len(successes)} succeeded, {len(failures)} failed (of {len(results)})")
        if successes:
            print("  Succeeded:")
            for m in successes:
                print(f"    {m}")
        if failures:
            print("  Failed:")
            for m in failures:
                print(f"    {m}")
        print()
        total_success += len(successes)
        total_fail += len(failures)
        total_all += len(results)

    print(f"=== Overall: {total_success} succeeded, {total_fail} failed (of {total_all}) ===")


if __name__ == "__main__":
    main()