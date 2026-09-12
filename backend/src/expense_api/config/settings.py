"""Application settings.

One Settings singleton, instantiated at module scope and imported everywhere as
`from expense_api.config.settings import settings`.

Two conventions worth stating explicitly:

1. Fields that must be supplied carry no default, so a missing environment is a boot-time crash
   rather than a silent misconfiguration discovered later. This application has no mandatory
   secret - the database is a local file and the only credential is optional - so nothing
   currently exercises that rule. It still applies to anything added later.
2. Any gate that protects something allowlists the safe value; it never denylists the unsafe
   ones. A denylist such as `app_env != "production"` reads as correct in review and matches
   every deployed environment, right up until a new one appears.
"""

import re
from functools import cached_property
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository root, four parents up from this file: config/ -> expense_api/ -> src/ -> backend/
BACKEND_ROOT = Path(__file__).resolve().parents[3]
PROJECT_ROOT = BACKEND_ROOT.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="allow",
    )

    # Literal rather than str: a typo in APP_ENV becomes a boot-time ValidationError instead of
    # an environment that silently fails every allowlist gate below.
    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    # SQLite, one file, owned entirely by this application. It shares no server and binds no
    # port, so it cannot collide with - or be mistaken for - any other database on the machine.
    # The cost is accepted deliberately: SQLite serialises writers, so the concurrent-approver
    # test exercises coarser locking than Postgres would. See docs/agents/testing.md.
    database_path: Path = BACKEND_ROOT / "data" / "expense.db"

    # Frontend origin. Used to build the CORS regex; see the note in main.py.
    web_host: str = "http://localhost:3000"

    # A second, *pattern* origin, for hosts that mint a new URL per deployment. Vercel preview
    # builds are the case this exists for: every preview gets its own subdomain, so an exact
    # origin can only ever match production. Supply a regex fragment - no anchors, they are
    # added here - e.g. `https://nortex-expense-[a-z0-9-]+\.vercel\.app`. Left unset, the
    # allowed set is exactly `web_host` and nothing else.
    web_origin_regex_extra: str | None = None

    # The specification pack is read-only input. Nothing in this application writes to it.
    pack_dir: Path = PROJECT_ROOT / "pack"

    # Where an employee's own uploads land. Deliberately outside pack_dir: the pack is the
    # specification and is mounted read-only, so an upload written there would fail at runtime
    # rather than at review time.
    upload_dir: Path = BACKEND_ROOT / "data" / "uploads"

    # Per-file ceiling for an upload, enforced while the body is streamed to disk.
    max_upload_bytes: int = 10 * 1024 * 1024

    # Demo reset. Allowlist, not denylist: off unless something turns it on, so an environment
    # nobody thought about cannot expose an endpoint that deletes every claim in the database.
    # `demo_reset_token`, when set, must be echoed in an `X-Demo-Token` header.
    demo_reset_enabled: bool = False
    demo_reset_token: str | None = None

    # Which extraction adapter the ingestion pipeline uses. "llm" requires anthropic_api_key
    # and is untested in this build - there is no credential available in the dev environment.
    extractor: Literal["rule_based", "llm"] = "rule_based"
    anthropic_api_key: str | None = None

    @field_validator("web_origin_regex_extra", "demo_reset_token", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        """An empty environment variable means "not set", not "set to the empty string".

        Compose and Render both substitute an unset variable as `""` rather than omitting it.
        Left as-is, an empty token would demand a caller send an empty `X-Demo-Token`, and an
        empty regex fragment would add `|` to the CORS alternation - which matches the empty
        origin.
        """
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("database_path", "pack_dir", "upload_dir")
    @classmethod
    def _resolve_against_backend_root(cls, value: Path) -> Path:
        """Anchor relative paths to the package, not to the current working directory.

        `.env` carries `DATABASE_PATH=data/expense.db`, and uvicorn, pytest and alembic are all
        launched from different directories. Resolving against CWD would silently create a
        second database next to whichever one you happened to run.
        """
        return value if value.is_absolute() else (BACKEND_ROOT / value).resolve()

    @cached_property
    def database_url(self) -> str:
        """Async URL for the application engine."""
        return f"sqlite+aiosqlite:///{self.database_path}"

    @cached_property
    def sync_database_url(self) -> str:
        """Sync URL. Alembic only - the application never opens a sync connection."""
        return f"sqlite:///{self.database_path}"

    @cached_property
    def cors_allow_origin_regex(self) -> str:
        """Anchored at both ends, and never `allow_origins=["*"]`.

        Starlette answers a bare `Access-Control-Allow-Origin: *` to requests that carry no
        Cookie header, and browsers reject `*` for `credentials: "include"`. Using
        allow_origin_regex disables allow_all_origins, which forces the explicit origin to be
        echoed back instead.
        """
        # re.escape, because an unescaped origin is a pattern: the dots in
        # `http://localhost:3000` match any character, so `http://localhostX3000` would be
        # allowed too. Harmless on a dev host, not harmless on a public domain.
        alternatives = [re.escape(self.web_host.rstrip("/"))]
        if self.web_origin_regex_extra:
            alternatives.append(self.web_origin_regex_extra)
        return f"^(?:{'|'.join(alternatives)})$"

    @cached_property
    def docs_enabled(self) -> bool:
        """Allowlist, not denylist. A new environment name defaults to docs off."""
        return self.app_env in ("development", "test")


settings = Settings()
