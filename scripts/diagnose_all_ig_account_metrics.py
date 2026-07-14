"""
Diagnostic script that tests Instagram account-level insights metrics against the
live Graph API, across multiple period grains and metric_type modes.

IG User Insights (/ig-user-id/insights) differs from Page Insights in that
different period grains (day, week, days_28, lifetime) accept different
metrics, and many metrics require a `metric_type` parameter to indicate
whether results should be time-series (aggregated by period) or a simple total.

Per the docs:
  metric_type=time_series → aggregates by time period (requires Period param)
  metric_type=total_value  → returns a simple total (no period grain needed)

Each metric is tested with its applicable parameter combinations. A FAIL printed
here could mean the metric is genuinely unavailable for IG user-level insights,
or simply unsupported for that parameter combination. The raw error (code +
message) is printed so those can be distinguished.

Uses the System User token directly, matching the IG media diagnostic
pattern (no Page token exchange needed for IG User calls).

The System User token is redacted from every line printed, including
response bodies.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "extraction"))

from config_loader import load_config  # noqa: E402

GRAPH_API_VERSION = "v25.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

# A test case is a dict of query parameters to include in the API call.
# Every test case includes "metric" (added automatically by the test loop).
# Tests can include "period", "metric_type", or both depending on what the
# metric supports per the docs.
#
# Key combos used below:
#   {"period": "day"}                                       — time-series, daily grain
#   {"period": "week"}                                      — time-series, weekly grain
#   {"period": "days_28"}                                   — time-series, 28-day grain
#   {"period": "lifetime"}                                  — time-series, lifetime grain
#   {"metric_type": "total_value", "period": "days_28"}     — total_value per 28-day window
#   {"metric_type": "total_value", "period": "lifetime"}    — total_value lifetime

CANDIDATE_METRICS: Dict[str, List[dict]] = {
    # === Core metrics (time-series tests, no metric_type) ===
    "reach": [
        {"period": "day"},
        {"period": "week"},
        {"period": "days_28"},
        {"period": "lifetime"},
    ],
    # === Metrics that need metric_type=total_value with a period ===
    # Testing period=day (alone and with total_value) in addition to days_28/lifetime
    "accounts_engaged": [
        {"period": "day"},
        {"metric_type": "total_value", "period": "day"},
        {"metric_type": "total_value", "period": "days_28"},
        {"metric_type": "total_value", "period": "lifetime"},
    ],
    "total_interactions": [
        {"period": "day"},
        {"metric_type": "total_value", "period": "day"},
        {"metric_type": "total_value", "period": "days_28"},
        {"metric_type": "total_value", "period": "lifetime"},
    ],
    "likes": [
        {"period": "day"},
        {"metric_type": "total_value", "period": "day"},
        {"metric_type": "total_value", "period": "days_28"},
        {"metric_type": "total_value", "period": "lifetime"},
    ],
    "comments": [
        {"period": "day"},
        {"metric_type": "total_value", "period": "day"},
        {"metric_type": "total_value", "period": "days_28"},
        {"metric_type": "total_value", "period": "lifetime"},
    ],
    "saves": [
        {"period": "day"},
        {"metric_type": "total_value", "period": "day"},
        {"metric_type": "total_value", "period": "days_28"},
        {"metric_type": "total_value", "period": "lifetime"},
    ],
    "shares": [
        {"period": "day"},
        {"metric_type": "total_value", "period": "day"},
        {"metric_type": "total_value", "period": "days_28"},
        {"metric_type": "total_value", "period": "lifetime"},
    ],
    "replies": [
        {"period": "day"},
        {"metric_type": "total_value", "period": "day"},
        {"metric_type": "total_value", "period": "days_28"},
        {"metric_type": "total_value", "period": "lifetime"},
    ],
    "views": [
        {"period": "day"},
        {"metric_type": "total_value", "period": "day"},
        {"metric_type": "total_value", "period": "days_28"},
        {"metric_type": "total_value", "period": "lifetime"},
    ],
    # === Account-growth metric ===
    "follows_and_unfollows": [
        {"period": "day"},
        {"metric_type": "total_value", "period": "day"},
        {"metric_type": "total_value", "period": "days_28"},
        {"metric_type": "total_value", "period": "lifetime"},
    ],
    # === Follower count (period=day confirmed; test total_value combos too) ===
    "follower_count": [
        {"period": "day"},
        {"period": "week"},
        {"period": "days_28"},
        {"period": "lifetime"},
        {"metric_type": "total_value", "period": "day"},
        {"metric_type": "total_value", "period": "days_28"},
        {"metric_type": "total_value", "period": "lifetime"},
    ],
    # === Profile-tap metric ===
    "profile_links_taps": [
        {"period": "day"},
        {"metric_type": "total_value", "period": "day"},
        {"metric_type": "total_value", "period": "days_28"},
        {"metric_type": "total_value", "period": "lifetime"},
    ],
    # === Profile views ===
    "profile_views": [
        {"period": "day"},
        {"metric_type": "total_value", "period": "day"},
        {"metric_type": "total_value", "period": "days_28"},
        {"metric_type": "total_value", "period": "lifetime"},
    ],
    # === Website clicks ===
    "website_clicks": [
        {"period": "day"},
        {"metric_type": "total_value", "period": "day"},
        {"metric_type": "total_value", "period": "days_28"},
        {"metric_type": "total_value", "period": "lifetime"},
    ],
    # === Deprecated metrics (expect FAIL across the board) ===
    "impressions": [
        {"period": "day"},
        {"period": "lifetime"},
    ],
    "email_contacts": [
        {"period": "day"},
        {"period": "lifetime"},
    ],
    "phone_call_clicks": [
        {"period": "day"},
        {"period": "lifetime"},
    ],
    "text_message_clicks": [
        {"period": "day"},
        {"period": "lifetime"},
    ],
    # === Audience/breakdown metrics ===
    "audience_city": [
        {"period": "lifetime"},
        {"period": "day"},
    ],
    "audience_country": [
        {"period": "lifetime"},
        {"period": "day"},
    ],
    "audience_gender_age": [
        {"period": "lifetime"},
        {"period": "day"},
    ],
    "audience_locale": [
        {"period": "lifetime"},
        {"period": "day"},
    ],
    # === Online followers (already confirmed working with lifetime) ===
    "online_followers": [
        {"period": "lifetime"},
        {"period": "day"},
    ],
}


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


def _describe_params(params: dict) -> str:
    """Return a human-readable label for a test-case param dict."""
    parts = []
    if "period" in params:
        parts.append(f"period={params['period']}")
    if "metric_type" in params:
        parts.append(f"metric_type={params['metric_type']}")
    return ", ".join(parts) if parts else "(no extra params)"


def test_metric_variant(
    ig_user_id: str,
    metric: str,
    params: dict,
    access_token: str,
    secrets: List[str],
) -> str:
    """
    Test a single metric+parameter combination against /{ig-user-id}/insights.

    `params` is a dict of additional query parameters (period, metric_type, etc.).
    The metric name is added automatically.

    Returns a status string: "SUCCESS" or "FAIL code=... msg=...".
    """
    call_params = dict(params)
    call_params["metric"] = metric
    parsed = _get(f"{ig_user_id}/insights", access_token, call_params, secrets)
    if parsed and "error" in parsed:
        error = parsed["error"]
        return (
            f"FAIL code={error.get('code')} subcode={error.get('error_subcode')} "
            f"msg={error.get('message')}"
        )
    elif parsed and "data" in parsed:
        return "SUCCESS"
    else:
        return "UNKNOWN (no parseable JSON)"


def main() -> None:
    config = load_config()
    system_token = config.system_user_token
    ig_user_id = config.ig_user_id
    secrets = [system_token]

    total_combos = 0
    total_success = 0
    total_fail = 0

    # Stores results grouped by metric: metric -> [ (param_label, status) ]
    all_results: Dict[str, List[Tuple[str, str]]] = {}

    print("=== IG Account-Level Insights -- Testing candidate metrics ===")
    print()

    for metric in sorted(CANDIDATE_METRICS.keys()):
        test_cases = CANDIDATE_METRICS[metric]
        per_metric_results: List[Tuple[str, str]] = []

        print(f"--- {metric} ---")
        for params in test_cases:
            label = _describe_params(params)
            status = test_metric_variant(ig_user_id, metric, params, system_token, secrets)
            per_metric_results.append((label, status))
            if status == "SUCCESS":
                total_success += 1
            else:
                total_fail += 1
            total_combos += 1
            indicator = "OK" if status == "SUCCESS" else "XX"
            print(f"  [{indicator}] {label}: {status}")

        all_results[metric] = per_metric_results
        print()

    # Summary
    print("=== Summary ===")
    print()
    print(f"Total metric+param combos tested: {total_combos}")
    print(f"SUCCESS: {total_success}, FAIL: {total_fail}")
    print()

    print("Per-metric breakdown:")
    for metric in sorted(all_results.keys()):
        results = all_results[metric]
        succeeded = [(lbl, st) for lbl, st in results if st == "SUCCESS"]
        if succeeded:
            print(f"  {metric}: SUCCESS with:")
            for lbl, _ in succeeded:
                print(f"    {lbl}")
        else:
            first_fail = next(
                (st for lbl, st in results if st != "SUCCESS"),
                "no results",
            )
            print(f"  {metric}: ALL FAILED ({first_fail})")

    print()
    print("=== Done ===")


if __name__ == "__main__":
    main()