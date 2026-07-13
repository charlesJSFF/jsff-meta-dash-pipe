"""
Diagnostic script for Graph API error 190 ("This method must be called with
a Page Access Token"). Makes four read-only GET calls and prints status code
+ raw JSON for each, so we can see what the API actually says about the
token before changing any extraction logic.

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


def _get(path: str, access_token: str, params: dict) -> None:
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
        return

    print(f"Status: {status}")
    try:
        parsed = json.loads(body)
        print(json.dumps(parsed, indent=2))
    except json.JSONDecodeError:
        text = body.decode("utf-8", errors="replace")
        print(_redact(text, access_token))


def main() -> None:
    config = load_config()
    token = config.system_user_token
    page_id = config.fb_page_id

    print("=== Call 1: Page basic fields ===")
    _get(page_id, token, {"fields": "id,name"})
    print()

    print("=== Call 2: Token permissions ===")
    _get("me/permissions", token, {})
    print()

    print("=== Call 3: Page insights (reproduces failing call) ===")
    _get(f"{page_id}/insights", token, {"metric": "page_views", "period": "day"})
    print()

    print("=== Call 4: Token identity ===")
    _get("me", token, {"fields": "id,name"})


if __name__ == "__main__":
    main()
