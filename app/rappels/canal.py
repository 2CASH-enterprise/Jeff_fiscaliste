"""Routeur de canal : choisit par où un rappel est remis au client.

Lot 8 : l'email par défaut dès que l'adresse est confirmée, sinon la bulle. WhatsApp viendra
plus tard (fenêtre de 24 h, ou parmi les 5 messages prioritaires du mois).
"""
from app.entreprises.models import Entreprise

BULLE = "bulle"
EMAIL = "email"
CANAUX = (BULLE, EMAIL)


def choisir_canal(entreprise: Entreprise) -> str:
    if entreprise.email and entreprise.email_confirme_le is not None:
        return EMAIL
    return BULLE
