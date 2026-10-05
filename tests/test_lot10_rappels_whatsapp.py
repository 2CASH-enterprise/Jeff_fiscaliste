"""Lot 10 — rappels par WhatsApp : fenêtre de 24 h, modèle Meta, 5 messages prioritaires par mois, repli."""
import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from app.conversation import messages_fixes as mf
from app.conversation.models import CANAL_WEB, CANAL_WHATSAPP, Conversation
from app.conversation.moteur import traiter_message, trouver_ou_creer_conversation
from app.core.config import VERSION, Settings, get_settings
from app.core.db import get_engine
from app.emails.models import RAPPEL as EMAIL_RAPPEL, Email
from app.entreprises.models import Entreprise
from app.main import MasquerJetons, app
from app.rappels import canal, livraison
from app.rappels.canal import BULLE, EMAIL, WHATSAPP, choisir, debut_du_mois, prioritaires_du_mois
from app.rappels.models import A_ENVOYER, ENVOYE, IGNORE, Rappel
from app.rappels.preparation import preparer_entreprise
from app.regles.chargement import charger_fichier
from app.whatsapp import envoi, format, modeles, reception
from app.whatsapp.models import A_ENVOYER as WA_A_ENVOYER, ANNULE, ECHEC, ENVOYE as WA_ENVOYE, WhatsappEnvoi
from tests.test_lot03_onboarding import niu_unique
from tests.test_lot09_whatsapp import (  # noqa: F401 (fixtures)
    NUMERO_JEFF, FauxMeta, ReponseHttp, meta, notification, numero_unique, whatsapp_configure,
)

RACINE = Path(__file__).resolve().parent.parent
FICHIER_CM = RACINE / "app/regles/donnees/regles_cm.json"
J7, J2 = date(2026, 10, 8), date(2026, 10, 13)  # échéance TVA du jeudi 15 octobre 2026
MAINTENANT = datetime(2026, 10, 13, 6, 30, tzinfo=timezone.utc)  # 7 h 30 à Douala
TITRE_TVA = "Déclaration et paiement mensuels de la TVA"


# --- Outils --------------------------------------------------------------------------------------

def entreprise(session, email_confirme=False) -> Entreprise:
    e = Entreprise(
        juridiction_code="CM", niu=niu_unique(), raison_sociale="Ets WhatsApp", regime_declare="reel",
        assujetti_tva_declare=True, nombre_salaries=0,
        email=f"wa.{uuid.uuid4().hex[:8]}@exemple.cm" if email_confirme else None,
        email_confirme_le=datetime.now(timezone.utc) if email_confirme else None,
    )
    session.add(e)
    session.flush()
    return e


def conversation_wa(session, e, dernier=None) -> Conversation:
    conversation = trouver_ou_creer_conversation(session, CANAL_WHATSAPP, numero_unique())
    conversation.entreprise_id = e.id
    conversation.dernier_message_client_le = dernier
    session.flush()
    return conversation


def ouverte():
    return MAINTENANT - timedelta(hours=2)


def fermee():
    return MAINTENANT - timedelta(days=3)


def envois_de(session, e) -> list[WhatsappEnvoi]:
    return list(session.scalars(select(WhatsappEnvoi).where(WhatsappEnvoi.entreprise_id == e.id).order_by(WhatsappEnvoi.id)))


def envoi_prioritaire(session, e, conversation, statut=WA_A_ENVOYER, cree_le=None) -> WhatsappEnvoi:
    m = WhatsappEnvoi(conversation_id=conversation.id, destinataire=conversation.identifiant_externe, contenu={},
                      statut=statut, essais=0, entreprise_id=e.id, modele="jeff_rappel_echeance")
    session.add(m)
    session.flush()
    if cree_le:
        session.execute(WhatsappEnvoi.__table__.update().where(WhatsappEnvoi.id == m.id).values(cree_le=cree_le))
    return m


