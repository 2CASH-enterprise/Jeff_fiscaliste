"""Routeur de canal : choisit par où un rappel est remis au client.

Lot 7 : seule la bulle existe. Les lots suivants ajouteront l'email (par défaut) et WhatsApp
(dans la fenêtre de 24 h, ou parmi les 5 messages prioritaires du mois).
"""
from app.entreprises.models import Entreprise

BULLE = "bulle"
CANAUX = (BULLE,)


def choisir_canal(entreprise: Entreprise) -> str:
    return BULLE
