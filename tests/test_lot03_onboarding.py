"""Lot 3 — lecture des montants, parcours d'onboarding, enregistrement de l'entreprise."""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.conversation import messages_fixes as mf
from app.conversation import onboarding
from app.conversation.models import (
    ABANDONNE,
    CANAL_WEB,
    EN_COURS,
    EN_PAUSE,
    TERMINE,
    Conversation,
    Parcours,
)
from app.conversation.montants import (
    LectureImpossible,
    formater_montant,
    lire_montant,
    lire_nombre_entier,
)
from app.conversation.moteur import traiter_message, trouver_ou_creer_conversation
from app.core.config import get_settings
from app.entreprises.models import Entreprise
from app.main import app
from app.referentiel.models import Juridiction


# --- Montants ----------------------------------------------------------------------------

@pytest.mark.parametrize(
    "saisie, attendu",
    [
        ("150000000", 150_000_000),
        ("150 000 000", 150_000_000),
        ("150 000 000", 150_000_000),
        ("150 000 000", 150_000_000),
        ("150.000.000", 150_000_000),
        ("150,000,000", 150_000_000),
        ("150 millions", 150_000_000),
        ("150 Millions", 150_000_000),
        ("150M", 150_000_000),
        ("150 m", 150_000_000),
        ("1 million", 1_000_000),
        ("1,5 milliard", 1_500_000_000),
        ("1.5 milliards", 1_500_000_000),
        ("2 Mds", 2_000_000_000),
        ("500 mille", 500_000),
        ("500k", 500_000),
        ("150 000 000 FCFA", 150_000_000),
        ("150 000 000 F CFA", 150_000_000),
        ("150 millions de francs", 150_000_000),
        ("12 500 000 xaf", 12_500_000),
        ("0", 0),
        ("1,25 million", 1_250_000),
    ],
)
def test_lire_montant(saisie, attendu):
    assert lire_montant(saisie) == attendu


@pytest.mark.parametrize(
    "saisie",
    [
        None, "", "   ", "abc", "cent millions", "beaucoup", "150,5", "1.5", "-5",
        "1,2345678 million", "150 lapins", "12.34.567", "1.000,000",
        "20 000 milliards", "99999999999999",
    ],
)
def test_lire_montant_refuse(saisie):
    with pytest.raises(LectureImpossible):
        lire_montant(saisie)


def test_montant_maximum_accepte():
    assert lire_montant("10 000 milliards") == 10**13


def test_formater_montant():
    assert formater_montant(150_000_000) == "150\u00a0000\u00a0000\u00a0FCFA"
    assert formater_montant(0) == "0\u00a0FCFA"


@pytest.mark.parametrize(
    "saisie, attendu",
    [("3", 3), (" 12 ", 12), ("1 200", 1200), ("aucun", 0), ("Aucun salarié", 0), ("0", 0), ("100000", 100000)],
)
def test_lire_nombre_entier(saisie, attendu):
    assert lire_nombre_entier(saisie, 100_000) == attendu


@pytest.mark.parametrize("saisie", [None, "trois", "3,5", "-1", "100001", ""])
def test_lire_nombre_entier_refuse(saisie):
    with pytest.raises(LectureImpossible):
        lire_nombre_entier(saisie, 100_000)


# --- Outils de conversation ----------------------------------------------------------------

class Visiteur:
    """Simule un client dans la bulle : chaque test a son propre identifiant."""

    def __init__(self, session):
        self.session = session
        self.identifiant = "test-" + uuid.uuid4().hex

    def dit(self, texte):
        return traiter_message(self.session, CANAL_WEB, self.identifiant, texte)

    @property
    def conversation(self) -> Conversation:
        return trouver_ou_creer_conversation(self.session, CANAL_WEB, self.identifiant)

    @property
    def parcours(self) -> Parcours | None:
        """Le parcours actif s'il existe, sinon le dernier parcours clos."""
        actif = onboarding.parcours_actif(self.session, self.conversation)
        if actif is not None:
            return actif
        return self.session.scalars(
            select(Parcours).where(Parcours.conversation_id == self.conversation.id)
        ).first()


def niu_unique():
    return "M" + uuid.uuid4().hex[:12].upper()


