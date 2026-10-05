"""Lot 11 — mots de commande plus souples, « STOP » sur WhatsApp, adresse email partagée par plusieurs entreprises."""
import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from app.conversation import liaison
from app.conversation import messages_fixes as mf
from app.conversation.models import ABANDONNE, CANAL_WEB, CANAL_WHATSAPP, EN_COURS, EN_PAUSE, Parcours
from app.conversation.moteur import ANNULER, MENU_MOTS, REPRENDRE, traiter_message, trouver_ou_creer_conversation
from app.conversation.normalisation import normaliser
from app.core.config import VERSION
from app.core.db import get_engine
from app.emails.models import Email
from app.entreprises.models import Entreprise
from app.main import app
from app.rappels.canal import BULLE, WHATSAPP, choisir
from tests.test_lot03_onboarding import Visiteur, jusqu_au_recapitulatif, niu_unique
from tests.test_lot09_whatsapp import Client, bouton, ligne, whatsapp_configure  # noqa: F401 (fixture)

MAINTENANT = datetime.now(timezone.utc)


# --- Mots de commande ---------------------------------------------------------------------------

def test_les_mots_sont_deja_normalises():
    for mots in (ANNULER, MENU_MOTS, REPRENDRE):
        assert all(m == normaliser(m) for m in mots)


@pytest.mark.parametrize("texte", ["annuler", "Annule", "annulé", "ANNULEZ", "Arrêter", "arrete", "abandonner", "Quitter", "STOP", "stop !"])
def test_annuler_le_questionnaire(session, texte):
    visiteur = Visiteur(session)
    visiteur.dit("1")
    visiteur.dit("oui")
    reponse = visiteur.dit(texte)
    assert reponse.texte == mf.ANNULE
    assert reponse.choix == list(mf.MENU)
    assert visiteur.parcours.statut == ABANDONNE


@pytest.mark.parametrize("texte", ["menu", "Accueil", "retour", "Retour au menu", "revenir au menu"])
def test_pause_du_questionnaire(session, texte):
    visiteur = Visiteur(session)
    visiteur.dit("1")
    visiteur.dit("oui")
    assert visiteur.dit(texte).texte == mf.PAUSE
    assert visiteur.parcours.statut == EN_PAUSE


@pytest.mark.parametrize("texte", ["reprendre", "Continuer", "continue", "Reprends", "reprenez"])
def test_reprise_du_questionnaire(session, texte):
    visiteur = Visiteur(session)
    visiteur.dit("1")
    visiteur.dit("oui")
    visiteur.dit("menu")
    assert visiteur.dit(texte).texte == mf.Q_RAISON_SOCIALE
    assert visiteur.parcours.statut == EN_COURS


@pytest.mark.parametrize("texte", ["accueil", "Retour", "retour au menu"])
def test_accueil_hors_questionnaire(session, texte):
    reponse = traiter_message(session, CANAL_WEB, "web-" + uuid.uuid4().hex, texte)
    assert reponse.texte == mf.ACCUEIL
    assert reponse.choix == list(mf.MENU)


def test_un_mot_de_commande_dans_une_reponse_reste_une_reponse(session):
    visiteur = Visiteur(session)
    visiteur.dit("1")
    visiteur.dit("oui")
    assert visiteur.dit("Stop Services SARL").texte == mf.Q_NIU
    assert visiteur.parcours.donnees["raison_sociale"] == "Stop Services SARL"


def test_annuler_une_modification_avec_stop(session):
    visiteur = Visiteur(session)
    jusqu_au_recapitulatif(visiteur, niu_unique())
    visiteur.dit("oui")
    visiteur.dit("modifier")
    assert visiteur.dit("stop").texte == mf.MODIFICATION_ANNULEE


def test_stop_sur_le_web_hors_questionnaire_non_compris(session):
    identifiant = "web-" + uuid.uuid4().hex
    assert traiter_message(session, CANAL_WEB, identifiant, "STOP").texte == mf.INCOMPRIS
    assert trouver_ou_creer_conversation(session, CANAL_WEB, identifiant).rappels_whatsapp is True


# --- STOP sur WhatsApp ----------------------------------------------------------------------------

def entreprise(session, email=None) -> Entreprise:
    e = Entreprise(juridiction_code="CM", niu=niu_unique(), raison_sociale="Ets Stop", regime_declare="reel",
                   assujetti_tva_declare=True, nombre_salaries=0, email=email,
                   email_confirme_le=datetime.now(timezone.utc) if email else None)
    session.add(e)
    session.flush()
    return e


def client_relie(session, e) -> Client:
    client = Client(session)
    client.ecrit("bonjour")
    client.conversation.entreprise_id = e.id
    session.flush()
    return client