@pytest.fixture
def regles(session):
    charger_fichier(session, FICHIER_CM)


# --- Routeur -------------------------------------------------------------------------------------

def test_decisions_du_porteur():
    assert canal.PALIERS_PRIORITAIRES == {2}
    assert canal.PLAFOND_MENSUEL == 5
    assert Settings().whatsapp_modele_rappel == "jeff_rappel_echeance"


def test_sans_whatsapp_repli(session, whatsapp_configure):
    assert choisir(session, entreprise(session), 2, MAINTENANT).canal == BULLE
    assert choisir(session, entreprise(session, email_confirme=True), 2, MAINTENANT).canal == EMAIL


def test_whatsapp_non_configure_repli(session, monkeypatch):
    monkeypatch.delenv("WHATSAPP_JETON", raising=False)
    get_settings.cache_clear()
    try:
        e = entreprise(session)
        conversation_wa(session, e, ouverte())
        assert choisir(session, e, 2, MAINTENANT).canal == BULLE
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("palier", [7, 2])
def test_fenetre_ouverte_message_libre(session, whatsapp_configure, palier):
    e = entreprise(session)
    conversation = conversation_wa(session, e, ouverte())
    choix = choisir(session, e, palier, MAINTENANT)
    assert (choix.canal, choix.conversation.id, choix.modele) == (WHATSAPP, conversation.id, None)


def test_fenetre_de_24_heures_exactement(session, whatsapp_configure):
    e = entreprise(session)
    conversation_wa(session, e, MAINTENANT - timedelta(hours=24))
    assert choisir(session, e, 7, MAINTENANT).canal == BULLE


def test_fenetre_fermee_j2_modele(session, whatsapp_configure):
    e = entreprise(session)
    conversation_wa(session, e, fermee())
    choix = choisir(session, e, 2, MAINTENANT)
    assert (choix.canal, choix.modele) == (WHATSAPP, "jeff_rappel_echeance")


def test_jamais_ecrit_compte_comme_fenetre_fermee(session, whatsapp_configure):
    e = entreprise(session)
    conversation_wa(session, e, None)
    assert choisir(session, e, 2, MAINTENANT).modele == "jeff_rappel_echeance"


def test_fenetre_fermee_j7_repli(session, whatsapp_configure):
    e = entreprise(session, email_confirme=True)
    conversation_wa(session, e, fermee())
    assert choisir(session, e, 7, MAINTENANT).canal == EMAIL


def test_plafond_de_5_par_mois(session, whatsapp_configure):
    e = entreprise(session, email_confirme=True)
    conversation = conversation_wa(session, e, fermee())
    for _ in range(4):
        envoi_prioritaire(session, e, conversation, statut=WA_ENVOYE)
    assert choisir(session, e, 2, MAINTENANT).canal == WHATSAPP
    envoi_prioritaire(session, e, conversation)
    assert prioritaires_du_mois(session, e, MAINTENANT, "Africa/Douala") == 5
    assert choisir(session, e, 2, MAINTENANT).canal == EMAIL


def test_les_echecs_et_annulations_ne_comptent_pas(session, whatsapp_configure):
    e = entreprise(session)
    conversation = conversation_wa(session, e, fermee())
    for _ in range(5):
        envoi_prioritaire(session, e, conversation, statut=ECHEC)
    envoi_prioritaire(session, e, conversation, statut=ANNULE)
    assert prioritaires_du_mois(session, e, MAINTENANT, "Africa/Douala") == 0
    assert choisir(session, e, 2, MAINTENANT).canal == WHATSAPP


def test_les_messages_libres_ne_comptent_pas(session, whatsapp_configure):
    e = entreprise(session)
    conversation = conversation_wa(session, e, fermee())
    for _ in range(6):
        session.add(WhatsappEnvoi(conversation_id=conversation.id, destinataire="1", contenu={}, statut=WA_ENVOYE,
                                  essais=0, entreprise_id=e.id))
    session.flush()
    assert prioritaires_du_mois(session, e, MAINTENANT, "Africa/Douala") == 0