REPONSES_TYPE = [
    ("1", mf.PROPOSITION_ONBOARDING),
    ("oui", mf.Q_RAISON_SOCIALE),
    ("Boulangerie du Centre SARL", mf.Q_NIU),
    (None, mf.Q_FORME_JURIDIQUE),  # NIU rempli par le test
    ("2", mf.Q_SECTEUR),
    ("Services", mf.Q_CHIFFRE_AFFAIRES),
    ("150 millions", mf.Q_CENTRE_IMPOTS),
    ("CDI de Yaoundé 1", mf.Q_REGIME),
    ("3", mf.Q_TVA),
    ("oui", mf.Q_SALARIES),
    ("3", mf.Q_CNPS),
]


def jusqu_au_recapitulatif(visiteur, niu, salaries="3", cnps="123-456-789", email="plus tard"):
    for texte, attendu in REPONSES_TYPE[:-1]:
        reponse = visiteur.dit(niu if texte is None else texte)
        assert reponse.texte == attendu
    reponse = visiteur.dit(salaries)
    if reponse.texte == mf.Q_CNPS:
        reponse = visiteur.dit(cnps)
    assert reponse.texte == mf.Q_EMAIL  # Lot 8 : dernière question.
    reponse = visiteur.dit(email)
    assert reponse.texte.startswith(mf.RECAP_INTRO)
    return reponse


# --- Parcours complet ----------------------------------------------------------------------

def test_onboarding_complet(session):
    visiteur = Visiteur(session)
    niu = niu_unique()
    assert visiteur.dit("Bonjour").texte == mf.ACCUEIL
    recap = jusqu_au_recapitulatif(visiteur, niu.lower())
    assert "• Raison sociale : Boulangerie du Centre SARL" in recap.texte
    assert f"• NIU : {niu}" in recap.texte
    assert "• Forme juridique : SARL" in recap.texte
    assert "• Secteur : Services" in recap.texte
    assert "• Chiffre d'affaires annuel : 150\u00a0000\u00a0000\u00a0FCFA" in recap.texte
    assert "• Régime d'imposition : Régime du réel" in recap.texte
    assert "• Assujetti à la TVA : Oui" in recap.texte
    assert "• N° employeur CNPS : 123456789" in recap.texte
    assert recap.choix == list(mf.CHOIX_RECAP)

    fin = visiteur.dit("oui")
    assert fin.texte == mf.BIENVENUE.format(raison_sociale="Boulangerie du Centre SARL")
    assert fin.choix == list(mf.MENU)

    entreprise = session.get(Entreprise, visiteur.conversation.entreprise_id)
    assert entreprise.juridiction_code == get_settings().juridiction == "CM"
    assert entreprise.niu == niu
    assert entreprise.forme_juridique == "sarl"
    assert entreprise.secteur == "services"
    assert entreprise.chiffre_affaires_annuel == 150_000_000
    assert entreprise.centre_impots == "CDI de Yaoundé 1"
    assert entreprise.regime_declare == "reel"
    assert entreprise.assujetti_tva_declare is True
    assert entreprise.nombre_salaries == 3
    assert entreprise.numero_employeur_cnps == "123456789"
    assert visiteur.parcours.statut == TERMINE

    # Profil connu : le menu ne relance plus l'onboarding.
    assert visiteur.dit("1").texte == mf.BIENTOT.format(libelle="Préparer ma déclaration")


def test_les_boutons_des_questions_a_choix(session):
    visiteur = Visiteur(session)
    assert visiteur.dit("2").choix == list(mf.CHOIX_PROPOSITION)
    visiteur.dit("oui")
    visiteur.dit("Société Test")
    forme = visiteur.dit(niu_unique())
    assert [libelle for _, libelle in forme.choix] == [
        "Entreprise individuelle", "SARL", "SARL unipersonnelle", "SA", "SAS", "Autre",
    ]
    assert [valeur for valeur, _ in forme.choix] == ["1", "2", "3", "4", "5", "6"]


def test_sans_salarie_pas_de_question_cnps(session):
    visiteur = Visiteur(session)
    recap = jusqu_au_recapitulatif(visiteur, niu_unique(), salaries="aucun")
    assert "CNPS" not in recap.texte
    visiteur.dit("oui")
    entreprise = session.get(Entreprise, visiteur.conversation.entreprise_id)
    assert entreprise.nombre_salaries == 0
    assert entreprise.numero_employeur_cnps is None