def test_stop_arrete_les_rappels_whatsapp(session, whatsapp_configure):
    e = entreprise(session)
    client = client_relie(session, e)
    assert choisir(session, e, 7, MAINTENANT).canal == WHATSAPP
    [message] = client.ecrit("STOP")
    assert message == {"type": "text", "text": {"body": mf.WA_STOP, "preview_url": False}}
    assert client.conversation.rappels_whatsapp is False
    assert choisir(session, e, 7, MAINTENANT).canal == BULLE
    assert choisir(session, e, 2, MAINTENANT).canal == BULLE


@pytest.mark.parametrize("texte", ["reprendre les rappels", "START", "Réactiver les rappels"])
def test_reprendre_les_rappels(session, whatsapp_configure, texte):
    e = entreprise(session)
    client = client_relie(session, e)
    client.ecrit("stop")
    assert client.dit(texte) == mf.WA_RAPPELS_REPRIS
    assert client.conversation.rappels_whatsapp is True
    assert choisir(session, e, 7, MAINTENANT).canal == WHATSAPP


def test_stop_pendant_un_questionnaire_annule_seulement(session, whatsapp_configure):
    client = Client(session)
    client.ecrit(ligne("1"))
    client.ecrit(bouton("oui"))
    assert client.dit("STOP") == mf.ANNULE
    assert client.conversation.rappels_whatsapp is True


def test_stop_avec_un_questionnaire_en_pause(session, whatsapp_configure):
    client = Client(session)
    client.ecrit(ligne("1"))
    client.ecrit(bouton("oui"))
    client.ecrit("menu")
    assert client.dit("stop") == mf.WA_STOP
    assert client.conversation.rappels_whatsapp is False
    parcours = session.scalars(select(Parcours).where(Parcours.conversation_id == client.conversation.id)).one()
    assert parcours.statut == EN_PAUSE


def test_une_autre_conversation_whatsapp_active_reste_utilisee(session, whatsapp_configure):
    e = entreprise(session)
    premiere = client_relie(session, e)
    seconde = client_relie(session, e)
    premiere.ecrit("stop")
    choix = choisir(session, e, 7, MAINTENANT)
    assert (choix.canal, choix.conversation.id) == (WHATSAPP, seconde.conversation.id)


def test_stop_repli_par_email(session, whatsapp_configure):
    e = entreprise(session, email=f"stop.{uuid.uuid4().hex[:6]}@exemple.cm")
    client_relie(session, e).ecrit("stop")
    assert choisir(session, e, 2, MAINTENANT).canal == "email"


# --- Adresse partagée par plusieurs entreprises ---------------------------------------------------

def deux_entreprises(session, adresse=None, noms=("Ets Zèbre", "Ets Alpha")):
    adresse = adresse or f"comptable.{uuid.uuid4().hex[:8]}@exemple.cm"
    return adresse, [entreprise_nommee(session, nom, adresse) for nom in noms]


def entreprise_nommee(session, nom, adresse, confirmee=True) -> Entreprise:
    e = Entreprise(juridiction_code="CM", niu=niu_unique(), raison_sociale=nom, regime_declare="reel",
                   assujetti_tva_declare=True, nombre_salaries=0, email=adresse,
                   email_confirme_le=datetime.now(timezone.utc) if confirmee else None)
    session.add(e)
    session.flush()
    return e


def codes(session, adresse) -> list[Email]:
    return list(session.scalars(select(Email).where(Email.destinataire == adresse).order_by(Email.id)))


def dernier_code(session, adresse) -> str:
    return re.search(r"\b(\d{6})\b", codes(session, adresse)[-1].texte).group(1)


def vers_le_choix(session, adresse):
    identifiant = "web-" + uuid.uuid4().hex

    def dit(texte):
        return traiter_message(session, CANAL_WEB, identifiant, texte)
    dit("1")
    dit("deja")
    dit(adresse)
    return identifiant, dit


def test_un_seul_email_avec_les_deux_entreprises(session):
    adresse, _ = deux_entreprises(session)
    _, dit = vers_le_choix(session, adresse)
    [email] = codes(session, adresse)
    assert "profil Jeff (« Ets Alpha », « Ets Zèbre »)" in email.texte
    assert email.texte == mf.EMAIL_LIAISON_TEXTE.format(entreprises="« Ets Alpha », « Ets Zèbre »", code=dernier_code(session, adresse)) + "\n\n" + mf.EMAIL_SIGNATURE


def test_choisir_l_entreprise_apres_le_code(session):
    adresse, (zebre, alpha) = deux_entreprises(session)
    identifiant, dit = vers_le_choix(session, adresse)
    choix = dit(dernier_code(session, adresse))
    assert choix.texte == mf.LIAISON_CHOIX
    assert choix.choix == [("1", "Ets Alpha"), ("2", "Ets Zèbre")]
    fin = dit("2")
    assert fin.texte == mf.LIAISON_OK.format(raison_sociale="Ets Zèbre")
    assert fin.choix == list(mf.MENU)
    assert trouver_ou_creer_conversation(session, CANAL_WEB, identifiant).entreprise_id == zebre.id


