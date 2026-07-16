"""
Diagnostic script that closes the REELS/STORY gap left by
diagnose_all_ig_media_metrics.py (see
scripts/output/diagnose_all_ig_media_metrics_output.txt -- that run found
7-of-10 candidate metrics working for IMAGE, VIDEO, and CAROUSEL_ALBUM, but
reported "not found" for both REELS and STORY).

This is a NEW, standalone script -- diagnose_all_ig_media_metrics.py itself
is intentionally left unmodified (task brief treats reworking it as out of
bounds). Its own discovery step only inspects the `media_type` field on
`/{ig-user-id}/media`, which per the Graph API only ever returns IMAGE,
VIDEO, or CAROUSEL_ALBUM -- Reels are returned with `media_type=VIDEO` and
are distinguished only by a separate field, `media_product_type` (values
observed elsewhere in Meta's API surface: FEED, REELS, STORY, AD). That
means the prior script's "REELS: not found" result cannot be trusted as
proof Reels content doesn't exist -- it may simply never have been able to
match REELS via the field it was checking. This script's discovery phase
queries `media_product_type` explicitly to test this for real, rather than
repeating the same query.

Stories additionally do not persist on the `/media` edge at all (per Meta's
own docs, Stories expire after 24h and only live on the dedicated
`/{ig-user-id}/stories` edge while active) -- this script checks BOTH the
`/media` edge (filtered by media_product_type=STORY, in case that
assumption is wrong) and the dedicated `/stories` edge, rather than
assuming either behavior.

Candidate metrics tested are the SAME 10 used by
diagnose_all_ig_media_metrics.py for IMAGE/VIDEO/CAROUSEL_ALBUM (reach,
saved, likes, comments, shares, total_interactions, engagement,
impressions, video_views, views) -- per the task brief, this keeps REELS/
STORY results directly comparable to the existing IMAGE/VIDEO/
CAROUSEL_ALBUM findings, even though REELS/STORY may have their own
additional dedicated metrics (plays, ig_reels_avg_watch_time, navigation,
etc.) not covered here.

For every metric that succeeds, one redacted sample payload is saved
(metric name, values array shape, any title/description metadata fields)
mirroring the FB parameter-space script's payload-sample format.

If no live Reels or Stories content is found, that media type is reported
as BLOCKED with the exact queries attempted -- not silently skipped.

Uses the existing config_loader pattern (IG_USER_ID, SYSTEM_USER_TOKEN),
called directly with no Page token exchange -- consistent with the other
IG diagnostic scripts in this repo, which have already empirically
confirmed the System User token works directly against IG Graph API
endpoints (see scripts/output/diagnose_all_ig_account_metrics.txt and
diagnose_all_ig_media_metrics_output.txt, both produced this way).
The System User token is redacted from every line printed and from the
saved output file.

Read-only: GET requests only, no writes/mutations to any IG data or to
src/, tests/, or existing scripts.
"""

import copy
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

OUTPUT_PATH = os.path.join(
    os.path.dirname(__file__), "output", "diagnose_ig_media_reels_stories_output.txt"
)

# Same 10 candidate metrics diagnose_all_ig_media_metrics.py used for
# IMAGE/VIDEO/CAROUSEL_ALBUM -- kept identical here so REELS/STORY results
# are directly comparable, per the task brief.
CANDIDATE_METRICS = [
    "reach",
    "saved",
    "likes",
    "comments",
    "shares",
    "total_interactions",
    "engagement",
    "impressions",
    "video_views",
    "views",
]


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
        return {"__transport_error__": _redact(str(exc.reason), secrets)}

    text = _redact(body.decode("utf-8", errors="replace"), secrets)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"__unparseable__": text}


def discover_reels_sample(ig_user_id: str, token: str, secrets: List[str], log: List[str]) -> Optional[dict]:
    """
    Query /{ig-user-id}/media with media_product_type included, and look
    for any item whose media_product_type == "REELS". Returns the sample
    item dict, or None if none found (with the query and raw findings
    logged either way).
    """
    log.append("--- REELS discovery: GET /{ig-user-id}/media, "
               "fields=id,media_type,media_product_type,timestamp, limit=50 ---")
    params = {"fields": "id,media_type,media_product_type,timestamp", "limit": 50}
    parsed = _get(f"{ig_user_id}/media", token, params, secrets)

    if parsed is None or "__transport_error__" in parsed:
        log.append(f"  <no response: {parsed}>")
        return None
    if "__unparseable__" in parsed:
        log.append(f"  <unparseable response> {parsed['__unparseable__']}")
        return None
    if "error" in parsed:
        e = parsed["error"]
        log.append(f"  ERROR code={e.get('code')} subcode={e.get('error_subcode')} msg={e.get('message')}")
        return None

    items = parsed.get("data", [])
    log.append(f"  Fetched {len(items)} recent media item(s).")
    product_type_counts: Dict[str, int] = {}
    for item in items:
        pt = item.get("media_product_type", "<missing>")
        product_type_counts[pt] = product_type_counts.get(pt, 0) + 1
    log.append(f"  media_product_type breakdown: {product_type_counts}")

    reels_items = [i for i in items if i.get("media_product_type") == "REELS"]
    if reels_items:
        sample = reels_items[0]
        log.append(
            f"  FOUND {len(reels_items)} REELS item(s). Using most recent: "
            f"id={sample['id']} media_type={sample.get('media_type')} "
            f"timestamp={sample.get('timestamp')}"
        )
        return sample

    log.append("  No items with media_product_type == 'REELS' found in the 50 most recent media items.")
    return None


