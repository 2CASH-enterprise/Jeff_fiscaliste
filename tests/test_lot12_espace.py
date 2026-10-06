"""Lot 12 — coffre fiscal : connexion par code email, session de 30 jours, choix d'entreprise, onglets."""
import re
import subprocess
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from app.conversation.models import CANAL_WHATSAPP, Conversation
from app.core.config import VERSION, get_settings
from app.core.db import get_engine, session_requete
from app.emails.models import CODE, Email
from app.entreprises.models import Entreprise
from app.espace import connexion, donnees
from app.espace import textes as tx
from app.espace.models import ABANDONNEE, EN_COURS, UTILISEE, DemandeConnexion, SessionEspace
from app.canaux import espace as canal
from app.main import app
from app.regles.chargement import charger_fichier
from tests.test_lot02_bulle_web import TUTOIEMENT
from tests.test_lot03_onboarding import niu_unique
from tests.test_lot07_rappels import FICHIER_CM, TITRE_TVA

MAINTENANT = datetime.now(timezone.utc)


# --- Outils ---------------------------------------------------------------------------------------

@pytest.fixture
def espace(monkeypatch, session):
    monkeypatch.setenv("ESPACE_ACTIF", "true")
    get_settings.cache_clear()

    def session_de_test():
        yield session
        session.flush()

    app.dependency_overrides[session_requete] = session_de_test
    yield
    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.fixture
def regles(session):
    charger_fichier(session, FICHIER_CM)


def adresse_unique() -> str:
    return f"gerant.{uuid.uuid4().hex[:10]}@exemple.cm"


def creer(session, nom="Ets Coffre", email=None, confirmee=True, **profil) -> Entreprise:
    valeurs = {"regime_declare": "reel", "assujetti_tva_declare": True, "nombre_salaries": 0, **profil}
    e = Entreprise(juridiction_code="CM", niu=niu_unique(), raison_sociale=nom, email=email,
                   email_confirme_le=MAINTENANT if (email and confirmee) else None, **valeurs)
    session.add(e)
    session.flush()
    return e


def navigateur() -> TestClient:
    return TestClient(app, follow_redirects=False)


def dernier_code(session, adresse) -> str:
    email = session.scalars(select(Email).where(Email.destinataire == adresse).order_by(Email.id.desc())).first()
    return re.search(r"\b(\d{6})\b", email.texte).group(1)


def codes_envoyes(session, adresse) -> list[Email]:
    return list(session.scalars(select(Email).where(Email.destinataire == adresse).order_by(Email.id)))


def chemin(reponse) -> str:
    return reponse.headers["location"].split("testserver", 1)[1]


def demander(client, adresse):
    reponse = client.post("/espace/connexion", data={"email": adresse})
    assert reponse.status_code == 303 and chemin(reponse) == "/espace/code"
    return reponse


def connecter(session, adresse, client=None) -> TestClient:
    client = client or navigateur()
    demander(client, adresse)
    reponse = client.post("/espace/code", data={"code": dernier_code(session, adresse)})
    assert reponse.status_code == 303
    return client


class Texte(HTMLParser):
    """Texte visible d'une page, pour vérifier le ton."""

    def __init__(self):
        super().__init__()
        self.morceaux, self.ignorer = [], 0

    def handle_starttag(self, balise, attributs):
        self.ignorer += balise in ("script", "style")

    def handle_endtag(self, balise):
        self.ignorer -= balise in ("script", "style")

    def handle_data(self, donnees_):
        if not self.ignorer:
            self.morceaux.append(donnees_)


def texte_visible(html: str) -> str:
    lecteur = Texte()
    lecteur.feed(html)
    return " ".join(" ".join(lecteur.morceaux).split())


# --- Interrupteur -------------------------------------------------------------------------------

@pytest.mark.parametrize("adresse", ["/espace", "/espace/connexion", "/espace/accueil", "/espace/documents"])
def test_coffre_ferme_par_defaut(monkeypatch, adresse):
    monkeypatch.delenv("ESPACE_ACTIF", raising=False)
    get_settings.cache_clear()
    try:
        assert TestClient(app).get(adresse).status_code == 404
    finally:
        get_settings.cache_clear()


def test_reglage_coupe_par_defaut(monkeypatch):
    monkeypatch.delenv("ESPACE_ACTIF", raising=False)
    get_settings.cache_clear()
    assert get_settings().espace_actif is False
    get_settings.cache_clear()


def test_exemple_env_coupe():
    with open(".env.example", encoding="utf-8") as f:
        assert "\nESPACE_ACTIF=false\n" in f.read()


# --- Connexion : demande de code ----------------------------------------------------------------

def test_entree_sans_session_vers_la_connexion(espace):
    reponse = navigateur().get("/espace")
    assert reponse.status_code == 303 and chemin(reponse) == "/espace/connexion"


def test_page_de_connexion(espace):
    reponse = navigateur().get("/espace/connexion")
    assert reponse.status_code == 200
    assert tx.CONNEXION_INTRO.replace("'", "&#39;") in reponse.text
    assert 'name="email"' in reponse.text and 'autocomplete="email"' in reponse.text
    assert "img/logo-jeff.webp" in reponse.text


@pytest.mark.parametrize("info,attendu", [
    ("deconnecte", tx.DECONNECTE), ("trop_d_essais", tx.CODE_TROP_D_ESSAIS),
    ("aucune", tx.CONNEXION_IMPOSSIBLE), ("invalide", tx.CODE_INVALIDE),
])
def test_messages_de_retour(espace, info, attendu):
    texte = texte_visible(navigateur().get(f"/espace/connexion?info={info}").text)
    assert attendu in texte


