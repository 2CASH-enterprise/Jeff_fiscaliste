"""Point d'entrée de l'application web Jeff."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import models as _modeles  # noqa: F401 — enregistre tous les modèles avant la première requête
from app.canaux import web
from app.core.config import VERSION, get_settings
from app.core.sante import OK, etat_general

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


@app.get("/sante")
def sante() -> JSONResponse:
    etat = etat_general()
    code = 200 if etat["statut"] == OK else 503
    return JSONResponse(status_code=code, content={**etat, "version": VERSION})
