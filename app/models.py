"""Regroupe tous les modèles pour les migrations Alembic. Chaque nouveau module y ajoute le sien."""
from app.conversation.models import Conversation, Message, Parcours
from app.core.db import Base
from app.entreprises.models import Entreprise
from app.referentiel.models import Juridiction
from app.regles.models import Regle

__all__ = ["Base", "Conversation", "Entreprise", "Juridiction", "Message", "Parcours", "Regle"]