def test_cnps_plus_tard(session):
    visiteur = Visiteur(session)
    recap = jusqu_au_recapitulatif(visiteur, niu_unique(), cnps="plus tard")
    assert f"• N° employeur CNPS : {mf.A_COMPLETER}" in recap.texte
    visiteur.dit("oui")
    assert session.get(Entreprise, visiteur.conversation.entreprise_id).numero_employeur_cnps is None


@pytest.mark.parametrize("reponse_tva, attendu", [("non", False), ("2", False), ("Je ne sais pas", None), ("3", None)])
def test_tva_declaree(session, reponse_tva, attendu):
    visiteur = Visiteur(session)
    for texte in ["1", "oui", "Entreprise TVA", niu_unique(), "1", "1", "20 millions", "CDI Douala", "4"]:
        visiteur.dit(texte)
    visiteur.dit(reponse_tva)
    visiteur.dit("0")
    visiteur.dit("plus tard")
    visiteur.dit("oui")
    entreprise = session.get(Entreprise, visiteur.conversation.entreprise_id)
    assert entreprise.assujetti_tva_declare is attendu
    assert entreprise.regime_declare == onboarding.INCONNU


# --- Proposition, pause, annulation ----------------------------------------------------------

def test_plus_tard_puis_nouvelle_proposition(session):
    visiteur = Visiteur(session)
    visiteur.dit("3")
    reponse = visiteur.dit("Plus tard")
    assert reponse.texte == mf.PLUS_TARD
    assert visiteur.parcours.statut == ABANDONNE
    assert visiteur.dit("2").texte == mf.PROPOSITION_ONBOARDING
    assert visiteur.parcours.statut == EN_COURS


def test_proposition_reponse_inattendue(session):
    visiteur = Visiteur(session)
    visiteur.dit("1")
    reponse = visiteur.dit("peut-être")
    assert reponse.texte == mf.ERR_CHOIX
    assert reponse.choix == list(mf.CHOIX_PROPOSITION)


def test_le_choix_4_ne_lance_pas_l_onboarding(session):
    visiteur = Visiteur(session)
    assert visiteur.dit("4").texte == mf.BIENTOT.format(libelle="Poser une question")
    assert visiteur.parcours is None


def test_pause_et_reprise(session):
    visiteur = Visiteur(session)
    for texte in ["1", "oui", "Atelier Mbarga"]:
        visiteur.dit(texte)
    pause = visiteur.dit("Menu")
    assert pause.texte == mf.PAUSE
    assert pause.choix == list(mf.MENU)
    assert visiteur.parcours.statut == EN_PAUSE
    # En pause, un message n'est pas pris comme une réponse.
    assert visiteur.dit("Bonjour").texte == mf.ACCUEIL
    assert visiteur.dit("Reprendre").texte == mf.Q_NIU
    assert visiteur.parcours.statut == EN_COURS
    assert visiteur.dit(niu_unique()).texte == mf.Q_FORME_JURIDIQUE


def test_reprise_par_le_menu(session):
    visiteur = Visiteur(session)
    for texte in ["1", "oui", "Atelier Ngono", "menu"]:
        visiteur.dit(texte)
    assert visiteur.dit("3").texte == mf.Q_NIU
    assert visiteur.parcours.statut == EN_COURS


def test_annulation(session):
    visiteur = Visiteur(session)
    for texte in ["1", "oui", "Atelier Essomba"]:
        visiteur.dit(texte)
    reponse = visiteur.dit("annuler")
    assert reponse.texte == mf.ANNULE
    assert visiteur.parcours.statut == ABANDONNE
    assert visiteur.conversation.entreprise_id is None


# --- Réponses invalides : la question est reposée ----------------------------------------------