def test_message_de_retour_inconnu_ignore(espace):
    html = navigateur().get("/espace/connexion?info=<script>").text
    assert "esp-message" not in html and "<script>" not in html.split("</head>")[1]


def test_code_envoye_pour_une_adresse_confirmee(espace, session):
    adresse = adresse_unique()
    creer(session, "Ets Alpha", adresse)
    client = navigateur()
    reponse = demander(client, adresse.upper())
    cookie = reponse.headers["set-cookie"]
    assert cookie.startswith(f"{canal.COOKIE_DEMANDE}=")
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/espace" in cookie
    assert "Max-Age=3600;" in cookie + ";" and "Secure" not in cookie
    [email] = codes_envoyes(session, adresse)
    assert email.type == CODE and email.objet == tx.EMAIL_CONNEXION_OBJET
    assert "« Ets Alpha »" in email.texte and email.texte.endswith("Jeff, votre assistant fiscal.")
    demande = session.scalars(select(DemandeConnexion).where(DemandeConnexion.email == adresse)).one()
    code = dernier_code(session, adresse)
    assert demande.empreinte == connexion.empreinte_code(demande, code) and code not in demande.empreinte
    assert demande.statut == EN_COURS and demande.essais == 0 and demande.renvois == 0
    assert timedelta(minutes=14) < demande.expire_le - datetime.now(timezone.utc) <= timedelta(minutes=15)
    page = client.get("/espace/code")
    assert page.status_code == 200 and adresse in page.text
    assert 'autocomplete="one-time-code"' in page.text


def test_un_seul_email_pour_plusieurs_entreprises(espace, session):
    adresse = adresse_unique()
    creer(session, "Zeta SARL", adresse)
    creer(session, "Alpha SA", adresse)
    demander(navigateur(), adresse)
    [email] = codes_envoyes(session, adresse)
    assert "« Alpha SA », « Zeta SARL »" in email.texte


@pytest.mark.parametrize("cas", ["inconnue", "non_confirmee"])
def test_meme_reponse_si_adresse_inconnue_ou_non_confirmee(espace, session, cas):
    adresse = adresse_unique()
    if cas == "non_confirmee":
        creer(session, "Ets Beta", adresse, confirmee=False)
    client = navigateur()
    demander(client, adresse)
    assert codes_envoyes(session, adresse) == []
    demande = session.scalars(select(DemandeConnexion).where(DemandeConnexion.email == adresse)).one()
    assert demande.empreinte is None
    page = client.get("/espace/code")
    assert tx.CODE_ENVOYE.format(email=adresse).replace("'", "&#39;") in page.text
    # Aucun code ne peut convenir, même le bon format.
    reponse = client.post("/espace/code", data={"code": "123456"})
    assert reponse.status_code == 400 and tx.CODE_FAUX in texte_visible(reponse.text) and demande.essais == 1


def test_autre_juridiction_n_ouvre_rien(espace, session, monkeypatch):
    adresse = adresse_unique()
    creer(session, "Ets Gamma", adresse)
    monkeypatch.setenv("JURIDICTION", "SN")
    get_settings.cache_clear()
    demander(navigateur(), adresse)
    assert codes_envoyes(session, adresse) == []


@pytest.mark.parametrize("saisie", ["", "pas-une-adresse", "a@b", "x" * 250 + "@exemple.cm", "plus tard"])
def test_adresse_invalide(espace, saisie):
    reponse = navigateur().post("/espace/connexion", data={"email": saisie})
    assert reponse.status_code == 400
    assert tx.ERR_EMAIL in texte_visible(reponse.text)
    assert canal.COOKIE_DEMANDE not in reponse.headers.get("set-cookie", "")


def test_adresse_invalide_echappee(espace):
    reponse = navigateur().post("/espace/connexion", data={"email": '"><script>alert(1)</script>'})
    assert "<script>alert(1)" not in reponse.text


def test_cinq_demandes_par_heure_au_plus(espace, session):
    adresse = adresse_unique()
    creer(session, "Ets Delta", adresse)
    for _ in range(connexion.DEMANDES_PAR_HEURE):
        demander(navigateur(), adresse)
    reponse = navigateur().post("/espace/connexion", data={"email": adresse})
    assert reponse.status_code == 429 and tx.TROP_DE_DEMANDES in texte_visible(reponse.text)
    assert len(codes_envoyes(session, adresse)) == connexion.DEMANDES_PAR_HEURE
    assert connexion.DEMANDES_PAR_HEURE == 5


def test_limite_par_adresse_et_sur_une_heure(espace, session):
    adresse = adresse_unique()
    for _ in range(connexion.DEMANDES_PAR_HEURE):
        connexion.demander_code(session, adresse)
    connexion.demander_code(session, adresse_unique())  # Une autre adresse n'est pas limitée.
    for demande in session.scalars(select(DemandeConnexion).where(DemandeConnexion.email == adresse)):
        demande.cree_le = MAINTENANT - timedelta(minutes=61)
    session.flush()
    connexion.demander_code(session, adresse)  # Les anciennes demandes ne comptent plus.


# --- Connexion : code ---------------------------------------------------------------------------

def test_page_code_sans_demande(espace):
    reponse = navigateur().get("/espace/code")
    assert reponse.status_code == 303 and chemin(reponse) == "/espace/connexion"


