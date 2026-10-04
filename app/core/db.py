"""Accès à la base PostgreSQL : un seul moteur, une seule base déclarative pour tous les modules."""
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


def get_session() -> Session:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)()
