"""Lot 8 — adresse email, confirmation par code, rappels par email, envoi SMTP (Brevo)."""
import os
import re
import subprocess
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from celery.schedules import crontab
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from app.conversation import confirmation, onboarding
from app.conversation import messages_fixes as mf
from app.conversation.models import ABANDONNE, CANAL_WEB, EN_PAUSE, TERMINE, Parcours
from app.conversation.moteur import traiter_message, trouver_ou_creer_conversation
from app.conversation.onboarding import ReponseInvalide, lire_email
from app.core.config import VERSION, Settings, get_settings
from app.core.db import get_engine
from app.emails import envoi, tester
from app.emails.composition import html_depuis_texte
from app.emails.envoi import CODE_EFFACE, envoyer_en_attente
from app.emails.models import A_ENVOYER, ANNULE, CODE, ECHEC, ENVOYE, RAPPEL, Email
from app.entreprises.models import Entreprise, ModificationEntreprise
from app.main import app
from app.rappels import livraison
from app.rappels import models as rappels
from app.rappels.canal import BULLE, EMAIL, choisir_canal
from app.rappels.preparation import preparer_entreprise
from app.regles.chargement import charger_fichier
from app.worker import celery_app, tache_envoyer_emails
from tests.test_lot03_onboarding import Visiteur, jusqu_au_recapitulatif, niu_unique

FICHIER_CM = Path(__file__).resolve().parent.parent / "app/regles/donnees/regles_cm.json"
ADRESSE = "compta@boulangerie.cm"


# --- Outils --------------------------------------------------------------------------------------

def emails_de(session, destinataire=None, type_=None) -> list[Email]:
    requete = select(Email).order_by(Email.id)
    if destinataire:
        requete = requete.where(Email.destinataire == destinataire)
    if type_:
        requete = requete.where(Email.type == type_)
    return list(session.scalars(requete))


def dernier_code(session, destinataire) -> str:
    return re.search(r"\b(\d{6})\b", emails_de(session, destinataire, CODE)[-1].texte).group(1)


def adresse_unique() -> str:
    return f"compta.{uuid.uuid4().hex[:8]}@exemple.cm"


def client_avec_email(session, email=None):
    """Onboarding terminé avec une adresse : la confirmation par code est ouverte."""
    visiteur = Visiteur(session)
    visiteur.email = email or adresse_unique()
    jusqu_au_recapitulatif(visiteur, niu_unique(), email=visiteur.email)
    visiteur.fin_onboarding = visiteur.dit("oui")
    return visiteur


def entreprise_de(visiteur) -> Entreprise:
    return visiteur.session.get(Entreprise, visiteur.conversation.entreprise_id)


def confirmation_de(visiteur) -> Parcours:
    return visiteur.session.scalars(
        select(Parcours)
        .where(Parcours.conversation_id == visiteur.conversation.id, Parcours.type == confirmation.TYPE)
        .order_by(Parcours.cree_le.desc(), Parcours.id)
    ).first()


@pytest.fixture
def smtp_configure(monkeypatch):
    for nom, valeur in {
        "SMTP_HOTE": "smtp.exemple.test", "SMTP_PORT": "2525", "SMTP_UTILISATEUR": "utilisateur-test",
        "SMTP_MOT_DE_PASSE": "cle-de-test", "EMAIL_EXPEDITEUR": "jeff@exemple.cm",
    }.items():
        monkeypatch.setenv(nom, valeur)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class FauxSMTP:
    instances: list["FauxSMTP"] = []
    envoyes: list = []
    panne: Exception | None = None

    def __init__(self, hote, port, timeout):
        self.hote, self.port, self.timeout = hote, port, timeout
        self.tls = False
        self.identifiants = None
        FauxSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *erreur):
        return False

    def starttls(self, context):
        self.tls = True

    def login(self, utilisateur, mot_de_passe):
        self.identifiants = (utilisateur, mot_de_passe)

    def send_message(self, message):
        if FauxSMTP.panne:
            raise FauxSMTP.panne
        FauxSMTP.envoyes.append(message)


@pytest.fixture
def faux_smtp(monkeypatch, smtp_configure):
    FauxSMTP.instances, FauxSMTP.envoyes, FauxSMTP.panne = [], [], None
    monkeypatch.setattr(envoi.smtplib, "SMTP", FauxSMTP)
    return FauxSMTP


# --- Lecture de l'adresse ------------------------------------------------------------------------

