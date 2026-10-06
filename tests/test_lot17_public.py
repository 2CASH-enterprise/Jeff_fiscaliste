"""Lot 17 — coffre public derrière nginx : préfixe /jeff, en-têtes de sécurité, limite par IP, nettoyage."""
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from app.core.config import VERSION
from app.core.db import get_engine
from app.core.proxy import PREFIXE_VALIDE
from app.espace import connexion
from app.espace import textes as tx
from app.espace.models import DemandeConnexion
from app.main import app
from app.worker import celery_app
from tests.test_lot12_espace import adresse_unique, creer, dernier_code, espace, texte_visible  # noqa: F401

RACINE = Path(__file__).resolve().parent.parent
PUBLIC = {"X-Forwarded-Prefix": "/jeff"}


def public(**kwargs) -> TestClient:
    return TestClient(app, base_url="https://agenc-ai.com", headers=PUBLIC, follow_redirects=False, **kwargs)


def connecter_en_public(session, adresse, client=None) -> TestClient:
    client = client or public()
    # Le navigateur appelle l'adresse publique (/jeff/…) : ses cookies ont le chemin /jeff/espace.
    reponse = client.post("/jeff/espace/connexion", data={"email": adresse})
    assert reponse.status_code == 303, reponse.text
    reponse = client.post("/jeff/espace/code", data={"code": dernier_code(session, adresse)})
    assert reponse.status_code == 303
    return client


# --- Préfixe public -----------------------------------------------------------------------------

def test_liens_et_ressources_avec_le_prefixe(espace, session):
    html = public().get("/espace/connexion").text
    assert 'action="https://agenc-ai.com/jeff/espace/connexion"' in html
    assert 'href="https://agenc-ai.com/jeff/static/css/espace.css"' in html
    assert 'src="https://agenc-ai.com/jeff/static/img/logo-jeff.webp"' in html
    assert '"/espace/' not in html and "testserver" not in html


def test_redirections_et_cookies_avec_le_prefixe(espace, session, monkeypatch):
    monkeypatch.setenv("ENVIRONNEMENT", "production")
    from app.core.config import get_settings

    get_settings.cache_clear()
    adresse = adresse_unique()
    creer(session, "Ets Public", adresse)
    client = public()
    reponse = client.post("/jeff/espace/connexion", data={"email": adresse})
    assert reponse.headers["location"] == "https://agenc-ai.com/jeff/espace/code"
    cookie = reponse.headers["set-cookie"]
    assert "Path=/jeff/espace" in cookie and "Secure" in cookie and "HttpOnly" in cookie
    reponse = client.post("/jeff/espace/code", data={"code": dernier_code(session, adresse)})
    assert reponse.headers["location"] == "https://agenc-ai.com/jeff/espace/accueil"
    session_cookie = [c for c in reponse.headers.get_list("set-cookie") if c.startswith("jeff_espace=")][0]
    assert "Path=/jeff/espace" in session_cookie and "Secure" in session_cookie
    accueil = client.get("/jeff/espace/accueil").text
    assert 'href="https://agenc-ai.com/jeff/espace/echeances"' in accueil


def test_sans_en_tete_rien_ne_change(espace, session):
    html = TestClient(app).get("/espace/connexion").text
    assert 'action="http://testserver/espace/connexion"' in html and "/jeff/" not in html


@pytest.mark.parametrize("prefixe", ["jeff", "/jeff/espace", "/../x", "/a b", "//evil.com", "/" + "a" * 31, "/%C3%A9"])
def test_prefixe_invalide_ignore(espace, prefixe):
    html = TestClient(app, headers={"X-Forwarded-Prefix": prefixe}).get("/espace/connexion").text
    assert 'action="http://testserver/espace/connexion"' in html


@pytest.mark.parametrize("prefixe,valide", [("/jeff", True), ("/a-b_9", True), ("/" + "a" * 30, True), ("/", False), ("", False)])
def test_forme_du_prefixe(prefixe, valide):
    assert bool(PREFIXE_VALIDE.match(prefixe)) is valide


