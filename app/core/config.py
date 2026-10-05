"""Configuration de l'application, lue uniquement depuis les variables d'environnement (.env).

Aucun secret n'est écrit dans le code : les valeurs par défaut ci-dessous ne servent qu'au
développement local et aux tests.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

VERSION = "0.9.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environnement: str = "developpement"
    database_url: str = "postgresql+psycopg://jeff:jeff@localhost:5432/jeff"
    redis_url: str = "redis://localhost:6379/0"
    # Page d'essai de la bulle web : coupée par défaut, à activer explicitement dans le .env.
    essai_actif: bool = False
    # Pays de ce déploiement : une entreprise relève d'une seule juridiction.
    juridiction: str = "CM"
    # Envoi des emails par SMTP (lot 8, fournisseur Brevo). Les identifiants ne sont que dans le .env.
    smtp_hote: str = ""
    smtp_port: int = 587
    smtp_utilisateur: str = ""
    smtp_mot_de_passe: str = ""
    email_expediteur: str = ""
    email_nom_expediteur: str = "Jeff"

    # WhatsApp Business, API Cloud de Meta (lot 9). Jeton, secret et jeton de vérification : .env seulement.
    whatsapp_jeton: str = ""
    whatsapp_secret_app: str = ""
    whatsapp_jeton_verification: str = ""
    whatsapp_id_numero: str = ""
    whatsapp_version_api: str = "v23.0"

    @property
    def whatsapp_configure(self) -> bool:
        valeurs = (self.whatsapp_jeton, self.whatsapp_secret_app, self.whatsapp_jeton_verification, self.whatsapp_id_numero)
        return all(v and v != "A_REMPLACER" for v in valeurs)

    @property
    def email_configure(self) -> bool:
        valeurs = (self.smtp_hote, self.smtp_utilisateur, self.smtp_mot_de_passe, self.email_expediteur)
        return all(v and v != "A_REMPLACER" and "VOTRE_DOMAINE" not in v for v in valeurs)

    @property
    def debug(self) -> bool:
        # Le mode debug est toujours coupé en production.
        return self.environnement != "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