@pytest.mark.parametrize(
    "saisie, attendu",
    [
        ("compta@boulangerie.cm", "compta@boulangerie.cm"),
        ("  Compta@Boulangerie.CM ", "compta@boulangerie.cm"),
        ("jean.paul+jeff@mail.example.com", "jean.paul+jeff@mail.example.com"),
        ("a_b-c@sous-domaine.entreprise.cm", "a_b-c@sous-domaine.entreprise.cm"),
        ("plus tard", None),
        ("Je la donnerai plus tard", None),
        ("supprimer", None),
        ("aucune", None),
    ],
)
def test_lire_email(session, saisie, attendu):
    assert lire_email(saisie, session) == attendu


@pytest.mark.parametrize(
    "saisie",
    ["compta", "compta@", "@boulangerie.cm", "compta@boulangerie", "compta@@boulangerie.cm", "compta boulangerie@x.cm",
     "compta..x@boulangerie.cm", "compta@boulangerie.c", "x" * 250 + "@ex.cm", "<script>@x.cm"],
)
def test_lire_email_refuse(session, saisie):
    with pytest.raises(ReponseInvalide) as erreur:
        lire_email(saisie, session)
    assert erreur.value.message == mf.ERR_EMAIL


def test_la_question_email_est_la_derniere():
    assert onboarding.ETAPES[-1].cle == "email"
    assert onboarding.ETAPES[-1].question == mf.Q_EMAIL
    assert onboarding.ETAPES[-1].choix == list(mf.CHOIX_EMAIL)


def test_email_invalide_puis_corrige(session):
    visiteur = Visiteur(session)
    for texte, _ in onboarding_jusqu_a_l_email(niu_unique()):
        visiteur.dit(texte)
    erreur = visiteur.dit("pas-une-adresse")
    assert erreur.texte == mf.ERR_EMAIL
    assert erreur.choix == list(mf.CHOIX_EMAIL)
    assert visiteur.dit(ADRESSE).texte.startswith(mf.RECAP_INTRO)


def onboarding_jusqu_a_l_email(niu):
    return [(t, None) for t in ["1", "oui", "Garage Fotso", niu, "1", "1", "20 millions", "CDI Douala", "3", "1", "0"]]


# --- Onboarding avec adresse et confirmation -------------------------------------------------------

def test_onboarding_avec_email_envoie_un_code(session):
    visiteur = client_avec_email(session, "Compta@Boulangerie-Centre.cm")
    fin = visiteur.fin_onboarding
    assert fin.texte == (
        mf.BIENVENUE.format(raison_sociale="Boulangerie du Centre SARL") + "\n\n"
        + mf.CODE_ENVOYE.format(email="compta@boulangerie-centre.cm")
    )
    assert fin.choix == list(mf.CHOIX_CODE)
    entreprise = entreprise_de(visiteur)
    assert entreprise.email == "compta@boulangerie-centre.cm"
    assert entreprise.email_confirme_le is None
    [email] = emails_de(session, "compta@boulangerie-centre.cm")
    assert email.type == CODE
    assert email.statut == A_ENVOYER
    assert email.entreprise_id == entreprise.id
    assert email.objet == mf.EMAIL_CODE_OBJET
    assert email.texte == mf.EMAIL_CODE_TEXTE.format(code=dernier_code(session, entreprise.email)) + "\n\n" + mf.EMAIL_SIGNATURE
    parcours = confirmation_de(visiteur)
    assert parcours.statut == "en_cours"
    # Seule l'empreinte du code est gardée.
    assert dernier_code(session, entreprise.email) not in str(parcours.donnees)


def test_recapitulatif_avec_email(session):
    visiteur = Visiteur(session)
    recap = jusqu_au_recapitulatif(visiteur, niu_unique(), email=ADRESSE)
    assert f"• Adresse email : {ADRESSE}" in recap.texte


def test_recapitulatif_sans_email(session):
    visiteur = Visiteur(session)
    recap = jusqu_au_recapitulatif(visiteur, niu_unique())
    assert "• Adresse email : À compléter" in recap.texte
    fin = visiteur.dit("oui")
    assert fin.texte == mf.BIENVENUE.format(raison_sociale="Boulangerie du Centre SARL")
    assert fin.choix == list(mf.MENU)
    assert session.scalars(select(Email).where(Email.entreprise_id == entreprise_de(visiteur).id)).all() == []
    assert confirmation_de(visiteur) is None


@pytest.mark.parametrize("saisie", ["{code}", "{espace}", " {code} "])
def test_confirmer_avec_le_bon_code(session, saisie):
    visiteur = client_avec_email(session)
    code = dernier_code(session, visiteur.email)
    reponse = visiteur.dit(saisie.format(code=code, espace=code[:3] + " " + code[3:]))
    assert reponse.texte == mf.EMAIL_CONFIRME.format(email=visiteur.email)
    assert reponse.choix == list(mf.MENU)
    assert entreprise_de(visiteur).email_confirme_le is not None
    assert confirmation_de(visiteur).statut == TERMINE


