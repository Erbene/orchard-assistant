"""app/core/db.py + app/core/vector_db.py wiring checks."""
from __future__ import annotations

import asyncio

from app.config import Settings
from app.core import db, vector_db

from conftest import stack_settings


def test_dsn_from_parts_and_url():
    s = Settings(
        postgres_user="u", postgres_password="p",
        postgres_host="h", postgres_port=6543, postgres_db="d",
    )
    assert s.sqlalchemy_dsn() == "postgresql+asyncpg://u:p@h:6543/d"

    assert Settings(
        database_url="postgresql+asyncpg://x:y@z:1/w"
    ).sqlalchemy_dsn() == "postgresql+asyncpg://x:y@z:1/w"


def test_engine_is_cached_per_dsn():
    a = db.get_engine(Settings(postgres_db="one"))
    b = db.get_engine(Settings(postgres_db="one"))
    c = db.get_engine(Settings(postgres_db="two"))
    try:
        assert a is b
        assert a is not c
    finally:
        asyncio.run(db.dispose_all())


def test_healthcheck_false_for_unreachable_host():
    unreachable = Settings(postgres_host="127.0.0.1", postgres_port=1)
    try:
        assert asyncio.run(db.healthcheck(unreachable)) is False
    finally:
        asyncio.run(db.dispose_all())


def test_healthcheck_true_against_running_container():
    try:
        assert asyncio.run(db.healthcheck(stack_settings())) is True
    finally:
        asyncio.run(db.dispose_all())


def test_vector_db_client_and_collection():
    assert callable(vector_db.get_chroma_client)
    assert vector_db.healthcheck() is True  # conftest ensured the container is up
