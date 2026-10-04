"""Canal web : bulle de discussion d'essai.

La page n'existe que si ESSAI_ACTIF=true. Chaque navigateur reçoit un jeton de session
aléatoire (cookie) ; il ne voit que sa propre conversation.
"""
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.conversation.models import CANAL_WEB
from app.conversation.moteur import MessageVide, historique, traiter_message
from app.core.config import get_settings
from app.core.db import session_requete

COOKIE = "jeff_essai"
DUREE_COOKIE = 30 * 24 * 3600

templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")
router = APIRouter(prefix="/essai")


class MessageEntrant(BaseModel):
    texte: str


def essai_actif() -> None:
    if not get_settings().essai_actif:
        raise HTTPException(status_code=404)


def jeton_valide(request: Request) -> str | None:
    jeton = request.cookies.get(COOKIE)
    if jeton and 20 <= len(jeton) <= 64 and jeton.replace("-", "").replace("_", "").isalnum():
        return jeton
    return None


@router.get("", response_class=HTMLResponse, dependencies=[Depends(essai_actif)])
def page_essai(request: Request):
    jeton = jeton_valide(request) or secrets.token_urlsafe(32)
    reponse = templates.TemplateResponse(request, "essai.html", {})
    reponse.set_cookie(
        COOKIE,
        jeton,
        max_age=DUREE_COOKIE,
        httponly=True,
        samesite="strict",
        secure=get_settings().environnement == "production" and request.url.scheme == "https",
    )
    return reponse


@router.post("/messages", dependencies=[Depends(essai_actif)])
def envoyer_message(
    corps: MessageEntrant, request: Request, session: Session = Depends(session_requete)
):
    jeton = jeton_valide(request)
    if jeton is None:
        raise HTTPException(status_code=401, detail="Session expirée. Rechargez la page.")
    try:
        reponse = traiter_message(session, CANAL_WEB, jeton, corps.texte)
    except MessageVide:
        raise HTTPException(status_code=422, detail="Le message est vide.")
    return JSONResponse(
        {
            "reponse": reponse.texte,
            "choix": [{"valeur": v, "libelle": l} for v, l in reponse.choix],
        }
    )


@router.get("/historique", dependencies=[Depends(essai_actif)])
def lire_historique(request: Request, session: Session = Depends(session_requete)):
    # Sans jeton valide, aucune conversation ne correspond : la liste est vide.
    jeton = jeton_valide(request)
    return {
        "messages": [
            {"sens": m.sens, "texte": m.texte} for m in historique(session, CANAL_WEB, jeton)
        ]
    }