@pytest.mark.parametrize("saisie", ["12345", "1234567", "abcdef", "2", "oui"])
def test_code_mal_forme(session, saisie):
    visiteur = client_avec_email(session)
    reponse = visiteur.dit(saisie)
    assert reponse.texte == mf.CODE_FORMAT
    assert reponse.choix == list(mf.CHOIX_CODE)
    assert confirmation_de(visiteur).donnees["essais"] == 0


def test_mauvais_code_puis_trop_d_essais(session):
    visiteur = client_avec_email(session)
    faux = "000000" if dernier_code(session, visiteur.email) != "000000" else "111111"
    for _ in range(confirmation.ESSAIS_MAX - 1):
        assert visiteur.dit(faux).texte == mf.CODE_FAUX
    fin = visiteur.dit(faux)
    assert fin.texte == mf.CODE_TROP_D_ESSAIS
    assert fin.choix == list(mf.MENU)
    assert confirmation_de(visiteur).statut == ABANDONNE
    assert entreprise_de(visiteur).email_confirme_le is None
    # Le bon code ne sert plus à rien une fois le parcours clos.
    assert visiteur.dit(dernier_code(session, visiteur.email)).texte == mf.INCOMPRIS


def test_code_expire_puis_renvoye(session, monkeypatch):
    visiteur = client_avec_email(session)
    ancien = dernier_code(session, visiteur.email)
    plus_tard = datetime.now(timezone.utc) + timedelta(minutes=16)
    monkeypatch.setattr(confirmation, "maintenant", lambda: plus_tard)
    assert visiteur.dit(ancien).texte == mf.CODE_EXPIRE
    renvoi = visiteur.dit("renvoyer")
    assert renvoi.texte == mf.CODE_RENVOYE.format(email=visiteur.email)
    assert renvoi.choix == list(mf.CHOIX_CODE)
    assert len(emails_de(session, visiteur.email, CODE)) == 2
    nouveau = dernier_code(session, visiteur.email)
    if nouveau != ancien:
        assert visiteur.dit(ancien).texte == mf.CODE_FAUX
    assert visiteur.dit(nouveau).texte == mf.EMAIL_CONFIRME.format(email=visiteur.email)


def test_code_valable_quinze_minutes(session, monkeypatch):
    visiteur = client_avec_email(session)
    presque = datetime.now(timezone.utc) + timedelta(minutes=14)
    monkeypatch.setattr(confirmation, "maintenant", lambda: presque)
    assert visiteur.dit(dernier_code(session, visiteur.email)).texte == mf.EMAIL_CONFIRME.format(email=visiteur.email)


def test_renvois_limites(session):
    visiteur = client_avec_email(session)
    for _ in range(confirmation.RENVOIS_MAX):
        assert visiteur.dit("Renvoyer").texte == mf.CODE_RENVOYE.format(email=visiteur.email)
    assert visiteur.dit("renvoyer").texte == mf.CODE_TROP_DE_RENVOIS
    assert len(emails_de(session, visiteur.email, CODE)) == 1 + confirmation.RENVOIS_MAX
    # Le dernier code reçu reste valable.
    assert visiteur.dit(dernier_code(session, visiteur.email)).texte == mf.EMAIL_CONFIRME.format(email=visiteur.email)


def test_un_renvoi_remet_les_essais_a_zero(session):
    visiteur = client_avec_email(session)
    faux = "000000" if dernier_code(session, visiteur.email) != "000000" else "111111"
    for _ in range(confirmation.ESSAIS_MAX - 1):
        visiteur.dit(faux)
    visiteur.dit("renvoyer")
    assert confirmation_de(visiteur).donnees["essais"] == 0


def test_pause_et_reprise_de_la_confirmation(session):
    charger_fichier(session, FICHIER_CM)
    visiteur = client_avec_email(session)
    assert visiteur.dit("menu").texte == mf.PAUSE
    assert confirmation_de(visiteur).statut == EN_PAUSE
    assert visiteur.dit("2").texte.startswith(mf.OBLIGATIONS_INTRO.format(raison_sociale="Boulangerie du Centre SARL"))
    reprise = visiteur.dit("confirmer")
    assert reprise.texte == mf.CODE_ATTENDU.format(email=visiteur.email)
    assert reprise.choix == list(mf.CHOIX_CODE)
    visiteur.dit("menu")
    assert visiteur.dit("reprendre").texte == mf.CODE_ATTENDU.format(email=visiteur.email)
    assert visiteur.dit(dernier_code(session, visiteur.email)).texte == mf.EMAIL_CONFIRME.format(email=visiteur.email)