def test_le_mois_precedent_ne_compte_pas(session, whatsapp_configure):
    e = entreprise(session)
    conversation = conversation_wa(session, e, fermee())
    for _ in range(5):
        envoi_prioritaire(session, e, conversation, cree_le=datetime(2026, 9, 30, 22, 0, tzinfo=timezone.utc))
    # 30 septembre 22 h UTC = 23 h à Douala : encore septembre.
    assert prioritaires_du_mois(session, e, MAINTENANT, "Africa/Douala") == 0
    envoi_prioritaire(session, e, conversation, cree_le=datetime(2026, 9, 30, 23, 30, tzinfo=timezone.utc))
    # 30 septembre 23 h 30 UTC = 1er octobre 0 h 30 à Douala : octobre.
    assert prioritaires_du_mois(session, e, MAINTENANT, "Africa/Douala") == 1


def test_debut_du_mois_a_douala():
    assert debut_du_mois(datetime(2026, 10, 13, 6, 30, tzinfo=timezone.utc), "Africa/Douala") == datetime(2026, 9, 30, 23, 0, tzinfo=timezone.utc)
    assert debut_du_mois(datetime(2026, 10, 31, 23, 30, tzinfo=timezone.utc), "Africa/Douala") == datetime(2026, 10, 31, 23, 0, tzinfo=timezone.utc)


def test_plafond_par_entreprise(session, whatsapp_configure):
    a, b = entreprise(session), entreprise(session)
    conversation_a = conversation_wa(session, a, fermee())
    conversation_wa(session, b, fermee())
    for _ in range(5):
        envoi_prioritaire(session, a, conversation_a)
    assert choisir(session, a, 2, MAINTENANT).canal == BULLE
    assert choisir(session, b, 2, MAINTENANT).canal == WHATSAPP


def test_sans_nom_de_modele_repli(session, monkeypatch, whatsapp_configure):
    monkeypatch.setenv("WHATSAPP_MODELE_RAPPEL", "")
    get_settings.cache_clear()
    e = entreprise(session)
    conversation_wa(session, e, fermee())
    assert choisir(session, e, 2, MAINTENANT).canal == BULLE


def test_conversation_la_plus_recente(session, whatsapp_configure):
    e = entreprise(session)
    conversation_wa(session, e, fermee())
    recente = conversation_wa(session, e, ouverte())
    conversation_wa(session, e, None)
    assert choisir(session, e, 7, MAINTENANT).conversation.id == recente.id


def test_conversation_web_ignoree(session, whatsapp_configure):
    e = entreprise(session)
    web = trouver_ou_creer_conversation(session, CANAL_WEB, "web-" + uuid.uuid4().hex)
    web.entreprise_id = e.id
    web.dernier_message_client_le = ouverte()
    session.flush()
    assert choisir(session, e, 7, MAINTENANT).canal == BULLE


# --- Préparation --------------------------------------------------------------------------------

def test_rappel_whatsapp_dans_la_fenetre(session, regles, whatsapp_configure):
    e = entreprise(session)
    conversation = conversation_wa(session, e, MAINTENANT - timedelta(hours=1))
    [rappel] = preparer_entreprise(session, e, J7, maintenant=MAINTENANT)
    assert (rappel.canal, rappel.statut, rappel.palier, rappel.conversation_id) == (WHATSAPP, A_ENVOYER, 7, conversation.id)
    [message] = envois_de(session, e)
    assert (message.rappel_id, message.modele, message.destinataire) == (rappel.id, None, conversation.identifiant_externe)
    assert message.contenu == format.textes(
        "\n".join([f"Rappel : « {TITRE_TVA} » — septembre 2026.",
                   "Au plus tard le jeudi 15 octobre 2026 (dans 7 jours).", mf.OBLIGATIONS_AVERTISSEMENT])
    )[0]
    assert session.scalars(select(Email).where(Email.rappel_id == rappel.id)).all() == []