@pytest.mark.parametrize("cookie", ["", "abc", str(uuid.uuid4())])
def test_code_avec_demande_inconnue(espace, cookie):
    client = navigateur()
    client.cookies.set(canal.COOKIE_DEMANDE, cookie, path="/espace")
    reponse = client.post("/espace/code", data={"code": "123456"})
    assert reponse.status_code == 303 and chemin(reponse) == "/espace/connexion?info=invalide"


def test_bon_code_une_entreprise(espace, session):
    adresse = adresse_unique()
    e = creer(session, "Ets Epsilon", adresse)
    client = navigateur()
    demander(client, adresse)
    code = dernier_code(session, adresse)
    reponse = client.post("/espace/code", data={"code": f"{code[:3]} {code[3:]}"})
    assert reponse.status_code == 303 and chemin(reponse) == "/espace/accueil"
    cookies = reponse.headers.get_list("set-cookie")
    [jeton] = [c for c in cookies if c.startswith(f"{canal.COOKIE_SESSION}=")]
    assert "HttpOnly" in jeton and "SameSite=lax" in jeton and "Path=/espace" in jeton
    assert f"Max-Age={30 * 24 * 3600}" in jeton
    assert any(c.startswith(f'{canal.COOKIE_DEMANDE}=""') and "Max-Age=0" in c for c in cookies)
    valeur = client.cookies.get(canal.COOKIE_SESSION)
    ouverte = session.scalars(select(SessionEspace).where(SessionEspace.email == adresse)).one()
    assert ouverte.empreinte_jeton == connexion.empreinte(valeur) != valeur
    assert ouverte.entreprise_id == e.id and ouverte.fermee_le is None
    assert ouverte.user_agent == "testclient"
    assert timedelta(days=29, hours=23) < ouverte.expire_le - datetime.now(timezone.utc) <= timedelta(days=30)
    demande = session.scalars(select(DemandeConnexion).where(DemandeConnexion.email == adresse)).one()
    assert demande.statut == UTILISEE
    assert client.get("/espace/accueil").status_code == 200
    # Le code ne sert qu'une fois.
    client.cookies.set(canal.COOKIE_DEMANDE, str(demande.id), path="/espace")
    assert chemin(client.post("/espace/code", data={"code": code})) == "/espace/connexion?info=invalide"


def test_cookie_secure_en_production_https(espace, session, monkeypatch):
    monkeypatch.setenv("ENVIRONNEMENT", "production")
    get_settings.cache_clear()
    client = TestClient(app, base_url="https://testserver", follow_redirects=False)
    reponse = client.post("/espace/connexion", data={"email": adresse_unique()})
    assert "Secure" in reponse.headers["set-cookie"]


def test_cookie_suit_le_prefixe(espace, session):
    client = TestClient(app, root_path="/jeff", follow_redirects=False)
    reponse = client.post("/jeff/espace/connexion", data={"email": adresse_unique()})
    assert "Path=/jeff/espace" in reponse.headers["set-cookie"]
    assert reponse.headers["location"].endswith("/jeff/espace/code")


@pytest.mark.parametrize("saisie", ["", "12345", "1234567", "abcdef", "12 34 5"])
def test_format_du_code(espace, session, saisie):
    adresse = adresse_unique()
    creer(session, "Ets Zeta", adresse)
    client = navigateur()
    demander(client, adresse)
    reponse = client.post("/espace/code", data={"code": saisie})
    assert reponse.status_code == 400 and tx.CODE_FORMAT in texte_visible(reponse.text)
    assert session.scalars(select(DemandeConnexion).where(DemandeConnexion.email == adresse)).one().essais == 0


def test_code_faux_puis_trop_d_essais(espace, session):
    adresse = adresse_unique()
    creer(session, "Ets Eta", adresse)
    client = navigateur()
    demander(client, adresse)
    bon = dernier_code(session, adresse)
    faux = f"{(int(bon) + 1) % 10**6:06d}"
    for essai in range(1, connexion.ESSAIS_MAX):
        reponse = client.post("/espace/code", data={"code": faux})
        assert reponse.status_code == 400 and tx.CODE_FAUX in texte_visible(reponse.text)
    reponse = client.post("/espace/code", data={"code": faux})
    assert reponse.status_code == 303 and chemin(reponse) == "/espace/connexion?info=trop_d_essais"
    demande = session.scalars(select(DemandeConnexion).where(DemandeConnexion.email == adresse)).one()
    assert demande.statut == ABANDONNEE and demande.essais == 5
    # Même le bon code ne passe plus.
    client.cookies.set(canal.COOKIE_DEMANDE, str(demande.id), path="/espace")
    assert chemin(client.post("/espace/code", data={"code": bon})) == "/espace/connexion?info=invalide"
    assert session.scalars(select(SessionEspace).where(SessionEspace.email == adresse)).all() == []


def test_code_expire(espace, session, monkeypatch):
    adresse = adresse_unique()
    creer(session, "Ets Theta", adresse)
    client = navigateur()
    demander(client, adresse)
    code = dernier_code(session, adresse)
    plus_tard = datetime.now(timezone.utc) + timedelta(minutes=16)
    monkeypatch.setattr(connexion, "maintenant", lambda: plus_tard)
    reponse = client.post("/espace/code", data={"code": code})
    assert reponse.status_code == 400 and tx.CODE_EXPIRE in texte_visible(reponse.text)


