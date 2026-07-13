"""
Entry point: pull the last 7 days of FB Page daily insights and write them
to a CSV file. Proves the auth -> request -> parse -> output chain works
end to end for a single endpoint/time grain before adding others.
"""

import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "extraction"))

from auth import get_page_access_token  # noqa: E402
from config_loader import load_config  # noqa: E402
from fb_page_insights import extract_page_insights, write_insights_csv  # noqa: E402

OUTPUT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "fb_page_insights.csv"
)


def main() -> None:
    config = load_config()
    page_token = get_page_access_token(config.system_user_token, config.fb_page_id)

    until = date.today() - timedelta(days=1)
    since = until - timedelta(days=6)

    rows = extract_page_insights(
        page_id=config.fb_page_id,
        access_token=page_token,
        since=since,
        until=until,
    )

    write_insights_csv(rows, OUTPUT_PATH)
    print(f"Wrote {len(rows)} row(s) to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
