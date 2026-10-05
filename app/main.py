"""Point d'entrée de l'application web Jeff."""
import logging
import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import models as _modeles  # noqa: F401 — enregistre tous les modèles avant la première requête
from app.canaux import web, whatsapp
from app.core.config import VERSION, get_settings
from app.core.sante import OK, etat_general

JETON_DANS_ADRESSE = re.compile(r"(verify_token=)[^&\s]*")


class MasquerJetons(logging.Filter):
    """Le journal des requêtes ne garde jamais le jeton de vérification de WhatsApp (lot 10)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(JETON_DANS_ADRESSE.sub(r"\1***", a) if isinstance(a, str) else a for a in record.args)
        return True


logging.getLogger("uvicorn.access").addFilter(MasquerJetons())

app = FastAPI(
    title="Jeff",
    version=VERSION,
    debug=get_settings().debug,
    # Pas de documentation interactive exposée en production.
    docs_url=None if get_settings().environnement == "production" else "/docs",
    redoc_url=None,
)

app.mount("/static", StaticFiles(directory=Path(__file__).resolve().parent / "static"), name="static")
app.include_router(web.router)
app.include_router(whatsapp.router)


@app.get("/sante")
def sante() -> JSONResponse:
    etat = etat_general()
    code = 200 if etat["statut"] == OK else 503
    return JSONResponse(status_code=code, content={**etat, "version": VERSION})