def test_code_juste_avant_expiration(espace, session, monkeypatch):
    adresse = adresse_unique()
    creer(session, "Ets Iota", adresse)
    client = navigateur()
    demander(client, adresse)
    demande = session.scalars(select(DemandeConnexion).where(DemandeConnexion.email == adresse)).one()
    monkeypatch.setattr(connexion, "maintenant", lambda: demande.expire_le)
    assert client.post("/espace/code", data={"code": dernier_code(session, adresse)}).status_code == 303


def test_renvoyer_le_code(espace, session):
    adresse = adresse_unique()
    creer(session, "Ets Kappa", adresse)
    client = navigateur()
    demander(client, adresse)
    premier = dernier_code(session, adresse)
    demande = session.scalars(select(DemandeConnexion).where(DemandeConnexion.email == adresse)).one()
    client.post("/espace/code", data={"code": f"{(int(premier) + 1) % 10**6:06d}"})
    assert demande.essais == 1
    for numero in range(1, 4):
        reponse = client.post("/espace/code", data={"action": "renvoyer"})
        assert reponse.status_code == 200 and tx.CODE_RENVOYE in texte_visible(reponse.text)
        assert demande.renvois == numero and demande.essais == 0
    reponse = client.post("/espace/code", data={"action": "renvoyer"})
    assert reponse.status_code == 429 and tx.CODE_TROP_DE_RENVOIS in texte_visible(reponse.text)
    assert len(codes_envoyes(session, adresse)) == 4
    # Seul le dernier code est valable.
    if premier != dernier_code(session, adresse):
        assert client.post("/espace/code", data={"code": premier}).status_code == 400
    assert client.post("/espace/code", data={"code": dernier_code(session, adresse)}).status_code == 303


def test_renvoi_repousse_l_expiration(session, monkeypatch):
    adresse = adresse_unique()
    creer(session, "Ets Lambda", adresse)
    demande = connexion.demander_code(session, adresse)
    plus_tard = datetime.now(timezone.utc) + timedelta(minutes=10)
    monkeypatch.setattr(connexion, "maintenant", lambda: plus_tard)
    assert connexion.renvoyer(session, demande)
    assert demande.expire_le == plus_tard + timedelta(minutes=15)


def test_adresse_changee_entre_le_code_et_la_saisie(espace, session):
    adresse = adresse_unique()
    e = creer(session, "Ets Mu", adresse)
    client = navigateur()
    demander(client, adresse)
    code = dernier_code(session, adresse)
    e.email = adresse_unique()
    session.flush()
    reponse = client.post("/espace/code", data={"code": code})
    assert chemin(reponse) == "/espace/connexion?info=aucune"
    assert session.scalars(select(DemandeConnexion).where(DemandeConnexion.email == adresse)).one().statut == ABANDONNEE
    assert session.scalars(select(SessionEspace).where(SessionEspace.email == adresse)).all() == []


def test_empreinte_liee_a_la_demande(session):
    import hashlib

    demande = connexion.demander_code(session, adresse_unique())
    assert connexion.empreinte_code(demande, "123456") == hashlib.sha256(f"{demande.id}:123456".encode()).hexdigest()


def test_demande_utilisee_ne_sert_plus(espace, session):
    adresse = adresse_unique()
    creer(session, "Ets Usage", adresse)
    client = connecter(session, adresse)
    demande = session.scalars(select(DemandeConnexion).where(DemandeConnexion.email == adresse)).one()
    client.cookies.set(canal.COOKIE_DEMANDE, str(demande.id), path="/espace")
    assert chemin(client.get("/espace/code")) == "/espace/connexion"
    envoyes = len(codes_envoyes(session, adresse))
    reponse = client.post("/espace/code", data={"action": "renvoyer"})
    assert chemin(reponse) == "/espace/connexion?info=invalide"
    assert len(codes_envoyes(session, adresse)) == envoyes and demande.renvois == 0


def test_verification_d_une_demande_terminee(session):
    demande = connexion.demander_code(session, adresse_unique())
    demande.statut = UTILISEE
    assert connexion.verifier_code(session, demande, "123456") == (connexion.INVALIDE, [])


# --- Choix de l'entreprise ----------------------------------------------------------------------

def test_plusieurs_entreprises_choix_puis_changement(espace, session):
    adresse = adresse_unique()
    zeta = creer(session, "Zeta SARL", adresse)
    alpha = creer(session, "Alpha SA", adresse)
    client = navigateur()
    demander(client, adresse)
    reponse = client.post("/espace/code", data={"code": dernier_code(session, adresse)})
    assert chemin(reponse) == "/espace/choix"
    assert session.scalars(select(SessionEspace).where(SessionEspace.email == adresse)).one().entreprise_id is None
    assert chemin(client.get("/espace/accueil")) == "/espace/choix"
    page = client.get("/espace/choix").text
    assert page.index("Alpha SA") < page.index("Zeta SARL") and f"NIU {alpha.niu}" in page
    reponse = client.post("/espace/choix", data={"entreprise": str(zeta.id)})
    assert chemin(reponse) == "/espace/accueil"
    accueil = client.get("/espace/accueil").text
    assert "Zeta SARL" in accueil and tx.CHANGER_ENTREPRISE.replace("'", "&#39;") in accueil
    assert 'href="http://testserver/espace/choix"' in accueil
    assert "esp-courante" in client.get("/espace/choix").text
    client.post("/espace/choix", data={"entreprise": str(alpha.id)})
    assert "Alpha SA" in texte_visible(client.get("/espace/entreprise").text)