def test_rappel_j2_par_modele(session, regles, whatsapp_configure):
    e = entreprise(session)
    conversation_wa(session, e, fermee())
    [rappel] = preparer_entreprise(session, e, J2, maintenant=MAINTENANT)
    [message] = envois_de(session, e)
    assert message.modele == "jeff_rappel_echeance"
    assert message.contenu == {
        "type": "template",
        "template": {
            "name": "jeff_rappel_echeance",
            "language": {"code": "fr"},
            "components": [{"type": "body", "parameters": [
                {"type": "text", "text": "Ets WhatsApp"},
                {"type": "text", "text": TITRE_TVA},
                {"type": "text", "text": "septembre 2026"},
                {"type": "text", "text": "jeudi 15 octobre 2026"},
            ]}],
        },
    }
    assert rappel.canal == WHATSAPP


def test_rappel_j7_fenetre_fermee_par_email(session, regles, whatsapp_configure):
    e = entreprise(session, email_confirme=True)
    conversation_wa(session, e, fermee())
    [rappel] = preparer_entreprise(session, e, J7, maintenant=MAINTENANT)
    assert rappel.canal == EMAIL
    assert envois_de(session, e) == []
    assert session.scalars(select(Email).where(Email.rappel_id == rappel.id, Email.type == EMAIL_RAPPEL)).one()


def test_j2_annule_le_whatsapp_j7_non_parti(session, regles, whatsapp_configure):
    e = entreprise(session)
    conversation_wa(session, e, MAINTENANT - timedelta(hours=1))
    preparer_entreprise(session, e, J7, maintenant=MAINTENANT)
    preparer_entreprise(session, e, J2, maintenant=MAINTENANT)
    assert [(m.statut, session.get(Rappel, m.rappel_id).palier) for m in envois_de(session, e)] == [(ANNULE, 7), (WA_A_ENVOYER, 2)]
    assert [r.statut for r in session.scalars(select(Rappel).where(Rappel.entreprise_id == e.id).order_by(Rappel.id))] == [IGNORE, A_ENVOYER]


def test_whatsapp_deja_parti_non_annule(session, regles, whatsapp_configure):
    e = entreprise(session)
    conversation_wa(session, e, MAINTENANT - timedelta(hours=1))
    preparer_entreprise(session, e, J7, maintenant=MAINTENANT)
    envois_de(session, e)[0].statut = WA_ENVOYE
    session.flush()
    preparer_entreprise(session, e, J2, maintenant=MAINTENANT)
    assert [m.statut for m in envois_de(session, e)] == [WA_ENVOYE, WA_A_ENVOYER]


def test_preparation_compte_le_plafond(session, regles, whatsapp_configure):
    e = entreprise(session)
    conversation = conversation_wa(session, e, fermee())
    for _ in range(5):
        envoi_prioritaire(session, e, conversation)
    [rappel] = preparer_entreprise(session, e, J2, maintenant=MAINTENANT)
    assert rappel.canal == BULLE


# --- Envoi et repli -------------------------------------------------------------------------------

def rappel_whatsapp(session, email_confirme=False, fenetre=None, jour=J2):
    charger_fichier(session, FICHIER_CM)
    e = entreprise(session, email_confirme)
    conversation = conversation_wa(session, e, fenetre or fermee())
    [rappel] = preparer_entreprise(session, e, jour, maintenant=MAINTENANT)
    [message] = envois_de(session, e)
    return e, conversation, rappel, message


def test_envoi_reussi(session, meta):
    e, _, rappel, message = rappel_whatsapp(session)
    assert envoi.envoyer_un(session, message.id) is True
    assert meta.appels[0]["json"]["type"] == "template"
    session.refresh(rappel)
    assert (rappel.statut, rappel.canal) == (ENVOYE, WHATSAPP)
    assert rappel.envoye_le is not None


