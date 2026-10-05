"""Canal WhatsApp : webhook appelé par Meta (seule adresse de Jeff ouverte au public, via nginx).

GET : vérification par Meta (jeton de vérification). POST : notifications, refusées si la
signature ne correspond pas au secret de l'application.
"""
import hmac
import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from app.core.config import get_settings
from app.core.db import get_session
from app.whatsapp.envoi import envoyer_un
from app.whatsapp.reception import signature_valide, traiter_notification

router = APIRouter(prefix="/whatsapp")
CORPS_MAX = 1_000_000


@router.get("/webhook")
def verifier(request: Request):
    reglages = get_settings()
    parametres = request.query_params
    jeton = parametres.get("hub.verify_token") or ""
    if (
        reglages.whatsapp_configure
        and parametres.get("hub.mode") == "subscribe"
        and hmac.compare_digest(jeton.encode(), reglages.whatsapp_jeton_verification.encode())
    ):
        return PlainTextResponse(parametres.get("hub.challenge") or "")
    return PlainTextResponse("Refusé", status_code=403)


@router.post("/webhook")
async def recevoir(request: Request):
    if not get_settings().whatsapp_configure:
        return JSONResponse({"detail": "WhatsApp n'est pas configuré."}, status_code=503)
    corps = await request.body()
    if len(corps) > CORPS_MAX or not signature_valide(corps, request.headers.get("x-hub-signature-256")):
        return JSONResponse({"detail": "Signature invalide."}, status_code=403)
    try:
        donnees = json.loads(corps)
    except ValueError:
        return JSONResponse({"detail": "Corps illisible."}, status_code=400)

    session = get_session()
    try:
        identifiants = traiter_notification(session, donnees)
        session.commit()
        # Réponses envoyées tout de suite ; en cas d'échec, la tâche de la minute suivante les reprend.
        for identifiant in identifiants:
            envoyer_un(session, identifiant)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return JSONResponse({"ok": True})
