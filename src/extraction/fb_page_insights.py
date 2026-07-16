"""
Facebook Page Insights extraction.

Pulls daily Page-level insights (page_media_view, page_total_media_view_unique,
page_views_total, page_follows) from `/{page-id}/insights` for an explicit
date range and flattens them into one row per day, with metrics as columns.

Row shape chosen: one row per day, metrics as columns (wide format), e.g.
{"date": "2026-06-18", "reach": 123, "impressions": 456, ...}. This was
picked over one-row-per-day-per-metric because each day already has a fixed,
known set of metrics (no sparse/variable metric sets per row), so the wide
form avoids repeating the date N times and is directly CSV/dashboard-ready
without a pivot step.
"""

import csv
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from typing import Dict, Iterable, List, Optional, Sequence, Union

GRAPH_API_VERSION = "v25.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

DEFAULT_METRICS: Sequence[str] = ("page_media_view", "page_total_media_view_unique", "page_views_total", "page_follows")

DateLike = Union[str, date]


class InsightsRequestError(RuntimeError):
    """Raised when the Graph API request fails or returns an error payload."""


def _format_date(value: DateLike) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return value


def _http_get_json(url: str) -> dict:
    """
    Perform the actual HTTP GET and parse the JSON body.

    Isolated into its own function so tests can patch this single seam
    instead of touching urllib directly or making a live network call.

    NOTE: no retry/backoff is implemented here yet. This is where retry
    logic for transient error code 2 (and, if/when IG volume grows, code
    80002) would eventually go -- see docs/meta_graph_api_reference.md
    sec 7 (Known systemic gaps / gotchas). Out of scope for this piece.
    """
    try:
        with urllib.request.urlopen(url) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise InsightsRequestError(
            f"Graph API request failed with HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}"
        ) from exc
    except urllib.error.URLError as exc:
        raise InsightsRequestError(f"Graph API request failed: {exc.reason}") from exc

    payload = json.loads(body)
    if isinstance(payload, dict) and "error" in payload:
        raise InsightsRequestError(f"Graph API returned an error: {payload['error']}")
    return payload


def fetch_page_insights_raw(
    page_id: str,
    access_token: str,
    since: DateLike,
    until: DateLike,
    period: str = "day",
    metrics: Sequence[str] = DEFAULT_METRICS,
    limit: int = 100,
) -> dict:
    """
    Call /{page-id}/insights for the given metrics/period/date range and
    return the raw decoded JSON, with any paginated pages merged into a
    single {"data": [...]} dict.

    Pagination follows `paging.next` (per docs/meta_graph_api_reference.md
    sec 3) and uses `limit`, not `page_size`, since Meta silently ignores
    `page_size`.
    """
    params = {
        "metric": ",".join(metrics),
        "period": period,
        "since": _format_date(since),
        "until": _format_date(until),
        "limit": limit,
        "access_token": access_token,
    }
    url = f"{GRAPH_API_BASE}/{page_id}/insights?{urllib.parse.urlencode(params)}"

    merged_data: List[dict] = []
    next_url: Optional[str] = url
    while next_url:
        page = _http_get_json(next_url)
        merged_data.extend(page.get("data", []))
        next_url = page.get("paging", {}).get("next")

    return {"data": merged_data}


def parse_insights_response(
    raw_response: dict,
    metrics: Sequence[str] = DEFAULT_METRICS,
) -> List[Dict[str, object]]:
    """
    Flatten a raw /{page-id}/insights response into one row per day, with
    each requested metric as a column.

    If a requested metric is absent from the response entirely, every row
    simply omits that column's value (None) rather than raising -- the
    caller still gets rows for the metrics that did come back.

    Known gap (not handled here): an empty/missing insights value for a
    given day is indistinguishable from a real zero for that day. See
    docs/meta_graph_api_reference.md sec 7. Flagging only; not solved here.
    """
    rows_by_date: Dict[str, Dict[str, object]] = {}

    for metric_entry in raw_response.get("data", []):
        metric_name = metric_entry.get("name")
        if metric_name not in metrics:
            continue
        for value_entry in metric_entry.get("values", []):
            end_time = value_entry.get("end_time", "")
            row_date = end_time[:10] if end_time else None
            if row_date is None:
                continue
            row = rows_by_date.setdefault(row_date, {"date": row_date})
            row[metric_name] = value_entry.get("value")

    return [rows_by_date[d] for d in sorted(rows_by_date)]


def extract_page_insights(
    page_id: str,
    access_token: str,
    since: DateLike,
    until: DateLike,
    period: str = "day",
    metrics: Sequence[str] = DEFAULT_METRICS,
    limit: int = 100,
) -> List[Dict[str, object]]:
    """Fetch and parse FB Page daily insights for an explicit date range."""
    raw = fetch_page_insights_raw(
        page_id=page_id,
        access_token=access_token,
        since=since,
        until=until,
        period=period,
        metrics=metrics,
        limit=limit,
    )
    return parse_insights_response(raw, metrics=metrics)


def write_insights_csv(
    rows: Iterable[Dict[str, object]],
    output_path: str,
    metrics: Sequence[str] = DEFAULT_METRICS,
) -> None:
    """Write extracted rows to a CSV file with columns: date, <metrics...>."""
    fieldnames = ["date", *metrics]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
