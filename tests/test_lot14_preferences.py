"""Lot 14 — coffre fiscal : préférences de rappels (WhatsApp par numéro, email) et historique des modifications."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from app.conversation import messages_fixes as mf
from app.conversation.models import CANAL_WEB, CANAL_WHATSAPP, Conversation
from app.conversation.moteur import traiter_message, trouver_ou_creer_conversation
from app.core.config import VERSION
from app.core.db import get_engine
from app.emails import models as emails
from app.entreprises.models import COFFRE, CONVERSATION, ORIGINES, Entreprise, ModificationEntreprise
from app.espace import donnees
from app.espace import textes as tx
from app.espace.models import SessionEspace
from app.rappels import preferences
from app.rappels.canal import BULLE, EMAIL, WHATSAPP, canal_de_repli
from app.rappels.models import Rappel
from app.rappels.preparation import preparer_entreprise
from app.whatsapp import models as whatsapp
from tests.test_lot09_whatsapp import whatsapp_configure  # noqa: F401 (fixture)
from tests.test_lot10_rappels_whatsapp import J2, J7, MAINTENANT, conversation_wa, fermee, regles  # noqa: F401
from tests.test_lot12_espace import adresse_unique, connecter, creer, espace, texte_visible  # noqa: F401


def entreprise_confirmee(session, nom="Ets Préférences", adresse=None) -> Entreprise:
    return creer(session, nom, adresse or adresse_unique())


def modifications(session, e) -> list[ModificationEntreprise]:
    return list(session.scalars(
        select(ModificationEntreprise).where(ModificationEntreprise.entreprise_id == e.id).order_by(ModificationEntreprise.id)
    ))


def session_du_coffre(session, adresse) -> SessionEspace:
    return session.scalars(select(SessionEspace).where(SessionEspace.email == adresse)).one()


# --- Routage ------------------------------------------------------------------------------------

def test_repli_email_seulement_si_rappels_email_actifs(session):
    e = entreprise_confirmee(session)
    assert canal_de_repli(e) == EMAIL
    e.rappels_email = False
    assert canal_de_repli(e) == BULLE


def test_preparation_sans_email_si_arrete(session, regles):  # noqa: F811
    e = entreprise_confirmee(session)
    e.rappels_email = False
    [rappel] = preparer_entreprise(session, e, J7, maintenant=MAINTENANT)
    assert rappel.canal == BULLE
    assert session.scalars(select(emails.Email).where(emails.Email.rappel_id == rappel.id)).all() == []


# --- Rappels par email --------------------------------------------------------------------------

def test_arreter_les_emails_replie_les_rappels_en_attente(session, regles):  # noqa: F811
    e = entreprise_confirmee(session)
    [rappel] = preparer_entreprise(session, e, J7, maintenant=MAINTENANT)
    [email] = session.scalars(select(emails.Email).where(emails.Email.rappel_id == rappel.id)).all()
    assert rappel.canal == EMAIL and email.statut == emails.A_ENVOYER
    assert preferences.changer_rappels_email(session, e, False, COFFRE, None) is True
    assert e.rappels_email is False and email.statut == emails.ANNULE
    assert (rappel.canal, rappel.statut) == (BULLE, "a_envoyer")
    [trace] = modifications(session, e)
    assert (trace.champ, trace.ancienne_valeur, trace.nouvelle_valeur, trace.origine) == ("rappels_email", True, False, COFFRE)
    assert trace.conversation_id is None


def test_emails_deja_partis_et_autres_types_intacts(session, regles):  # noqa: F811
    e = entreprise_confirmee(session)
    [rappel] = preparer_entreprise(session, e, J7, maintenant=MAINTENANT)
    [email] = session.scalars(select(emails.Email).where(emails.Email.rappel_id == rappel.id)).all()
    email.statut = emails.ENVOYE
    code = emails.Email(type=emails.CODE, destinataire=e.email, objet="o", texte="t", html="h", entreprise_id=e.id,
                        statut=emails.A_ENVOYER, essais=0)
    autre = entreprise_confirmee(session, "Ets Autre")
    [rappel_autre] = preparer_entreprise(session, autre, J7, maintenant=MAINTENANT)
    session.add(code)
    session.flush()
    preferences.changer_rappels_email(session, e, False, COFFRE)
    assert email.statut == emails.ENVOYE and code.statut == emails.A_ENVOYER and rappel.canal == EMAIL
    [email_autre] = session.scalars(select(emails.Email).where(emails.Email.rappel_id == rappel_autre.id)).all()
    assert email_autre.statut == emails.A_ENVOYER


def test_reactiver_les_emails(session):
    e = entreprise_confirmee(session)
    preferences.changer_rappels_email(session, e, False, COFFRE)
    assert preferences.changer_rappels_email(session, e, False, COFFRE) is False
    assert preferences.changer_rappels_email(session, e, True, COFFRE, None) is True
    assert e.rappels_email is True and canal_de_repli(e) == EMAIL
    assert [(m.ancienne_valeur, m.nouvelle_valeur) for m in modifications(session, e)] == [(True, False), (False, True)]


# --- Rappels WhatsApp ---------------------------------------------------------------------------

def test_arreter_whatsapp_replie_les_envois_en_attente(session, regles, whatsapp_configure):  # noqa: F811
    e = entreprise_confirmee(session)
    conversation = conversation_wa(session, e, fermee())
    [rappel] = preparer_entreprise(session, e, J2, maintenant=MAINTENANT)
    [envoi] = session.scalars(select(whatsapp.WhatsappEnvoi).where(whatsapp.WhatsappEnvoi.rappel_id == rappel.id)).all()
    assert rappel.canal == WHATSAPP
    assert preferences.changer_rappels_whatsapp(session, conversation, False, COFFRE, None) is True
    assert conversation.rappels_whatsapp is False and envoi.statut == whatsapp.ANNULE
    assert (rappel.canal, rappel.conversation_id) == (EMAIL, None)
    assert session.scalars(select(emails.Email).where(emails.Email.rappel_id == rappel.id)).one().statut == emails.A_ENVOYER
    [trace] = modifications(session, e)
    assert (trace.champ, trace.ancienne_valeur, trace.nouvelle_valeur) == ("rappels_whatsapp", True, False)
    assert (trace.conversation_id, trace.origine) == (conversation.id, COFFRE)


def test_arreter_whatsapp_ne_touche_que_ce_numero(session, whatsapp_configure):
    e = entreprise_confirmee(session)
    premier, second = conversation_wa(session, e), conversation_wa(session, e)
    autre = whatsapp.WhatsappEnvoi(conversation_id=second.id, destinataire="x", contenu={}, statut=whatsapp.A_ENVOYER,
                                   essais=0, entreprise_id=e.id)
    reponse = whatsapp.WhatsappEnvoi(conversation_id=premier.id, destinataire="x", contenu={}, statut=whatsapp.A_ENVOYER,
                                     essais=0, entreprise_id=e.id)  # Réponse ordinaire, sans rappel.
    session.add_all([autre, reponse])
    session.flush()
    preferences.changer_rappels_whatsapp(session, premier, False, COFFRE)
    assert second.rappels_whatsapp is True and autre.statut == reponse.statut == whatsapp.A_ENVOYER


def test_seuls_les_envois_en_attente_de_ce_numero(session, regles, whatsapp_configure):  # noqa: F811
    e = entreprise_confirmee(session)
    ancienne = conversation_wa(session, e, fermee() - timedelta(days=1))
    recente = conversation_wa(session, e, fermee())
    [rappel] = preparer_entreprise(session, e, J2, maintenant=MAINTENANT)
    [envoi] = session.scalars(select(whatsapp.WhatsappEnvoi).where(whatsapp.WhatsappEnvoi.rappel_id == rappel.id)).all()
    assert envoi.conversation_id == recente.id
    preferences.changer_rappels_whatsapp(session, ancienne, False, COFFRE)
    assert envoi.statut == whatsapp.A_ENVOYER and rappel.canal == WHATSAPP
    envoi.statut = whatsapp.ENVOYE
    session.flush()
    preferences.changer_rappels_whatsapp(session, recente, False, COFFRE)
    assert envoi.statut == whatsapp.ENVOYE and rappel.canal == WHATSAPP


def test_valeur_par_defaut_du_modele():
    colonne = Entreprise.__table__.c.rappels_email
    assert colonne.server_default.arg.text == "true" and colonne.default.arg is True


def test_reactiver_whatsapp(session):
    e = entreprise_confirmee(session)
    conversation = conversation_wa(session, e)
    assert preferences.changer_rappels_whatsapp(session, conversation, True, COFFRE) is False
    preferences.changer_rappels_whatsapp(session, conversation, False, COFFRE)
    preferences.changer_rappels_whatsapp(session, conversation, True, COFFRE)
    assert conversation.rappels_whatsapp is True
    assert [(m.nouvelle_valeur, m.origine) for m in modifications(session, e)] == [(False, COFFRE), (True, COFFRE)]


def test_stop_sur_whatsapp_trace_et_replie(session, regles, whatsapp_configure):  # noqa: F811
    e = entreprise_confirmee(session)
    conversation = conversation_wa(session, e, fermee())
    [rappel] = preparer_entreprise(session, e, J2, maintenant=MAINTENANT)
    assert traiter_message(session, CANAL_WHATSAPP, conversation.identifiant_externe, "STOP").texte == mf.WA_STOP
    assert rappel.canal == EMAIL
    assert traiter_message(session, CANAL_WHATSAPP, conversation.identifiant_externe, "start").texte == mf.WA_RAPPELS_REPRIS
    traces = modifications(session, e)
    assert [(m.champ, m.nouvelle_valeur, m.origine, m.conversation_id) for m in traces] == [
        ("rappels_whatsapp", False, CONVERSATION, conversation.id), ("rappels_whatsapp", True, CONVERSATION, conversation.id),
    ]


def test_stop_sans_entreprise_pas_de_trace(session):
    conversation = trouver_ou_creer_conversation(session, CANAL_WHATSAPP, "2376" + uuid.uuid4().hex[:8])
    traiter_message(session, CANAL_WHATSAPP, conversation.identifiant_externe, "stop")
    assert conversation.rappels_whatsapp is False
    assert session.scalars(select(ModificationEntreprise).where(ModificationEntreprise.conversation_id == conversation.id)).all() == []


# --- Coffre : interrupteurs ---------------------------------------------------------------------

def test_interrupteurs_affiches(espace, session):
    adresse = adresse_unique()
    e = entreprise_confirmee(session, "Ets Interrupteurs", adresse)
    premier, second = conversation_wa(session, e), conversation_wa(session, e)
    second.rappels_whatsapp = False
    session.flush()
    html = connecter(session, adresse).get("/espace/entreprise").text
    assert html.count('<form method="post" action="http://testserver/espace/entreprise/rappels" class="esp-interrupteur">') == 3
    assert f'name="numero" value="{premier.id}"' in html and f'name="numero" value="{second.id}"' in html
    # Chaque bouton propose l'inverse de l'état actuel.
    valeurs = [html.split(f'name="numero" value="{n}"', 1)[1].split('name="actifs" value="', 1)[1][:1] for n in (premier.id, second.id, "")]
    assert valeurs == ["0", "1", "0"]
    texte = texte_visible(html)
    assert f"{tx.RAPPELS_WHATSAPP} (•••• {premier.identifiant_externe[-4:]})" in texte
    assert texte.count(tx.ARRETER) == 2 and texte.count(tx.REACTIVER) == 1 and tx.RAPPELS_AIDE in texte
    assert f"{tx.RAPPELS_EMAIL} {tx.ACTIFS} {tx.ARRETER}" in texte


def test_un_seul_numero_sans_detail(espace, session):
    adresse = adresse_unique()
    e = entreprise_confirmee(session, "Ets Un Numéro", adresse)
    conversation_wa(session, e)
    texte = texte_visible(connecter(session, adresse).get("/espace/entreprise").text)
    assert f"{tx.RAPPELS_WHATSAPP} {tx.ACTIFS} {tx.ARRETER}" in texte and "(••••" not in texte


def test_arreter_les_emails_depuis_le_coffre(espace, session):
    adresse = adresse_unique()
    e = entreprise_confirmee(session, "Ets Email", adresse)
    client = connecter(session, adresse)
    reponse = client.post("/espace/entreprise/rappels", data={"canal": "email", "actifs": "0"}, follow_redirects=False)
    assert reponse.status_code == 303 and reponse.headers["location"].endswith("/espace/entreprise?info=enregistre")
    assert e.rappels_email is False
    [trace] = modifications(session, e)
    assert (trace.origine, trace.session_espace_id) == (COFFRE, session_du_coffre(session, adresse).id)
    texte = texte_visible(client.get("/espace/entreprise?info=enregistre").text)
    assert tx.ENREGISTRE in texte and f"{tx.RAPPELS_EMAIL} {tx.ARRETES} {tx.REACTIVER}" in texte
    client.post("/espace/entreprise/rappels", data={"canal": "email", "actifs": "1"})
    assert e.rappels_email is True


def test_arreter_un_numero_depuis_le_coffre(espace, session):
    adresse = adresse_unique()
    e = entreprise_confirmee(session, "Ets Numéro", adresse)
    conversation = conversation_wa(session, e)
    client = connecter(session, adresse)
    client.post("/espace/entreprise/rappels", data={"canal": "whatsapp", "numero": str(conversation.id), "actifs": "0"})
    assert conversation.rappels_whatsapp is False
    [trace] = modifications(session, e)
    assert (trace.champ, trace.conversation_id, trace.origine) == ("rappels_whatsapp", conversation.id, COFFRE)


@pytest.mark.parametrize("cas", ["inconnu", "autre_entreprise", "web", "pas_un_uuid", "vide"])
def test_numero_refuse(espace, session, cas):
    adresse = adresse_unique()
    e = entreprise_confirmee(session, "Ets Refus", adresse)
    autre = entreprise_confirmee(session, "Ets Étrangère")
    numero = {
        "inconnu": str(uuid.uuid4()),
        "autre_entreprise": str(conversation_wa(session, autre).id),
        "web": str(trouver_ou_creer_conversation(session, CANAL_WEB, "web-" + uuid.uuid4().hex).id),
        "pas_un_uuid": "abc",
        "vide": "",
    }[cas]
    if cas == "web":
        session.get(Conversation, uuid.UUID(numero)).entreprise_id = e.id
        session.flush()
    client = connecter(session, adresse)
    reponse = client.post("/espace/entreprise/rappels", data={"canal": "whatsapp", "numero": numero, "actifs": "0"},
                          follow_redirects=False)
    assert reponse.headers["location"].endswith("/espace/entreprise?info=impossible")
    assert modifications(session, e) == [] and modifications(session, autre) == []
    assert tx.CHANGEMENT_IMPOSSIBLE in texte_visible(client.get("/espace/entreprise?info=impossible").text)


@pytest.mark.parametrize("donnees_envoyees", [
    {"canal": "email", "actifs": "oui"}, {"canal": "email"}, {"canal": "sms", "actifs": "0"}, {"actifs": "0"},
])
def test_formulaire_invalide(espace, session, donnees_envoyees):
    adresse = adresse_unique()
    e = entreprise_confirmee(session, "Ets Invalide", adresse)
    reponse = connecter(session, adresse).post("/espace/entreprise/rappels", data=donnees_envoyees, follow_redirects=False)
    assert reponse.headers["location"].endswith("/espace/entreprise?info=impossible")
    assert e.rappels_email is True and modifications(session, e) == []


def test_interrupteur_sans_session(espace, session):
    from fastapi.testclient import TestClient

    from app.main import app

    reponse = TestClient(app, follow_redirects=False).post("/espace/entreprise/rappels", data={"canal": "email", "actifs": "0"})
    assert reponse.headers["location"].endswith("/espace/connexion")


def test_interrupteur_seulement_en_post(espace, session):
    adresse = adresse_unique()
    entreprise_confirmee(session, "Ets Get", adresse)
    assert connecter(session, adresse).get("/espace/entreprise/rappels").status_code == 405


def test_message_inconnu_ignore(espace, session):
    adresse = adresse_unique()
    entreprise_confirmee(session, "Ets Info", adresse)
    html = connecter(session, adresse).get("/espace/entreprise?info=autre").text
    assert "esp-message" not in html


# --- Historique ---------------------------------------------------------------------------------

def ajouter_trace(session, e, champ, avant, apres, il_y_a=timedelta(0), **champs):
    trace = ModificationEntreprise(entreprise_id=e.id, champ=champ, ancienne_valeur=avant, nouvelle_valeur=apres, **champs)
    session.add(trace)
    session.flush()
    session.execute(ModificationEntreprise.__table__.update().where(ModificationEntreprise.id == trace.id)
                    .values(cree_le=datetime(2026, 10, 5, 16, 40, tzinfo=timezone.utc) - il_y_a))
    session.refresh(trace)
    return trace


def test_historique(session):
    e = entreprise_confirmee(session)
    wa = conversation_wa(session, e)
    web = trouver_ou_creer_conversation(session, CANAL_WEB, "web-" + uuid.uuid4().hex)
    ajouter_trace(session, e, "assujetti_tva_declare", None, True, timedelta(days=3), conversation_id=web.id)
    ajouter_trace(session, e, "nombre_salaries", 0, 3, timedelta(days=2), conversation_id=wa.id)
    ajouter_trace(session, e, "secteur", "commerce", "services", timedelta(days=1))
    ajouter_trace(session, e, "rappels_whatsapp", True, False, timedelta(hours=1), conversation_id=wa.id, origine=COFFRE)
    ajouter_trace(session, e, "rappels_email", True, False, origine=COFFRE)
    ajouter_trace(session, e, "champ_futur", "a", None, timedelta(days=4))
    lignes = [(c.libelle, c.avant, c.apres, c.origine) for c in donnees.historique(session, e)]
    assert lignes == [
        ("Rappels par email", tx.ACTIFS, tx.ARRETES, tx.ORIGINE_COFFRE),
        (f"Rappels WhatsApp (•••• {wa.identifiant_externe[-4:]})", tx.ACTIFS, tx.ARRETES, tx.ORIGINE_COFFRE),
        ("Secteur", "Commerce", "Services", tx.ORIGINE_INCONNUE),
        ("Nombre de salariés", "0", "3", tx.ORIGINE_WHATSAPP),
        ("Assujetti à la TVA", "Je ne sais pas", "Oui", tx.ORIGINE_CONVERSATION),
        ("champ_futur", "a", mf.A_COMPLETER, tx.ORIGINE_INCONNUE),
    ]
    assert donnees.historique(session, e)[0].quand == "lundi 5 octobre 2026 à 17 h 40"


def test_historique_meme_instant_par_ordre_d_enregistrement(session):
    e = entreprise_confirmee(session)
    ajouter_trace(session, e, "secteur", "commerce", "services")
    ajouter_trace(session, e, "nombre_salaries", 0, 1)
    assert [c.libelle for c in donnees.historique(session, e)] == ["Nombre de salariés", "Secteur"]


def test_historique_limite_a_50(session):
    e = entreprise_confirmee(session)
    for numero in range(donnees.HISTORIQUE_MAX + 2):
        ajouter_trace(session, e, "nombre_salaries", numero, numero + 1, timedelta(minutes=numero))
    changements = donnees.historique(session, e)
    assert donnees.HISTORIQUE_MAX == 50 and len(changements) == 50 and changements[0].apres == "1"


def test_historique_d_une_seule_entreprise(session):
    e, autre = entreprise_confirmee(session), entreprise_confirmee(session, "Ets Voisine")
    ajouter_trace(session, autre, "secteur", "commerce", "services")
    assert donnees.historique(session, e) == []


def test_valeurs_historiques():
    assert donnees.valeur_historique("assujetti_tva_declare", False) == "Non"
    assert donnees.valeur_historique("chiffre_affaires_annuel", 150_000_000) == "150 000 000 FCFA"
    assert donnees.valeur_historique("email", None) == mf.A_COMPLETER
    assert donnees.valeur_historique("rappels_email", True) == tx.ACTIFS
    assert donnees.libelle_du_champ("rappels_email") == "Rappels par email" and donnees.libelle_du_champ("niu") == "NIU"


def test_page_historique(espace, session):
    adresse = adresse_unique()
    e = entreprise_confirmee(session, "Ets Historique", adresse)
    texte = texte_visible(connecter(session, adresse).get("/espace/entreprise").text)
    assert tx.HISTORIQUE in texte and tx.HISTORIQUE_VIDE in texte
    for numero in range(donnees.HISTORIQUE_MAX):
        ajouter_trace(session, e, "nombre_salaries", numero, numero + 1, timedelta(minutes=numero))
    client = connecter(session, adresse)
    html = client.get("/espace/entreprise").text
    texte = texte_visible(html)
    assert tx.HISTORIQUE_LIMITE in texte and tx.HISTORIQUE_VIDE not in texte
    assert html.count('<span class="esp-avant">') == 50
    assert "Nombre de salariés 0 " in texte and "lundi 5 octobre 2026 à 17 h 40 · " + tx.ORIGINE_INCONNUE in texte


def test_page_historique_sous_la_limite(espace, session):
    adresse = adresse_unique()
    e = entreprise_confirmee(session, "Ets Peu", adresse)
    ajouter_trace(session, e, "secteur", "commerce", "services")
    texte = texte_visible(connecter(session, adresse).get("/espace/entreprise").text)
    assert "Secteur Commerce Services" in texte and tx.HISTORIQUE_LIMITE not in texte


# --- Base -----------------------------------------------------------------------------------------

def test_colonnes_du_lot():
    inspecteur = inspect(get_engine())
    entreprise = {c["name"]: c for c in inspecteur.get_columns("entreprises")}["rappels_email"]
    assert entreprise["nullable"] is False and "true" in str(entreprise["default"])
    colonnes = {c["name"]: c for c in inspecteur.get_columns("modifications_entreprise")}
    assert colonnes["origine"]["nullable"] is False and "conversation" in str(colonnes["origine"]["default"])
    assert colonnes["session_espace_id"]["nullable"] is True
    [verif] = [c for c in inspecteur.get_check_constraints("modifications_entreprise")
               if c["name"] == "ck_modifications_entreprise_origine"]
    assert "conversation" in verif["sqltext"] and "coffre" in verif["sqltext"]
    assert ORIGINES == (CONVERSATION, COFFRE) == ("conversation", "coffre")


def test_valeurs_par_defaut_en_base(session):
    e = entreprise_confirmee(session)
    session.execute(text("INSERT INTO modifications_entreprise (entreprise_id, champ) VALUES (:e, 'secteur')"), {"e": e.id})
    assert session.execute(text("SELECT origine FROM modifications_entreprise WHERE entreprise_id = :e"), {"e": e.id}).scalar() == "conversation"
    session.execute(text("INSERT INTO entreprises (id, juridiction_code, niu, raison_sociale) VALUES (:i, 'CM', :n, 'X')"),
                    {"i": uuid.uuid4(), "n": "Z" + uuid.uuid4().hex[:10].upper()})
    assert session.execute(text("SELECT bool_and(rappels_email) FROM entreprises")).scalar() is True


def test_origine_inconnue_refusee(session):
    e = entreprise_confirmee(session)
    session.add(ModificationEntreprise(entreprise_id=e.id, champ="secteur", origine="autre"))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_version():
    assert VERSION == "0.14.0"