def test_refus_de_meta_repli_immediat_par_email(session, meta):
    e, _, rappel, message = rappel_whatsapp(session, email_confirme=True)
    meta.reponse = ReponseHttp(400, {"error": {"code": 132001, "message": "Template name does not exist in the translation"}})
    assert envoi.envoyer_un(session, message.id) is False
    session.refresh(message)
    session.refresh(rappel)
    assert (message.statut, message.essais) == (ECHEC, 1)
    assert message.erreur == "ErreurMeta: HTTP 400 : 132001 Template name does not exist in the translation"
    assert (rappel.canal, rappel.statut, rappel.conversation_id) == (EMAIL, A_ENVOYER, None)
    [email] = session.scalars(select(Email).where(Email.rappel_id == rappel.id)).all()
    assert email.type == EMAIL_RAPPEL
    assert email.destinataire == e.email


def test_refus_de_meta_repli_dans_la_bulle(session, meta, monkeypatch):
    e, _, rappel, message = rappel_whatsapp(session)
    meta.reponse = ReponseHttp(400, {"error": {"code": 131047, "message": "Re-engagement message"}})
    envoi.envoyer_un(session, message.id)
    session.refresh(rappel)
    assert (rappel.canal, rappel.statut) == (BULLE, A_ENVOYER)
    web = trouver_ou_creer_conversation(session, CANAL_WEB, "web-" + uuid.uuid4().hex)
    web.entreprise_id = e.id
    session.flush()
    monkeypatch.setattr(livraison, "aujourd_hui", lambda fuseau: J2)
    assert len(traiter_message(session, CANAL_WEB, web.identifiant_externe, "bonjour").rappels) == 1


def test_trop_d_envois_on_reessaie(session, meta):
    _, _, rappel, message = rappel_whatsapp(session)
    meta.reponse = ReponseHttp(429, {"error": {"code": 130429, "message": "Rate limit hit"}})
    envoi.envoyer_un(session, message.id)
    session.refresh(message)
    assert (message.statut, message.essais) == (WA_A_ENVOYER, 1)
    assert session.get(Rappel, rappel.id).canal == WHATSAPP


def test_erreur_meta_serveur_on_reessaie(session, meta):
    _, _, _, message = rappel_whatsapp(session)
    meta.reponse = ReponseHttp(500, {"error": {"code": 1, "message": "Unknown"}})
    envoi.envoyer_un(session, message.id)
    session.refresh(message)
    assert message.statut == WA_A_ENVOYER


def test_trois_pannes_reseau_puis_repli(session, meta):
    _, _, rappel, message = rappel_whatsapp(session, email_confirme=True)
    meta.panne = ConnectionError("coupure")
    for _ in range(envoi.ESSAIS_MAX):
        envoi.envoyer_un(session, message.id)
    session.refresh(rappel)
    assert rappel.canal == EMAIL


def test_echec_d_un_message_sans_rappel(session, meta):
    conversation = trouver_ou_creer_conversation(session, CANAL_WHATSAPP, numero_unique())
    m = WhatsappEnvoi(conversation_id=conversation.id, destinataire="1", contenu={}, statut=WA_A_ENVOYER, essais=0)
    session.add(m)
    session.flush()
    meta.reponse = ReponseHttp(400, {"error": {"code": 100, "message": "Invalid"}})
    assert envoi.envoyer_un(session, m.id) is False
    assert m.statut == ECHEC


def test_erreur_definitive():
    assert envoi.ErreurMeta("x", 400).definitive is True
    assert envoi.ErreurMeta("x", 499).definitive is True
    assert envoi.ErreurMeta("x", 429).definitive is False
    assert envoi.ErreurMeta("x", 500).definitive is False
    assert envoi.ErreurMeta("x").definitive is False


# --- Accusés de Meta (statuts) --------------------------------------------------------------------

