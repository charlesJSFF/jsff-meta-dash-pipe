"""
Configuration loader for the Meta Graph API pipeline.

Loads credentials from environment variables (populated via a .env file
through python-dotenv) and validates that every required variable is
present and non-empty. Never logs, prints, or includes secret values in
any error message or exception -- only variable *names* are surfaced.
"""

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv

REQUIRED_VARS = ("SYSTEM_USER_TOKEN", "FB_PAGE_ID", "IG_USER_ID")
OPTIONAL_VARS = ("AD_ACCOUNT_ID",)


class MissingConfigError(RuntimeError):
    """Raised when one or more required configuration variables are missing or empty."""


@dataclass(frozen=True)
class Config:
    system_user_token: str
    fb_page_id: str
    ig_user_id: str
    ad_account_id: Optional[str] = None


def load_config(env_path: Optional[str] = None) -> Config:
    """
    Load and validate Meta Graph API configuration.

    Reads `env_path` (or the default .env discovery location if omitted)
    via python-dotenv, then validates that SYSTEM_USER_TOKEN, FB_PAGE_ID,
    and IG_USER_ID are present and non-empty. AD_ACCOUNT_ID is optional.

    Raises MissingConfigError naming every missing/empty required
    variable if validation fails. The error message never contains the
    value of any variable, only its name.
    """
    load_dotenv(dotenv_path=env_path)

    missing = [name for name in REQUIRED_VARS if not os.environ.get(name)]
    if missing:
        raise MissingConfigError(
            f"Missing required configuration variable(s): {', '.join(missing)}"
        )

    return Config(
        system_user_token=os.environ["SYSTEM_USER_TOKEN"],
        fb_page_id=os.environ["FB_PAGE_ID"],
        ig_user_id=os.environ["IG_USER_ID"],
        ad_account_id=os.environ.get("AD_ACCOUNT_ID") or None,
    )
