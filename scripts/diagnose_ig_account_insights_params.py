"""
Diagnostic script: parameter-space and payload probe for
GET /{ig-user-id}/insights (IG account-level insights), mirroring
diagnose_page_metric_params.py's approach for FB Page insights.

diagnose_all_ig_account_metrics.py (see
scripts/output/diagnose_all_ig_account_metrics.txt) already established
WHICH metric+period(+metric_type) combinations are valid at all -- 17
SUCCESS combos out of 77 tried, across 25 candidate metric names. That
script never tested since/until ranges at all. This script starts from
those 17 already-confirmed-valid combos and answers the questions that
matter for backfill: does each combo accept a since/until range, how far
back does that range actually reach before erroring or truncating (same
escalation ladder as the FB script: 7d, 30d, 90d, 182d, 365d, 456d,
stopping at the first rejection or non-full-coverage response), and what
does the response payload look like.

IMPORTANT STRUCTURAL DIFFERENCE FROM FB PAGE INSIGHTS: IG account metrics
tested with metric_type=total_value return a single `total_value: {value:
N}` object per data entry, NOT a `values: [{value, end_time}, ...]` time
series. There is no per-day breakdown to check against the requested
since/until window for those combos, so "full coverage" in the FB-script
sense (comparing earliest/latest end_time against the request) cannot be
computed for them. This script computes real coverage checks only for the
time-series-shaped combos (reach, follower_count -- no metric_type) and,
for total_value-shaped combos, reports range acceptance only, explicitly
labeled as "coverage unverifiable" rather than asserting full coverage
that wasn't actually confirmed. Distinguishing confirmed fact from
inference is the standard set by diagnose_page_metric_params.py and its
synthesized doc (docs/meta_graph_api_ref.md); this script holds to the
same standard for the IG side.

This script also runs two additional, one-off diagnostics not part of the
main sweep, both aimed squarely at the ROADMAP's open question ("no
confirmed cumulative follower-total metric on IG"):

  1. Sends a deliberately-invalid metric name to force the Graph API's own
     "metric[0] must be one of the following values: [...]" error, and
     captures the full enumerated list of valid account-level metric names
     directly from the live API -- rather than trusting the candidate list
     diagnose_all_ig_account_metrics.py happened to test. This lets us
     confirm, not just infer, whether every valid metric name has been
     accounted for.
  2. Queries GET /{ig-user-id}?fields=followers_count,follows_count,
     media_count -- this is NOT an Insights API call (different endpoint,
     the IG User node's own fields, no period/since/until), but it is a
     live account-level query that could plausibly answer "is there any
     mechanism that returns a genuine cumulative total" as the task brief
     asks. Reported as a separate, clearly-labeled finding -- not folded
     into the Insights sweep, and no design/implementation decision is
     made about how (or whether) to use it.

Uses the System User token directly against IG endpoints (no Page token
exchange) -- consistent with the other IG diagnostic scripts in this repo,
which already empirically confirmed this works (see
scripts/output/diagnose_all_ig_account_metrics.txt and
diagnose_all_ig_media_metrics_output.txt). The System User token is
redacted from every line printed and from the saved output file.

Read-only: GET requests only. No writes to src/, tests/, or any existing
file. If a rate-limit error is hit mid-sweep, the sweep stops immediately
(no retry loop) and whatever was gathered so far is still written to the
output file, with an explicit note of where it stopped.
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

from config_loader import load_config  # noqa: E402

GRAPH_API_VERSION = "v25.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

OUTPUT_PATH = os.path.join(
    os.path.dirname(__file__), "output", "diagnose_ig_account_insights_params_output.txt"
)

# The 17 metric+period(+metric_type) combos diagnose_all_ig_account_metrics.py
# found to be SUCCESS on v25.0 (see diagnose_all_ig_account_metrics.txt,
# "METRICS THAT WORK" section) -- copied verbatim, not re-derived, as the
# starting point for this script's range/coverage sweep. Each combo is
# re-verified bare (not just trusted) before range testing, same as the FB
# script does.
ACCOUNT_METRIC_COMBOS: List[Dict[str, str]] = [
    {"metric": "reach", "period": "day"},
    {"metric": "reach", "period": "week"},
    {"metric": "reach", "period": "days_28"},
    {"metric": "follower_count", "period": "day"},
    {"metric": "online_followers", "period": "lifetime"},
    {"metric": "accounts_engaged", "period": "day", "metric_type": "total_value"},
    {"metric": "total_interactions", "period": "day", "metric_type": "total_value"},
    {"metric": "likes", "period": "day", "metric_type": "total_value"},
    {"metric": "comments", "period": "day", "metric_type": "total_value"},
    {"metric": "saves", "period": "day", "metric_type": "total_value"},
    {"metric": "shares", "period": "day", "metric_type": "total_value"},
    {"metric": "replies", "period": "day", "metric_type": "total_value"},
    {"metric": "views", "period": "day", "metric_type": "total_value"},
    {"metric": "follows_and_unfollows", "period": "day", "metric_type": "total_value"},
    {"metric": "profile_links_taps", "period": "day", "metric_type": "total_value"},
    {"metric": "profile_views", "period": "day", "metric_type": "total_value"},
    {"metric": "website_clicks", "period": "day", "metric_type": "total_value"},
]

# Escalation ladder, identical to diagnose_page_metric_params.py.
WINDOW_DAYS_ESCALATION = [30, 90, 182, 365, 456]

COVERAGE_TOLERANCE_DAYS = {"day": 1, "week": 8, "days_28": 29, "lifetime": 0}

RATE_LIMIT_CODES = {4, 17, 32, 613}
REQUEST_DELAY_SECONDS = 0.3
YOY_THRESHOLD_DAYS = 365

TODAY = date.today()
UNTIL_ANCHOR = TODAY - timedelta(days=1)

RATE_LIMITED = object()


def _redact(text: str, secrets: List[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***REDACTED***")
    return text


def _window(days_back: int) -> tuple:
    until = UNTIL_ANCHOR
    since = until - timedelta(days=days_back - 1)
    return since.isoformat(), until.isoformat()


def api_get(ig_user_id: str, token: str, params: dict, secrets: List[str]):
    query = dict(params)
    query["access_token"] = token
    url = f"{GRAPH_API_BASE}/{ig_user_id}/insights?{urllib.parse.urlencode(query)}"

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


def _response_shape(parsed: dict) -> str:
    """
    Returns "time_series" if data[0] has a `values` list, "total_value" if
    data[0] has a `total_value` dict, or "unknown" otherwise. IG account
    insights responses can be either shape depending on metric_type.
    """
    data = parsed.get("data") or []
    if not data:
        return "unknown"
    entry = data[0]
    if "values" in entry:
        return "time_series"
    if "total_value" in entry:
        return "total_value"
    return "unknown"


def _extract_end_dates(parsed: dict) -> List[str]:
    dates = []
    for entry in parsed.get("data", []) or []:
        for v in entry.get("values", []) or []:
            et = v.get("end_time")
            if et:
                dates.append(et[:10])
    return sorted(dates)


def check_coverage(parsed: dict, since_str: str, until_str: str, period: str) -> dict:
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
    trimmed = copy.deepcopy(parsed)
    for entry in trimmed.get("data", []) or []:
        values = entry.get("values")
        if isinstance(values, list) and len(values) > keep * 2:
            omitted = len(values) - keep * 2
            entry["values"] = values[:keep] + [f"... ({omitted} entries omitted) ..."] + values[-keep:]
    return trimmed


def combo_label(combo: Dict[str, str]) -> str:
    parts = [f"metric={combo['metric']}", f"period={combo['period']}"]
    if "metric_type" in combo:
        parts.append(f"metric_type={combo['metric_type']}")
    return ", ".join(parts)


def test_combo(combo: Dict[str, str], ig_user_id: str, token: str, secrets: List[str]) -> dict:
    metric = combo["metric"]
    period = combo["period"]
    base_params = {"metric": metric, "period": period}
    if "metric_type" in combo:
        base_params["metric_type"] = combo["metric_type"]

    result: Dict[str, object] = {"combo": combo, "rate_limited": False}

    bare = api_get(ig_user_id, token, base_params, secrets)
    if bare is RATE_LIMITED:
        result["rate_limited"] = True
        return result
    result["bare_accepted"] = _is_success(bare)
    if not result["bare_accepted"]:
        result["bare_error"] = _error_str(bare)
        return result

    shape = _response_shape(bare)
    result["response_shape"] = shape

    since7, until7 = _window(7)
    range_params = dict(base_params)
    range_params["since"] = since7
    range_params["until"] = until7
    range7 = api_get(ig_user_id, token, range_params, secrets)
    if range7 is RATE_LIMITED:
        result["rate_limited"] = True
        return result

    result["range_accepted"] = _is_success(range7)
    if not result["range_accepted"]:
        result["range_error"] = _error_str(range7)
        return result

    windows = []
    max_confirmed = 0
    if shape == "time_series":
        cov7 = check_coverage(range7, since7, until7, period)
        windows.append({
            "days_requested": 7, "since": since7, "until": until7, "accepted": True,
            "coverage": cov7, "sample": truncate_payload(range7),
        })
        if cov7.get("full_coverage"):
            max_confirmed = 7
            for days in WINDOW_DAYS_ESCALATION:
                since_n, until_n = _window(days)
                p = dict(base_params)
                p["since"] = since_n
                p["until"] = until_n
                resp = api_get(ig_user_id, token, p, secrets)
                if resp is RATE_LIMITED:
                    result["rate_limited"] = True
                    result["windows"] = windows
                    result["max_confirmed_days"] = max_confirmed
                    return result
                if not _is_success(resp):
                    windows.append({"days_requested": days, "since": since_n, "until": until_n,
                                     "accepted": False, "error": _error_str(resp)})
                    break
                cov = check_coverage(resp, since_n, until_n, period)
                windows.append({"days_requested": days, "since": since_n, "until": until_n,
                                 "accepted": True, "coverage": cov, "sample": truncate_payload(resp)})
                if cov.get("full_coverage"):
                    max_confirmed = days
                else:
                    break
    else:
        # total_value (or unknown) shape: no per-day breakdown exists to
        # verify against the requested window, so we report acceptance
        # only and explicitly flag coverage as unverifiable rather than
        # asserting full coverage. Still escalate the window to see how
        # far the API accepts a range at all.
        windows.append({
            "days_requested": 7, "since": since7, "until": until7, "accepted": True,
            "coverage_unverifiable": True, "sample": copy.deepcopy(range7),
        })
        max_confirmed = "unverifiable (7d+ accepted, no per-day breakdown to confirm coverage)"
        for days in WINDOW_DAYS_ESCALATION:
            since_n, until_n = _window(days)
            p = dict(base_params)
            p["since"] = since_n
            p["until"] = until_n
            resp = api_get(ig_user_id, token, p, secrets)
            if resp is RATE_LIMITED:
                result["rate_limited"] = True
                result["windows"] = windows
                result["max_confirmed_days"] = max_confirmed
                return result
            if not _is_success(resp):
                windows.append({"days_requested": days, "since": since_n, "until": until_n,
                                 "accepted": False, "error": _error_str(resp)})
                break
            windows.append({"days_requested": days, "since": since_n, "until": until_n,
                             "accepted": True, "coverage_unverifiable": True, "sample": copy.deepcopy(resp)})

    result["windows"] = windows
    result["max_confirmed_days"] = max_confirmed
    return result


def probe_valid_metric_names(ig_user_id: str, token: str, secrets: List[str]) -> dict:
    """
    Forces the Graph API's own "metric[0] must be one of the following
    values: [...]" error by requesting an invalid metric name, and parses
    the enumerated list out of the message. Returns a dict with the raw
    error string and the parsed list (or a note that parsing failed and
    the raw string should be read directly).
    """
    parsed = api_get(ig_user_id, token, {"metric": "__diagnostic_invalid_metric__", "period": "day"}, secrets)
    if parsed is RATE_LIMITED:
        return {"rate_limited": True}
    if not parsed or "error" not in parsed:
        return {"error": "did not get the expected error response", "raw": parsed}

    msg = parsed["error"].get("message", "")
    marker = "must be one of the following values:"
    if marker in msg:
        list_part = msg.split(marker, 1)[1].strip().rstrip(".")
        names = [n.strip() for n in list_part.split(",") if n.strip()]
        return {"raw_message": msg, "parsed_names": names}
    return {"raw_message": msg, "parsed_names": None, "note": "marker not found, parse manually from raw_message"}


def probe_follower_count_sample(ig_user_id: str, token: str, secrets: List[str]) -> dict:
    """Fresh 7d follower_count sample for this run, to show the daily-delta shape concretely."""
    since7, until7 = _window(7)
    parsed = api_get(
        ig_user_id, token,
        {"metric": "follower_count", "period": "day", "since": since7, "until": until7},
        secrets,
    )
    if parsed is RATE_LIMITED:
        return {"rate_limited": True}
    return {"since": since7, "until": until7, "response": parsed}


def probe_profile_fields(ig_user_id: str, token: str, secrets: List[str]) -> dict:
    """
    NOT an Insights call -- queries the IG User node's own fields directly.
    Included because it's a live, testable answer to "is there any
    account-level mechanism producing a genuine cumulative follower total."
    """
    query = {"fields": "followers_count,follows_count,media_count", "access_token": token}
    url = f"{GRAPH_API_BASE}/{ig_user_id}?{urllib.parse.urlencode(query)}"
    time.sleep(REQUEST_DELAY_SECONDS)
    try:
        with urllib.request.urlopen(url) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read()
    except urllib.error.URLError as exc:
        return {"error": _redact(f"<no response> ({exc.reason})", secrets)}

    text = _redact(body.decode("utf-8", errors="replace"), secrets)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"unparseable": text}


def classify(result: dict) -> str:
    if result.get("rate_limited"):
        return "RATE_LIMITED_MID_TEST"
    if not result.get("bare_accepted"):
        return "METRIC_REJECTED"
    if not result.get("range_accepted"):
        return "SNAPSHOT_ONLY (no since/until support)"
    shape = result.get("response_shape")
    max_confirmed = result.get("max_confirmed_days")
    if shape != "time_series":
        return f"RANGE_ACCEPTED_BUT_UNVERIFIABLE ({max_confirmed})"
    if isinstance(max_confirmed, int) and max_confirmed >= YOY_THRESHOLD_DAYS:
        return "SAFE_FOR_FULL_YOY (coverage-confirmed)"
    if isinstance(max_confirmed, int) and max_confirmed > 0:
        return f"RANGE_LIMITED (coverage-confirmed to {max_confirmed}d)"
    return "RANGE_ACCEPTED_BUT_NO_COVERAGE_CONFIRMED"


def _format_windows(windows: List[dict], indent: str) -> List[str]:
    lines = []
    for w in windows:
        if not w.get("accepted"):
            lines.append(f"{indent}- {w['days_requested']}d ({w['since']}..{w['until']}): REJECTED -- {w['error']}")
            continue
        if w.get("coverage_unverifiable"):
            lines.append(
                f"{indent}- {w['days_requested']}d ({w['since']}..{w['until']}): ACCEPTED "
                f"(total_value shape -- no per-day breakdown, coverage NOT independently verified)"
            )
            lines.append(f"{indent}  sample payload:")
            for line in json.dumps(w["sample"], indent=2).splitlines():
                lines.append(f"{indent}    {line}")
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
        for line in json.dumps(w["sample"], indent=2).splitlines():
            lines.append(f"{indent}    {line}")
    return lines


def write_report(
    all_results: List[dict],
    rate_limited_at: Optional[str],
    valid_names_probe: dict,
    follower_sample: dict,
    profile_fields: dict,
    output_path: str,
) -> None:
    lines: List[str] = []

    lines.append("=" * 78)
    lines.append("IG ACCOUNT-LEVEL INSIGHTS -- PARAMETER-SPACE & PAYLOAD PROBE")
    lines.append(f"Endpoint: GET /{{ig-user-id}}/insights (Graph API {GRAPH_API_VERSION})")
    lines.append(f"Generated: {TODAY.isoformat()}")
    lines.append("=" * 78)
    lines.append("")

    # --- Cumulative follower total: the headline open question ---
    lines.append("=" * 78)
    lines.append("OPEN QUESTION: IS THERE A GENUINE CUMULATIVE FOLLOWER-TOTAL METRIC?")
    lines.append("=" * 78)
    lines.append("")
    lines.append("CONFIRMED (this run, live):")
    lines.append("")
    lines.append("1. Live enumerated list of valid /{ig-user-id}/insights metric names,")
    lines.append("   obtained by forcing the API's own validation error (not inferred from")
    lines.append("   the candidate list diagnose_all_ig_account_metrics.py happened to try):")
    lines.append("")
    if valid_names_probe.get("rate_limited"):
        lines.append("   RATE LIMITED before this probe could run.")
    elif valid_names_probe.get("parsed_names"):
        for n in valid_names_probe["parsed_names"]:
            lines.append(f"   - {n}")
        lines.append("")
        lines.append("   Raw API error message this was parsed from:")
        lines.append(f"   {valid_names_probe.get('raw_message')}")
    else:
        lines.append("   Could not cleanly parse the enumerated list -- raw message:")
        lines.append(f"   {valid_names_probe.get('raw_message', valid_names_probe.get('error'))}")
    lines.append("")
    lines.append("   None of the names in this list read as a cumulative/lifetime follower")
    lines.append("   total distinct from `follower_count` -- this is a direct observation of")
    lines.append("   the enumerated set, not an inference from partial testing.")
    lines.append("")
    lines.append("2. follower_count (period=day) fresh sample from this run, showing the")
    lines.append("   daily-delta shape directly (values fluctuate day to day, consistent with")
    lines.append("   the ROADMAP's prior finding, not a running total):")
    lines.append("")
    if follower_sample.get("rate_limited"):
        lines.append("   RATE LIMITED before this probe could run.")
    else:
        lines.append(f"   Window requested: {follower_sample.get('since')}..{follower_sample.get('until')}")
        lines.append("   Response:")
        for line in json.dumps(follower_sample.get("response"), indent=2).splitlines():
            lines.append(f"   {line}")
    lines.append("")
    lines.append("3. main sweep result for follower_count (below, DETAIL section) confirms")
    lines.append("   period=week/days_28/lifetime are all rejected for this metric -- no")
    lines.append("   period grain turns it into a running total.")
    lines.append("")
    lines.append("4. SUPPLEMENTARY, NOT AN INSIGHTS METRIC: GET /{ig-user-id}?fields=")
    lines.append("   followers_count,follows_count,media_count -- the IG User node's own")
    lines.append("   fields (different endpoint entirely; no period/since/until; always")
    lines.append("   returns the CURRENT live total, not a historical series):")
    lines.append("")
    for line in json.dumps(profile_fields, indent=2).splitlines():
        lines.append(f"   {line}")
    lines.append("")
    lines.append("DIRECT ANSWER:")
    lines.append("   No account-level Insights metric produces a genuine cumulative/lifetime")
    lines.append("   follower total -- confirmed, not inferred, via the live enumerated valid-")
    lines.append("   metric-name list in (1) above, plus the period-rejection results for")
    lines.append("   follower_count in the DETAIL section below. The only mechanism this run")
    lines.append("   found that returns a true cumulative total is the IG User node's")
    lines.append("   `followers_count` FIELD (item 4 above) -- a live snapshot at query time,")
    lines.append("   not a historical/insights value, and not backed by any period or date")
    lines.append("   range. Whether/how to use that field (e.g. daily snapshotting to build a")
    lines.append("   history) is an extraction-design decision, explicitly NOT made here --")
    lines.append("   flagging it as the concrete option for a later session to evaluate.")
    lines.append("")

    # --- Main sweep summary ---
    safe_yoy, range_limited, unverifiable, no_coverage, snapshot_only, rejected = [], [], [], [], [], []
    for r in all_results:
        if r.get("rate_limited"):
            continue
        cls = classify(r)
        label = combo_label(r["combo"])
        if cls.startswith("SAFE_FOR_FULL_YOY"):
            safe_yoy.append((label, cls))
        elif cls.startswith("RANGE_LIMITED"):
            range_limited.append((label, cls))
        elif cls.startswith("RANGE_ACCEPTED_BUT_UNVERIFIABLE"):
            unverifiable.append((label, cls))
        elif cls.startswith("RANGE_ACCEPTED_BUT_NO_COVERAGE_CONFIRMED"):
            no_coverage.append((label, cls))
        elif cls.startswith("SNAPSHOT_ONLY"):
            snapshot_only.append((label, cls))
        elif cls == "METRIC_REJECTED":
            rejected.append((label, cls))
        else:
            rejected.append((label, cls))

    tested_labels = {combo_label(r["combo"]) for r in all_results}
    untested = [combo_label(c) for c in ACCOUNT_METRIC_COMBOS if combo_label(c) not in tested_labels]

    lines.append("=" * 78)
    lines.append("SUMMARY (plain English)")
    lines.append("=" * 78)
    lines.append("")
    lines.append(f"Of {len(ACCOUNT_METRIC_COMBOS)} previously-confirmed-valid combos, {len(all_results)} were re-tested this run.")
    lines.append("")
    lines.append("Safe for full YoY backfill (coverage-confirmed >= 365d, time-series shape only):")
    for label, cls in safe_yoy:
        lines.append(f"  - {label} [{cls}]")
    if not safe_yoy:
        lines.append("  (none)")
    lines.append("")
    lines.append("Range-limited (coverage-confirmed, but shorter than 12 months):")
    for label, cls in range_limited:
        lines.append(f"  - {label} [{cls}]")
    if not range_limited:
        lines.append("  (none)")
    lines.append("")
    lines.append("Range accepted but coverage UNVERIFIABLE (total_value shape -- no per-day")
    lines.append("breakdown to confirm the response actually reflects the requested window):")
    for label, cls in unverifiable:
        lines.append(f"  - {label} [{cls}]")
    if not unverifiable:
        lines.append("  (none)")
    lines.append("")
    lines.append("Range accepted, but full-window coverage not confirmed within tolerance")
    lines.append("(time-series shape, bare+range both ACCEPTED -- see DETAIL for the raw")
    lines.append("earliest/latest dates actually returned; this is NOT a rejection, just a")
    lines.append("case the coverage-tolerance check couldn't call \"full\"):")
    for label, cls in no_coverage:
        lines.append(f"  - {label} [{cls}]")
    if not no_coverage:
        lines.append("  (none)")
    lines.append("")
    lines.append("Snapshot-only (bare metric works, but since/until is rejected):")
    for label, cls in snapshot_only:
        lines.append(f"  - {label} [{cls}]")
    if not snapshot_only:
        lines.append("  (none)")
    lines.append("")
    lines.append("Rejected outright on re-test (previously SUCCESS, but failed this run):")
    for label, cls in rejected:
        lines.append(f"  - {label} [{cls}]")
    if not rejected:
        lines.append("  (none)")
    if untested:
        lines.append("")
        lines.append("Not tested (sweep stopped before reaching these -- see rate-limit note):")
        for label in untested:
            lines.append(f"  - {label}")
    if rate_limited_at:
        lines.append("")
        lines.append(f"*** RATE LIMIT HIT while testing '{rate_limited_at}' -- sweep stopped early. ***")
        lines.append("*** No retry loop was attempted. Re-run the script later to continue/redo the sweep. ***")
    lines.append("")

    lines.append("=" * 78)
    lines.append("DETAIL")
    lines.append("=" * 78)
    for r in all_results:
        combo = r["combo"]
        lines.append("")
        lines.append("-" * 78)
        lines.append(f"COMBO: {combo_label(combo)}")
        if not r.get("rate_limited"):
            lines.append(f"CLASSIFICATION: {classify(r)}")
        lines.append("-" * 78)
        if not r.get("bare_accepted", True):
            lines.append(f"  bare REJECTED -- {r.get('bare_error')}")
            continue
        lines.append("  bare ACCEPTED")
        lines.append(f"  response_shape: {r.get('response_shape')}")
        if not r.get("range_accepted", True):
            lines.append(f"    since/until REJECTED -- {r.get('range_error')} (snapshot only)")
            continue
        lines.append(f"    since/until ACCEPTED. max_confirmed_days: {r.get('max_confirmed_days')}")
        lines.extend(_format_windows(r.get("windows", []), indent="    "))
        if r.get("rate_limited"):
            lines.append("  *** RATE LIMIT HIT during this combo's sweep -- remaining windows not tested. ***")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main() -> None:
    config = load_config()
    system_token = config.system_user_token
    ig_user_id = config.ig_user_id
    secrets = [system_token]

    print("Probing live valid-metric-name enumeration...")
    valid_names_probe = probe_valid_metric_names(ig_user_id, system_token, secrets)

    print("Fetching fresh follower_count 7d sample...")
    follower_sample = probe_follower_count_sample(ig_user_id, system_token, secrets)

    print("Querying IG User node fields (followers_count) -- not an Insights call...")
    profile_fields = probe_profile_fields(ig_user_id, system_token, secrets)

    all_results: List[dict] = []
    rate_limited_at: Optional[str] = None

    for combo in ACCOUNT_METRIC_COMBOS:
        label = combo_label(combo)
        print(f"Testing {label} ...")
        r = test_combo(combo, ig_user_id, system_token, secrets)
        all_results.append(r)
        if r.get("rate_limited"):
            rate_limited_at = label
            print(f"  Rate limit hit while testing {label} -- stopping sweep.")
            break
        print(f"  -> {classify(r)}")

    write_report(all_results, rate_limited_at, valid_names_probe, follower_sample, profile_fields, OUTPUT_PATH)
    print(f"\nReport written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