def test_annuler_la_confirmation(session):
    visiteur = client_avec_email(session)
    reponse = visiteur.dit("annuler")
    assert reponse.texte == mf.CONFIRMATION_ANNULEE
    assert reponse.choix == list(mf.MENU)
    assert confirmation_de(visiteur).statut == ABANDONNE
    assert entreprise_de(visiteur).email_confirme_le is None


def test_adresse_changee_pendant_la_confirmation(session):
    visiteur = client_avec_email(session)
    code = dernier_code(session, visiteur.email)
    entreprise_de(visiteur).email = "autre@exemple.cm"
    session.flush()
    reponse = visiteur.dit(code)
    assert reponse.texte == mf.CONFIRMATION_ANNULEE
    assert entreprise_de(visiteur).email_confirme_le is None
    assert confirmation_de(visiteur).statut == ABANDONNE


def test_un_code_ne_vaut_que_pour_son_parcours(session):
    alice, bruno = client_avec_email(session), client_avec_email(session)
    code_alice = dernier_code(session, alice.email)
    if code_alice != dernier_code(session, bruno.email):
        assert bruno.dit(code_alice).texte == mf.CODE_FAUX
    assert entreprise_de(bruno).email_confirme_le is None


# --- « Mon entreprise » et « confirmer » ---------------------------------------------------------

def test_profil_avec_email_a_confirmer(session):
    visiteur = client_avec_email(session)
    visiteur.dit("annuler")
    profil = visiteur.dit("5")
    assert f"• Adresse email : {visiteur.email} ({mf.EMAIL_A_CONFIRMER})" in profil.texte
    assert profil.choix == [mf.CHOIX_PROFIL[0], mf.CHOIX_CONFIRMER, mf.CHOIX_PROFIL[1]]
    relance = visiteur.dit("Confirmer mon email")
    assert relance.texte == mf.CODE_ENVOYE.format(email=visiteur.email)
    assert len(emails_de(session, visiteur.email, CODE)) == 2
    visiteur.dit(dernier_code(session, visiteur.email))
    profil = visiteur.dit("5")
    assert f"• Adresse email : {visiteur.email}\n" in profil.texte
    assert profil.choix == list(mf.CHOIX_PROFIL)


def test_confirmer_sans_objet(session):
    visiteur = client_avec_email(session)
    visiteur.dit(dernier_code(session, visiteur.email))
    assert visiteur.dit("confirmer").texte == mf.INCOMPRIS  # déjà confirmée
    sans = Visiteur(session)
    jusqu_au_recapitulatif(sans, niu_unique())
    sans.dit("oui")
    assert sans.dit("confirmer").texte == mf.INCOMPRIS  # pas d'adresse
    assert traiter_message(session, CANAL_WEB, "x-" + uuid.uuid4().hex, "confirmer").texte == mf.INCOMPRIS


def test_ajouter_une_adresse_depuis_mon_entreprise(session):
    visiteur = Visiteur(session)
    jusqu_au_recapitulatif(visiteur, niu_unique())
    visiteur.dit("oui")
    visiteur.dit("modifier")
    assert visiteur.dit("10").texte == mf.Q_EMAIL
    recap = visiteur.dit(ADRESSE)
    assert f"• Adresse email : {ADRESSE}" in recap.texte
    fin = visiteur.dit("oui")
    assert fin.texte == mf.PROFIL_A_JOUR + "\n\n" + mf.CODE_ENVOYE.format(email=ADRESSE)
    assert fin.choix == list(mf.CHOIX_CODE)
    trace = session.scalars(select(ModificationEntreprise).where(
        ModificationEntreprise.entreprise_id == entreprise_de(visiteur).id
    )).one()
    assert (trace.champ, trace.ancienne_valeur, trace.nouvelle_valeur) == ("email", None, ADRESSE)
    assert visiteur.dit(dernier_code(session, ADRESSE)).texte == mf.EMAIL_CONFIRME.format(email=ADRESSE)


def test_changer_d_adresse_annule_la_confirmation(session):
    visiteur = client_avec_email(session)
    visiteur.dit(dernier_code(session, visiteur.email))
    assert entreprise_de(visiteur).email_confirme_le is not None
    nouvelle = adresse_unique()
    visiteur.dit("modifier")
    visiteur.dit("10")
    visiteur.dit(nouvelle)
    fin = visiteur.dit("oui")
    assert fin.texte.endswith(mf.CODE_ENVOYE.format(email=nouvelle))
    assert entreprise_de(visiteur).email == nouvelle
    assert entreprise_de(visiteur).email_confirme_le is None


