import os
import sys

import pytest

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "src", "extraction")
)

from fb_page_insights import (  # noqa: E402
    DAYS_28_METRICS,
    DEFAULT_METRICS,
    extract_page_insights,
    fetch_page_insights_raw,
    merge_insights_rows,
    parse_insights_response,
)

REALISTIC_RESPONSE = {
    "data": [
        {
            "name": "page_media_view",
            "period": "day",
            "values": [
                {"value": 100, "end_time": "2026-06-18T07:00:00+0000"},
                {"value": 110, "end_time": "2026-06-19T07:00:00+0000"},
            ],
        },
        {
            "name": "page_total_media_view_unique",
            "period": "day",
            "values": [
                {"value": 200, "end_time": "2026-06-18T07:00:00+0000"},
                {"value": 210, "end_time": "2026-06-19T07:00:00+0000"},
            ],
        },
        {
            "name": "page_views_total",
            "period": "day",
            "values": [
                {"value": 5, "end_time": "2026-06-18T07:00:00+0000"},
                {"value": 7, "end_time": "2026-06-19T07:00:00+0000"},
            ],
        },
        {
            "name": "page_follows",
            "period": "day",
            "values": [
                {"value": 1000, "end_time": "2026-06-18T07:00:00+0000"},
                {"value": 1001, "end_time": "2026-06-19T07:00:00+0000"},
            ],
        },
        {
            "name": "page_post_engagements",
            "period": "day",
            "values": [
                {"value": 50, "end_time": "2026-06-18T07:00:00+0000"},
                {"value": 75, "end_time": "2026-06-19T07:00:00+0000"},
            ],
        },
    ],
    "paging": {},
}


def test_parses_realistic_response_into_expected_rows():
    rows = parse_insights_response(REALISTIC_RESPONSE)

    assert rows == [
        {
            "date": "2026-06-17",
            "page_media_view": 100,
            "page_total_media_view_unique": 200,
            "page_views_total": 5,
            "page_follows": 1000,
            "page_post_engagements": 50,
        },
        {
            "date": "2026-06-18",
            "page_media_view": 110,
            "page_total_media_view_unique": 210,
            "page_views_total": 7,
            "page_follows": 1001,
            "page_post_engagements": 75,
        },
    ]


def test_handles_response_missing_one_metric_without_crashing():
    response_missing_follower_count = {
        "data": [m for m in REALISTIC_RESPONSE["data"] if m["name"] != "page_follows"],
        "paging": {},
    }

    rows = parse_insights_response(response_missing_follower_count)

    assert len(rows) == 2
    for row in rows:
        assert "page_follows" not in row
        assert row["page_media_view"] is not None
        assert row["page_total_media_view_unique"] is not None
        assert row["page_views_total"] is not None


def test_fetch_passes_correct_date_range_and_params(monkeypatch):
    captured_urls = []

    def fake_http_get_json(url):
        captured_urls.append(url)
        return {"data": [], "paging": {}}

    monkeypatch.setattr("fb_page_insights._http_get_json", fake_http_get_json)

    fetch_page_insights_raw(
        page_id="page-123",
        access_token="token-abc",
        since="2026-06-12",
        until="2026-06-18",
        period="day",
        metrics=DEFAULT_METRICS,
        limit=100,
    )

    assert len(captured_urls) == 1
    url = captured_urls[0]
    assert "/page-123/insights" in url
    assert "since=2026-06-12" in url
    assert "until=2026-06-18" in url
    assert "period=day" in url
    assert "limit=100" in url
    assert "metric=page_media_view%2Cpage_total_media_view_unique%2Cpage_views_total%2Cpage_follows%2Cpage_post_engagements" in url


REALISTIC_DAYS_28_RESPONSE = {
    "data": [
        {
            "name": "page_total_media_view_unique",
            "period": "days_28",
            "values": [
                {"value": 220, "end_time": "2026-06-18T07:00:00+0000"},
                {"value": 230, "end_time": "2026-06-20T07:00:00+0000"},
            ],
        },
    ],
    "paging": {},
}


