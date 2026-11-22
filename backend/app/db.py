"""Database access: plain SQL over psycopg 3 (async). No ORM."""

import psycopg


async def connect(database_url: str) -> psycopg.AsyncConnection:
    return await psycopg.AsyncConnection.connect(database_url)
