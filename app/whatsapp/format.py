"""Mise en forme des réponses de Jeff pour WhatsApp (limites fixées par Meta).

- 3 choix au plus, libellés de 20 caractères au plus : boutons de réponse ;
- 10 choix au plus : liste (bouton « Voir les choix ») ;
- au-delà : texte avec les choix numérotés, le client tape le numéro.
Un texte trop long pour un message interactif (1 024 caractères) part d'abord seul.
"""
from app.conversation import messages_fixes as mf
from app.conversation.reponse import Reponse

TEXTE_MAX = 4096
CORPS_INTERACTIF_MAX = 1024
BOUTONS_MAX = 3
BOUTON_TITRE_MAX = 20
LISTE_MAX = 10
LIGNE_TITRE_MAX = 24
LIGNE_DESCRIPTION_MAX = 72


def couper(texte: str, maximum: int) -> str:
    return texte if len(texte) <= maximum else texte[: maximum - 1] + "…"


def textes(texte: str) -> list[dict]:
    """Un ou plusieurs messages texte, coupés entre deux paragraphes si possible."""
    morceaux, courant = [], ""
    for paragraphe in texte.split("\n\n"):
        candidat = paragraphe if not courant else courant + "\n\n" + paragraphe
        if len(candidat) <= TEXTE_MAX:
            courant = candidat
            continue
        if courant:
            morceaux.append(courant)
        while len(paragraphe) > TEXTE_MAX:
            morceaux.append(paragraphe[:TEXTE_MAX])
            paragraphe = paragraphe[TEXTE_MAX:]
        courant = paragraphe
    if courant:
        morceaux.append(courant)
    return [{"type": "text", "text": {"body": m, "preview_url": False}} for m in morceaux]


def boutons(corps: str, choix: list[tuple[str, str]]) -> dict:
    return {
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": corps},
            "action": {"buttons": [{"type": "reply", "reply": {"id": v, "title": l}} for v, l in choix]},
        },
    }


def liste(corps: str, choix: list[tuple[str, str]]) -> dict:
    lignes = []
    for valeur, libelle in choix:
        ligne = {"id": valeur, "title": couper(libelle, LIGNE_TITRE_MAX)}
        if len(libelle) > LIGNE_TITRE_MAX:
            ligne["description"] = couper(libelle, LIGNE_DESCRIPTION_MAX)
        lignes.append(ligne)
    return {
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": corps},
            "action": {"button": mf.WA_BOUTON_LISTE, "sections": [{"title": couper(mf.WA_VOTRE_CHOIX, 24), "rows": lignes}]},
        },
    }


def choix_en_texte(choix: list[tuple[str, str]]) -> str:
    return "\n".join(f"{v}. {l}" if v.isdigit() else f"« {v} » : {l}" for v, l in choix)


def contenus(reponse: Reponse) -> list[dict]:
    """Les messages WhatsApp à envoyer pour une réponse : rappels éventuels, puis la réponse."""
    messages = []
    for rappel in reponse.rappels:
        messages += textes(rappel)
    choix = reponse.choix
    if not choix:
        return messages + textes(reponse.texte)

    en_boutons = len(choix) <= BOUTONS_MAX and all(len(l) <= BOUTON_TITRE_MAX for _, l in choix)
    if not en_boutons and len(choix) > LISTE_MAX:
        return messages + textes(reponse.texte + "\n\n" + choix_en_texte(choix))

    corps = reponse.texte
    if len(corps) > CORPS_INTERACTIF_MAX:
        messages += textes(corps)
        corps = mf.WA_VOTRE_CHOIX
    messages.append(boutons(corps, choix) if en_boutons else liste(corps, choix))
    return messages


PARAMETRE_MAX = 100


def parametre(valeur: str) -> dict:
    """Une case du modèle : Meta refuse les retours à la ligne, les tabulations et les longues suites d'espaces."""
    propre = " ".join(str(valeur).split())
    return {"type": "text", "text": couper(propre, PARAMETRE_MAX)}


def modele(nom: str, valeurs: list[str], langue: str = "fr") -> dict:
    return {
        "type": "template",
        "template": {
            "name": nom,
            "language": {"code": langue},
            "components": [{"type": "body", "parameters": [parametre(v) for v in valeurs]}],
        },
    }
