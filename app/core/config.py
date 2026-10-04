"""Configuration de l'application, lue uniquement depuis les variables d'environnement (.env).

Aucun secret n'est écrit dans le code : les valeurs par défaut ci-dessous ne servent qu'au
développement local et aux tests.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

VERSION = "0.6.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environnement: str = "developpement"
    database_url: str = "postgresql+psycopg://jeff:jeff@localhost:5432/jeff"
    redis_url: str = "redis://localhost:6379/0"
    # Page d'essai de la bulle web : coupée par défaut, à activer explicitement dans le .env.
    essai_actif: bool = False
    # Pays de ce déploiement : une entreprise relève d'une seule juridiction.
    juridiction: str = "CM"

    @property
    def debug(self) -> bool:
        # Le mode debug est toujours coupé en production.
        return self.environnement != "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
