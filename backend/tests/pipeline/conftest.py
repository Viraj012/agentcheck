"""Pipeline API tests own the whole runs table of the throwaway test database."""

from collections.abc import AsyncIterator

import psycopg
import pytest

from app.db import connect


@pytest.fixture
async def clean_conn(migrated_url: str) -> AsyncIterator[psycopg.AsyncConnection]:
    connection = await connect(migrated_url)
    await connection.execute("DELETE FROM runs")
    await connection.commit()
    yield connection
    await connection.rollback()
    await connection.execute("DELETE FROM runs")
    await connection.commit()
    await connection.close()
