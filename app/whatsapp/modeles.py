"""Commande : soumettre à Meta le modèle WhatsApp des rappels et suivre sa validation.

Sur le serveur :
  docker compose exec api python -m app.whatsapp.modeles creer    # soumet le modèle (une fois)
  docker compose exec api python -m app.whatsapp.modeles statut   # en attente, approuvé ou refusé
Aucun jeton n'est affiché.
"""
import sys

import httpx

from app.conversation import messages_fixes as mf
from app.core.config import get_settings

LANGUE = "fr"
CATEGORIE = "UTILITY"


def url_modeles() -> str:
    reglages = get_settings()
    return f"https://graph.facebook.com/{reglages.whatsapp_version_api}/{reglages.whatsapp_id_compte}/message_templates"


def entetes() -> dict:
    return {"Authorization": f"Bearer {get_settings().whatsapp_jeton}"}


def definition() -> dict:
    return {
        "name": get_settings().whatsapp_modele_rappel,
        "language": LANGUE,
        "category": CATEGORIE,
        "components": [{
            "type": "BODY",
            "text": mf.MODELE_RAPPEL_TEXTE,
            "example": {"body_text": [list(mf.MODELE_RAPPEL_EXEMPLE)]},
        }],
    }


def erreur_de(reponse) -> str:
    try:
        erreur = reponse.json().get("error", {})
        return f"{erreur.get('code')} {erreur.get('error_user_msg') or erreur.get('message')}"
    except ValueError:
        return reponse.text[:200]


def creer() -> int:
    reponse = httpx.post(url_modeles(), json=definition(), headers=entetes(), timeout=30)
    if reponse.status_code >= 400:
        print(f"Refus de Meta (HTTP {reponse.status_code}) : {erreur_de(reponse)}")
        return 1
    donnees = reponse.json()
    print(f"Modèle « {get_settings().whatsapp_modele_rappel} » soumis : statut {donnees.get('status')}, catégorie {donnees.get('category')}.")
    return 0


def statut() -> int:
    reponse = httpx.get(
        url_modeles(),
        params={"name": get_settings().whatsapp_modele_rappel, "fields": "name,status,language,category,rejected_reason"},
        headers=entetes(),
        timeout=30,
    )
    if reponse.status_code >= 400:
        print(f"Refus de Meta (HTTP {reponse.status_code}) : {erreur_de(reponse)}")
        return 1
    modeles = reponse.json().get("data", [])
    if not modeles:
        print("Aucun modèle de ce nom : lancez d'abord « creer ».")
        return 1
    for m in modeles:
        motif = f", motif : {m['rejected_reason']}" if m.get("rejected_reason") not in (None, "NONE") else ""
        print(f"{m.get('name')} ({m.get('language')}, {m.get('category')}) : {m.get('status')}{motif}")
    return 0


def main(arguments: list[str]) -> int:
    reglages = get_settings()
    if not reglages.whatsapp_configure or not reglages.whatsapp_id_compte or reglages.whatsapp_id_compte == "A_REMPLACER":
        print("WhatsApp n'est pas configuré : complétez WHATSAPP_JETON et WHATSAPP_ID_COMPTE (entre autres) dans le .env.")
        return 1
    if arguments == ["creer"]:
        return creer()
    if arguments == ["statut"]:
        return statut()
    print("Usage : python -m app.whatsapp.modeles creer|statut")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
