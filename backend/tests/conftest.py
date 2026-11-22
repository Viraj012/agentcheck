import os
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from app.config import Settings

BACKEND_DIR = Path(__file__).resolve().parents[1]


def alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(scope="session")
def test_database_url() -> Iterator[str]:
    """A throwaway database next to the configured one, created fresh per test session."""
    base_url = Settings().database_url
    parts = urlsplit(base_url)
    test_name = f"{parts.path.lstrip('/')}_test"
    try:
        admin = psycopg.connect(base_url, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        message = f"Postgres not reachable ({exc}); run `docker compose up -d db`"
        if os.environ.get("CI"):
            pytest.fail(message)
        pytest.skip(message)
    with admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{test_name}" WITH (FORCE)')
        admin.execute(f'CREATE DATABASE "{test_name}"')
    yield parts._replace(path=f"/{test_name}").geturl()
    with psycopg.connect(base_url, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{test_name}" WITH (FORCE)')


@pytest.fixture(scope="session")
def migrated_url(test_database_url: str) -> str:
    command.upgrade(alembic_config(test_database_url), "head")
    return test_database_url