@pytest.mark.parametrize("valeur", ["", "nimporte", "autre"])
def test_choix_d_une_entreprise_non_autorisee(espace, session, valeur):
    adresse = adresse_unique()
    creer(session, "Alpha SA", adresse)
    creer(session, "Beta SA", adresse)
    etrangere = creer(session, "Etrangere SA", adresse_unique())
    client = connecter(session, adresse)
    reponse = client.post("/espace/choix", data={"entreprise": str(etrangere.id) if valeur == "autre" else valeur})
    assert chemin(reponse) == "/espace/choix"
    assert session.scalars(select(SessionEspace).where(SessionEspace.email == adresse)).one().entreprise_id is None


def test_une_seule_entreprise_pas_de_selecteur(espace, session):
    adresse = adresse_unique()
    creer(session, "Ets Solo", adresse)
    accueil = connecter(session, adresse).get("/espace/accueil").text
    assert "Ets Solo" in accueil and "/espace/choix" not in accueil


def test_choix_sans_session(espace):
    client = navigateur()
    assert chemin(client.get("/espace/choix")) == "/espace/connexion"
    assert chemin(client.post("/espace/choix", data={"entreprise": "x"})) == "/espace/connexion"


def test_choix_quand_plus_aucune_entreprise(espace, session):
    adresse = adresse_unique()
    e = creer(session, "Ets Nu", adresse)
    client = connecter(session, adresse)
    e.email_confirme_le = None
    session.flush()
    reponse = client.get("/espace/accueil")
    assert chemin(reponse) == "/espace/choix"
    reponse = client.get("/espace/choix")
    assert chemin(reponse) == "/espace/connexion?info=aucune"
    assert any(c.startswith(f'{canal.COOKIE_SESSION}=""') for c in reponse.headers.get_list("set-cookie"))
    assert session.scalars(select(SessionEspace).where(SessionEspace.email == adresse)).one().fermee_le is not None


def test_entreprise_retiree_de_la_session(espace, session):
    """L'adresse d'une des entreprises change : elle disparaît du coffre, l'autre reste."""
    adresse = adresse_unique()
    alpha = creer(session, "Alpha SA", adresse)
    beta = creer(session, "Beta SA", adresse)
    client = connecter(session, adresse)
    client.post("/espace/choix", data={"entreprise": str(alpha.id)})
    alpha.email = adresse_unique()
    session.flush()
    assert chemin(client.get("/espace/entreprise")) == "/espace/choix"
    assert session.scalars(select(SessionEspace).where(SessionEspace.email == adresse)).one().entreprise_id is None
    page = client.get("/espace/choix").text
    assert "Beta SA" in page and "Alpha SA" not in page
    client.post("/espace/choix", data={"entreprise": str(beta.id)})
    accueil = client.get("/espace/accueil").text
    assert "Beta SA" in accueil and "/espace/choix" not in accueil


# --- Session ------------------------------------------------------------------------------------

def test_session_reconnue_partout(espace, session):
    adresse = adresse_unique()
    creer(session, "Ets Omicron", adresse)
    client = connecter(session, adresse)
    assert chemin(client.get("/espace")) == "/espace/accueil"
    assert chemin(client.get("/espace/connexion")) == "/espace/accueil"


def test_activite_mise_a_jour(espace, session, monkeypatch):
    adresse = adresse_unique()
    creer(session, "Ets Pi", adresse)
    client = connecter(session, adresse)
    plus_tard = datetime.now(timezone.utc) + timedelta(days=3)
    monkeypatch.setattr(connexion, "maintenant", lambda: plus_tard)
    client.get("/espace/accueil")
    assert session.scalars(select(SessionEspace).where(SessionEspace.email == adresse)).one().derniere_activite_le == plus_tard


def test_session_expiree_apres_30_jours(espace, session, monkeypatch):
    adresse = adresse_unique()
    creer(session, "Ets Rho", adresse)
    client = connecter(session, adresse)
    ouverte = session.scalars(select(SessionEspace).where(SessionEspace.email == adresse)).one()
    monkeypatch.setattr(connexion, "maintenant", lambda: ouverte.expire_le - timedelta(seconds=1))
    assert client.get("/espace/accueil").status_code == 200
    monkeypatch.setattr(connexion, "maintenant", lambda: ouverte.expire_le)
    assert chemin(client.get("/espace/accueil")) == "/espace/connexion"


@pytest.mark.parametrize("jeton", ["", "faux", "x" * 101])
def test_jeton_inconnu(espace, jeton):
    client = navigateur()
    client.cookies.set(canal.COOKIE_SESSION, jeton, path="/espace")
    assert chemin(client.get("/espace/accueil")) == "/espace/connexion"


def test_jeton_trop_long_jamais_cherche(session, monkeypatch):
    vus = []
    monkeypatch.setattr(connexion, "empreinte", lambda valeur: vus.append(len(valeur)) or "0" * 64)
    assert connexion.session_active(session, "x" * 101) is None
    assert connexion.session_active(session, None) is None
    assert vus == []
    assert connexion.session_active(session, "x" * 100) is None
    assert vus == [100]


def test_deconnexion(espace, session):
    adresse = adresse_unique()
    creer(session, "Ets Sigma", adresse)
    client = connecter(session, adresse)
    jeton = client.cookies.get(canal.COOKIE_SESSION)
    reponse = client.post("/espace/deconnexion")
    assert chemin(reponse) == "/espace/connexion?info=deconnecte"
    assert any(c.startswith(f'{canal.COOKIE_SESSION}=""') and "Path=/espace" in c for c in reponse.headers.get_list("set-cookie"))
    assert session.scalars(select(SessionEspace).where(SessionEspace.email == adresse)).one().fermee_le is not None
    # Le même jeton, rejoué, n'ouvre plus rien.
    autre = navigateur()
    autre.cookies.set(canal.COOKIE_SESSION, jeton, path="/espace")
    assert chemin(autre.get("/espace/accueil")) == "/espace/connexion"


