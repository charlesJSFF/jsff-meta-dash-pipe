"""
Diagnostic script for the v25.0 Page Insights metric restructuring. Tests
each of the "untested by us on v25.0" / "VERSION-SENSITIVE" candidate
metrics from docs/meta_api_reference.md one at a time (Graph API rejects
the whole call if any one requested metric is invalid, so a combined call
wouldn't tell us which ones actually work).

Uses the exchanged Page access token (src/extraction/auth.get_page_access_token),
matching the pipeline's current auth methodology.

Both the System User token and the exchanged Page token are redacted from
every line printed -- including response *bodies*, not just request URLs.
(An earlier version of a similar diagnostic only redacted URLs and leaked a
live Page token via the /me/accounts response body.)
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "extraction"))

from auth import get_page_access_token  # noqa: E402
from config_loader import load_config  # noqa: E402

GRAPH_API_VERSION = "v25.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

CANDIDATE_METRICS = [
    "page_impressions_unique",
    "page_impressions_paid_unique",
    "page_impressions_viral_unique",
    "page_impressions_nonviral_unique",
    "page_fan_adds_by_paid_non_paid_unique",
    "page_media_view",
    "page_total_actions",
    "page_post_engagements",
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

    print(f"URL: {_redact(url, secrets)}")

    try:
        with urllib.request.urlopen(url) as response:
            status = response.status
            body = response.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        body = exc.read()
    except urllib.error.URLError as exc:
        print(f"Status: <no response> ({exc.reason})")
        return None

    print(f"Status: {status}")
    text = _redact(body.decode("utf-8", errors="replace"), secrets)
    print(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def main() -> None:
    config = load_config()
    system_token = config.system_user_token
    page_id = config.fb_page_id
    page_token = get_page_access_token(system_token, page_id)
    secrets = [system_token, page_token]

    results = {}
    for metric in CANDIDATE_METRICS:
        print(f"=== {metric} ===")
        parsed = _get(f"{page_id}/insights", page_token, {"metric": metric, "period": "day"}, secrets)
        if parsed and "error" in parsed:
            error = parsed["error"]
            results[metric] = (
                f"FAIL code={error.get('code')} subcode={error.get('error_subcode')} "
                f"msg={error.get('message')}"
            )
        elif parsed and "data" in parsed:
            results[metric] = "SUCCESS"
        else:
            results[metric] = "UNKNOWN (no parseable JSON)"
        print()

    print("=== Summary ===")
    for metric, result in results.items():
        print(f"{metric}: {result}")


if __name__ == "__main__":
    main()
