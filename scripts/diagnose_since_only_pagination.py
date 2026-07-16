"""
Diagnostic script: since-only query behavior and true historical depth probe.

The earlier parameter-space diagnostic (diagnose_page_metric_params.py)
found a hard rejection at ~90+ day spans, but that test always passed
`since` AND `until` together. A manual Graph API Explorer check found
that omitting `until` entirely (passing `since` alone) returns a much
larger continuous window -- roughly 560 days in one response for
page_media_view/period=day -- and the response's own paging.next /
paging.previous cursors show the API auto-paginating in ~560-day
increments when `until` is left to its default.

This script:
  1. For a small representative set of metrics (page_media_view as the
     known-working baseline, page_video_views for the video family,
     page_post_engagements for engagement, page_views_total), and for
     ALL FOUR periods (day, week, days_28, lifetime), issues a
     since-only query (since present, until omitted) and records:
       - the date range actually returned in that single call,
       - the paging.next / paging.previous since/until values and the
         implied window size (in days) each cursor step represents.
  2. For page_media_view/day specifically, follows the paging.previous
     cursor backward repeatedly to find the true historical depth --
     until a response has no data, an explicit rejection occurs, or 3+
     years of backward walking is reached.

Read-only: makes live Graph API GET calls against /{page-id}/insights
only. No writes to src/, tests/, or .env. Uses the exchanged Page access
token (src/extraction/auth.get_page_access_token), same as the other
diagnostic scripts in this directory.

Redaction: the access_token query parameter is stripped from EVERY
string written to disk or printed, including inside embedded
paging.next / paging.previous URLs -- this is the specific gap that
motivated this script (a manual Explorer session leaked a live token
inside an un-redacted paging URL). See _redact() and redact_url(),
and the self-test in _selftest_redaction() run at import time before
any live call is made.

If the Graph API returns a rate-limit error mid-run, the run stops
immediately (no retry loop) and whatever was gathered so far is still
written to the output file, with an explicit note marking where it
stopped. If a call fails with an auth error (code 190), this is treated
as an expected consequence of the manual Explorer token being rotated
--- not an API bug --- and the run stops immediately with a clear note,
rather than guessing at a replacement token.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "extraction"))

from auth import get_page_access_token  # noqa: E402
from config_loader import load_config  # noqa: E402

GRAPH_API_VERSION = "v25.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "output", "diagnose_since_only_pagination_output.txt")

# Representative set per task brief: page_media_view is the manually
# spot-checked baseline, page_video_views covers the video family,
# page_post_engagements covers reaction/engagement, page_views_total is
# tested separately.
METRICS = [
    "page_media_view",
    "page_video_views",
    "page_post_engagements",
    "page_views_total",
]

PERIODS = ["day", "week", "days_28", "lifetime"]

# Meta Graph API error codes associated with rate limiting / throttling.
RATE_LIMIT_CODES = {4, 17, 32, 613}
# OAuthException -- invalid/expired access token.
AUTH_ERROR_CODES = {190}

REQUEST_DELAY_SECONDS = 0.3

TODAY = date.today()
UNTIL_ANCHOR = TODAY - timedelta(days=1)  # yesterday; avoids partial current-day data
# Anchor "since" far enough back (3 years) that any auto-paginated
# window size the API chooses will be fully observable in one call,
# without this script assuming or asserting what that size should be.
SINCE_ANCHOR = TODAY - timedelta(days=3 * 365)

# Safety cap on backward-walk steps, independent of the 3-year target --
# guards against an unexpectedly small per-step window turning the walk
# into an unbounded loop.
MAX_BACKWARD_STEPS = 40
BACKWARD_TARGET = TODAY - timedelta(days=3 * 365)


def _redact(text: str, secrets: List[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***REDACTED***")
    return text


def redact_url(url: Optional[str], secrets: List[str]) -> Optional[str]:
    """
    Redact the access_token query parameter out of a URL string
    specifically (in addition to the blanket secret-substring replace in
    _redact, which is the primary defense). Rebuilds the query string
    with access_token's value replaced rather than relying solely on
    substring matching, so redaction holds even if the token value were
    ever percent-encoded differently than the raw secret string.
    """
    if not url:
        return url
    url = _redact(url, secrets)
    try:
        parsed = urllib.parse.urlsplit(url)
        query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        new_pairs = [
            (k, "***REDACTED***" if k == "access_token" else v) for k, v in query_pairs
        ]
        new_query = urllib.parse.urlencode(new_pairs, safe="*")
        return urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, new_query, parsed.fragment)
        )
    except Exception:
        # If URL parsing itself fails for any reason, fall back to the
        # blanket string-replace result computed above -- never return
        # the raw, unparsed URL.
        return url


def _selftest_redaction() -> None:
    """
    Verify redact_url() actually strips a token-shaped value out of a
    paging-style URL BEFORE any live call is made or any output is
    written. Raises AssertionError (halting the script) if redaction
    does not hold.
    """
    fake_token = "EAAFAKETOKENVALUE1234567890abcdefTEST"
    sample = (
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/12345/insights"
        f"?access_token={fake_token}&since=1783062000&until=1783580400"
        f"&metric=page_media_view&period=day"
    )
    redacted = redact_url(sample, [fake_token])
    assert fake_token not in redacted, "redact_url() failed to strip a token-shaped value"
    redacted_qs = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(redacted).query))
    assert redacted_qs.get("access_token") == "***REDACTED***", "redact_url() did not mark the field as redacted"

    # Also verify the blanket _redact() catches it independently, since
    # that is the fallback path if URL parsing ever fails.
    blanket = _redact(sample, [fake_token])
    assert fake_token not in blanket, "_redact() failed to strip a token-shaped value"


def api_get(url: str, secrets: List[str]):
    """
    GET a fully-formed Graph API URL (either freshly built from params,
    or taken directly from a paging.next/previous cursor). Returns the
    RAW parsed JSON dict (which may itself carry an "error" key -- check
    with _is_rate_limited / _is_auth_error / _is_success), or None if
    the response wasn't parseable JSON or the request failed at the
    network layer.

    IMPORTANT: the returned dict is intentionally NOT redacted -- its
    embedded paging.next/paging.previous URLs still carry the live
    access_token, because callers need that raw URL to follow the
    cursor for the next request (walk_backward). Redacting the response
    body before parsing would corrupt those URLs into an unusable
    "***REDACTED***" token string, which is exactly what happened during
    development of this script (a "Cannot parse access token" error on
    the second hop, not a real auth failure). Everything that leaves
    this module bound for print()/write_report() MUST go through
    _redact()/redact_url() explicitly at the point of output -- never
    rely on the dict itself being pre-redacted.
    """
    time.sleep(REQUEST_DELAY_SECONDS)
    try:
        with urllib.request.urlopen(url) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read()
    except urllib.error.URLError as exc:
        print(_redact(f"  <no response> ({exc.reason})", secrets))
        return None

    raw_text = body.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        print(f"  <unparseable response> {_redact(raw_text, secrets)}")
        return None

    return parsed


def _is_rate_limited(parsed: Optional[dict]) -> bool:
    if not parsed or "error" not in parsed:
        return False
    error = parsed["error"]
    if error.get("code") in RATE_LIMIT_CODES:
        return True
    msg = (error.get("message") or "").lower()
    return "rate limit" in msg or "too many calls" in msg


def _is_auth_error(parsed: Optional[dict]) -> bool:
    if not parsed or "error" not in parsed:
        return False
    return parsed["error"].get("code") in AUTH_ERROR_CODES


def _is_success(parsed: Optional[dict]) -> bool:
    return bool(parsed) and "data" in parsed and "error" not in parsed


def _error_str(parsed: Optional[dict], secrets: Optional[List[str]] = None) -> str:
    """
    Render an error dict for display. Redacts against `secrets` if
    given -- defense in depth in case an error message ever happened to
    echo back part of the request URL; `parsed` may be the raw,
    unredacted dict from api_get().
    """
    if not parsed:
        return "<no response / unparseable>"
    if "error" in parsed:
        e = parsed["error"]
        s = f"code={e.get('code')} subcode={e.get('error_subcode')} msg={e.get('message')}"
        return _redact(s, secrets) if secrets else s
    return "<response has neither data nor error>"


def build_url(page_id: str, params: dict, token: str) -> str:
    query = dict(params)
    query["access_token"] = token
    return f"{GRAPH_API_BASE}/{page_id}/insights?{urllib.parse.urlencode(query)}"


def _extract_end_dates(parsed: dict) -> List[str]:
    dates = []
    for entry in parsed.get("data", []) or []:
        for v in entry.get("values", []) or []:
            et = v.get("end_time")
            if et:
                dates.append(et[:10])
    return sorted(dates)


def _parse_paging_cursor(url: Optional[str]) -> Optional[Dict[str, object]]:
    """
    Parse since/until out of a paging.next / paging.previous URL. These
    are observed to be Unix epoch seconds (not ISO dates) in this API's
    paging cursors. Returns None if the URL is absent or doesn't carry
    both params.
    """
    if not url:
        return None
    parsed = urllib.parse.urlsplit(url)
    qs = dict(urllib.parse.parse_qsl(parsed.query))
    since_raw, until_raw = qs.get("since"), qs.get("until")
    if since_raw is None or until_raw is None:
        return None
    try:
        since_i, until_i = int(since_raw), int(until_raw)
    except ValueError:
        return {"since_raw": since_raw, "until_raw": until_raw, "delta_days": None}
    delta_days = (until_i - since_i) / 86400
    return {
        "since_epoch": since_i,
        "until_epoch": until_i,
        "since_iso": date.fromtimestamp(since_i).isoformat(),
        "until_iso": date.fromtimestamp(until_i).isoformat(),
        "delta_days": round(delta_days, 3),
    }


def test_since_only(
    metric: str, period: str, page_id: str, token: str, secrets: List[str], since_anchor: date = SINCE_ANCHOR
) -> dict:
    params = {"metric": metric, "period": period, "since": since_anchor.isoformat()}
    url = build_url(page_id, params, token)
    parsed = api_get(url, secrets)

    if _is_rate_limited(parsed):
        return {"metric": metric, "period": period, "status": "rate_limited"}
    if _is_auth_error(parsed):
        return {"metric": metric, "period": period, "status": "auth_error", "error": _error_str(parsed, secrets)}
    if not _is_success(parsed):
        return {"metric": metric, "period": period, "status": "rejected", "error": _error_str(parsed, secrets)}

    dates = _extract_end_dates(parsed)
    paging = parsed.get("paging", {}) or {}
    next_cursor = _parse_paging_cursor(paging.get("next"))
    prev_cursor = _parse_paging_cursor(paging.get("previous"))

    return {
        "metric": metric,
        "period": period,
        "status": "ok",
        "requested_since": since_anchor.isoformat(),
        "n_points": len(dates),
        "earliest_returned": dates[0] if dates else None,
        "latest_returned": dates[-1] if dates else None,
        "returned_span_days": (
            (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days if dates else None
        ),
        "paging_next": next_cursor,
        "paging_previous": prev_cursor,
        "paging_next_url_redacted": redact_url(paging.get("next"), secrets),
        "paging_previous_url_redacted": redact_url(paging.get("previous"), secrets),
        # Raw (unredacted, live-token-bearing) cursor URLs, kept only in
        # memory to chain the backward walk. Never pass these into
        # write_report / any line that gets written to disk.
        "_raw_paging_previous_url": paging.get("previous"),
        "_raw_paging_next_url": paging.get("next"),
    }


def walk_backward(baseline: dict, secrets: List[str]) -> dict:
    """
    Follow paging.previous repeatedly, starting from the raw
    paging.previous cursor URL of an already-fetched since-only baseline
    response (`baseline`, e.g. the page_media_view/day entry from
    test_since_only). Each step is the API's own literal cursor URL --
    not a range this script constructs itself -- so this walk never
    re-issues the already-established since+until wide-range rejection
    test; it only observes what the API's own pagination produces.
    """
    metric, period = baseline["metric"], baseline["period"]
    steps: List[dict] = [
        {
            "step": 0,
            "status": "ok",
            "n_points": baseline["n_points"],
            "earliest_returned": baseline["earliest_returned"],
            "latest_returned": baseline["latest_returned"],
            "paging_previous_url_redacted": baseline["paging_previous_url_redacted"],
            "paging_previous_cursor": baseline["paging_previous"],
        }
    ]
    current_url = baseline["_raw_paging_previous_url"]
    stop_reason = None
    step_i = 1

    while True:
        if current_url is None:
            stop_reason = "no_previous_cursor"
            break
        if step_i > MAX_BACKWARD_STEPS:
            stop_reason = "max_backward_steps_reached"
            break

        parsed = api_get(current_url, secrets)

        if _is_rate_limited(parsed):
            stop_reason = "rate_limited"
            break
        if _is_auth_error(parsed):
            stop_reason = "auth_error"
            steps.append({"step": step_i, "status": "auth_error", "error": _error_str(parsed, secrets)})
            break
        if not _is_success(parsed):
            stop_reason = "rejected"
            err = (parsed or {}).get("error", {})
            steps.append(
                {
                    "step": step_i,
                    "status": "rejected",
                    "error": _error_str(parsed, secrets),
                    "error_code": err.get("code"),
                    "error_subcode": err.get("error_subcode"),
                    # The URL that was rejected, so we can inspect its
                    # since/until width (redacted) rather than just the
                    # error text.
                    "rejected_cursor": _parse_paging_cursor(current_url),
                }
            )
            break

        dates = _extract_end_dates(parsed)
        paging = parsed.get("paging", {}) or {}
        prev_url = paging.get("previous")
        prev_cursor = _parse_paging_cursor(prev_url)

        step_record = {
            "step": step_i,
            "status": "ok",
            "n_points": len(dates),
            "earliest_returned": dates[0] if dates else None,
            "latest_returned": dates[-1] if dates else None,
            "paging_previous_url_redacted": redact_url(prev_url, secrets),
            "paging_previous_cursor": prev_cursor,
        }
        steps.append(step_record)

        if not dates:
            stop_reason = "empty_values"
            break

        earliest_d = date.fromisoformat(dates[0])
        if earliest_d <= BACKWARD_TARGET:
            stop_reason = "reached_3yr_target_with_data_present"
            break
        if not prev_url:
            stop_reason = "no_previous_cursor"
            break

        current_url = prev_url  # raw URL (with live token) kept only in memory, never written
        step_i += 1

    return {"metric": metric, "period": period, "steps": steps, "stop_reason": stop_reason}


def _fmt_cursor(c: Optional[dict]) -> str:
    if c is None:
        return "(absent)"
    if c.get("delta_days") is None:
        return f"since_raw={c.get('since_raw')} until_raw={c.get('until_raw')} (non-numeric, could not compute delta)"
    return (
        f"since={c['since_iso']} until={c['until_iso']} "
        f"(delta={c['delta_days']}d)"
    )


def write_report(
    since_only_results: List[dict],
    backward_result: Optional[dict],
    stopped_note: Optional[str],
    output_path: str,
    control_result: Optional[dict] = None,
) -> None:
    lines: List[str] = []

    lines.append("=" * 78)
    lines.append("SINCE-ONLY QUERY BEHAVIOR (since present, until omitted)")
    lines.append("=" * 78)
    lines.append("")
    lines.append(f"Requested since anchor for all since-only calls: {SINCE_ANCHOR.isoformat()} (~3 years back)")
    lines.append("")

    deltas_seen = []
    for r in since_only_results:
        lines.append("-" * 78)
        lines.append(f"metric={r['metric']} period={r['period']}")
        lines.append("-" * 78)
        if r["status"] == "rate_limited":
            lines.append("  RATE LIMITED -- stopped before this combo completed.")
            continue
        if r["status"] == "auth_error":
            lines.append(f"  AUTH ERROR -- {r.get('error')} (treated as expected token rotation; run stopped)")
            continue
        if r["status"] == "rejected":
            lines.append(f"  REJECTED -- {r['error']}")
            continue

        lines.append(
            f"  single-call coverage: {r['n_points']} points, "
            f"earliest={r['earliest_returned']}, latest={r['latest_returned']}, "
            f"span={r['returned_span_days']}d"
        )
        lines.append(f"  paging.previous: {_fmt_cursor(r['paging_previous'])}")
        lines.append(f"  paging.next:     {_fmt_cursor(r['paging_next'])}")
        for c in (r["paging_previous"], r["paging_next"]):
            if c and c.get("delta_days") is not None:
                deltas_seen.append(c["delta_days"])
        lines.append(f"  paging.previous URL (redacted): {r['paging_previous_url_redacted']}")
        lines.append(f"  paging.next URL (redacted):     {r['paging_next_url_redacted']}")
        lines.append("")

    lines.append("=" * 78)
    lines.append("AUTO-PAGE WINDOW SIZE -- CONSISTENCY CHECK (at a fixed since anchor)")
    lines.append("=" * 78)
    lines.append("")
    lines.append(
        "IMPORTANT CAVEAT: every combo above was tested with the SAME since anchor "
        f"({SINCE_ANCHOR.isoformat()}). A single shared delta across all of them is consistent with EITHER "
        "(a) a fixed auto-page window size, OR (b) since-only simply returning everything from `since` "
        "through 'now', with no fixed window at all -- since both explanations predict identical results "
        "when since is held constant. See the CONTROL TEST section below, which varies `since` to "
        "distinguish these two explanations. Do not read the word CONFIRMED below as ruling out (b)."
    )
    lines.append("")
    if deltas_seen:
        unique_deltas = sorted(set(deltas_seen))
        lines.append(f"Distinct deltas (days) observed across all tested combos at this fixed since anchor: {unique_deltas}")
        if len(unique_deltas) == 1:
            lines.append(
                f"CONFIRMED (at this fixed since anchor only): all tested metric/period combos with a "
                f"numeric paging cursor show the same ~{unique_deltas[0]}d delta."
            )
        else:
            lines.append(
                "NOT CONSISTENT: delta varies across tested combos even at this fixed since anchor -- see "
                "per-combo detail above. Do not generalize a single figure across metrics/periods from this data."
            )
    else:
        lines.append("No numeric paging cursors were observed in any successful since-only response.")
    lines.append("")
    lines.append(
        "Baseline for comparison (from the manual Explorer check that motivated this session): "
        "~560 days observed for page_media_view / period=day."
    )

    lines.append("")
    lines.append("=" * 78)
    lines.append("CONTROL TEST -- does the window scale with the requested `since`, or is it fixed?")
    lines.append("=" * 78)
    lines.append("")
    if control_result is None:
        lines.append("Control test was not run (see stop note below, if any).")
    elif control_result["status"] != "ok":
        lines.append(f"Control test did not complete: status={control_result['status']} error={control_result.get('error')}")
    else:
        baseline_3yr = next(
            (r for r in since_only_results if r["metric"] == "page_media_view" and r["period"] == "day"), None
        )
        lines.append(
            f"page_media_view/day, since={control_result['requested_since']} (~560 days back): "
            f"returned span={control_result['returned_span_days']}d "
            f"(earliest={control_result['earliest_returned']}, latest={control_result['latest_returned']})"
        )
        if baseline_3yr and baseline_3yr["status"] == "ok":
            lines.append(
                f"page_media_view/day, since={baseline_3yr['requested_since']} (~3 years back): "
                f"returned span={baseline_3yr['returned_span_days']}d "
                f"(earliest={baseline_3yr['earliest_returned']}, latest={baseline_3yr['latest_returned']})"
            )
        lines.append("")
        if control_result["returned_span_days"] is not None:
            # Compare the returned span to the distance from the control
            # since-anchor to "now" -- if they match, the response is
            # simply "since through now", not a fixed-size window.
            days_since_to_now = (UNTIL_ANCHOR - (TODAY - timedelta(days=560))).days
            if abs(control_result["returned_span_days"] - days_since_to_now) <= 2:
                lines.append(
                    f"FINDING: the ~560-day since anchor returned a span of "
                    f"{control_result['returned_span_days']}d, matching since-to-now "
                    f"({days_since_to_now}d) rather than the ~{deltas_seen[0] if deltas_seen else '?'}d delta "
                    "seen with the 3-year anchor. This supports explanation (b): since-only queries return "
                    "everything from `since` through 'now', not a fixed-size auto-page window. The "
                    "manually-observed ~560-day figure was very likely just a function of the `since` date "
                    "used in that manual check, not a fixed API page size."
                )
            else:
                lines.append(
                    f"FINDING: the ~560-day since anchor returned a span of "
                    f"{control_result['returned_span_days']}d, which does NOT simply match since-to-now "
                    f"({days_since_to_now}d). This does not cleanly support explanation (b) either -- "
                    "treat the window-size mechanism as unresolved rather than assuming a fixed constant."
                )
    lines.append("")
    lines.append("=" * 78)
    lines.append("BACKWARD WALK -- TRUE HISTORICAL DEPTH")
    lines.append("=" * 78)
    lines.append("")
    if backward_result is None:
        lines.append("Backward walk was not run (see stop note below, if any).")
    else:
        lines.append(f"metric={backward_result['metric']} period={backward_result['period']}")
        lines.append(f"stop_reason={backward_result['stop_reason']}")
        lines.append("")
        for s in backward_result["steps"]:
            if s["status"] != "ok":
                lines.append(f"  step {s['step']}: {s['status']} -- {s.get('error')}")
                continue
            lines.append(
                f"  step {s['step']}: {s['n_points']} points, "
                f"earliest={s['earliest_returned']}, latest={s['latest_returned']}"
            )
            lines.append(f"    paging.previous: {_fmt_cursor(s['paging_previous_cursor'])}")
            lines.append(f"    paging.previous URL (redacted): {s['paging_previous_url_redacted']}")
        lines.append("")
        reason = backward_result["stop_reason"]
        if reason == "empty_values":
            last_ok = next((s for s in reversed(backward_result["steps"]) if s["status"] == "ok"), None)
            if last_ok:
                lines.append(
                    f"FINDING: data stops being returned once the walk reaches back past "
                    f"{last_ok['earliest_returned']} -- the response at that point had ACCEPTED status but "
                    f"an empty values array. Data for {backward_result['metric']}/{backward_result['period']} "
                    f"appears to go back to approximately {last_ok['earliest_returned']}."
                )
        elif reason == "rejected":
            last_ok = next((s for s in reversed(backward_result["steps"]) if s["status"] == "ok"), None)
            rejected_step = next((s for s in backward_result["steps"] if s["status"] == "rejected"), None)
            is_known_width_cap = (
                rejected_step is not None
                and rejected_step.get("error_code") == 100
                and rejected_step.get("error_subcode") == 1504016
            )
            if last_ok:
                if is_known_width_cap:
                    cursor = (rejected_step or {}).get("rejected_cursor") or {}
                    lines.append(
                        f"FINDING: the walk was rejected past {last_ok['earliest_returned']} with "
                        f"code=100 subcode=1504016 -- the SAME error signature already established (in "
                        f"diagnose_page_metric_params.py's output) for since+until ranges wider than "
                        f"~90 days. The rejected cursor itself requested a "
                        f"{cursor.get('delta_days', '?')}d wide since+until range "
                        f"({cursor.get('since_iso', '?')}..{cursor.get('until_iso', '?')}), reconstructed "
                        f"verbatim from the API's own paging.previous URL. "
                        f"CAVEAT -- this rejection does NOT confirm data stops existing before "
                        f"{last_ok['earliest_returned']}; it more likely just means the API's own "
                        f"auto-generated paging.previous cursor is itself subject to the same range-width "
                        f"cap as a manually-constructed since+until query, making naive cursor-following an "
                        f"unreliable way to probe historical depth beyond the first hop. True historical "
                        f"depth beyond {last_ok['earliest_returned']} remains UNKNOWN from this walk -- "
                        f"confirmed only: since-only queries return real data back to at least "
                        f"{last_ok['earliest_returned']} in a single call (see the since-only results above)."
                    )
                else:
                    lines.append(
                        f"FINDING: the walk was explicitly rejected past "
                        f"{last_ok['earliest_returned']} with {rejected_step.get('error') if rejected_step else 'an error'} "
                        f"-- this does not match the previously-established ~90-day since+until width-cap "
                        f"signature (code=100 subcode=1504016), so unlike that known case this looks like a "
                        f"genuine rejection at this specific point rather than a range-width artifact. Data "
                        f"for {backward_result['metric']}/{backward_result['period']} appears to go back to "
                        f"approximately {last_ok['earliest_returned']}."
                    )
        elif reason == "reached_3yr_target_with_data_present":
            lines.append(
                f"FINDING: walked back 3+ years (target {BACKWARD_TARGET.isoformat()}) and data was STILL "
                f"present at that point. True historical depth beyond 3 years is UNKNOWN -- this walk did not "
                f"reach a boundary."
            )
        elif reason == "no_previous_cursor":
            last_ok = next((s for s in reversed(backward_result["steps"]) if s["status"] == "ok"), None)
            if last_ok:
                lines.append(
                    f"FINDING: paging.previous cursor disappeared after reaching "
                    f"{last_ok['earliest_returned']} (response still had data, but no further cursor to "
                    f"follow). This may itself mark the historical boundary, or may be an API quirk -- "
                    f"treat as inconclusive, not a confirmed boundary."
                )
        elif reason == "auth_error":
            lines.append("FINDING: walk stopped on an auth error -- see note below, not a data-boundary finding.")
        elif reason == "rate_limited":
            lines.append("FINDING: walk stopped on a rate limit -- see note below, not a data-boundary finding.")
        elif reason == "max_backward_steps_reached":
            lines.append(
                f"FINDING: hit the {MAX_BACKWARD_STEPS}-step safety cap before reaching either a data "
                f"boundary or the 3-year target. True historical depth is UNKNOWN from this run."
            )

    if stopped_note:
        lines.append("")
        lines.append("=" * 78)
        lines.append("RUN STOPPED EARLY")
        lines.append("=" * 78)
        lines.append(stopped_note)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main() -> None:
    _selftest_redaction()
    print("Redaction self-test passed.")

    config = load_config()
    system_token = config.system_user_token
    page_id = config.fb_page_id
    page_token = get_page_access_token(system_token, page_id)
    secrets = [system_token, page_token]

    since_only_results: List[dict] = []
    backward_result: Optional[dict] = None
    stopped_note: Optional[str] = None

    for metric in METRICS:
        for period in PERIODS:
            print(f"since-only: {metric} / {period} ...")
            r = test_since_only(metric, period, page_id, page_token, secrets)
            since_only_results.append(r)
            if r["status"] == "rate_limited":
                stopped_note = f"Rate limit hit while testing since-only {metric}/{period}. Stopping immediately."
                print(f"  {stopped_note}")
                write_report(since_only_results, backward_result, stopped_note, OUTPUT_PATH)
                print(f"Partial report written to {OUTPUT_PATH}")
                return
            if r["status"] == "auth_error":
                stopped_note = (
                    f"Auth error (code 190) hit while testing since-only {metric}/{period}. "
                    "Treating as an expected consequence of the manual Explorer token being rotated/"
                    "invalidated -- not troubleshooting further. Stopping run."
                )
                print(f"  {stopped_note}")
                write_report(since_only_results, backward_result, stopped_note, OUTPUT_PATH)
                print(f"Partial report written to {OUTPUT_PATH}")
                return
            print(f"  -> {r['status']}")

    # Control test: the initial sweep uses a since anchor ~3 years back
    # for every combo, and every combo came back with the SAME ~1094d
    # window (== SINCE_ANCHOR-to-today). That's consistent with two
    # different explanations that this sweep alone can't distinguish:
    #   (a) the API has a fixed auto-page window size (this session's
    #       working assumption per the task brief), or
    #   (b) since-only just returns everything from `since` to "now",
    #       with no fixed window at all -- and the manually-observed
    #       ~560d figure was itself just a function of whatever `since`
    #       the manual check happened to use.
    # Re-run the baseline combo with a materially different since anchor
    # (~560 days back, matching the manual check's ballpark) to see
    # which explanation the data supports.
    print("Control test: page_media_view / day with a ~560-day since anchor ...")
    control_anchor = TODAY - timedelta(days=560)
    control_result = test_since_only(
        "page_media_view", "day", page_id, page_token, secrets, since_anchor=control_anchor
    )
    if control_result["status"] == "rate_limited":
        stopped_note = "Rate limit hit during the ~560-day control test. Stopping immediately."
        print(f"  {stopped_note}")
        write_report(since_only_results, backward_result, stopped_note, OUTPUT_PATH, control_result)
        print(f"Partial report written to {OUTPUT_PATH}")
        return
    if control_result["status"] == "auth_error":
        stopped_note = (
            "Auth error (code 190) hit during the ~560-day control test. Treating as an expected "
            "consequence of the manual Explorer token being rotated/invalidated. Stopping run."
        )
        print(f"  {stopped_note}")
        write_report(since_only_results, backward_result, stopped_note, OUTPUT_PATH, control_result)
        print(f"Partial report written to {OUTPUT_PATH}")
        return
    print(f"  -> {control_result['status']}")

    print("Starting backward walk on page_media_view / day ...")
    baseline = next(r for r in since_only_results if r["metric"] == "page_media_view" and r["period"] == "day")
    backward_result = walk_backward(baseline, secrets)
    if backward_result["stop_reason"] == "rate_limited":
        stopped_note = "Rate limit hit during backward walk on page_media_view/day. Stopping immediately."
        print(f"  {stopped_note}")
    elif backward_result["stop_reason"] == "auth_error":
        stopped_note = (
            "Auth error (code 190) hit during backward walk. Treating as an expected consequence of the "
            "manual Explorer token being rotated/invalidated. Stopping run."
        )
        print(f"  {stopped_note}")
    else:
        print(f"  -> stop_reason={backward_result['stop_reason']}")

    write_report(since_only_results, backward_result, stopped_note, OUTPUT_PATH, control_result)
    print(f"\nReport written to {OUTPUT_PATH}")

    # Explicit post-write verification that no secret substring survived
    # into the output file, per the task's redaction constraint.
    with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
        written = f.read()
    leaked = [s for s in secrets if s and s in written]
    if leaked:
        print(
            f"*** WARNING: {len(leaked)} secret value(s) were found in the written output file! "
            "This should never happen -- investigate immediately. ***"
        )
    else:
        print("Post-write verification: no secret token substrings found in output file.")


if __name__ == "__main__":
    main()
