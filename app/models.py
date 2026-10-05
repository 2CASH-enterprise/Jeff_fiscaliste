"""Regroupe tous les modèles pour les migrations Alembic. Chaque nouveau module y ajoute le sien."""
from app.conversation.models import Conversation, Message, Parcours
from app.core.db import Base
from app.emails.models import Email
from app.entreprises.models import Entreprise, ModificationEntreprise
from app.rappels.models import Rappel
from app.referentiel.models import Juridiction
from app.regles.models import Regle
from app.whatsapp.models import WhatsappEnvoi, WhatsappRecu

__all__ = ["Base", "Conversation", "Email", "Entreprise", "Juridiction", "Message", "ModificationEntreprise", "Parcours", "Rappel", "Regle", "WhatsappEnvoi", "WhatsappRecu"]
