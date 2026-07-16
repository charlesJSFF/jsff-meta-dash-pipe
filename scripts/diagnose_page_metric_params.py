"""
Diagnostic script: parameter-space and payload probe for the 37 Page-level
metrics already confirmed to be valid metric *names* by
diagnose_all_page_metrics.py (see
scripts/output/diagnose_all_page_metrics_output.txt). That script only
answered "does this metric name exist on v25.0" -- this one answers the
questions that actually matter for year-over-year backfill: which `period`
values each metric accepts, whether it accepts a `since`/`until` range at
all, how far back that range actually reaches before it errors or silently
truncates, and what the response payload looks like for each working
combination.

Per metric, per period in {day, week, days_28, lifetime}:
  1. Try the period alone, no date range -- accept/reject.
  2. If accepted bare, try since/until with a 7-day window ending
     yesterday -- accept/reject.
  3. If the 7-day range is accepted AND its returned data actually covers
     the requested window (see `check_coverage` -- a 200 response with
     data that doesn't reach back to `since` counts as a truncation, not
     a pass), escalate the window: 30d, 90d, ~6mo (182d), ~12mo (365d),
     ~15mo (456d). Escalation stops at the first rejected call or the
     first non-full-coverage response -- there is no point testing a
     longer window once a shorter one has already failed, per the task's
     "stop early" instruction.
  4. Save one truncated, redacted sample payload for each *working*
     period+window combination (bare-only accepts don't get a range
     sample; there is no range to sample).

Read-only: makes live Graph API GET calls against /{page-id}/insights only.
No writes to src/, tests/, or .env. Uses the exchanged Page access token
(src/extraction/auth.get_page_access_token), same as
diagnose_all_page_metrics.py. Both the System User token and the Page
token are redacted from every printed line and every saved response body.

If the Graph API returns a rate-limit error mid-sweep, the sweep stops
immediately (no retry loop) and whatever was gathered so far is still
written to the output file, with an explicit note marking which metric it
stopped at.
"""

import copy
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from typing import Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "extraction"))

from auth import get_page_access_token  # noqa: E402
from config_loader import load_config  # noqa: E402

GRAPH_API_VERSION = "v25.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "output", "diagnose_page_metric_params_output.txt")

# The 37 metrics diagnose_all_page_metrics.py confirmed as valid names on
# v25.0. See scripts/output/diagnose_all_page_metrics_output.txt "Succeeded"
# list -- copied verbatim, not re-derived here.
PAGE_METRICS = [
    "page_total_actions",
    "page_post_engagements",
    "page_fan_adds_by_paid_non_paid_unique",
    "page_lifetime_engaged_followers_unique",
    "page_daily_follows",
    "page_daily_follows_unique",
    "page_daily_unfollows_unique",
    "page_follows",
    "page_media_view",
    "page_total_media_view_unique",
    "page_actions_post_reactions_like_total",
    "page_actions_post_reactions_love_total",
    "page_actions_post_reactions_wow_total",
    "page_actions_post_reactions_haha_total",
    "page_actions_post_reactions_sorry_total",
    "page_actions_post_reactions_anger_total",
    "page_actions_post_reactions_total",
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
    "page_video_view_time",
    "page_views_total",
    "content_monetization_earnings",
    "monetization_approximate_earnings",
]

PERIODS = ["day", "week", "days_28", "lifetime"]

# Escalation ladder after the initial 7-day probe. Chosen per the task
# brief: 30d, 90d, ~6mo, ~12mo, ~15mo.
WINDOW_DAYS_ESCALATION = [30, 90, 182, 365, 456]

# Coverage tolerance (days) per period -- how far the earliest/latest
# returned end_time is allowed to drift from the requested since/until
# before we call it a truncation rather than normal aggregation lag.
COVERAGE_TOLERANCE_DAYS = {"day": 1, "week": 8, "days_28": 29, "lifetime": 0}

# Meta Graph API error codes associated with rate limiting / throttling.
# 4 = app-level API too many calls, 17 = user request limit reached,
# 32 = page request limit reached, 613 = custom rate limit hit.
RATE_LIMIT_CODES = {4, 17, 32, 613}

REQUEST_DELAY_SECONDS = 0.3