def test_deconnexion_sans_session(espace):
    assert chemin(navigateur().post("/espace/deconnexion")) == "/espace/connexion?info=deconnecte"


def test_deconnexion_seulement_en_post(espace, session):
    adresse = adresse_unique()
    creer(session, "Ets Tau", adresse)
    client = connecter(session, adresse)
    assert client.get("/espace/deconnexion").status_code == 405
    assert client.get("/espace/accueil").status_code == 200


def test_deux_appareils_deux_sessions(espace, session):
    adresse = adresse_unique()
    creer(session, "Ets Upsilon", adresse)
    telephone = connecter(session, adresse)
    ordinateur = connecter(session, adresse)
    telephone.post("/espace/deconnexion")
    assert ordinateur.get("/espace/accueil").status_code == 200


# --- Onglets ------------------------------------------------------------------------------------

@pytest.mark.parametrize("onglet", ["accueil", "echeances", "obligations", "documents", "entreprise"])
def test_onglets_proteges(espace, onglet):
    assert chemin(navigateur().get(f"/espace/{onglet}")) == "/espace/connexion"


def test_navigation_cinq_onglets(espace, session):
    adresse = adresse_unique()
    creer(session, "Ets Phi", adresse)
    client = connecter(session, adresse)
    for cle, libelle in tx.ONGLETS:
        reponse = client.get(f"/espace/{cle}")
        assert reponse.status_code == 200
        html = reponse.text
        assert f'href="http://testserver/espace/{cle}" class="esp-menu-lien actif" aria-current="page"' in html
        assert f'href="http://testserver/espace/{cle}" class="actif" aria-current="page"' in html
        assert html.count('aria-current="page"') == 2
        for autre, _ in tx.ONGLETS:
            assert f'href="http://testserver/espace/{autre}"' in html
        assert f"<title>{libelle} · Jeff</title>".replace("'", "&#39;") in html
    assert "<span>Entreprise</span>" in client.get("/espace/accueil").text


def test_accueil_prochaine_echeance(espace, session, regles):
    adresse = adresse_unique()
    creer(session, "Ets Psi", adresse, nombre_salaries=None)
    texte = texte_visible(connecter(session, adresse).get("/espace/accueil").text)
    assert tx.PROCHAINE_ECHEANCE in texte and TITRE_TVA in texte
    assert tx.A_CONFIRMER in texte and tx.AVERTISSEMENT_VALIDATION in texte


def test_tableau_tva(session, regles):
    e = creer(session, "Ets Omega", adresse_unique())
    t = donnees.tableau(session, e, date(2026, 10, 5))
    assert (t.prochaine.titre, t.prochaine.periode, t.prochaine.date_limite) == (TITRE_TVA, "septembre 2026", date(2026, 10, 15))
    assert t.prochaine.jours == 10 and t.prochaine.date_texte == "jeudi 15 octobre 2026" and t.prochaine.mois_court == "oct."
    assert t.prochaine.alerte is None and t.a_valider is True
    assert t.nombre_obligations >= 1 and t.a_confirmer == []


def test_tableau_ordre_et_limite(session, regles, monkeypatch):
    class Regle:
        def __init__(self, titre, jour, statut="publiee", incertaine=False, calcul=True, periodicite="mensuelle"):
            self.titre, self.statut, self.type, self.periodicite = titre, statut, "obligation", periodicite
            self.echeance_calcul = {"type": "jour_du_mois_suivant", "jour": jour} if calcul else None

    class Resultat:
        def __init__(self, regle, applicabilite="oui"):
            self.regle, self.applicabilite = regle, applicabilite

    alerte = Regle("Alerte", 3)
    alerte.type = "alerte"
    resultats = [Resultat(Regle(f"R{j}", j)) for j in (20, 6, 25, 10, 15, 28)] + [
        Resultat(Regle("Incertaine", 7), "incertain"),
        Resultat(Regle("Sans date", 1, calcul=False)),
        Resultat(Regle("Ponctuelle", 1, calcul=False, periodicite="ponctuelle")),
        Resultat(alerte),
    ]
    monkeypatch.setattr(donnees, "evaluer_entreprise", lambda *a: resultats)
    t = donnees.tableau(session, creer(session), date(2026, 10, 5))
    assert t.prochaine.titre == "R6" and t.prochaine.jours == 1
    assert [e.titre for e in t.a_venir] == ["R10", "R15", "R20", "R25"]
    assert t.a_confirmer == ["Incertaine"] and t.sans_date == ["Sans date"]
    assert t.nombre_obligations == 9 and t.a_valider is False


def test_tableau_meme_date_par_titre(session, monkeypatch):
    class R:
        def __init__(self, titre):
            self.titre, self.statut, self.type, self.periodicite = titre, "publiee", "obligation", "mensuelle"
            self.echeance_calcul = {"type": "jour_du_mois_suivant", "jour": 15}

    class Res:
        def __init__(self, titre):
            self.regle, self.applicabilite = R(titre), "oui"

    monkeypatch.setattr(donnees, "evaluer_entreprise", lambda *a: [Res("B"), Res("A")])
    t = donnees.tableau(session, creer(session), date(2026, 10, 5))
    assert [t.prochaine.titre] + [e.titre for e in t.a_venir] == ["A", "B"]