def envoyer(session, message):
    """Envoi réel (Meta simulé), puis identifiant Meta unique : la base de test garde des envois d'autres tests."""
    envoi.envoyer_un(session, message.id)
    session.refresh(message)
    message.wamid = "wamid.unique." + uuid.uuid4().hex
    session.flush()


def statut(wamid, etat, code=131026, titre="Message undeliverable", numero_jeff=NUMERO_JEFF):
    donnees = notification(numero_unique(), numero_jeff=numero_jeff)
    valeur = donnees["entry"][0]["changes"][0]["value"]
    del valeur["messages"]
    valeur["statuses"] = [{"id": wamid, "status": etat, "timestamp": "1790000000", "recipient_id": "1",
                           **({"errors": [{"code": code, "title": titre}]} if etat == "failed" else {})}]
    return donnees


def test_statut_echec_apres_envoi_repli(session, meta):
    e, _, rappel, message = rappel_whatsapp(session, email_confirme=True)
    envoyer(session, message)
    assert reception.traiter_notification(session, statut(message.wamid, "failed")) == []
    session.refresh(message)
    session.refresh(rappel)
    assert (message.statut, message.erreur) == (ECHEC, "Meta : 131026 Message undeliverable")
    assert rappel.canal == EMAIL
    assert session.scalars(select(Email).where(Email.rappel_id == rappel.id)).one()
    # Un second accusé d'échec ne déclenche pas un second email.
    reception.traiter_notification(session, statut(message.wamid, "failed"))
    assert len(session.scalars(select(Email).where(Email.rappel_id == rappel.id)).all()) == 1


@pytest.mark.parametrize("etat", ["sent", "delivered", "read"])
def test_statuts_ordinaires_sans_effet(session, meta, etat):
    _, _, rappel, message = rappel_whatsapp(session)
    envoyer(session, message)
    reception.traiter_notification(session, statut(message.wamid, etat))
    session.refresh(message)
    assert message.statut == WA_ENVOYE
    assert session.get(Rappel, rappel.id).statut == ENVOYE


def test_statut_inconnu_ou_autre_numero(session, meta):
    _, _, rappel, message = rappel_whatsapp(session)
    envoyer(session, message)
    assert reception.traiter_statuts(session, statut("wamid.inconnu", "failed")) == 0
    assert reception.traiter_statuts(session, statut(message.wamid, "failed", numero_jeff="999")) == 0
    session.refresh(message)
    assert message.statut == WA_ENVOYE


def test_statut_echec_sans_detail(session, meta):
    _, _, _, message = rappel_whatsapp(session)
    envoyer(session, message)
    donnees = statut(message.wamid, "failed")
    del donnees["entry"][0]["changes"][0]["value"]["statuses"][0]["errors"]
    assert reception.traiter_statuts(session, donnees) == 1
    session.refresh(message)
    assert message.erreur == "Meta : None None"


def test_webhook_avec_statuts_seulement(meta):
    from tests.test_lot09_whatsapp import TestClient as Client, poster

    reponse = poster(Client(app), statut("wamid.absent", "delivered"))
    assert (reponse.status_code, reponse.json()) == (200, {"ok": True})
    assert meta.appels == []


# --- Modèle Meta ---------------------------------------------------------------------------------

def test_texte_du_modele_respecte_les_regles_de_meta():
    texte = mf.MODELE_RAPPEL_TEXTE
    assert re.findall(r"\{\{(\d+)\}\}", texte) == ["1", "2", "3", "4"]
    assert not texte.lstrip().startswith("{{") and not texte.rstrip(" .").endswith("}}")
    assert not re.search(r"\}\}\s*\{\{", texte)
    assert len(texte) <= 1024
    assert "\n" not in texte
    assert len(mf.MODELE_RAPPEL_EXEMPLE) == 4
    assert re.search(r"\b(vous|votre|vos)\b|Répondez", texte)


def test_parametres_nettoyes():
    assert format.parametre("Ets\nBABA\t  et   fils") == {"type": "text", "text": "Ets BABA et fils"}
    assert len(format.parametre("x" * 300)["text"]) == format.PARAMETRE_MAX == 100