def test_le_prefixe_ne_vaut_que_pour_la_requete(espace):
    assert "/jeff/" in public().get("/espace/connexion").text
    assert "/jeff/" not in TestClient(app).get("/espace/connexion").text


# --- En-têtes de sécurité -----------------------------------------------------------------------

def test_en_tetes_des_pages_du_coffre(espace):
    reponse = public().get("/espace/connexion")
    assert reponse.headers["x-frame-options"] == "DENY"
    assert reponse.headers["x-content-type-options"] == "nosniff"
    assert reponse.headers["referrer-policy"] == "same-origin"
    assert reponse.headers["permissions-policy"] == "geolocation=(), microphone=(), payment=()"
    assert reponse.headers["cache-control"] == "private, no-store"
    redirection = public().get("/espace")
    assert redirection.status_code == 303 and redirection.headers["x-frame-options"] == "DENY"


def test_en_tetes_deja_poses_gardes(espace, session, tmp_path, monkeypatch):
    """Un document garde son propre Cache-Control et n'est pas doublé."""
    from io import BytesIO

    from app.core.config import get_settings
    from app.documents import stockage

    monkeypatch.setenv("DOCUMENTS_DOSSIER", str(tmp_path))
    get_settings.cache_clear()
    adresse = adresse_unique()
    e = creer(session, "Ets Entêtes", adresse)
    document = stockage.deposer(session, e, BytesIO(b"\x89PNG\r\n\x1a\n" + b"0" * 10), "x.png", "autre", datetime(2026, 10, 1).date(), None)
    client = connecter_en_public(session, adresse)
    reponse = client.get(f"/jeff/espace/documents/{document.id}/fichier")
    assert reponse.headers.get_list("cache-control") == ["private, no-store"]
    assert reponse.headers.get_list("x-content-type-options") == ["nosniff"]
    assert reponse.headers["x-frame-options"] == "DENY"


def test_pas_d_en_tetes_du_coffre_ailleurs():
    reponse = TestClient(app).get("/sante")
    assert "x-frame-options" not in reponse.headers and "cache-control" not in reponse.headers


# --- Limite par adresse IP ----------------------------------------------------------------------

def test_vingt_demandes_par_ip_et_par_heure(session):
    assert connexion.DEMANDES_PAR_IP_ET_PAR_HEURE == 20 and connexion.DEMANDES_PAR_HEURE == 5
    ip = "203.0.113.7"
    for _ in range(connexion.DEMANDES_PAR_IP_ET_PAR_HEURE):
        demande = connexion.demander_code(session, adresse_unique(), ip)
    assert demande.ip == ip
    with pytest.raises(connexion.TropDeDemandes):
        connexion.demander_code(session, adresse_unique(), ip)
    connexion.demander_code(session, adresse_unique(), "203.0.113.8")  # Une autre adresse IP passe.
    connexion.demander_code(session, adresse_unique(), None)  # Sans IP (tâche, test) : pas de limite IP.
    for d in session.scalars(select(DemandeConnexion).where(DemandeConnexion.ip == ip)):
        d.cree_le = datetime.now(timezone.utc) - timedelta(minutes=61)
    session.flush()
    connexion.demander_code(session, adresse_unique(), ip)  # Les anciennes ne comptent plus.


def test_ip_tronquee_et_vide(session):
    assert connexion.demander_code(session, adresse_unique(), "x" * 60).ip == "x" * 45
    assert connexion.demander_code(session, adresse_unique(), "").ip is None


def test_ip_du_visiteur_enregistree(espace, session):
    adresse = adresse_unique()
    public(client=("198.51.100.4", 4444)).post("/espace/connexion", data={"email": adresse})
    assert session.scalars(select(DemandeConnexion).where(DemandeConnexion.email == adresse)).one().ip == "198.51.100.4"


def test_trop_de_demandes_depuis_une_ip(espace, session):
    client = public(client=("198.51.100.9", 4444))
    for _ in range(connexion.DEMANDES_PAR_IP_ET_PAR_HEURE):
        assert client.post("/espace/connexion", data={"email": adresse_unique()}).status_code == 303
    reponse = client.post("/espace/connexion", data={"email": adresse_unique()})
    assert reponse.status_code == 429 and tx.TROP_DE_DEMANDES in texte_visible(reponse.text)


