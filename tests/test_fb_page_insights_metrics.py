import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "extraction"))

from fb_page_insights import DEFAULT_METRICS  # noqa: E402

# Hardcoded from scripts/output/diagnose_all_page_metrics_output.txt
# lines 84-121 ("Succeeded:" block) -- 37 confirmed-valid FB Page
# Insights metric names on Graph API v25.0, tested against Page
# 145245558842140 on 2026-07-13.
CONFIRMED_VALID_METRICS = {
    "page_total_actions", "page_post_engagements",
    "page_fan_adds_by_paid_non_paid_unique",
    "page_lifetime_engaged_followers_unique", "page_daily_follows",
    "page_daily_follows_unique", "page_daily_unfollows_unique",
    "page_follows", "page_media_view", "page_total_media_view_unique",
    "page_actions_post_reactions_like_total",
    "page_actions_post_reactions_love_total",
    "page_actions_post_reactions_wow_total",
    "page_actions_post_reactions_haha_total",
    "page_actions_post_reactions_sorry_total",
    "page_actions_post_reactions_anger_total",
    "page_actions_post_reactions_total", "page_video_views",
    "page_video_views_by_uploaded_hosted", "page_video_views_paid",
    "page_video_views_organic", "page_video_views_by_paid_non_paid",
    "page_video_views_autoplayed", "page_video_views_click_to_play",
    "page_video_views_unique", "page_video_repeat_views",
    "page_video_complete_views_30s", "page_video_complete_views_30s_paid",
    "page_video_complete_views_30s_organic",
    "page_video_complete_views_30s_autoplayed",
    "page_video_complete_views_30s_click_to_play",
    "page_video_complete_views_30s_unique",
    "page_video_complete_views_30s_repeat_views", "page_video_view_time",
    "page_views_total", "content_monetization_earnings",
    "monetization_approximate_earnings",
}
assert len(CONFIRMED_VALID_METRICS) == 37  # sanity-checks the literal itself

# Hardcoded from the same file's "Failed:" block -- names confirmed
# invalid (code=100) on v25.0, including the legacy names DEFAULT_METRICS
# must never regress to.
KNOWN_INVALID_LEGACY_METRICS = {
    "page_views", "page_fans", "page_fans_locale", "page_fans_city",
    "page_fans_country", "page_fan_adds", "page_fan_adds_unique",
    "page_fan_removes", "page_fan_removes_unique",
    "page_impressions", "page_impressions_unique", "page_impressions_paid",
    "page_impressions_paid_unique", "page_impressions_viral",
    "page_impressions_viral_unique", "page_impressions_nonviral",
    "page_impressions_nonviral_unique",
}


def test_default_metrics_are_all_confirmed_valid():
    assert set(DEFAULT_METRICS).issubset(CONFIRMED_VALID_METRICS)


def test_default_metrics_exclude_known_invalid_legacy_names():
    assert set(DEFAULT_METRICS).isdisjoint(KNOWN_INVALID_LEGACY_METRICS)
