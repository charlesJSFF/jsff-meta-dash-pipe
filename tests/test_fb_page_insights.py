import os
import sys

import pytest

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "src", "extraction")
)

from fb_page_insights import (  # noqa: E402
    extract_page_insights,
    fetch_page_insights_raw,
    parse_insights_response,
)

REALISTIC_RESPONSE = {
    "data": [
        {
            "name": "reach",
            "period": "day",
            "values": [
                {"value": 100, "end_time": "2026-06-18T07:00:00+0000"},
                {"value": 110, "end_time": "2026-06-19T07:00:00+0000"},
            ],
        },
        {
            "name": "impressions",
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
            "name": "follower_count",
            "period": "day",
            "values": [
                {"value": 1000, "end_time": "2026-06-18T07:00:00+0000"},
                {"value": 1001, "end_time": "2026-06-19T07:00:00+0000"},
            ],
        },
    ],
    "paging": {},
}


def test_parses_realistic_response_into_expected_rows():
    rows = parse_insights_response(REALISTIC_RESPONSE)

    assert rows == [
        {
            "date": "2026-06-18",
            "reach": 100,
            "impressions": 200,
            "page_views_total": 5,
            "follower_count": 1000,
        },
        {
            "date": "2026-06-19",
            "reach": 110,
            "impressions": 210,
            "page_views_total": 7,
            "follower_count": 1001,
        },
    ]


def test_handles_response_missing_one_metric_without_crashing():
    response_missing_follower_count = {
        "data": [m for m in REALISTIC_RESPONSE["data"] if m["name"] != "follower_count"],
        "paging": {},
    }

    rows = parse_insights_response(response_missing_follower_count)

    assert len(rows) == 2
    for row in rows:
        assert "follower_count" not in row
        assert row["reach"] is not None
        assert row["impressions"] is not None
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
        metrics=("reach", "impressions", "page_views_total", "follower_count"),
        limit=100,
    )

    assert len(captured_urls) == 1
    url = captured_urls[0]
    assert "/page-123/insights" in url
    assert "since=2026-06-12" in url
    assert "until=2026-06-18" in url
    assert "period=day" in url
    assert "limit=100" in url
    assert "metric=reach%2Cimpressions%2Cpage_views_total%2Cfollower_count" in url


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
    assert rows[0]["date"] == "2026-06-18"