def test_reponses_invalides(session):
    visiteur = Visiteur(session)
    visiteur.dit("1")
    visiteur.dit("oui")
    assert visiteur.dit("A").texte == mf.ERR_TEXTE_COURT
    assert visiteur.dit("x" * 201).texte == mf.ERR_TEXTE_LONG
    assert visiteur.dit("Garage Fotso").texte == mf.Q_NIU
    assert visiteur.dit("M0123/45").texte == mf.ERR_NIU
    assert visiteur.dit(niu_unique()).texte == mf.Q_FORME_JURIDIQUE
    erreur = visiteur.dit("7")
    assert erreur.texte == mf.ERR_CHOIX
    assert len(erreur.choix) == 6
    assert visiteur.dit("sarl").texte == mf.Q_SECTEUR
    assert visiteur.dit("btp").texte == mf.Q_CHIFFRE_AFFAIRES
    assert visiteur.dit("beaucoup").texte == mf.ERR_MONTANT
    assert visiteur.dit("80 000 000").texte == mf.Q_CENTRE_IMPOTS
    assert visiteur.dit("C").texte == mf.ERR_TEXTE_COURT
    assert visiteur.dit("CIME Douala").texte == mf.Q_REGIME
    assert visiteur.dit("réel").texte == mf.Q_TVA
    assert visiteur.dit("peut-être").texte == mf.ERR_CHOIX
    assert visiteur.dit("o").texte == mf.Q_SALARIES
    assert visiteur.dit("trois").texte == mf.ERR_NOMBRE
    assert visiteur.dit("2").texte == mf.Q_CNPS
    assert visiteur.dit("!!").texte == mf.ERR_CNPS
    assert visiteur.dit("ab").texte == mf.ERR_CNPS
    assert visiteur.dit("12#45@78").texte == mf.ERR_CNPS
    assert visiteur.dit("CNPS 55 66").texte == mf.Q_EMAIL
    assert visiteur.dit("plus tard").texte.startswith(mf.RECAP_INTRO)
    assert visiteur.dit("peut-être").texte == mf.ERR_CHOIX


# --- NIU déjà enregistré : jamais de rattachement ----------------------------------------------

def test_niu_deja_connu_refuse_sans_reveler_l_entreprise(session):
    niu = niu_unique()
    session.add(Entreprise(juridiction_code="CM", niu=niu, raison_sociale="Société Existante Secrète"))
    session.flush()
    visiteur = Visiteur(session)
    for texte in ["1", "oui", "Usurpateur SARL"]:
        visiteur.dit(texte)
    reponse = visiteur.dit(niu.lower())
    assert reponse.texte == mf.NIU_DEJA_CONNU
    assert "Secrète" not in reponse.texte
    assert visiteur.parcours.etape == "niu"
    assert visiteur.dit(niu_unique()).texte == mf.Q_FORME_JURIDIQUE


def test_niu_d_un_autre_pays_accepte(session):
    niu = niu_unique()
    session.add(
        Juridiction(code="CI", nom="Côte d'Ivoire", devise="XOF", langue="fr", fuseau_horaire="Africa/Abidjan", active=False)
    )
    session.flush()
    session.add(Entreprise(juridiction_code="CI", niu=niu, raison_sociale="Société Ivoirienne"))
    session.flush()
    visiteur = Visiteur(session)
    for texte in ["1", "oui", "Société Camerounaise"]:
        visiteur.dit(texte)
    assert visiteur.dit(niu).texte == mf.Q_FORME_JURIDIQUE


def test_niu_enregistre_pendant_le_parcours(session):
    visiteur = Visiteur(session)
    niu = niu_unique()
    jusqu_au_recapitulatif(visiteur, niu)
    session.add(Entreprise(juridiction_code="CM", niu=niu, raison_sociale="Plus rapide"))
    session.flush()
    reponse = visiteur.dit("oui")
    assert reponse.texte == mf.NIU_DEJA_CONNU
    assert visiteur.conversation.entreprise_id is None
    assert visiteur.parcours.etape == "niu"
    # Un nouveau NIU ramène directement au récapitulatif.
    assert visiteur.dit(niu_unique()).texte.startswith(mf.RECAP_INTRO)


# --- Correction ---------------------------------------------------------------------------------

def test_corriger_une_reponse(session):
    visiteur = Visiteur(session)
    jusqu_au_recapitulatif(visiteur, niu_unique())
    menu = visiteur.dit("Corriger")
    assert menu.texte == mf.CORRECTION
    assert len(menu.choix) == 11
    assert menu.choix[0] == ("1", "Raison sociale")
    assert visiteur.dit("1").texte == mf.Q_RAISON_SOCIALE
    recap = visiteur.dit("Boulangerie Moderne")
    assert recap.texte.startswith(mf.RECAP_INTRO)
    assert "• Raison sociale : Boulangerie Moderne" in recap.texte
    visiteur.dit("oui")
    assert session.get(Entreprise, visiteur.conversation.entreprise_id).raison_sociale == "Boulangerie Moderne"