def test_supprimer_son_adresse(session):
    visiteur = client_avec_email(session)
    visiteur.dit(dernier_code(session, visiteur.email))
    visiteur.dit("modifier")
    visiteur.dit("10")
    recap = visiteur.dit("supprimer")
    assert "• Adresse email : À compléter" in recap.texte
    fin = visiteur.dit("oui")
    assert fin.texte == mf.PROFIL_A_JOUR
    assert fin.choix == list(mf.MENU)
    entreprise = entreprise_de(visiteur)
    assert entreprise.email is None
    assert entreprise.email_confirme_le is None
    assert choisir_canal(entreprise) == BULLE


def test_modifier_autre_chose_garde_la_confirmation(session):
    visiteur = client_avec_email(session)
    visiteur.dit(dernier_code(session, visiteur.email))
    visiteur.dit("modifier")
    visiteur.dit("4")
    visiteur.dit("90 millions")
    assert visiteur.dit("oui").texte == mf.PROFIL_A_JOUR
    assert entreprise_de(visiteur).email_confirme_le is not None


# --- Routeur et rappels par email ---------------------------------------------------------------

def entreprise_tva(session, email=None, confirmee=False) -> Entreprise:
    e = Entreprise(
        juridiction_code="CM", niu=niu_unique(), raison_sociale="Ets Courriel", regime_declare="reel",
        assujetti_tva_declare=True, nombre_salaries=0, email=email,
        email_confirme_le=datetime.now(timezone.utc) if confirmee else None,
    )
    session.add(e)
    session.flush()
    return e


def test_choisir_canal(session):
    assert choisir_canal(entreprise_tva(session)) == BULLE
    assert choisir_canal(entreprise_tva(session, ADRESSE)) == BULLE
    assert choisir_canal(entreprise_tva(session, ADRESSE, confirmee=True)) == EMAIL


def test_rappel_par_email(session):
    charger_fichier(session, FICHIER_CM)
    adresse = adresse_unique()
    e = entreprise_tva(session, adresse, confirmee=True)
    [rappel] = preparer_entreprise(session, e, date(2026, 10, 8))
    assert rappel.canal == EMAIL
    assert rappel.statut == rappels.A_ENVOYER
    [email] = emails_de(session, adresse)
    assert email.type == RAPPEL
    assert email.rappel_id == rappel.id
    assert email.entreprise_id == e.id
    assert email.objet == "Rappel Jeff : Déclaration et paiement mensuels de la TVA, au plus tard le jeudi 15 octobre 2026"
    assert email.texte == "\n\n".join([
        "Bonjour,\n\nVoici un rappel pour « Ets Courriel » :",
        "Rappel : « Déclaration et paiement mensuels de la TVA » — septembre 2026.\n"
        "Au plus tard le jeudi 15 octobre 2026 (dans 7 jours).\n" + mf.OBLIGATIONS_AVERTISSEMENT,
        mf.EMAIL_SIGNATURE,
        mf.EMAIL_DESABONNEMENT,
    ])
    assert "Ets Courriel" in email.html


def test_rappel_email_non_affiche_dans_la_bulle(session, monkeypatch):
    charger_fichier(session, FICHIER_CM)
    e = entreprise_tva(session, adresse_unique(), confirmee=True)
    identifiant = "courriel-" + uuid.uuid4().hex
    trouver_ou_creer_conversation(session, CANAL_WEB, identifiant).entreprise_id = e.id
    preparer_entreprise(session, e, date(2026, 10, 8))
    monkeypatch.setattr(livraison, "aujourd_hui", lambda fuseau: date(2026, 10, 8))
    assert traiter_message(session, CANAL_WEB, identifiant, "bonjour").rappels == []


def test_adresse_non_confirmee_rappel_dans_la_bulle(session):
    charger_fichier(session, FICHIER_CM)
    e = entreprise_tva(session, adresse_unique())
    [rappel] = preparer_entreprise(session, e, date(2026, 10, 8))
    assert rappel.canal == BULLE
    assert emails_de(session, e.email) == []


def test_j_moins_2_annule_l_email_j_moins_7_non_parti(session):
    charger_fichier(session, FICHIER_CM)
    adresse = adresse_unique()
    e = entreprise_tva(session, adresse, confirmee=True)
    preparer_entreprise(session, e, date(2026, 10, 8))
    preparer_entreprise(session, e, date(2026, 10, 13))
    assert [(m.statut, session.get(rappels.Rappel, m.rappel_id).palier) for m in emails_de(session, adresse)] == [
        (ANNULE, 7), (A_ENVOYER, 2),
    ]


def test_un_email_deja_parti_n_est_pas_annule(session):
    charger_fichier(session, FICHIER_CM)
    adresse = adresse_unique()
    e = entreprise_tva(session, adresse, confirmee=True)
    preparer_entreprise(session, e, date(2026, 10, 8))
    emails_de(session, adresse)[0].statut = ENVOYE
    session.flush()
    preparer_entreprise(session, e, date(2026, 10, 13))
    assert [m.statut for m in emails_de(session, adresse)] == [ENVOYE, A_ENVOYER]