def discover_story_sample(ig_user_id: str, token: str, secrets: List[str], log: List[str]) -> Optional[dict]:
    """
    Checks two places for an active Story, since it isn't known in advance
    whether Stories ever appear on /media (they're documented as
    expiring after 24h and living on a separate /stories edge):

    1. /{ig-user-id}/media filtered for media_product_type == "STORY"
    2. /{ig-user-id}/stories (the dedicated, currently-active-only edge)

    Returns the sample item dict, or None if neither yields a result
    (with both queries and their raw findings logged either way).
    """
    log.append("--- STORY discovery, attempt 1: media_product_type=='STORY' within /{ig-user-id}/media ---")
    params = {"fields": "id,media_type,media_product_type,timestamp", "limit": 50}
    parsed = _get(f"{ig_user_id}/media", token, params, secrets)

    story_items: List[dict] = []
    if parsed and "data" in parsed:
        items = parsed.get("data", [])
        story_items = [i for i in items if i.get("media_product_type") == "STORY"]
        if story_items:
            sample = story_items[0]
            log.append(
                f"  FOUND {len(story_items)} STORY item(s) on the /media edge. Using: "
                f"id={sample['id']} timestamp={sample.get('timestamp')}"
            )
            return sample
        log.append("  No media_product_type == 'STORY' items found on the /media edge (of the 50 most recent items).")
    elif parsed and "error" in parsed:
        e = parsed["error"]
        log.append(f"  ERROR code={e.get('code')} subcode={e.get('error_subcode')} msg={e.get('message')}")
    else:
        log.append(f"  <no usable response: {parsed}>")

    log.append("--- STORY discovery, attempt 2: GET /{ig-user-id}/stories (active-only edge) ---")
    params2 = {"fields": "id,media_type,media_product_type,timestamp"}
    parsed2 = _get(f"{ig_user_id}/stories", token, params2, secrets)

    if parsed2 is None or "__transport_error__" in parsed2:
        log.append(f"  <no response: {parsed2}>")
        return None
    if "__unparseable__" in parsed2:
        log.append(f"  <unparseable response> {parsed2['__unparseable__']}")
        return None
    if "error" in parsed2:
        e = parsed2["error"]
        log.append(
            f"  ERROR code={e.get('code')} subcode={e.get('error_subcode')} msg={e.get('message')} "
            f"-- this may mean the endpoint requires a permission/scope not granted to this token, "
            f"NOT necessarily that no Stories exist. Flagging as inference, not confirmed absence."
        )
        return None

    items2 = parsed2.get("data", [])
    log.append(f"  /stories edge returned {len(items2)} active item(s).")
    if items2:
        sample = items2[0]
        log.append(f"  FOUND active Story: id={sample['id']} timestamp={sample.get('timestamp')}")
        return sample

    log.append("  No active Stories found on the dedicated /stories edge.")
    return None


def truncate_payload(parsed: dict, keep: int = 3) -> dict:
    trimmed = copy.deepcopy(parsed)
    for entry in trimmed.get("data", []) or []:
        values = entry.get("values")
        if isinstance(values, list) and len(values) > keep:
            omitted = len(values) - keep
            entry["values"] = values[:keep] + [f"... ({omitted} entries omitted) ..."]
    return trimmed


def test_metrics(media_id: str, media_type_label: str, token: str, secrets: List[str], log: List[str]) -> List[dict]:
    log.append(f"--- Testing {media_type_label} (media ID {media_id}) against the 10 candidate metrics ---")
    results = []
    for metric in CANDIDATE_METRICS:
        parsed = _get(f"{media_id}/insights", token, {"metric": metric}, secrets)
        if parsed and "error" in parsed:
            e = parsed["error"]
            status = f"FAIL code={e.get('code')} subcode={e.get('error_subcode')} msg={e.get('message')}"
            log.append(f"  {metric}: {status}")
            results.append({"metric": metric, "status": status, "success": False})
        elif parsed and "data" in parsed:
            log.append(f"  {metric}: SUCCESS")
            results.append({"metric": metric, "status": "SUCCESS", "success": True, "sample": truncate_payload(parsed)})
        else:
            log.append(f"  {metric}: UNKNOWN (no parseable JSON) -- raw: {parsed}")
            results.append({"metric": metric, "status": "UNKNOWN", "success": False})
    log.append("")
    return results


