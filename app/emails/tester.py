"""Commande : envoie un email de test pour vérifier les réglages SMTP du .env.

Sur le serveur : docker compose exec api python -m app.emails.tester VOTRE_EMAIL_ICI
Aucun identifiant n'est jamais affiché.
"""
import sys

from app.conversation import messages_fixes as mf
from app.core.config import get_settings
from app.emails.composition import html_depuis_texte
from app.emails.envoi import envoyer_smtp

REGLAGES = ("SMTP_HOTE", "SMTP_UTILISATEUR", "SMTP_MOT_DE_PASSE", "EMAIL_EXPEDITEUR")


def main(arguments: list[str]) -> int:
    if len(arguments) != 1 or "@" not in arguments[0]:
        print("Usage : python -m app.emails.tester adresse@exemple.cm")
        return 1
    reglages = get_settings()
    if not reglages.email_configure:
        print("Envoi désactivé : complétez dans le .env " + ", ".join(REGLAGES) + ", puis relancez les conteneurs.")
        return 1
    texte = mf.EMAIL_TEST_TEXTE + "\n\n" + mf.EMAIL_SIGNATURE
    try:
        envoyer_smtp(arguments[0], mf.EMAIL_TEST_OBJET, texte, html_depuis_texte(texte))
    except Exception as erreur:
        print(f"Échec de l'envoi : {type(erreur).__name__}: {erreur}")
        return 1
    print(f"Email de test envoyé à {arguments[0]} depuis {reglages.email_expediteur}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