# --- Envoi SMTP ---------------------------------------------------------------------------------

def test_reglages_email(monkeypatch):
    complets = dict(smtp_hote="smtp-relay.brevo.com", smtp_utilisateur="u", smtp_mot_de_passe="m",
                    email_expediteur="jeff@exemple.cm")
    assert Settings(**complets).email_configure is True
    assert Settings(**{**complets, "smtp_mot_de_passe": "A_REMPLACER"}).email_configure is False
    assert Settings(**{**complets, "email_expediteur": "jeff@VOTRE_DOMAINE"}).email_configure is False
    assert Settings(**{**complets, "smtp_hote": ""}).email_configure is False
    assert Settings(**{**complets, "smtp_utilisateur": ""}).email_configure is False
    assert Settings(**complets).smtp_port == 587


def test_fichier_env_exemple_sans_secret():
    contenu = (Path(__file__).resolve().parent.parent / ".env.example").read_text()
    assert "SMTP_MOT_DE_PASSE=A_REMPLACER" in contenu
    assert "SMTP_UTILISATEUR=A_REMPLACER" in contenu
    assert "SMTP_HOTE=smtp-relay.brevo.com" in contenu
    assert "EMAIL_EXPEDITEUR=jeff@VOTRE_DOMAINE" in contenu


def test_envoi_desactive_sans_reglages(session, monkeypatch):
    for nom in ("SMTP_HOTE", "SMTP_UTILISATEUR", "SMTP_MOT_DE_PASSE", "EMAIL_EXPEDITEUR"):
        monkeypatch.delenv(nom, raising=False)
    get_settings.cache_clear()
    try:
        visiteur = client_avec_email(session)
        bilan = envoyer_en_attente(session)
        assert bilan.desactive is True
        assert bilan.envoyes == 0
        assert emails_de(session, visiteur.email)[0].statut == A_ENVOYER
    finally:
        get_settings.cache_clear()


def test_envoi_d_un_code(session, faux_smtp):
    visiteur = client_avec_email(session)
    code = dernier_code(session, visiteur.email)
    bilan = envoyer_en_attente(session)
    assert bilan.envoyes >= 1 and bilan.echecs == 0
    [message] = [m for m in faux_smtp.envoyes if m["To"] == visiteur.email]
    assert message["From"] == "Jeff <jeff@exemple.cm>"
    assert message["Subject"] == mf.EMAIL_CODE_OBJET
    assert message["Message-ID"].endswith("@exemple.cm>")
    assert message["Date"]
    assert code in message.get_body(("plain",)).get_content()
    assert code in message.get_body(("html",)).get_content()
    smtp = faux_smtp.instances[0]
    assert (smtp.hote, smtp.port, smtp.timeout) == ("smtp.exemple.test", 2525, 30)
    assert smtp.tls is True
    assert smtp.identifiants == ("utilisateur-test", "cle-de-test")
    [email] = emails_de(session, visiteur.email)
    assert email.statut == ENVOYE
    assert email.envoye_le is not None
    # Le code ne reste pas en base une fois envoyé.
    assert email.texte == email.html == CODE_EFFACE
    # L'empreinte suffit toujours à confirmer.
    assert visiteur.dit(code).texte == mf.EMAIL_CONFIRME.format(email=visiteur.email)


def test_envoi_d_un_rappel(session, faux_smtp):
    charger_fichier(session, FICHIER_CM)
    adresse = adresse_unique()
    e = entreprise_tva(session, adresse, confirmee=True)
    [rappel] = preparer_entreprise(session, e, date(2026, 10, 8))
    envoyer_en_attente(session)
    [email] = emails_de(session, adresse)
    assert email.statut == ENVOYE
    assert email.texte.startswith("Bonjour,")  # le texte d'un rappel est gardé
    session.refresh(rappel)
    assert rappel.statut == rappels.ENVOYE
    assert rappel.envoye_le is not None
    assert envoyer_en_attente(session).envoyes == 0  # rien n'est envoyé deux fois