def test_merge_insights_rows_combines_both_periods():
    day_rows = parse_insights_response(REALISTIC_RESPONSE)
    days_28_rows = parse_insights_response(
        REALISTIC_DAYS_28_RESPONSE, metrics=DAYS_28_METRICS
    )

    merged, columns = merge_insights_rows(day_rows, days_28_rows)

    # Column list should have suffixed names in expected order.
    assert columns == [
        "page_media_view",
        "page_views_total",
        "page_post_engagements",
        "page_follows",
        "page_total_media_view_unique_day",
        "page_total_media_view_unique_days_28",
    ]

    assert len(merged) == 3  # 3 distinct dates across both periods

    # 2026-06-17: present in both periods.
    assert merged[0] == {
        "date": "2026-06-17",
        "page_media_view": 100,
        "page_views_total": 5,
        "page_post_engagements": 50,
        "page_follows": 1000,
        "page_total_media_view_unique_day": 200,
        "page_total_media_view_unique_days_28": 220,
    }

    # 2026-06-18: day-only date.
    assert merged[1] == {
        "date": "2026-06-18",
        "page_media_view": 110,
        "page_views_total": 7,
        "page_post_engagements": 75,
        "page_follows": 1001,
        "page_total_media_view_unique_day": 210,
        "page_total_media_view_unique_days_28": None,
    }

    # 2026-06-19: days_28-only date.
    assert merged[2] == {
        "date": "2026-06-19",
        "page_media_view": None,
        "page_views_total": None,
        "page_post_engagements": None,
        "page_follows": None,
        "page_total_media_view_unique_day": None,
        "page_total_media_view_unique_days_28": 230,
    }


def test_merge_insights_rows_handles_empty_days_28():
    day_rows = parse_insights_response(REALISTIC_RESPONSE)
    merged, columns = merge_insights_rows(day_rows, [])

    assert columns == [
        "page_media_view",
        "page_views_total",
        "page_post_engagements",
        "page_follows",
        "page_total_media_view_unique_day",
        "page_total_media_view_unique_days_28",
    ]
    assert len(merged) == 2
    for row in merged:
        assert row["page_total_media_view_unique_days_28"] is None


def test_merge_insights_rows_handles_empty_day():
    days_28_rows = parse_insights_response(
        REALISTIC_DAYS_28_RESPONSE, metrics=DAYS_28_METRICS
    )
    merged, columns = merge_insights_rows([], days_28_rows)

    assert len(merged) == 2
    for row in merged:
        assert row["page_total_media_view_unique_day"] is None
        assert row["page_total_media_view_unique_days_28"] is not None


def test_fetch_stops_at_until_date(monkeypatch):
    """fetch_page_insights_raw must not include data whose end_time
    exceeds the caller's until date. This guards against the API's
    paging.next links advancing past the original until and injecting
    future-dated placeholder rows."""

    captured_urls = []

    FAKE_FIRST_PAGE = {
        "data": [
            {"name": "page_media_view", "values": [{"value": 100, "end_time": "2026-07-17T07:00:00+0000"}]},
        ],
        "paging": {"next": "https://graph.facebook.com/v25.0/123/insights?since=1784444400&until=1785052800"},
    }

    FAKE_SECOND_PAGE = {
        "data": [
            {"name": "page_media_view", "values": [{"value": 0, "end_time": "2026-07-25T07:00:00+0000"}]},
        ],
        "paging": {},
    }

    def fake_http_get_json(url):
        captured_urls.append(url)
        if len(captured_urls) == 1:
            return FAKE_FIRST_PAGE
        return FAKE_SECOND_PAGE

    monkeypatch.setattr("fb_page_insights._http_get_json", fake_http_get_json)

    result = fetch_page_insights_raw(
        page_id="123",
        access_token="tok",
        since="2026-07-10",
        until="2026-07-18",
    )

    # The second page was fetched (its URL was visited), but its data
    # (2026-07-25) exceeds until (2026-07-18) so it must be discarded.
    assert len(captured_urls) == 2
    assert len(result["data"]) == 1
    assert result["data"][0]["name"] == "page_media_view"


def test_extract_page_insights_combines_fetch_and_parse(monkeypatch):
    def fake_http_get_json(url):
        return REALISTIC_RESPONSE

    monkeypatch.setattr("fb_page_insights._http_get_json", fake_http_get_json)

    rows = extract_page_insights(
        page_id="page-123",
        access_token="token-abc",
        since="2026-06-18",
        until="2026-06-19",
    )

    assert len(rows) == 2
    assert rows[0]["date"] == "2026-06-17"
    assert rows[1]["date"] == "2026-06-18"
