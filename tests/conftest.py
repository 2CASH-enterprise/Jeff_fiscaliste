"""Préparation des tests : une vraie base PostgreSQL, remise à zéro puis migrée par Alembic.

Variables attendues : DATABASE_URL (base de test dédiée, jamais la production) et REDIS_URL.
"""
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import get_engine

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def alembic_config() -> Config:
    config = Config(os.path.join(RACINE, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(RACINE, "migrations"))
    return config


@pytest.fixture(scope="session", autouse=True)
def base_migree():
    assert "test" in get_settings().database_url, "Les tests doivent viser une base de test."
    with get_engine().begin() as connexion:
        connexion.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    command.upgrade(alembic_config(), "head")
    yield


@pytest.fixture
def session():
    connexion = get_engine().connect()
    transaction = connexion.begin()
    from sqlalchemy.orm import Session

    s = Session(bind=connexion, join_transaction_mode="create_savepoint")
    yield s
    s.close()
    transaction.rollback()
    connexion.close()