def test_tableau_sans_obligation(espace, session, monkeypatch):
    monkeypatch.setattr(donnees, "evaluer_entreprise", lambda *a: [])
    adresse = adresse_unique()
    creer(session, "Ets Vide", adresse)
    t = donnees.tableau(session, session.scalars(select(Entreprise).where(Entreprise.email == adresse)).one(), date(2026, 10, 5))
    assert t.prochaine is None and t.a_venir == [] and t.nombre_obligations == 0
    texte = texte_visible(connecter(session, adresse).get("/espace/accueil").text)
    assert tx.AUCUNE_ECHEANCE in texte and tx.A_CONFIRMER not in texte


def test_tableau_jour_de_la_juridiction(session, regles, monkeypatch):
    vus = []
    monkeypatch.setattr(donnees, "aujourd_hui", lambda fuseau: vus.append(fuseau) or date(2026, 10, 14))
    t = donnees.tableau(session, creer(session, "Ets Fuseau", adresse_unique()))
    assert vus == ["Africa/Douala"] and t.prochaine.jours == 1


@pytest.mark.parametrize("jours,attendu", [(0, tx.AUJOURD_HUI), (1, tx.DEMAIN), (12, "12 " + tx.JOURS_RESTANTS)])
def test_compte_a_rebours(espace, session, monkeypatch, jours, attendu):
    adresse = adresse_unique()
    creer(session, "Ets Compte", adresse)
    prochaine = donnees.Echeance("TVA", "septembre 2026", date(2026, 10, 15), "jeudi 15 octobre 2026", "oct.", jours, "Attention : jour férié")
    monkeypatch.setattr(donnees, "tableau", lambda *a: donnees.Tableau(prochaine=prochaine))
    texte = texte_visible(connecter(session, adresse).get("/espace/accueil").text)
    assert attendu in texte and "Attention : jour férié" in texte
    assert tx.PERIODE.format(periode="septembre 2026") in texte
    assert tx.A_FAIRE_AVANT.format(date="jeudi 15 octobre 2026") in texte


def test_accueil_listes(espace, session, monkeypatch):
    adresse = adresse_unique()
    creer(session, "Ets Listes", adresse)
    suivante = donnees.Echeance("Acompte", "septembre 2026", date(2026, 10, 15), "jeudi 15 octobre 2026", "oct.", 10, None)
    monkeypatch.setattr(donnees, "tableau", lambda *a: donnees.Tableau(
        prochaine=suivante, a_venir=[suivante], a_confirmer=["Patente"], sans_date=["Registre"], nombre_obligations=7,
    ))
    html = connecter(session, adresse).get("/espace/accueil").text
    texte = texte_visible(html)
    assert tx.A_VENIR in texte and "15 oct." in texte and "septembre 2026 · jeudi 15 octobre 2026" in texte
    assert "Patente" in texte and tx.A_CONFIRMER_AIDE in texte and tx.SANS_DATE in texte and "Registre" in texte
    assert "7 " + tx.OBLIGATIONS_SUIVIES in texte and "1 " + tx.OBLIGATIONS_A_CONFIRMER in texte
    assert tx.AVERTISSEMENT_VALIDATION not in texte


def test_fiche_entreprise(espace, session):
    adresse = adresse_unique()
    e = creer(session, "Ets Fiche", adresse, forme_juridique="sarl", secteur="commerce", chiffre_affaires_annuel=150_000_000,
              nombre_salaries=3, numero_employeur_cnps="123456789")
    for numero, actifs in (("237690001234", True), ("237690005678", False)):
        session.add(Conversation(canal=CANAL_WHATSAPP, identifiant_externe=numero + uuid.uuid4().hex[:4], entreprise_id=e.id,
                                 rappels_whatsapp=actifs))
    session.add(Conversation(canal="web", identifiant_externe="web-" + uuid.uuid4().hex, entreprise_id=e.id))
    session.flush()
    html = connecter(session, adresse).get("/espace/entreprise").text
    texte = texte_visible(html)
    assert f"NIU {e.niu}" in texte and tx.NIU_VERROUILLE in texte
    assert "Forme juridique SARL" in texte and "Secteur Commerce" in texte
    assert "150 000 000 FCFA" in html and "123456789" in texte
    assert f"{tx.EMAIL} {adresse} {tx.EMAIL_CONFIRMEE}" in texte
    assert texte.count(tx.WHATSAPP_RELIE) == 2 and "237690001234" not in texte and "•••• " in texte
    assert tx.ACTIFS in texte and tx.ARRETES in texte and tx.MODIFIER_AIDE in texte
    assert html.count('class="esp-verrou"') == 1


def test_fiche_sans_whatsapp(espace, session):
    adresse = adresse_unique()
    creer(session, "Ets Sans WA", adresse)
    texte = texte_visible(connecter(session, adresse).get("/espace/entreprise").text)
    assert tx.WHATSAPP_AUCUN in texte and tx.RAPPELS_WHATSAPP not in texte


def test_numero_masque():
    assert donnees.masquer("237690001234") == "•••• 1234"