def test_echecs_puis_retour_dans_la_bulle(session, faux_smtp, monkeypatch):
    charger_fichier(session, FICHIER_CM)
    adresse = adresse_unique()
    e = entreprise_tva(session, adresse, confirmee=True)
    identifiant = "echec-" + uuid.uuid4().hex
    trouver_ou_creer_conversation(session, CANAL_WEB, identifiant).entreprise_id = e.id
    [rappel] = preparer_entreprise(session, e, date(2026, 10, 8))
    faux_smtp.panne = ConnectionRefusedError("serveur injoignable")
    for essai in range(1, envoi.ESSAIS_MAX + 1):
        bilan = envoyer_en_attente(session)
        assert bilan.echecs >= 1
        [email] = emails_de(session, adresse)
        assert email.essais == essai
        assert email.erreur == "ConnectionRefusedError: serveur injoignable"
        assert email.statut == (ECHEC if essai == envoi.ESSAIS_MAX else A_ENVOYER)
    session.refresh(rappel)
    assert (rappel.canal, rappel.statut) == (BULLE, rappels.A_ENVOYER)
    monkeypatch.setattr(livraison, "aujourd_hui", lambda fuseau: date(2026, 10, 8))
    assert len(traiter_message(session, CANAL_WEB, identifiant, "bonjour").rappels) == 1


def test_un_echec_puis_reussite(session, faux_smtp):
    visiteur = client_avec_email(session)
    faux_smtp.panne = TimeoutError("délai dépassé")
    envoyer_en_attente(session)
    faux_smtp.panne = None
    envoyer_en_attente(session)
    [email] = emails_de(session, visiteur.email)
    assert (email.statut, email.essais, email.erreur) == (ENVOYE, 1, None)


def test_erreur_tronquee(session, faux_smtp):
    visiteur = client_avec_email(session)
    faux_smtp.panne = RuntimeError("x" * 1000)
    envoyer_en_attente(session)
    assert len(emails_de(session, visiteur.email)[0].erreur) == 500


def test_html_echappe():
    html = html_depuis_texte("Bonjour <script>alert(1)</script> & co\nligne 2\n\nParagraphe 2")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "&amp; co<br>ligne 2</p>" in html
    assert html.count("<p ") == 2
    assert "#4680ff" in html


def test_objet_tronque(session):
    from app.emails.composition import deposer

    email = deposer(session, "test", ADRESSE, "o" * 300, "texte")
    assert len(email.objet) == 200


# --- Commande de test et tâches -----------------------------------------------------------------

def test_commande_tester_usage(capsys):
    assert tester.main([]) == 1
    assert tester.main(["pas-une-adresse"]) == 1
    assert "Usage" in capsys.readouterr().out


def test_commande_tester_sans_reglages(monkeypatch, capsys):
    for nom in ("SMTP_HOTE", "SMTP_UTILISATEUR", "SMTP_MOT_DE_PASSE", "EMAIL_EXPEDITEUR"):
        monkeypatch.delenv(nom, raising=False)
    get_settings.cache_clear()
    try:
        assert tester.main([ADRESSE]) == 1
        sortie = capsys.readouterr().out
        assert "SMTP_MOT_DE_PASSE" in sortie and "désactivé" in sortie
    finally:
        get_settings.cache_clear()


def test_commande_tester_envoie(faux_smtp, capsys):
    assert tester.main([ADRESSE]) == 0
    [message] = faux_smtp.envoyes
    assert message["To"] == ADRESSE
    assert message["Subject"] == mf.EMAIL_TEST_OBJET
    sortie = capsys.readouterr().out
    assert "Email de test envoyé" in sortie
    assert "cle-de-test" not in sortie


def test_commande_tester_echec(faux_smtp, capsys):
    faux_smtp.panne = OSError("refusé")
    assert tester.main([ADRESSE]) == 1
    sortie = capsys.readouterr().out
    assert "Échec de l'envoi : OSError: refusé" in sortie
    assert "cle-de-test" not in sortie


def test_tache_d_envoi_chaque_minute():
    entree = celery_app.conf.beat_schedule["envoyer-emails"]
    assert entree["task"] == "jeff.envoyer_emails"
    assert entree["schedule"] == crontab()
    assert "jeff.envoyer_emails" in celery_app.tasks
    assert celery_app.conf.beat_schedule["preparer-rappels"]["schedule"] == crontab(hour=7, minute=30)


class SessionFactice:
    def __init__(self):
        self.actions = []

    def rollback(self):
        self.actions.append("rollback")

    def close(self):
        self.actions.append("close")


def test_la_tache_d_envoi(monkeypatch):
    factice = SessionFactice()
    monkeypatch.setattr("app.core.db.get_session", lambda: factice)
    monkeypatch.setattr(envoi, "envoyer_en_attente", lambda s: envoi.Bilan(envoyes=2, echecs=1))
    assert tache_envoyer_emails() == {"envoyes": 2, "echecs": 1, "desactive": False}
    assert factice.actions == ["close"]

    def panne(s):
        raise RuntimeError("panne")
    monkeypatch.setattr(envoi, "envoyer_en_attente", panne)
    with pytest.raises(RuntimeError):
        tache_envoyer_emails()
    assert factice.actions == ["close", "rollback", "close"]