# Sentinel distinguishing "rate limited" from a normal error/None response.
RATE_LIMITED = object()

# "Safe for full YoY backfill" threshold, in days of confirmed lookback.
YOY_THRESHOLD_DAYS = 365

TODAY = date.today()
UNTIL_ANCHOR = TODAY - timedelta(days=1)  # yesterday; avoids partial current-day data


def _redact(text: str, secrets: List[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***REDACTED***")
    return text


def _window(days_back: int) -> tuple:
    until = UNTIL_ANCHOR
    since = until - timedelta(days=days_back - 1)
    return since.isoformat(), until.isoformat()


def api_get(page_id: str, token: str, params: dict, secrets: List[str]):
    """
    GET /{page_id}/insights with the given params. Returns the parsed JSON
    dict, the RATE_LIMITED sentinel if a rate-limit error code/message is
    detected, or None if the response wasn't parseable JSON or the request
    itself failed at the network layer.
    """
    query = dict(params)
    query["access_token"] = token
    url = f"{GRAPH_API_BASE}/{page_id}/insights?{urllib.parse.urlencode(query)}"

    time.sleep(REQUEST_DELAY_SECONDS)
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
        parsed = json.loads(text)
    except json.JSONDecodeError:
        print(f"  <unparseable response> {text}")
        return None

    if _is_rate_limited(parsed):
        return RATE_LIMITED
    return parsed


def _is_rate_limited(parsed: Optional[dict]) -> bool:
    if not parsed or "error" not in parsed:
        return False
    error = parsed["error"]
    if error.get("code") in RATE_LIMIT_CODES:
        return True
    msg = (error.get("message") or "").lower()
    return "rate limit" in msg or "too many calls" in msg


def _is_success(parsed: Optional[dict]) -> bool:
    return bool(parsed) and "data" in parsed and "error" not in parsed


def _error_str(parsed: Optional[dict]) -> str:
    if not parsed:
        return "<no response / unparseable>"
    if "error" in parsed:
        e = parsed["error"]
        return f"code={e.get('code')} subcode={e.get('error_subcode')} msg={e.get('message')}"
    return "<response has neither data nor error>"


def _extract_end_dates(parsed: dict) -> List[str]:
    dates = []
    for entry in parsed.get("data", []) or []:
        for v in entry.get("values", []) or []:
            et = v.get("end_time")
            if et:
                dates.append(et[:10])
    return sorted(dates)


def check_coverage(parsed: dict, since_str: str, until_str: str, period: str) -> dict:
    """
    Compare the earliest/latest end_time actually returned against the
    requested since/until. A 200 response whose data doesn't reach back to
    `since` (beyond the period's aggregation tolerance) is a truncation,
    not a working full-range response.
    """
    dates = _extract_end_dates(parsed)
    if not dates:
        return {"has_data": False, "full_coverage": False}

    earliest, latest = dates[0], dates[-1]
    tolerance = COVERAGE_TOLERANCE_DAYS.get(period, 1)
    since_d = date.fromisoformat(since_str)
    until_d = date.fromisoformat(until_str)
    earliest_d = date.fromisoformat(earliest)
    latest_d = date.fromisoformat(latest)
    front_gap = (earliest_d - since_d).days
    back_gap = (until_d - latest_d).days
    full = front_gap <= tolerance and back_gap <= tolerance
    return {
        "has_data": True,
        "earliest": earliest,
        "latest": latest,
        "n_points": len(dates),
        "front_gap_days": front_gap,
        "back_gap_days": back_gap,
        "full_coverage": full,
    }


def truncate_payload(parsed: dict, keep: int = 2) -> dict:
    """Trim long `values` arrays to first/last `keep` entries for the saved sample."""
    trimmed = copy.deepcopy(parsed)
    for entry in trimmed.get("data", []) or []:
        values = entry.get("values")
        if isinstance(values, list) and len(values) > keep * 2:
            omitted = len(values) - keep * 2
            entry["values"] = values[:keep] + [f"... ({omitted} entries omitted) ..."] + values[-keep:]
    return trimmed


def test_metric(metric: str, page_id: str, token: str, secrets: List[str]) -> dict:
    result: Dict[str, object] = {"metric": metric, "periods": {}, "rate_limited": False}

    for period in PERIODS:
        period_entry: Dict[str, object] = {}
        bare = api_get(page_id, token, {"metric": metric, "period": period}, secrets)
        if bare is RATE_LIMITED:
            result["rate_limited"] = True
            return result

        bare_ok = _is_success(bare)
        period_entry["bare_accepted"] = bare_ok
        if not bare_ok:
            period_entry["bare_error"] = _error_str(bare)
            result["periods"][period] = period_entry
            continue

        since7, until7 = _window(7)
        range7 = api_get(
            page_id, token, {"metric": metric, "period": period, "since": since7, "until": until7}, secrets
        )
        if range7 is RATE_LIMITED:
            result["rate_limited"] = True
            result["periods"][period] = period_entry
            return result

        range_ok = _is_success(range7)
        period_entry["range_accepted"] = range_ok
        if not range_ok:
            period_entry["range_error"] = _error_str(range7)
            result["periods"][period] = period_entry
            continue

        cov7 = check_coverage(range7, since7, until7, period)
        windows = [
            {
                "days_requested": 7,
                "since": since7,
                "until": until7,
                "accepted": True,
                "coverage": cov7,
                "sample": truncate_payload(range7),
            }
        ]
        max_confirmed = 7 if cov7.get("full_coverage") else 0

        if cov7.get("full_coverage"):
            for days in WINDOW_DAYS_ESCALATION:
                since_n, until_n = _window(days)
                resp = api_get(
                    page_id, token, {"metric": metric, "period": period, "since": since_n, "until": until_n}, secrets
                )
                if resp is RATE_LIMITED:
                    result["rate_limited"] = True
                    period_entry["windows"] = windows
                    period_entry["max_confirmed_days"] = max_confirmed
                    result["periods"][period] = period_entry
                    return result

                ok = _is_success(resp)
                if not ok:
                    windows.append(
                        {"days_requested": days, "since": since_n, "until": until_n, "accepted": False, "error": _error_str(resp)}
                    )
                    break

                cov = check_coverage(resp, since_n, until_n, period)
                windows.append(
                    {
                        "days_requested": days,
                        "since": since_n,
                        "until": until_n,
                        "accepted": True,
                        "coverage": cov,
                        "sample": truncate_payload(resp),
                    }
                )
                if cov.get("full_coverage"):
                    max_confirmed = days
                else:
                    break

        period_entry["windows"] = windows
        period_entry["max_confirmed_days"] = max_confirmed
        result["periods"][period] = period_entry

    return result


def classify(metric_result: dict) -> str:
    best = 0
    any_range_accepted = False
    for entry in metric_result["periods"].values():
        if entry.get("range_accepted"):
            any_range_accepted = True
            best = max(best, entry.get("max_confirmed_days", 0) or 0)
    if best >= YOY_THRESHOLD_DAYS:
        return "SAFE_FOR_FULL_YOY"
    if any_range_accepted:
        return "RANGE_LIMITED"
    return "SNAPSHOT_ONLY"


def _format_windows(windows: List[dict], indent: str) -> List[str]:
    lines = []
    for w in windows:
        if not w.get("accepted"):
            lines.append(f"{indent}- {w['days_requested']}d ({w['since']}..{w['until']}): REJECTED -- {w['error']}")
            continue
        cov = w["coverage"]
        if not cov.get("has_data"):
            lines.append(f"{indent}- {w['days_requested']}d ({w['since']}..{w['until']}): ACCEPTED, but no data points returned")
            continue
        tag = "FULL COVERAGE" if cov["full_coverage"] else "TRUNCATED"
        lines.append(
            f"{indent}- {w['days_requested']}d ({w['since']}..{w['until']}): ACCEPTED, {tag} "
            f"[{cov['n_points']} points, earliest={cov['earliest']}, latest={cov['latest']}, "
            f"front_gap={cov['front_gap_days']}d, back_gap={cov['back_gap_days']}d]"
        )
        lines.append(f"{indent}  sample payload:")
        sample_json = json.dumps(w["sample"], indent=2)
        for line in sample_json.splitlines():
            lines.append(f"{indent}    {line}")
    return lines


def write_report(all_results: List[dict], rate_limited_at: Optional[str], output_path: str) -> None:
    lines: List[str] = []

    safe_yoy, range_limited, snapshot_only, untested = [], [], [], []
    for r in all_results:
        if r.get("rate_limited"):
            continue
        cls = classify(r)
        if cls == "SAFE_FOR_FULL_YOY":
            safe_yoy.append(r["metric"])
        elif cls == "RANGE_LIMITED":
            range_limited.append(r["metric"])
        else:
            snapshot_only.append(r["metric"])

    tested_metrics = {r["metric"] for r in all_results}
    untested = [m for m in PAGE_METRICS if m not in tested_metrics]

    lines.append("=" * 78)
    lines.append("SUMMARY (plain English)")
    lines.append("=" * 78)
    lines.append("")
    lines.append(
        f"Of {len(PAGE_METRICS)} previously-confirmed-valid Page metrics, "
        f"{len(all_results) - (1 if rate_limited_at else 0)} were fully tested this run."
    )
    lines.append("")
    lines.append(f"Safe for full YoY backfill (>= {YOY_THRESHOLD_DAYS}d confirmed lookback on at least one period):")
    for m in safe_yoy:
        lines.append(f"  - {m}")
    if not safe_yoy:
        lines.append("  (none)")
    lines.append("")
    lines.append("Range-limited (accepts since/until, but confirmed max lookback is shorter than 12 months):")
    for m in range_limited:
        lines.append(f"  - {m}")
    if not range_limited:
        lines.append("  (none)")
    lines.append("")
    lines.append("Snapshot-only (no period+since/until combination worked -- no historical backfill possible):")
    for m in snapshot_only:
        lines.append(f"  - {m}")
    if not snapshot_only:
        lines.append("  (none)")
    if untested:
        lines.append("")
        lines.append("Not tested (sweep stopped before reaching these, see rate-limit note below):")
        for m in untested:
            lines.append(f"  - {m}")
    if rate_limited_at:
        lines.append("")
        lines.append(f"*** RATE LIMIT HIT while testing '{rate_limited_at}' -- sweep stopped early. ***")
        lines.append("*** No retry loop was attempted. Re-run the script later to continue/redo the sweep. ***")
    lines.append("")
    lines.append("=" * 78)
    lines.append("DETAIL")
    lines.append("=" * 78)

    for r in all_results:
        lines.append("")
        lines.append("-" * 78)
        lines.append(f"METRIC: {r['metric']}")
        if not r.get("rate_limited"):
            lines.append(f"CLASSIFICATION: {classify(r)}")
        lines.append("-" * 78)
        for period in PERIODS:
            entry = r["periods"].get(period)
            if entry is None:
                lines.append(f"  period={period}: NOT TESTED (rate limit hit earlier in this metric's sweep)")
                continue
            if not entry.get("bare_accepted"):
                lines.append(f"  period={period}: bare REJECTED -- {entry.get('bare_error')}")
                continue
            lines.append(f"  period={period}: bare ACCEPTED")
            if not entry.get("range_accepted"):
                lines.append(f"    since/until REJECTED -- {entry.get('range_error')} (snapshot/prior-period only)")
                continue
            lines.append(f"    since/until ACCEPTED. max confirmed full-coverage lookback: {entry.get('max_confirmed_days')} days")
            lines.extend(_format_windows(entry.get("windows", []), indent="    "))
        if r.get("rate_limited"):
            lines.append("  *** RATE LIMIT HIT during this metric's sweep -- remaining periods not tested. ***")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main() -> None:
    config = load_config()
    system_token = config.system_user_token
    page_id = config.fb_page_id
    page_token = get_page_access_token(system_token, page_id)
    secrets = [system_token, page_token]

    all_results: List[dict] = []
    rate_limited_at: Optional[str] = None

    for metric in PAGE_METRICS:
        print(f"Testing {metric} ...")
        r = test_metric(metric, page_id, page_token, secrets)
        all_results.append(r)
        if r.get("rate_limited"):
            rate_limited_at = metric
            print(f"  Rate limit hit while testing {metric} -- stopping sweep.")
            break
        print(f"  -> {classify(r)}")

    write_report(all_results, rate_limited_at, OUTPUT_PATH)
    print(f"\nReport written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
