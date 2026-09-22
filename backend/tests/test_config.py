"""Deployment settings checked at startup (v0.30.0): a missing or wrong one
stops the backend with a message naming the variable."""

import pytest
from fastapi.testclient import TestClient

from app.config import ConfigError, Settings, check_startup, normalize_origin, public_origins
from app.config import get_settings as env_settings
from app.main import app

GOOD_CODE = "3f9a0c7e2b8d4165a0e9c3b7f1d2e8a4"  # 32 hex characters


def settings(**values) -> Settings:
    return Settings(**{"public_origins": "https://cabinet.example.com", **values})


@pytest.mark.parametrize(
    "value, expected",
    [
        ("https://Cabinet.Example.com", "https://cabinet.example.com"),
        ("https://cabinet.example.com:443", "https://cabinet.example.com"),
        ("http://localhost:80", "http://localhost"),
        ("http://localhost:5173", "http://localhost:5173"),
        ("http://192.168.1.20:8080", "http://192.168.1.20:8080"),
        ("https://cabinet.example.com/", None),  # a path, even an empty one
        ("https://cabinet.example.com/app", None),
        ("cabinet.example.com", None),
        ("ftp://cabinet.example.com", None),
        ("https://user@cabinet.example.com", None),
        ("https://cabinet.example.com:99999", None),
        ("https://-bad.example.com", None),
        ("null", None),
    ],
)
def test_origins_are_normalized_or_refused(value, expected):
    assert normalize_origin(value) == expected


def test_public_origins_is_required():
    with pytest.raises(ConfigError, match="PUBLIC_ORIGINS is required"):
        check_startup(Settings(public_origins=" , "))


def test_public_origins_names_the_bad_entry():
    config = settings(public_origins="https://ok.example.com, https://bad.example.com/path")
    with pytest.raises(ConfigError, match=r"PUBLIC_ORIGINS: 'https://bad.example.com/path'"):
        check_startup(config)


def test_public_origins_are_parsed_as_a_list():
    config = settings(public_origins="http://localhost, http://proxy:80 ,")
    assert public_origins(config) == ["http://localhost", "http://proxy"]


def test_insecure_http_only_beside_http_origins():
    warnings = check_startup(settings(public_origins="http://localhost", auth_insecure_http=True))
    assert any("AUTH_INSECURE_HTTP" in w for w in warnings)
    with pytest.raises(ConfigError, match="AUTH_INSECURE_HTTP"):
        check_startup(
            settings(
                public_origins="http://localhost,https://cabinet.example.com",
                auth_insecure_http=True,
            )
        )
    assert check_startup(settings()) == []


@pytest.mark.parametrize(
    "code, message",
    [
        ("too-short-1234", "at least 32"),
        ("a" * 40, "repeats one character"),
        ("ab" * 16 + "a" * 20, "repeats one character"),
    ],
)
def test_weak_setup_code_stops_startup(code, message):
    with pytest.raises(ConfigError, match=f"SETUP_CODE .*{message}"):
        check_startup(settings(setup_code=code))


def test_setup_code_ignores_spaces_and_dashes_when_counting():
    grouped = "-".join(GOOD_CODE[i : i + 4] for i in range(0, 32, 4))
    check_startup(settings(setup_code=grouped))
    with pytest.raises(ConfigError, match="at least 32"):
        check_startup(settings(setup_code="-" * 20 + GOOD_CODE[:20]))


def test_setup_code_file_is_read_and_checked(tmp_path):
    good = tmp_path / "code"
    good.write_text(GOOD_CODE + "\n", encoding="utf-8")
    check_startup(settings(setup_code_file=str(good)))

    weak = tmp_path / "weak"
    weak.write_text("short", encoding="utf-8")
    with pytest.raises(ConfigError, match="SETUP_CODE_FILE must be at least 32"):
        check_startup(settings(setup_code_file=str(weak)))

    # the file wins over the variable, so a weak variable beside it is unused
    check_startup(settings(setup_code_file=str(good), setup_code="short"))


def test_unreadable_setup_code_file_stops_startup(tmp_path):
    missing = tmp_path / "no-such-secret"
    with pytest.raises(ConfigError, match="SETUP_CODE_FILE .* cannot be read"):
        check_startup(settings(setup_code_file=str(missing)))
    with pytest.raises(ConfigError, match="cannot be read"):
        check_startup(settings(setup_code_file=str(tmp_path)))  # a folder


def test_the_app_refuses_to_start_without_public_origins(monkeypatch):
    monkeypatch.setenv("PUBLIC_ORIGINS", "")
    env_settings.cache_clear()
    try:
        with pytest.raises(ConfigError, match="PUBLIC_ORIGINS"):
            with TestClient(app):
                pass
    finally:
        env_settings.cache_clear()


def test_no_interactive_docs_page(client):
    for path in ("/api/docs", "/api/redoc", "/docs", "/docs/oauth2-redirect"):
        assert client.get(path).status_code == 404, path
    assert app.docs_url is None and app.redoc_url is None
    assert app.swagger_ui_oauth2_redirect_url is None
    assert client.get("/api/openapi.json").status_code == 200
