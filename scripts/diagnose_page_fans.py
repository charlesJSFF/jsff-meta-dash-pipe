"""
Diagnostic script for the v25.0 Page Insights metric restructuring. Several
classic metrics (the page_impressions* family) are now deprecated, and
page_views/follower_count have no documented 1:1 replacement in our
original field list. This makes a single read-only GET to /{page-id}/insights
with metric=page_fans alone (period=day) and prints the raw response body
verbatim, so we can see -- before changing any extraction code -- whether
page_fans succeeds for this Page/token, and if not, the full error object
(code, error_subcode, message).

Tries the call twice: once with the System User token as-is (current
pipeline behavior), and once after exchanging it for the Page's own access
token via /me/accounts (what the old POC repo's meta_auth.get_page_token
did). This rules out a token-type difference as the cause before concluding
page_fans itself is the problem.

The token itself is never printed -- redacted from any URL or error text
that gets logged.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "extraction"))

from config_loader import load_config  # noqa: E402

GRAPH_API_VERSION = "v25.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


def _redact(url: str, token: str) -> str:
    return url.replace(token, "***REDACTED***")


def _get(path: str, access_token: str, params: dict) -> dict:
    query = dict(params)
    query["access_token"] = access_token
    url = f"{GRAPH_API_BASE}/{path}?{urllib.parse.urlencode(query)}"

    print(f"URL: {_redact(url, access_token)}")

    try:
        with urllib.request.urlopen(url) as response:
            status = response.status
            body = response.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        body = exc.read()
    except urllib.error.URLError as exc:
        print(f"Status: <no response> ({exc.reason})")
        return {}

    print(f"Status: {status}")
    try:
        parsed = json.loads(body)
        print(json.dumps(parsed, indent=2))
        error = parsed.get("error") if isinstance(parsed, dict) else None
        if error:
            print()
            print(f"error.code: {error.get('code')}")
            print(f"error.error_subcode: {error.get('error_subcode')}")
            print(f"error.message: {error.get('message')}")
        return parsed
    except json.JSONDecodeError:
        text = body.decode("utf-8", errors="replace")
        print(_redact(text, access_token))
        return {}


def _get_page_access_token(system_user_token: str, page_id: str) -> str:
    """
    Mirrors the old POC's meta_auth.get_page_token: looks up /me/accounts
    under the System User token and returns the matching Page's own
    access_token, falling back to the System User token if not found.
    """
    result = _get("me/accounts", system_user_token, {})
    for page in result.get("data", []):
        if page.get("id") == page_id:
            return page.get("access_token", system_user_token)
    print("Page not found in /me/accounts -- falling back to System User token.")
    return system_user_token


def main() -> None:
    config = load_config()
    token = config.system_user_token
    page_id = config.fb_page_id

    print("=== Call 1: page_fans with System User token (current pipeline behavior) ===")
    _get(f"{page_id}/insights", token, {"metric": "page_fans", "period": "day"})
    print()

    print("=== Call 2: exchange for Page access token via /me/accounts ===")
    page_token = _get_page_access_token(token, page_id)
    print()

    print("=== Call 3: page_fans with exchanged Page access token (POC behavior) ===")
    _get(f"{page_id}/insights", page_token, {"metric": "page_fans", "period": "day"})


if __name__ == "__main__":
    main()
