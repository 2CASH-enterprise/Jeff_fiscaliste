"""Lot 2 — moteur conversationnel (messages fixes), historique, bulle web d'essai."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.conversation import messages_fixes as mf
from sqlalchemy.exc import IntegrityError

from app.conversation.models import CANAL_WEB, ENTRANT, SORTANT, Conversation
from app.conversation.moteur import (
    LONGUEUR_MAX,
    MessageVide,
    historique,
    repondre,
    traiter_message,
)
from app.canaux.web import COOKIE
from app.core.config import get_settings
from app.main import app

RACINE = Path(__file__).resolve().parent.parent


@pytest.fixture
def essai(monkeypatch):
    monkeypatch.setenv("ESSAI_ACTIF", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def sans_essai(monkeypatch):
    monkeypatch.delenv("ESSAI_ACTIF", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def nouveau_visiteur() -> TestClient:
    client = TestClient(app)
    assert client.get("/essai").status_code == 200
    return client


# --- Moteur : décisions -------------------------------------------------------

@pytest.mark.parametrize("texte", ["bonjour", "Bonjour Jeff !", "BÔNJOUR", "  salut  ", "menu", "Bonsoir."])
def test_salutation_affiche_le_menu(texte):
    reponse = repondre(texte)
    assert reponse.texte == mf.ACCUEIL
    assert reponse.choix == list(mf.MENU)
    assert [v for v, _ in reponse.choix] == ["1", "2", "3", "4"]


@pytest.mark.parametrize("valeur, libelle", mf.MENU)
def test_choix_du_menu_annonce_bientot(valeur, libelle):
    reponse = repondre(f" {valeur} ")
    assert reponse.texte == mf.BIENTOT.format(libelle=libelle)
    assert reponse.choix == []


@pytest.mark.parametrize("texte", ["5", "0", "bonjourno", "quelle est la TVA ?", "12", "1 2", "..."])
def test_message_non_compris(texte):
    assert repondre(texte).texte == mf.INCOMPRIS


def test_message_trop_long():
    assert repondre("a" * (LONGUEUR_MAX + 1)).texte == mf.TROP_LONG
    assert repondre("a" * LONGUEUR_MAX).texte == mf.INCOMPRIS


# --- Ton : vouvoiement imposé ----------------------------------------------------

TUTOIEMENT = re.compile(r"\b(tu|toi|ton|ta|tes|te|t'|tapes)\b", re.IGNORECASE)


@pytest.mark.parametrize("message", mf.TOUS)
def test_messages_fixes_sans_tutoiement(message):
    assert not TUTOIEMENT.search(message), message


def test_messages_fixes_au_vouvoiement():
    for message in (mf.ACCUEIL, mf.INCOMPRIS, mf.TROP_LONG):
        assert re.search(r"\b(vous|votre|vos)\b", message, re.IGNORECASE), message


# --- Moteur : enregistrement ------------------------------------------------------

def test_un_echange_enregistre_deux_messages(session):
    reponse = traiter_message(session, CANAL_WEB, "visiteur-a" * 3, "Bonjour")
    messages = historique(session, CANAL_WEB, "visiteur-a" * 3)
    assert [(m.sens, m.texte) for m in messages] == [(ENTRANT, "Bonjour"), (SORTANT, reponse.texte)]


def test_la_conversation_est_reprise(session):
    traiter_message(session, CANAL_WEB, "visiteur-b" * 3, "Bonjour")
    traiter_message(session, CANAL_WEB, "visiteur-b" * 3, "1")
    assert len(historique(session, CANAL_WEB, "visiteur-b" * 3)) == 4


def test_canaux_separes(session):
    traiter_message(session, CANAL_WEB, "meme-identifiant", "Bonjour")
    assert historique(session, "whatsapp", "meme-identifiant") == []
    traiter_message(session, "whatsapp", "meme-identifiant", "Bonjour")
    assert len(historique(session, CANAL_WEB, "meme-identifiant")) == 2
    assert len(historique(session, "whatsapp", "meme-identifiant")) == 2


def test_une_seule_conversation_par_canal_et_identifiant(session):
    session.add(Conversation(canal=CANAL_WEB, identifiant_externe="doublon-conversation"))
    session.flush()
    session.add(Conversation(canal=CANAL_WEB, identifiant_externe="doublon-conversation"))
    with pytest.raises(IntegrityError):
        session.flush()


@pytest.mark.parametrize("texte", ["", "   ", None])
def test_message_vide_refuse(session, texte):
    with pytest.raises(MessageVide):
        traiter_message(session, CANAL_WEB, "visiteur-c" * 3, texte)
    assert historique(session, CANAL_WEB, "visiteur-c" * 3) == []


def test_message_long_tronque_a_l_enregistrement(session):
    traiter_message(session, CANAL_WEB, "visiteur-d" * 3, "x" * (LONGUEUR_MAX + 50))
    entrant = historique(session, CANAL_WEB, "visiteur-d" * 3)[0]
    assert len(entrant.texte) == LONGUEUR_MAX


# --- Bulle web ---------------------------------------------------------------------

@pytest.mark.parametrize(
    "methode, chemin", [("get", "/essai"), ("post", "/essai/messages"), ("get", "/essai/historique")]
)
def test_essai_ferme_par_defaut(sans_essai, methode, chemin):
    client = TestClient(app)
    reponse = getattr(client, methode)(chemin, **({"json": {"texte": "Bonjour"}} if methode == "post" else {}))
    assert reponse.status_code == 404


def test_page_essai_pose_un_cookie_protege(essai):
    reponse = TestClient(app).get("/essai")
    assert reponse.status_code == 200
    assert "bootstrap.min.css" in reponse.text
    cookie = reponse.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE}=")
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie


def test_le_jeton_est_conserve_au_rechargement(essai):
    client = nouveau_visiteur()
    jeton = client.cookies[COOKIE]
    client.get("/essai")
    assert client.cookies[COOKIE] == jeton


def test_echange_complet_dans_la_bulle(essai):
    client = nouveau_visiteur()
    reponse = client.post("/essai/messages", json={"texte": "Bonjour"})
    assert reponse.status_code == 200
    assert reponse.json()["reponse"] == mf.ACCUEIL
    assert reponse.json()["choix"][0] == {"valeur": "1", "libelle": "Préparer ma déclaration"}
    client.post("/essai/messages", json={"texte": "3"})
    messages = client.get("/essai/historique").json()["messages"]
    assert [m["sens"] for m in messages] == [ENTRANT, SORTANT, ENTRANT, SORTANT]
    assert messages[3]["texte"] == mf.BIENTOT.format(libelle="Voir mes échéances")


def test_un_autre_visiteur_ne_voit_rien(essai):
    alice = nouveau_visiteur()
    alice.post("/essai/messages", json={"texte": "Mon chiffre d'affaires est secret"})
    bruno = nouveau_visiteur()
    assert bruno.get("/essai/historique").json() == {"messages": []}
    assert alice.cookies[COOKIE] != bruno.cookies[COOKIE]


def test_message_refuse_sans_session(essai):
    reponse = TestClient(app).post("/essai/messages", json={"texte": "Bonjour"})
    assert reponse.status_code == 401


def test_jeton_fabrique_refuse(essai):
    client = TestClient(app, cookies={COOKIE: "court"})
    assert client.post("/essai/messages", json={"texte": "Bonjour"}).status_code == 401
    client = TestClient(app, cookies={COOKIE: "<script>alert(1)</script>" + "x" * 20})
    assert client.post("/essai/messages", json={"texte": "Bonjour"}).status_code == 401


def test_historique_vide_sans_session(essai):
    assert TestClient(app).get("/essai/historique").json() == {"messages": []}


def test_message_vide_dans_la_bulle(essai):
    client = nouveau_visiteur()
    assert client.post("/essai/messages", json={"texte": "   "}).status_code == 422


def test_styles_servis_par_jeff(essai):
    client = TestClient(app)
    assert client.get("/static/vendor/bootstrap/bootstrap.min.css").status_code == 200
    assert client.get("/static/css/jeff.css").status_code == 200
    assert client.get("/static/js/essai.js").status_code == 200


# --- Sécurité de l'interface ---------------------------------------------------------

def test_le_script_n_insere_jamais_de_html():
    script = (RACINE / "app/static/js/essai.js").read_text()
    assert "innerHTML" not in script
    assert "insertAdjacentHTML" not in script
    assert "textContent" in script


def test_le_gabarit_n_utilise_pas_safe():
    for gabarit in (RACINE / "app/templates").glob("*.html"):
        assert "|safe" not in gabarit.read_text().replace(" ", "")


# --- Correctifs du socle ----------------------------------------------------------------

def test_port_par_defaut_8020():
    assert "JEFF_PORT=8020" in (RACINE / ".env.example").read_text()
    assert "${JEFF_PORT:-8020}" in (RACINE / "docker-compose.yml").read_text()


def test_l_application_seule_connait_tous_ses_modeles():
    """Conditions réelles : un processus neuf qui ne charge que app.main (comme uvicorn)."""
    import subprocess
    import sys

    code = (
        "from app.main import app\n"
        "from app.core.db import Base\n"
        "for table in Base.metadata.tables.values():\n"
        "    for cle in table.foreign_keys:\n"
        "        cle.column\n"
        "print('ok')\n"
    )
    resultat = subprocess.run([sys.executable, "-c", code], cwd=RACINE, capture_output=True, text=True)
    assert resultat.returncode == 0, resultat.stderr
    assert resultat.stdout.strip() == "ok"