def test_correction_choix_invalide(session):
    visiteur = Visiteur(session)
    jusqu_au_recapitulatif(visiteur, niu_unique())
    visiteur.dit("corriger")
    assert visiteur.dit("12").texte == mf.ERR_CHOIX
    assert visiteur.dit("0").texte == mf.ERR_CHOIX
    assert visiteur.dit("10").texte == mf.Q_CNPS


def test_corriger_salaries_a_zero_retire_la_cnps(session):
    visiteur = Visiteur(session)
    jusqu_au_recapitulatif(visiteur, niu_unique())
    visiteur.dit("corriger")
    visiteur.dit("9")
    recap = visiteur.dit("0")
    assert recap.texte.startswith(mf.RECAP_INTRO)
    assert "CNPS" not in recap.texte
    visiteur.dit("oui")
    assert session.get(Entreprise, visiteur.conversation.entreprise_id).numero_employeur_cnps is None


def test_corriger_salaries_depuis_zero_demande_la_cnps(session):
    visiteur = Visiteur(session)
    jusqu_au_recapitulatif(visiteur, niu_unique(), salaries="0")
    visiteur.dit("corriger")
    visiteur.dit("9")
    assert visiteur.dit("4").texte == mf.Q_CNPS
    recap = visiteur.dit("CN-778899")
    assert "• N° employeur CNPS : CN778899" in recap.texte


# --- Isolation et intégrité ---------------------------------------------------------------------

def test_l_entreprise_n_est_rattachee_qu_a_sa_conversation(session):
    alice = Visiteur(session)
    jusqu_au_recapitulatif(alice, niu_unique())
    alice.dit("oui")
    bruno = Visiteur(session)
    bruno.dit("Bonjour")
    assert alice.conversation.entreprise_id is not None
    assert bruno.conversation.entreprise_id is None
    assert bruno.dit("1").texte == mf.PROPOSITION_ONBOARDING


def test_un_seul_parcours_actif_par_conversation(session):
    visiteur = Visiteur(session)
    visiteur.dit("1")
    session.add(Parcours(conversation_id=visiteur.conversation.id, type="onboarding", etape="x", donnees={}))
    with pytest.raises(IntegrityError):
        session.flush()


def test_un_parcours_en_pause_compte_comme_actif(session):
    visiteur = Visiteur(session)
    visiteur.dit("1")
    visiteur.dit("menu")
    assert visiteur.parcours.statut == EN_PAUSE
    session.add(Parcours(conversation_id=visiteur.conversation.id, type="onboarding", etape="x", donnees={}))
    with pytest.raises(IntegrityError):
        session.flush()


def test_parcours_termines_multiples_autorises(session):
    visiteur = Visiteur(session)
    visiteur.dit("1")
    visiteur.dit("plus tard")
    visiteur.dit("1")
    visiteur.dit("plus tard")
    nombre = session.scalars(
        select(Parcours).where(Parcours.conversation_id == visiteur.conversation.id)
    ).all()
    assert len(nombre) == 2


# --- Bulle web ----------------------------------------------------------------------------------

def test_onboarding_dans_la_bulle(monkeypatch):
    monkeypatch.setenv("ESSAI_ACTIF", "true")
    get_settings.cache_clear()
    try:
        client = TestClient(app)
        client.get("/essai")
        reponse = client.post("/essai/messages", json={"texte": "1"}).json()
        assert reponse["reponse"] == mf.PROPOSITION_ONBOARDING
        assert reponse["choix"] == [
            {"valeur": "oui", "libelle": "Oui, commençons"},
            {"valeur": "plus tard", "libelle": "Plus tard"},
        ]
        assert client.post("/essai/messages", json={"texte": "oui"}).json()["reponse"] == mf.Q_RAISON_SOCIALE
    finally:
        get_settings.cache_clear()


def test_l_index_des_parcours_actifs_est_le_meme_dans_le_code_et_la_base(session):
    from sqlalchemy import text

    index_code = next(i for i in Parcours.__table__.indexes if i.name == "uq_parcours_actif_par_conversation")
    clause_code = str(index_code.dialect_options["postgresql"]["where"])
    definition_base = session.execute(
        text("SELECT indexdef FROM pg_indexes WHERE indexname = 'uq_parcours_actif_par_conversation'")
    ).scalar_one()
    for statut in (EN_COURS, EN_PAUSE):
        assert f"'{statut}'" in clause_code
        assert f"'{statut}'" in definition_base
    assert index_code.unique and "UNIQUE" in definition_base