def main() -> None:
    config = load_config()
    system_token = config.system_user_token
    ig_user_id = config.ig_user_id
    secrets = [system_token]

    log: List[str] = []
    log.append("=== IG Media Insights -- REELS/STORY gap-closing diagnostic ===")
    log.append(f"Endpoint under test: GET /{{ig-media-id}}/insights (Graph API {GRAPH_API_VERSION})")
    log.append("Candidate metrics (same 10 used for IMAGE/VIDEO/CAROUSEL_ALBUM): "
                + ", ".join(CANDIDATE_METRICS))
    log.append("")

    all_results: Dict[str, List[dict]] = {}
    blocked: Dict[str, str] = {}

    # --- REELS ---
    print("Running REELS discovery...")
    reels_sample = discover_reels_sample(ig_user_id, system_token, secrets, log)
    if reels_sample:
        print(f"REELS sample found ({reels_sample['id']}); testing metrics...")
        all_results["REELS"] = test_metrics(reels_sample["id"], "REELS", system_token, secrets, log)
    else:
        blocked["REELS"] = (
            "BLOCKED -- no live Reels content found via media_product_type=='REELS' "
            "on the 50 most recent /media items. See discovery log above for the exact "
            "query and the media_product_type breakdown observed. Not guessed/skipped silently."
        )
        log.append(f"*** REELS: {blocked['REELS']} ***")
        log.append("")
        print("REELS: no sample found -- marking BLOCKED (see log).")

    # --- STORY ---
    print("Running STORY discovery...")
    story_sample = discover_story_sample(ig_user_id, system_token, secrets, log)
    if story_sample:
        print(f"STORY sample found ({story_sample['id']}); testing metrics...")
        all_results["STORY"] = test_metrics(story_sample["id"], "STORY", system_token, secrets, log)
    else:
        blocked["STORY"] = (
            "BLOCKED -- no live/active Story content found via either the /media edge "
            "(filtered for media_product_type=='STORY') or the dedicated /{ig-user-id}/stories "
            "edge. Stories expire ~24h after posting, so this is consistent with (but not "
            "conclusive proof of) 'no Story was posted in the last 24h at run time' -- re-run "
            "this script within 24h of posting a Story to get a real test. Not guessed/skipped silently."
        )
        log.append(f"*** STORY: {blocked['STORY']} ***")
        log.append("")
        print("STORY: no sample found -- marking BLOCKED (see log).")

    # --- Summary ---
    log.append("=" * 78)
    log.append("SUMMARY")
    log.append("=" * 78)
    log.append("")
    for media_type in ("REELS", "STORY"):
        if media_type in blocked:
            log.append(f"{media_type}: {blocked[media_type]}")
            log.append("")
            continue
        results = all_results.get(media_type, [])
        successes = [r["metric"] for r in results if r["success"]]
        failures = [r["metric"] for r in results if not r["success"]]
        log.append(f"{media_type}: {len(successes)} succeeded, {len(failures)} failed (of {len(results)})")
        if successes:
            log.append("  Succeeded: " + ", ".join(successes))
        if failures:
            log.append("  Failed: " + ", ".join(failures))
        log.append("")

    log.append("=" * 78)
    log.append("SAMPLE PAYLOADS (one per working metric, redacted, values array truncated to 3 entries)")
    log.append("=" * 78)
    for media_type, results in all_results.items():
        for r in results:
            if r["success"]:
                log.append("")
                log.append(f"--- {media_type} / {r['metric']} ---")
                log.append(json.dumps(r["sample"], indent=2))

    log.append("")
    log.append("=" * 78)
    log.append("NOTE ON diagnose_all_ig_media_metrics.py's PRIOR 'REELS: not found' RESULT")
    log.append("=" * 78)
    log.append(
        "diagnose_all_ig_media_metrics.py's discovery phase buckets media by the "
        "`media_type` field, which per the Graph API only ever returns IMAGE, VIDEO, "
        "or CAROUSEL_ALBUM -- Reels report media_type=VIDEO and are only distinguishable "
        "via the separate `media_product_type` field, which that script never queried. "
        "This means its prior 'REELS: not found' conclusion was not a reliable test of "
        "Reels' existence -- it could never have matched REELS regardless of whether Reels "
        "content existed. This script queries media_product_type directly instead. "
        "(This is a factual observation about the two scripts' queries, not a fix applied "
        "to the original file, which was left unmodified per the task brief.)"
    )

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(log) + "\n")

    print(f"\nReport written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
