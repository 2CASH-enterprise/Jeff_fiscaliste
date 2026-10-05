"""Canal web : coffre fiscal du client (lot 12).

Les pages n'existent que si ESPACE_ACTIF=true. Connexion par code email, puis session de
30 jours gardée dans un cookie HttpOnly. Chaque page vérifie de nouveau que l'adresse de la
session est toujours confirmée pour l'entreprise affichée.
"""
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.conversation.onboarding import ReponseInvalide, lire_email
from app.core.config import get_settings
from app.core.db import session_requete
from app.espace import connexion, donnees
from app.espace import textes as tx

COOKIE_DEMANDE = "jeff_connexion"
COOKIE_SESSION = "jeff_espace"
DUREE_COOKIE_DEMANDE = 3600
DUREE_COOKIE_SESSION = int(connexion.DUREE_SESSION.total_seconds())
BIENTOT = ("documents",)

MESSAGES_CODE = {
    connexion.FORMAT: tx.CODE_FORMAT,
    connexion.EXPIRE: tx.CODE_EXPIRE,
    connexion.FAUX: tx.CODE_FAUX,
}
RETOUR_CONNEXION = {
    connexion.TROP_D_ESSAIS: tx.CODE_TROP_D_ESSAIS,
    connexion.AUCUNE: tx.CONNEXION_IMPOSSIBLE,
    connexion.INVALIDE: tx.CODE_INVALIDE,
}

templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")
templates.env.globals["tx"] = tx


def espace_actif() -> None:
    if not get_settings().espace_actif:
        raise HTTPException(status_code=404)


router = APIRouter(prefix="/espace", dependencies=[Depends(espace_actif)])


# --- Outils -------------------------------------------------------------------------------------

def chemin_cookie(request: Request) -> str:
    # Derrière nginx (lot 16), l'application sera servie sous un préfixe : le cookie le suit.
    return request.scope.get("root_path", "") + "/espace"


def poser_cookie(request: Request, reponse, nom: str, valeur: str, duree: int) -> None:
    reponse.set_cookie(
        nom,
        valeur,
        max_age=duree,
        path=chemin_cookie(request),
        httponly=True,
        samesite="lax",
        secure=get_settings().environnement == "production" and request.url.scheme == "https",
    )


def effacer_cookie(request: Request, reponse, nom: str) -> None:
    reponse.delete_cookie(nom, path=chemin_cookie(request))


def aller(request: Request, page: str, **parametres) -> RedirectResponse:
    adresse = str(request.url_for(page))
    if parametres:
        adresse += "?" + "&".join(f"{cle}={valeur}" for cle, valeur in parametres.items())
    return RedirectResponse(adresse, status_code=303)


def page(request: Request, gabarit: str, contexte: dict, statut: int = 200) -> HTMLResponse:
    return templates.TemplateResponse(request, f"espace/{gabarit}", contexte, status_code=statut)


def session_du_navigateur(request: Request, session: Session):
    return connexion.session_active(session, request.cookies.get(COOKIE_SESSION))


def contexte_espace(request: Request, session: Session, onglet: str):
    """Session et entreprise affichée, ou la redirection à faire (connexion ou choix)."""
    ouverte = session_du_navigateur(request, session)
    if ouverte is None:
        return None, aller(request, "espace_connexion")
    entreprise = connexion.entreprise_courante(session, ouverte)
    if entreprise is None:
        session.commit()
        return None, aller(request, "espace_choix")
    return {
        "onglet": onglet,
        "entreprise": entreprise,
        "plusieurs": len(connexion.entreprises_de(session, ouverte)) > 1,
    }, None


# --- Entrée et connexion ------------------------------------------------------------------------

@router.get("", name="espace_entree")
def entree(request: Request, session: Session = Depends(session_requete)):
    if session_du_navigateur(request, session) is None:
        return aller(request, "espace_connexion")
    return aller(request, "espace_accueil")


@router.get("/connexion", response_class=HTMLResponse, name="espace_connexion")
def formulaire_connexion(request: Request, info: str = "", session: Session = Depends(session_requete)):
    if session_du_navigateur(request, session) is not None:
        return aller(request, "espace_accueil")
    messages = {"deconnecte": tx.DECONNECTE, **{cle: texte for cle, texte in RETOUR_CONNEXION.items()}}
    return page(request, "connexion.html", {"info": messages.get(info), "erreur": None, "email": ""})


@router.post("/connexion", response_class=HTMLResponse)
def demander_code(request: Request, email: str = Form(""), session: Session = Depends(session_requete)):
    try:
        adresse = lire_email(email, session)
    except ReponseInvalide:
        adresse = None
    if adresse is None:
        return page(request, "connexion.html", {"info": None, "erreur": tx.ERR_EMAIL, "email": email[:254]}, 400)
    try:
        demande = connexion.demander_code(session, adresse)
    except connexion.TropDeDemandes:
        return page(request, "connexion.html", {"info": None, "erreur": tx.TROP_DE_DEMANDES, "email": adresse}, 429)
    session.commit()
    reponse = aller(request, "espace_code")
    poser_cookie(request, reponse, COOKIE_DEMANDE, str(demande.id), DUREE_COOKIE_DEMANDE)
    return reponse


@router.get("/code", response_class=HTMLResponse, name="espace_code")
def formulaire_code(request: Request, session: Session = Depends(session_requete)):
    demande = connexion.demande_en_cours(session, request.cookies.get(COOKIE_DEMANDE))
    if demande is None:
        return aller(request, "espace_connexion")
    return page(request, "code.html", {"email": demande.email, "erreur": None, "info": None})


