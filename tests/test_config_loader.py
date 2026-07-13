import os
import sys

import pytest

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "src", "extraction")
)

from config_loader import (  # noqa: E402
    OPTIONAL_VARS,
    REQUIRED_VARS,
    MissingConfigError,
    load_config,
)

SECRET_VALUES = {
    "SYSTEM_USER_TOKEN": "tok-marker-aaaaaaaa",
    "FB_PAGE_ID": "fbid-marker-bbbbbbbb",
    "IG_USER_ID": "igid-marker-cccccccc",
    "AD_ACCOUNT_ID": "act-marker-dddddddd",
}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """
    Ensure every relevant variable is absent before each test, regardless of
    what a prior test's load_dotenv() call wrote directly into os.environ
    (monkeypatch only undoes its own changes, not dotenv's).
    """
    for name in (*REQUIRED_VARS, *OPTIONAL_VARS):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def empty_env_file(tmp_path):
    """An existing-but-empty .env path, so load_dotenv never falls back to
    discovering a real .env file elsewhere on disk."""
    path = tmp_path / ".env"
    path.write_text("")
    return str(path)


def test_load_config_success_all_present(monkeypatch, empty_env_file):
    for name, value in SECRET_VALUES.items():
        monkeypatch.setenv(name, value)

    config = load_config(env_path=empty_env_file)

    assert config.system_user_token == SECRET_VALUES["SYSTEM_USER_TOKEN"]
    assert config.fb_page_id == SECRET_VALUES["FB_PAGE_ID"]
    assert config.ig_user_id == SECRET_VALUES["IG_USER_ID"]
    assert config.ad_account_id == SECRET_VALUES["AD_ACCOUNT_ID"]


def test_load_config_success_without_optional_var(monkeypatch, empty_env_file):
    for name in REQUIRED_VARS:
        monkeypatch.setenv(name, SECRET_VALUES[name])

    config = load_config(env_path=empty_env_file)

    assert config.ad_account_id is None


def test_loads_values_from_env_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(f"{name}={value}" for name, value in SECRET_VALUES.items())
    )

    config = load_config(env_path=str(env_file))

    assert config.system_user_token == SECRET_VALUES["SYSTEM_USER_TOKEN"]
    assert config.fb_page_id == SECRET_VALUES["FB_PAGE_ID"]
    assert config.ig_user_id == SECRET_VALUES["IG_USER_ID"]
    assert config.ad_account_id == SECRET_VALUES["AD_ACCOUNT_ID"]


@pytest.mark.parametrize("missing_var", REQUIRED_VARS)
def test_missing_required_var_raises_named_error(
    monkeypatch, empty_env_file, missing_var
):
    for name in REQUIRED_VARS:
        if name != missing_var:
            monkeypatch.setenv(name, SECRET_VALUES[name])

    with pytest.raises(MissingConfigError) as exc_info:
        load_config(env_path=empty_env_file)

    assert missing_var in str(exc_info.value)


@pytest.mark.parametrize("empty_var", REQUIRED_VARS)
def test_empty_required_var_raises_named_error(
    monkeypatch, empty_env_file, empty_var
):
    for name in REQUIRED_VARS:
        monkeypatch.setenv(name, "" if name == empty_var else SECRET_VALUES[name])

    with pytest.raises(MissingConfigError) as exc_info:
        load_config(env_path=empty_env_file)

    assert empty_var in str(exc_info.value)


def test_no_secret_value_appears_in_exception(monkeypatch, empty_env_file):
    present_vars = REQUIRED_VARS[1:]
    for name in present_vars:
        monkeypatch.setenv(name, SECRET_VALUES[name])
    monkeypatch.setenv("AD_ACCOUNT_ID", SECRET_VALUES["AD_ACCOUNT_ID"])

    with pytest.raises(MissingConfigError) as exc_info:
        load_config(env_path=empty_env_file)

    message = str(exc_info.value)
    for name, value in SECRET_VALUES.items():
        assert value not in message
