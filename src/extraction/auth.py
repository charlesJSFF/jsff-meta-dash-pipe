"""
Page Access Token resolution for the Meta Graph API pipeline.

The System User token alone is not guaranteed to behave the same as a
Page's own access token for every Graph API call (see error code 190,
"This method must be called with a Page Access Token", investigated in
scripts/diagnose_token_190.py). The old POC pipeline (meta_auth.py)
always exchanged the System User token for the Page's own token via
/me/accounts before calling Page Insights -- this module reproduces that
same exchange step for this pipeline.
"""

import json
import urllib.error
import urllib.parse
import urllib.request

GRAPH_API_VERSION = "v25.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


class PageTokenLookupError(RuntimeError):
    """Raised when the /me/accounts lookup itself fails (network or API error)."""


def _http_get_json(url: str) -> dict:
    """
    Isolated into its own function so tests can patch this single seam
    instead of touching urllib directly or making a live network call.
    """
    try:
        with urllib.request.urlopen(url) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise PageTokenLookupError(
            f"/me/accounts request failed with HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}"
        ) from exc
    except urllib.error.URLError as exc:
        raise PageTokenLookupError(f"/me/accounts request failed: {exc.reason}") from exc

    payload = json.loads(body)
    if "error" in payload:
        raise PageTokenLookupError(f"/me/accounts returned an error: {payload['error']}")
    return payload


def get_page_access_token(system_user_token: str, page_id: str) -> str:
    """
    Exchange a System User token for the given Page's own access token by
    calling /me/accounts and matching on page_id.

    Falls back to returning the System User token unchanged -- with a
    printed warning, not an exception -- if the Page isn't found in the
    managed-accounts list, matching the old POC's fallback behavior.
    Raises PageTokenLookupError only if the /me/accounts call itself fails.
    """
    params = {"access_token": system_user_token}
    url = f"{GRAPH_API_BASE}/me/accounts?{urllib.parse.urlencode(params)}"

    payload = _http_get_json(url)
    for page in payload.get("data", []):
        if page.get("id") == page_id:
            return page.get("access_token", system_user_token)

    print("Page not found in /me/accounts -- falling back to System User token.")
    return system_user_token