@pytest.mark.parametrize("texte", ["3", "0", "Alpha", ""])
def test_choix_invalide(session, texte):
    adresse, _ = deux_entreprises(session)
    _, dit = vers_le_choix(session, adresse)
    dit(dernier_code(session, adresse))
    if texte:
        erreur = dit(texte)
        assert erreur.texte == mf.ERR_CHOIX
        assert erreur.choix == [("1", "Ets Alpha"), ("2", "Ets Zèbre")]


def test_entreprise_choisie_plus_valide(session):
    adresse, (zebre, alpha) = deux_entreprises(session)
    identifiant, dit = vers_le_choix(session, adresse)
    dit(dernier_code(session, adresse))
    alpha.email_confirme_le = None
    session.flush()
    assert dit("1").texte == mf.LIAISON_ANNULEE
    assert trouver_ou_creer_conversation(session, CANAL_WEB, identifiant).entreprise_id is None


def test_une_seule_encore_valide_reliee_directement(session):
    adresse, (zebre, alpha) = deux_entreprises(session)
    identifiant, dit = vers_le_choix(session, adresse)
    code = dernier_code(session, adresse)
    zebre.email = "autre@exemple.cm"
    session.flush()
    assert dit(code).texte == mf.LIAISON_OK.format(raison_sociale="Ets Alpha")
    assert trouver_ou_creer_conversation(session, CANAL_WEB, identifiant).entreprise_id == alpha.id


def test_les_adresses_non_confirmees_sont_ignorees(session):
    adresse = f"partage.{uuid.uuid4().hex[:8]}@exemple.cm"
    confirmee = entreprise_nommee(session, "Ets Confirmée", adresse)
    entreprise_nommee(session, "Ets Pas Confirmée", adresse, confirmee=False)
    assert [e.id for e in liaison.entreprises_confirmees(session, adresse)] == [confirmee.id]
    _, dit = vers_le_choix(session, adresse)
    assert dit(dernier_code(session, adresse)).texte == mf.LIAISON_OK.format(raison_sociale="Ets Confirmée")


def test_ordre_alphabetique(session):
    adresse, (zebre, alpha) = deux_entreprises(session)
    assert [e.raison_sociale for e in liaison.entreprises_confirmees(session, adresse)] == ["Ets Alpha", "Ets Zèbre"]
    assert liaison.entreprise_confirmee(session, adresse).id == alpha.id


def test_pause_pendant_le_choix(session):
    adresse, _ = deux_entreprises(session)
    _, dit = vers_le_choix(session, adresse)
    dit(dernier_code(session, adresse))
    dit("menu")
    reprise = dit("reprendre")
    assert reprise.texte == mf.LIAISON_CHOIX
    assert reprise.choix == [("1", "Ets Alpha"), ("2", "Ets Zèbre")]


def test_renvoi_du_code_avec_plusieurs_entreprises(session):
    adresse, _ = deux_entreprises(session)
    _, dit = vers_le_choix(session, adresse)
    assert dit("renvoyer").texte == mf.LIAISON_CODE_ENVOYE
    assert len(codes(session, adresse)) == 2
    assert "« Ets Alpha », « Ets Zèbre »" in codes(session, adresse)[-1].texte
    assert dit(dernier_code(session, adresse)).texte == mf.LIAISON_CHOIX


def test_liaison_commencee_avant_le_lot_11(session):
    """Une liaison en cours au moment du déploiement garde « entreprise_id » (une seule entreprise)."""
    adresse = f"ancien.{uuid.uuid4().hex[:8]}@exemple.cm"
    e = entreprise_nommee(session, "Ets Ancienne", adresse)
    identifiant, dit = vers_le_choix(session, adresse)
    conversation = trouver_ou_creer_conversation(session, CANAL_WEB, identifiant)
    parcours = session.scalars(select(Parcours).where(Parcours.conversation_id == conversation.id, Parcours.type == liaison.TYPE)).one()
    donnees = {k: v for k, v in parcours.donnees.items() if k != "entreprise_ids"}
    parcours.donnees = {**donnees, "entreprise_id": str(e.id)}
    session.flush()
    assert liaison.identifiants(parcours.donnees) == [str(e.id)]
    assert dit(dernier_code(session, adresse)).texte == mf.LIAISON_OK.format(raison_sociale="Ets Ancienne")
    assert liaison.identifiants({"entreprise_id": None}) == []


# --- Base et version -----------------------------------------------------------------------------

def test_colonne_rappels_whatsapp():
    colonne = {c["name"]: c for c in inspect(get_engine()).get_columns("conversations")}["rappels_whatsapp"]
    assert colonne["nullable"] is False
    assert "true" in str(colonne["default"]).lower()


def test_version():
    assert TestClient(app).get("/sante").json()["version"] == VERSION
