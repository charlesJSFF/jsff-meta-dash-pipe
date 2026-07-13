"""
Diagnostic script that tests every Page-level metric listed at
https://developers.facebook.com/docs/graph-api/reference/v25.0/insights#availmetrics
one at a time against /{page-id}/insights with period=day, and reports
SUCCESS/FAIL for each.

Scope is Page-level metrics only (the page_* family, tested via
/{page-id}/insights) -- the doc page also lists Post-level metrics
(post_*, tested via /{post-id}/insights, a different endpoint/ID), which
are out of scope: Post Insights isn't wired up in this pipeline at all,
and testing them against a Page ID would just fail on wrong-node-type
rather than telling us anything about deprecation.

Each metric is tested individually with period=day only (matches this
pipeline's current daily-grain scope). A FAIL here does not necessarily
mean the metric is dead -- some (e.g. demographic breakdowns) may require
a different period such as lifetime. The raw error is printed so that
distinction can be made by eye afterward; this script does not retry with
a different period automatically.

Uses the exchanged Page access token (src/extraction/auth.get_page_access_token).
Both the System User token and the exchanged Page token are redacted from
every line printed, including response bodies.
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

# Page-level (page_* / unprefixed monetization) metrics from the v25.0
# availmetrics doc. Post-level (post_*) metrics are deliberately excluded --
# see module docstring. Entries the doc marks "(deprecated)" are included
# anyway so we get a live confirmation rather than trusting the doc label.
PAGE_METRICS = [
    "page_tab_views_login_top_unique",
    "page_tab_views_login_top",
    "page_tab_views_logout_top",
    "page_total_actions",
    "page_post_engagements",
    "page_fan_adds_by_paid_non_paid_unique",
    "page_lifetime_engaged_followers_unique",
    "page_daily_follows",
    "page_daily_follows_unique",
    "page_daily_unfollows_unique",
    "page_follows",
    "page_impressions",
    "page_impressions_unique",
    "page_impressions_paid",
    "page_impressions_paid_unique",
    "page_impressions_viral",
    "page_impressions_viral_unique",
    "page_impressions_nonviral",
    "page_impressions_nonviral_unique",
    "page_media_view",
    "page_total_media_view_unique",
    "page_posts_impressions",
    "page_posts_impressions_unique",
    "page_posts_impressions_paid",
    "page_posts_impressions_paid_unique",
    "page_posts_impressions_organic_unique",
    "page_posts_served_impressions_organic_unique",
    "page_posts_impressions_viral",
    "page_posts_impressions_viral_unique",
    "page_posts_impressions_nonviral",
    "page_posts_impressions_nonviral_unique",
    "page_actions_post_reactions_like_total",
    "page_actions_post_reactions_love_total",
    "page_actions_post_reactions_wow_total",
    "page_actions_post_reactions_haha_total",
    "page_actions_post_reactions_sorry_total",
    "page_actions_post_reactions_anger_total",
    "page_actions_post_reactions_total",
    "page_fans",
    "page_fans_locale",
    "page_fans_city",
    "page_fans_country",
    "page_fan_adds",
    "page_fan_adds_unique",
    "page_fan_removes",
    "page_fan_removes_unique",
    "page_video_views",
    "page_video_views_by_uploaded_hosted",
    "page_video_views_paid",
    "page_video_views_organic",
    "page_video_views_by_paid_non_paid",
    "page_video_views_autoplayed",
    "page_video_views_click_to_play",
    "page_video_views_unique",
    "page_video_repeat_views",
    "page_video_complete_views_30s",
    "page_video_complete_views_30s_paid",
    "page_video_complete_views_30s_organic",
    "page_video_complete_views_30s_autoplayed",
    "page_video_complete_views_30s_click_to_play",
    "page_video_complete_views_30s_unique",
    "page_video_complete_views_30s_repeat_views",
    "page_video_views_10s",  # (deprecated per doc)
    "page_video_views_10s_paid",  # (deprecated per doc)
    "page_video_views_10s_organic",  # (deprecated per doc)
    "page_video_views_10s_autoplayed",  # (deprecated per doc)
    "page_video_views_10s_click_to_play",  # (deprecated per doc)
    "page_video_views_10s_unique",  # (deprecated per doc)
    "page_video_views_10s_repeat",  # (deprecated per doc)
    "page_video_view_time",
    "page_uploaded_3s_to_15s_views_rate",
    "page_uploaded_views_15s_count",
    "page_uploaded_views_60s_excludes_shorter_unique_count_by_is_60s_returning_viewer",
    "page_views_total",
    "page_daily_video_ad_break_ad_impressions_by_crosspost_status",
    "page_daily_video_ad_break_cpm_by_crosspost_status",
    "page_daily_video_ad_break_earnings_by_crosspost_status",
    "creator_monetization_qualified_views",
    "content_monetization_earnings",
    "monetization_approximate_earnings",
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
        print(_redact(f"  <no response> ({exc.reason})", secrets))
        return None

    text = _redact(body.decode("utf-8", errors="replace"), secrets)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        print(f"  <unparseable response> {text}")
        return None


def main() -> None:
    config = load_config()
    system_token = config.system_user_token
    page_id = config.fb_page_id
    page_token = get_page_access_token(system_token, page_id)
    secrets = [system_token, page_token]

    results = []
    for metric in PAGE_METRICS:
        parsed = _get(f"{page_id}/insights", page_token, {"metric": metric, "period": "day"}, secrets)
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
        print(f"{metric}: {status}")
        results.append((metric, status))

    successes = [m for m, s in results if s == "SUCCESS"]
    failures = [m for m, s in results if s != "SUCCESS"]

    print()
    print(f"=== Summary: {len(successes)} succeeded, {len(failures)} failed (of {len(results)}) ===")
    print()
    print("Succeeded:")
    for m in successes:
        print(f"  {m}")
    print()
    print("Failed:")
    for m in failures:
        print(f"  {m}")


if __name__ == "__main__":
    main()