def test_definition_du_modele(whatsapp_configure):
    definition = modeles.definition()
    assert definition == {
        "name": "jeff_rappel_echeance", "language": "fr", "category": "UTILITY",
        "components": [{"type": "BODY", "text": mf.MODELE_RAPPEL_TEXTE,
                        "example": {"body_text": [list(mf.MODELE_RAPPEL_EXEMPLE)]}}],
    }
    assert re.fullmatch(r"[a-z0-9_]+", definition["name"])


@pytest.fixture
def compte(monkeypatch, whatsapp_configure):
    monkeypatch.setenv("WHATSAPP_ID_COMPTE", "1701078431037415")
    get_settings.cache_clear()


class FauxHttp:
    def __init__(self, reponse):
        self.reponse = reponse
        self.appels = []

    def __call__(self, url, **kwargs):
        self.appels.append({"url": url, **kwargs})
        return self.reponse


def test_commande_creer(compte, monkeypatch, capsys):
    faux = FauxHttp(ReponseHttp(200, {"id": "123", "status": "PENDING", "category": "UTILITY"}))
    monkeypatch.setattr(modeles.httpx, "post", faux)
    assert modeles.main(["creer"]) == 0
    [appel] = faux.appels
    assert appel["url"] == "https://graph.facebook.com/v23.0/1701078431037415/message_templates"
    assert appel["json"] == modeles.definition()
    assert appel["headers"] == {"Authorization": "Bearer jeton-meta-de-test"}
    sortie = capsys.readouterr().out
    assert "statut PENDING, catégorie UTILITY" in sortie
    assert "jeton-meta-de-test" not in sortie


def test_commande_creer_refus(compte, monkeypatch, capsys):
    monkeypatch.setattr(modeles.httpx, "post", FauxHttp(ReponseHttp(400, {"error": {"code": 100, "error_user_msg": "Le nom existe déjà"}})))
    assert modeles.main(["creer"]) == 1
    assert "Refus de Meta (HTTP 400) : 100 Le nom existe déjà" in capsys.readouterr().out


def test_commande_statut(compte, monkeypatch, capsys):
    faux = FauxHttp(ReponseHttp(200, {"data": [
        {"name": "jeff_rappel_echeance", "language": "fr", "category": "UTILITY", "status": "APPROVED", "rejected_reason": "NONE"},
    ]}))
    monkeypatch.setattr(modeles.httpx, "get", faux)
    assert modeles.main(["statut"]) == 0
    assert faux.appels[0]["params"]["name"] == "jeff_rappel_echeance"
    assert capsys.readouterr().out.strip() == "jeff_rappel_echeance (fr, UTILITY) : APPROVED"


def test_commande_statut_refuse(compte, monkeypatch, capsys):
    monkeypatch.setattr(modeles.httpx, "get", FauxHttp(ReponseHttp(200, {"data": [
        {"name": "jeff_rappel_echeance", "language": "fr", "category": "UTILITY", "status": "REJECTED", "rejected_reason": "INVALID_FORMAT"},
    ]})))
    modeles.main(["statut"])
    assert "REJECTED, motif : INVALID_FORMAT" in capsys.readouterr().out


def test_commande_statut_absent_ou_erreur(compte, monkeypatch, capsys):
    monkeypatch.setattr(modeles.httpx, "get", FauxHttp(ReponseHttp(200, {"data": []})))
    assert modeles.main(["statut"]) == 1
    monkeypatch.setattr(modeles.httpx, "get", FauxHttp(ReponseHttp(401, None, "Unauthorized")))
    assert modeles.main(["statut"]) == 1
    sortie = capsys.readouterr().out
    assert "lancez d'abord « creer »" in sortie and "HTTP 401" in sortie


