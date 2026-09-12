"""Unit 1 verification: the app builds through create_app(), gates are safe, CORS is correct."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "environment": "test"}


def test_docs_gate_allowlists_rather_than_denylists() -> None:
    """An unrecognised environment must default to docs off, not docs on."""
    from expense_api.config.settings import Settings

    assert Settings(_env_file=None, app_env="development").docs_enabled
    assert Settings(_env_file=None, app_env="test").docs_enabled
    assert not Settings(_env_file=None, app_env="production").docs_enabled


def test_database_urls_are_sqlite_and_share_one_path() -> None:
    """The async and Alembic URLs must point at the same file, or migrations land elsewhere."""
    from expense_api.config.settings import Settings

    settings = Settings(_env_file=None, database_path="/tmp/example.db")

    assert settings.database_url == "sqlite+aiosqlite:////tmp/example.db"
    assert settings.sync_database_url == "sqlite:////tmp/example.db"


def test_invalid_app_env_fails_at_construction() -> None:
    """APP_ENV is a Literal so a typo is a boot-time error, not a silently closed gate."""
    from pydantic import ValidationError

    from expense_api.config.settings import Settings

    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="prod")  # type: ignore[arg-type]


def test_cors_regex_is_anchored_at_both_ends() -> None:
    """An unanchored regex would match http://localhost:3000.attacker.com."""
    from expense_api.config.settings import Settings

    settings = Settings(_env_file=None, web_host="http://localhost:3000")

    assert settings.cors_allow_origin_regex.startswith("^")
    assert settings.cors_allow_origin_regex.endswith("$")


@pytest.mark.asyncio
async def test_preflight_echoes_explicit_origin_not_wildcard(client: AsyncClient) -> None:
    """Browsers reject `*` for credentialed requests; the exact origin must come back."""
    response = await client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert response.headers["access-control-allow-credentials"] == "true"


@pytest.mark.asyncio
async def test_preflight_allows_the_identity_header(client: AsyncClient) -> None:
    """Every request the browser makes carries X-Emp-Code, and it is not CORS-safelisted.

    Without it in allow_headers the middleware refuses the preflight before any route runs, and
    the symptom in the browser is that the whole API appears unreachable.
    """
    response = await client.options(
        "/api/v1/me",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "content-type,x-emp-code",
        },
    )

    assert response.status_code == 200
    allowed = response.headers["access-control-allow-headers"].lower()
    assert "x-emp-code" in allowed


@pytest.mark.asyncio
async def test_unknown_origin_is_not_allowed(client: AsyncClient) -> None:
    response = await client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:3000.attacker.com",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert "access-control-allow-origin" not in response.headers


def test_cors_escapes_the_exact_origin() -> None:
    """The origin is data, not a pattern: an unescaped dot matches any character."""
    import re

    from expense_api.config.settings import Settings

    pattern = Settings(_env_file=None, web_host="http://localhost:3000").cors_allow_origin_regex

    assert re.match(pattern, "http://localhost:3000")
    assert not re.match(pattern, "http://localhostX3000")


def test_a_preview_origin_pattern_widens_cors_without_opening_it() -> None:
    """Vercel mints a subdomain per deployment, so previews need a pattern, not an origin."""
    import re

    from expense_api.config.settings import Settings

    pattern = Settings(
        _env_file=None,
        web_host="https://nortex.vercel.app",
        web_origin_regex_extra=r"https://nortex-[a-z0-9-]+\.vercel\.app",
    ).cors_allow_origin_regex

    assert re.match(pattern, "https://nortex.vercel.app")
    assert re.match(pattern, "https://nortex-git-feat-abc.vercel.app")
    assert not re.match(pattern, "https://nortex.vercel.app.attacker.com")
    assert not re.match(pattern, "https://attacker.app")


def test_a_blank_environment_variable_means_unset() -> None:
    """Compose and Render substitute an unset variable as "", not as nothing at all.

    Left as an empty string, the regex fragment would add `|` to the alternation - which
    matches the empty origin - and the token would demand an empty X-Demo-Token header.
    """
    import re

    from expense_api.config.settings import Settings

    settings = Settings(_env_file=None, web_origin_regex_extra="", demo_reset_token="")

    assert settings.demo_reset_token is None
    assert not re.match(settings.cors_allow_origin_regex, "")


def test_the_demo_reset_gate_is_closed_by_default() -> None:
    """It deletes every claim in the database. Nothing but an explicit opt-in turns it on."""
    from expense_api.config.settings import Settings

    assert not Settings(_env_file=None).demo_reset_enabled
