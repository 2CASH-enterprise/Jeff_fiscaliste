"""Regroupe tous les modèles pour les migrations Alembic. Chaque nouveau module y ajoute le sien."""
from app.conversation.models import Conversation, Message
from app.core.db import Base
from app.entreprises.models import Entreprise
from app.referentiel.models import Juridiction

__all__ = ["Base", "Conversation", "Entreprise", "Juridiction", "Message"]