def test_fiche_un_numero_sans_rappel_detaille(session):
    e = creer(session, "Ets Un", adresse_unique())
    session.add(Conversation(canal=CANAL_WHATSAPP, identifiant_externe="2376" + uuid.uuid4().hex[:8], entreprise_id=e.id))
    session.flush()
    fiche = donnees.fiche(session, e)
    assert [actifs for _, _, actifs in fiche.whatsapp] == [True]
    assert [l for l, _, _ in fiche.lignes][:2] == ["Raison sociale", "NIU"]
    assert all(libelle != "Adresse email" for libelle, _, _ in fiche.lignes)


# --- Ton, gabarits, sécurité ----------------------------------------------------------------------

@pytest.mark.parametrize("message", tx.TOUS)
def test_textes_sans_tutoiement(message):
    assert not TUTOIEMENT.search(message), message


def test_pages_sans_tutoiement(espace, session, regles):
    adresse = adresse_unique()
    creer(session, "Ets Lumière", adresse)
    creer(session, "Ets Lumière Bis", adresse)
    client = navigateur()
    pages = [client.get("/espace/connexion").text, client.post("/espace/connexion", data={"email": "x"}).text]
    demander(client, adresse)
    pages.append(client.get("/espace/code").text)
    client.post("/espace/code", data={"code": dernier_code(session, adresse)})
    pages.append(client.get("/espace/choix").text)
    client.post("/espace/choix", data={"entreprise": str(session.scalars(select(Entreprise).where(Entreprise.email == adresse)).first().id)})
    pages += [client.get(f"/espace/{cle}").text for cle, _ in tx.ONGLETS]
    for html in pages:
        texte = texte_visible(html)
        assert not TUTOIEMENT.search(texte), texte
        assert "noindex" in html and 'lang="fr"' in html and "prefers-color-scheme: dark" in html


def test_nom_d_entreprise_echappe(espace, session):
    adresse = adresse_unique()
    creer(session, "<b>Piège</b> & Cie", adresse)
    html = connecter(session, adresse).get("/espace/accueil").text
    assert "<b>Piège</b>" not in html and "&lt;b&gt;Piège&lt;/b&gt; &amp; Cie" in html


def test_ressources_statiques():
    client = TestClient(app)
    css = client.get("/static/css/espace.css")
    assert css.status_code == 200 and "prefers-color-scheme" not in css.text and '[data-bs-theme="dark"]' in css.text
    assert "@media (min-width: 992px)" in css.text
    assert client.get("/static/img/logo-jeff.webp").headers["content-type"] == "image/webp"
    assert client.get("/static/img/logo-jeff-marque.svg").status_code == 200


def test_requirements_formulaires():
    with open("requirements.txt", encoding="utf-8") as f:
        assert "python-multipart==" in f.read()


# --- Base et version ----------------------------------------------------------------------------

def test_tables_du_lot():
    inspecteur = inspect(get_engine())
    colonnes = {c["name"]: c for c in inspecteur.get_columns("demandes_connexion")}
    assert set(colonnes) == {"id", "email", "empreinte", "expire_le", "essais", "renvois", "statut", "cree_le"} | {"ip"}  # ip : lot 17
    assert colonnes["empreinte"]["nullable"] is True and colonnes["statut"]["nullable"] is False
    colonnes = {c["name"]: c for c in inspecteur.get_columns("sessions_espace")}
    assert set(colonnes) == {"id", "empreinte_jeton", "email", "entreprise_id", "user_agent", "cree_le", "expire_le",
                             "derniere_activite_le", "fermee_le"}
    assert colonnes["entreprise_id"]["nullable"] is True
    uniques = inspecteur.get_unique_constraints("sessions_espace")
    assert [u["column_names"] for u in uniques] == [["empreinte_jeton"]]
    [cle] = inspecteur.get_foreign_keys("sessions_espace")
    assert cle["referred_table"] == "entreprises"
    assert {i["name"] for i in inspecteur.get_indexes("demandes_connexion")} == {"ix_demandes_connexion_email", "ix_demandes_connexion_ip"}
    assert {i["name"] for i in inspecteur.get_indexes("sessions_espace")} == {
        "ix_sessions_espace_email", "uq_sessions_espace_empreinte_jeton"}
    [verif] = inspecteur.get_check_constraints("demandes_connexion")
    assert "en_cours" in verif["sqltext"] and "utilisee" in verif["sqltext"] and "abandonnee" in verif["sqltext"]


def test_statut_inconnu_refuse(session):
    from sqlalchemy.exc import IntegrityError

    session.add(DemandeConnexion(id=uuid.uuid4(), email="a@b.cm", expire_le=MAINTENANT, statut="autre"))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_valeurs_par_defaut_en_base(session):
    from sqlalchemy import text

    identifiant = uuid.uuid4()
    session.execute(text("INSERT INTO demandes_connexion (id, email, expire_le) VALUES (:i, 'a@b.cm', now())"), {"i": identifiant})
    ligne = session.execute(text("SELECT essais, renvois, statut, cree_le FROM demandes_connexion WHERE id = :i"), {"i": identifiant}).one()
    assert ligne[:3] == (0, 0, "en_cours") and ligne[3] is not None


def test_jeton_unique(session):
    from sqlalchemy.exc import IntegrityError

    for _ in range(2):
        session.add(SessionEspace(empreinte_jeton="e" * 64, email="a@b.cm", expire_le=MAINTENANT, derniere_activite_le=MAINTENANT))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_import_des_modeles_seul():
    """La commande de migration charge tous les modèles, y compris ceux du coffre."""
    code = "import app.models as m; assert 'SessionEspace' in m.__all__ and 'DemandeConnexion' in m.__all__"
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


def test_version():
    assert TestClient(app).get("/sante").json()["version"] == VERSION