@router.post("/code", response_class=HTMLResponse)
def verifier_code(
    request: Request,
    code: str = Form(""),
    action: str = Form("valider"),
    session: Session = Depends(session_requete),
):
    demande = connexion.demande_en_cours(session, request.cookies.get(COOKIE_DEMANDE))
    if demande is None:
        return aller(request, "espace_connexion", info=connexion.INVALIDE)

    if action == "renvoyer":
        if connexion.renvoyer(session, demande):
            return page(request, "code.html", {"email": demande.email, "erreur": None, "info": tx.CODE_RENVOYE})
        return page(request, "code.html", {"email": demande.email, "erreur": tx.CODE_TROP_DE_RENVOIS, "info": None}, 429)

    resultat, entreprises = connexion.verifier_code(session, demande, code)
    if resultat in MESSAGES_CODE:
        return page(request, "code.html", {"email": demande.email, "erreur": MESSAGES_CODE[resultat], "info": None}, 400)
    if resultat != connexion.OK:
        session.commit()
        reponse = aller(request, "espace_connexion", info=resultat)
        effacer_cookie(request, reponse, COOKIE_DEMANDE)
        return reponse

    jeton, ouverte = connexion.ouvrir_session(session, demande.email, entreprises, request.headers.get("user-agent"))
    session.commit()
    reponse = aller(request, "espace_accueil" if ouverte.entreprise_id else "espace_choix")
    effacer_cookie(request, reponse, COOKIE_DEMANDE)
    poser_cookie(request, reponse, COOKIE_SESSION, jeton, DUREE_COOKIE_SESSION)
    return reponse


@router.get("/choix", response_class=HTMLResponse, name="espace_choix")
def formulaire_choix(request: Request, session: Session = Depends(session_requete)):
    ouverte = session_du_navigateur(request, session)
    if ouverte is None:
        return aller(request, "espace_connexion")
    entreprises = connexion.entreprises_de(session, ouverte)
    if not entreprises:
        connexion.fermer(ouverte)
        session.commit()
        reponse = aller(request, "espace_connexion", info=connexion.AUCUNE)
        effacer_cookie(request, reponse, COOKIE_SESSION)
        return reponse
    return page(request, "choix.html", {"entreprises": entreprises, "courante": ouverte.entreprise_id})


@router.post("/choix")
def choisir(request: Request, entreprise: str = Form(""), session: Session = Depends(session_requete)):
    ouverte = session_du_navigateur(request, session)
    if ouverte is None:
        return aller(request, "espace_connexion")
    if not connexion.choisir(session, ouverte, entreprise):
        return aller(request, "espace_choix")
    session.commit()
    return aller(request, "espace_accueil")


@router.post("/deconnexion", name="espace_deconnexion")
def deconnexion(request: Request, session: Session = Depends(session_requete)):
    ouverte = session_du_navigateur(request, session)
    if ouverte is not None:
        connexion.fermer(ouverte)
        session.commit()
    reponse = aller(request, "espace_connexion", info="deconnecte")
    effacer_cookie(request, reponse, COOKIE_SESSION)
    return reponse


# --- Onglets ------------------------------------------------------------------------------------

@router.get("/accueil", response_class=HTMLResponse, name="espace_accueil")
def accueil(request: Request, session: Session = Depends(session_requete)):
    contexte, redirection = contexte_espace(request, session, "accueil")
    if redirection:
        return redirection
    contexte["tableau"] = donnees.tableau(session, contexte["entreprise"])
    return page(request, "accueil.html", contexte)


@router.get("/entreprise", response_class=HTMLResponse, name="espace_entreprise")
def entreprise(request: Request, session: Session = Depends(session_requete)):
    contexte, redirection = contexte_espace(request, session, "entreprise")
    if redirection:
        return redirection
    contexte["fiche"] = donnees.fiche(session, contexte["entreprise"])
    return page(request, "entreprise.html", contexte)


@router.get("/echeances", response_class=HTMLResponse, name="espace_echeances")
def echeances(request: Request, mois: str = "", session: Session = Depends(session_requete)):
    contexte, redirection = contexte_espace(request, session, "echeances")
    if redirection:
        return redirection
    contexte["mois"] = donnees.mois_affiche(session, contexte["entreprise"], mois[:7])
    contexte["filtre_du_domaine"] = donnees.FILTRE_DU_DOMAINE
    return page(request, "echeances.html", contexte)


@router.get("/obligations", response_class=HTMLResponse, name="espace_obligations")
def obligations(request: Request, filtre: str = "", session: Session = Depends(session_requete)):
    contexte, redirection = contexte_espace(request, session, "obligations")
    if redirection:
        return redirection
    contexte["filtre"] = filtre if filtre in donnees.FILTRES else donnees.FISCALES
    contexte["obligations"] = donnees.obligations(session, contexte["entreprise"])
    return page(request, "obligations.html", contexte)


def bientot(onglet: str):
    def vue(request: Request, session: Session = Depends(session_requete)):
        contexte, redirection = contexte_espace(request, session, onglet)
        if redirection:
            return redirection
        contexte["texte"] = tx.BIENTOT[onglet]
        return page(request, "bientot.html", contexte)

    return vue


for _onglet in BIENTOT:
    router.add_api_route(
        f"/{_onglet}", bientot(_onglet), methods=["GET"], response_class=HTMLResponse, name=f"espace_{_onglet}"
    )
