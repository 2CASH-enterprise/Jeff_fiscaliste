"""Point d'entrée de l'application web Jeff."""
from fastapi import FastAPI
from fastapi.responses import JSONResponse

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


@app.get("/sante")
def sante() -> JSONResponse:
    etat = etat_general()
    code = 200 if etat["statut"] == OK else 503
    return JSONResponse(status_code=code, content={**etat, "version": VERSION})