def test_commande_sans_configuration(monkeypatch, capsys, whatsapp_configure):
    monkeypatch.delenv("WHATSAPP_ID_COMPTE", raising=False)
    get_settings.cache_clear()
    assert modeles.main(["creer"]) == 1
    monkeypatch.setenv("WHATSAPP_ID_COMPTE", "A_REMPLACER")
    get_settings.cache_clear()
    assert modeles.main(["statut"]) == 1
    assert "pas configuré" in capsys.readouterr().out


def test_commande_usage(compte, capsys):
    assert modeles.main([]) == 1
    assert modeles.main(["supprimer"]) == 1
    assert "Usage" in capsys.readouterr().out


# --- Journaux, configuration, base, version -------------------------------------------------------

def test_journal_sans_jeton_de_verification():
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d', (
        "1.2.3.4", "GET", "/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=SECRET123&hub_verify_token=SECRET123", "1.1", 200,
    ), None)
    assert MasquerJetons().filter(record) is True
    assert "SECRET123" not in record.getMessage()
    assert "hub.verify_token=***&hub_verify_token=***" in record.getMessage()
    assert record.args[4] == 200
    assert any(isinstance(f, MasquerJetons) for f in logging.getLogger("uvicorn.access").filters)


def test_journal_sans_arguments():
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, "démarrage", None, None)
    assert MasquerJetons().filter(record) is True


def test_fichier_env_exemple():
    assert "WHATSAPP_ID_COMPTE=A_REMPLACER" in (RACINE / ".env.example").read_text()


def test_colonnes():
    colonnes = {c["name"]: c for c in inspect(get_engine()).get_columns("whatsapp_envois")}
    for nom in ("entreprise_id", "rappel_id", "modele"):
        assert colonnes[nom]["nullable"] is True
    index = {i["name"] for i in inspect(get_engine()).get_indexes("whatsapp_envois")}
    assert {"ix_whatsapp_envois_entreprise_id", "ix_whatsapp_envois_wamid"} <= index
    cles = {fk["referred_table"] for fk in inspect(get_engine()).get_foreign_keys("whatsapp_envois")}
    assert cles == {"conversations", "entreprises", "rappels"}


def test_version():
    assert TestClient(app).get("/sante").json()["version"] == VERSION


# --- Cas limites (compléments) --------------------------------------------------------------------

def test_deux_messages_du_meme_rappel_echouent_un_seul_repli(session, meta):
    e, conversation, rappel, premier = rappel_whatsapp(session, email_confirme=True)
    second = WhatsappEnvoi(conversation_id=conversation.id, destinataire=conversation.identifiant_externe,
                           contenu={"type": "text", "text": {"body": "suite"}}, statut=WA_A_ENVOYER, essais=0,
                           entreprise_id=e.id, rappel_id=rappel.id)
    session.add(second)
    session.flush()
    meta.reponse = ReponseHttp(400, {"error": {"code": 131047, "message": "Re-engagement message"}})
    envoi.envoyer_un(session, premier.id)
    envoi.envoyer_un(session, second.id)
    assert len(session.scalars(select(Email).where(Email.rappel_id == rappel.id)).all()) == 1


def test_un_second_accuse_d_echec_ne_change_rien(session, meta):
    _, _, _, message = rappel_whatsapp(session, email_confirme=True)
    envoyer(session, message)
    reception.traiter_notification(session, statut(message.wamid, "failed", code=131026, titre="Undeliverable"))
    assert reception.traiter_statuts(session, statut(message.wamid, "failed", code=999, titre="Autre")) == 0
    session.refresh(message)
    assert message.erreur == "Meta : 131026 Undeliverable"


def test_accuse_incomplet_ignore(session, whatsapp_configure):
    donnees = statut("wamid.x", "failed")
    donnees["entry"][0]["changes"][0]["value"]["statuses"] += [{"status": "failed"}, {"id": "wamid.y"}]
    assert len(reception.statuts_recus(donnees)) == 1
    assert reception.traiter_statuts(session, donnees) == 0
