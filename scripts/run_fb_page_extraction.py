"""
Entry point: pull the last 7 days of FB Page daily insights and write them
to a CSV file. Also pulls page_total_media_view_unique at period=days_28
(same-cadence rolling sum) and merges both into a single output.
"""

import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "extraction"))

from auth import get_page_access_token  # noqa: E402
from config_loader import load_config  # noqa: E402
from fb_page_insights import (  # noqa: E402
    DAYS_28_METRICS,
    DEFAULT_METRICS,
    extract_page_insights,
    merge_insights_rows,
    write_insights_csv,
)

OUTPUT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "fb_page_insights.csv"
)


def main() -> None:
    config = load_config()
    page_token = get_page_access_token(config.system_user_token, config.fb_page_id)

    until = date.today()
    since = until - timedelta(days=28)

    # Day-period pull for all DEFAULT_METRICS.
    day_rows = extract_page_insights(
        page_id=config.fb_page_id,
        access_token=page_token,
        since=since,
        until=until,
        period="day",
        metrics=DEFAULT_METRICS,
    )

    # days_28-period pull for page_total_media_view_unique only.
    days_28_rows = extract_page_insights(
        page_id=config.fb_page_id,
        access_token=page_token,
        since=since,
        until=until,
        period="days_28",
        metrics=DAYS_28_METRICS,
    )

    merged_rows, merged_columns = merge_insights_rows(day_rows, days_28_rows)

    write_insights_csv(merged_rows, OUTPUT_PATH, metrics=merged_columns)
    print(f"Wrote {len(merged_rows)} row(s) to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()