def test_la_tache_d_envoi_connait_toutes_les_tables():
    code = (
        "import app.worker as w, app.emails.envoi as e, app.core.db as db\n"
        "from app.core.db import Base\n"
        "class S:\n    def rollback(self): pass\n    def close(self): pass\n"
        "def verifier(session):\n"
        "    [fk.column for t in Base.metadata.tables.values() for fk in t.foreign_keys]\n"
        "    return e.Bilan()\n"
        "e.envoyer_en_attente = verifier\ndb.get_session = lambda: S()\nw.tache_envoyer_emails()\n"
    )
    racine = Path(__file__).resolve().parent.parent
    resultat = subprocess.run([sys.executable, "-c", code], cwd=racine, env=os.environ.copy(), capture_output=True, text=True)
    assert resultat.returncode == 0, resultat.stderr


# --- Base de données, bulle, version --------------------------------------------------------------

def test_tables_et_colonnes():
    inspecteur = inspect(get_engine())
    entreprises = {c["name"]: c for c in inspecteur.get_columns("entreprises")}
    assert entreprises["email"]["nullable"] is True
    assert entreprises["email_confirme_le"]["nullable"] is True
    colonnes = {c["name"]: c for c in inspecteur.get_columns("emails")}
    assert set(colonnes) == {
        "id", "type", "entreprise_id", "rappel_id", "destinataire", "objet", "texte", "html", "statut", "essais",
        "erreur", "cree_le", "envoye_le",
    }
    for obligatoire in ("type", "destinataire", "objet", "texte", "html", "statut", "essais"):
        assert colonnes[obligatoire]["nullable"] is False
    assert {fk["referred_table"] for fk in inspecteur.get_foreign_keys("emails")} == {"entreprises", "rappels"}
    assert {i["name"] for i in inspecteur.get_indexes("emails")} >= {"ix_emails_statut", "ix_emails_entreprise_id"}


def test_onboarding_avec_email_dans_la_bulle(monkeypatch):
    monkeypatch.setenv("ESSAI_ACTIF", "true")
    get_settings.cache_clear()
    try:
        client = TestClient(app)
        client.get("/essai")
        adresse = adresse_unique()
        for texte in ["1", "oui", "Ets Courriel Web", niu_unique(), "1", "1", "20 millions", "CDI Douala", "1", "2", "0"]:
            client.post("/essai/messages", json={"texte": texte})
        assert client.post("/essai/messages", json={"texte": adresse}).json()["reponse"].startswith(mf.RECAP_INTRO)
        fin = client.post("/essai/messages", json={"texte": "oui"}).json()
        assert fin["reponse"].endswith(mf.CODE_ENVOYE.format(email=adresse))
        assert fin["choix"] == [{"valeur": "renvoyer", "libelle": "Renvoyer le code"}]
    finally:
        get_settings.cache_clear()


def test_version():
    assert VERSION == "0.8.0"


# --- Limites décidées et cas de concurrence ------------------------------------------------------

def test_limites_decidees():
    assert confirmation.DUREE == timedelta(minutes=15)
    assert confirmation.ESSAIS_MAX == 5
    assert confirmation.RENVOIS_MAX == 3
    assert envoi.ESSAIS_MAX == 3


def test_l_empreinte_depend_du_parcours():
    premier, second = Parcours(id=uuid.uuid4()), Parcours(id=uuid.uuid4())
    assert confirmation.empreinte(premier, "123456") != confirmation.empreinte(second, "123456")
    assert confirmation.empreinte(premier, "123456") == confirmation.empreinte(premier, "123456")
    assert "123456" not in confirmation.empreinte(premier, "123456")


def test_un_email_annule_pendant_l_envoi_n_est_pas_envoye(session, faux_smtp, monkeypatch):
    from app.emails.composition import deposer

    premier = deposer(session, "test", adresse_unique(), "Premier", "texte")
    second = deposer(session, "test", adresse_unique(), "Second", "texte")
    envoi_reel = envoi.envoyer_smtp

    def envoyer_puis_annuler(destinataire, objet, texte, html):
        envoi_reel(destinataire, objet, texte, html)
        if objet == "Premier":
            # Pendant l'envoi du premier, le second est annulé ailleurs (rappel remplacé).
            session.execute(Email.__table__.update().where(Email.id == second.id).values(statut=ANNULE))

    monkeypatch.setattr(envoi, "envoyer_smtp", envoyer_puis_annuler)
    envoyer_en_attente(session)
    assert [m["Subject"] for m in faux_smtp.envoyes if m["Subject"] in ("Premier", "Second")] == ["Premier"]
    session.refresh(second)
    assert second.statut == ANNULE