def test_sans_client_connu(espace, session, monkeypatch):
    from app.canaux import espace as canal

    vus = []
    monkeypatch.setattr(canal.connexion, "demander_code", lambda s, e, ip=None: vus.append(ip) or (_ for _ in ()).throw(connexion.TropDeDemandes()))

    async def sans_client(scope, receive, send):
        await app({**scope, "client": None}, receive, send)

    TestClient(sans_client).post("/espace/connexion", data={"email": adresse_unique()})
    assert vus == [None]


# --- Nettoyage ----------------------------------------------------------------------------------

def test_nettoyage_des_vieilles_demandes(session):
    vieille, recente, limite = (connexion.demander_code(session, adresse_unique()) for _ in range(3))
    maintenant = datetime.now(timezone.utc)
    vieille.cree_le = maintenant - timedelta(days=8)
    limite.cree_le = maintenant - timedelta(days=7) + timedelta(minutes=5)
    session.flush()
    assert connexion.GARDER_DEMANDES == timedelta(days=7)
    assert connexion.nettoyer(session) >= 1
    restantes = {d.id for d in session.scalars(select(DemandeConnexion))}
    assert vieille.id not in restantes and recente.id in restantes and limite.id in restantes


def test_tache_planifiee_chaque_nuit():
    planif = celery_app.conf.beat_schedule["nettoyer-espace"]
    assert planif["task"] == "jeff.nettoyer_espace"
    assert planif["schedule"].hour == {4} and planif["schedule"].minute == {0}
    assert celery_app.conf.timezone == "Africa/Douala"


def test_tache_de_nettoyage(monkeypatch):
    from app import worker

    appels = []

    class FausseSession:
        def commit(self):
            appels.append("commit")

        def rollback(self):
            appels.append("rollback")

        def close(self):
            appels.append("close")

    monkeypatch.setattr("app.core.db.get_session", lambda: FausseSession())
    monkeypatch.setattr("app.espace.connexion.nettoyer", lambda s: 3)
    assert worker.tache_nettoyer_espace() == 3 and appels == ["commit", "close"]
    appels.clear()

    def echec(_session):
        raise RuntimeError("base indisponible")

    monkeypatch.setattr("app.espace.connexion.nettoyer", echec)
    with pytest.raises(RuntimeError):
        worker.tache_nettoyer_espace()
    assert appels == ["rollback", "close"]


# --- Déploiement --------------------------------------------------------------------------------

def test_bloc_nginx():
    conf = (RACINE / "deploy/nginx/jeff-espace.conf").read_text()
    for attendu in (
        "location = /jeff/espace { return 302 /jeff/espace/connexion; }",
        "location = /jeff/espace/ { return 302 /jeff/espace/connexion; }",
        "location /jeff/espace/ {\n    proxy_pass http://127.0.0.1:8020/espace/;",
        "proxy_set_header X-Forwarded-For $remote_addr;",
        "proxy_set_header X-Forwarded-Proto $scheme;",
        "proxy_set_header X-Forwarded-Prefix /jeff;",
        "client_max_body_size 11m;",
        "location /jeff/static/ {\n    proxy_pass http://127.0.0.1:8020/static/;",
    ):
        assert attendu in conf, attendu
    assert "proxy_add_x_forwarded_for" not in conf
    assert not re.search(r"location[^{]*/(essai|sante|docs)", conf)


def test_uvicorn_lit_les_en_tetes_du_proxy():
    dockerfile = (RACINE / "Dockerfile").read_text()
    assert '"--proxy-headers", "--forwarded-allow-ips", "*"' in dockerfile
    assert '"127.0.0.1:${JEFF_PORT:-8020}:8000"' in (RACINE / "docker-compose.yml").read_text()


def test_colonne_ip():
    inspecteur = inspect(get_engine())
    colonne = {c["name"]: c for c in inspecteur.get_columns("demandes_connexion")}["ip"]
    assert colonne["nullable"] is True and colonne["type"].length == 45


def test_version():
    assert VERSION == "0.17.0"
