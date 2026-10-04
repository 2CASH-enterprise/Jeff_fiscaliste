"""Lot 6 — « Mon entreprise » : voir le profil, le modifier, tracer chaque changement."""
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError

from app.conversation import messages_fixes as mf
from app.conversation import profil
from app.conversation.models import ABANDONNE, CANAL_WEB, EN_PAUSE, TERMINE, Parcours
from app.conversation.moteur import traiter_message, trouver_ou_creer_conversation
from app.core.config import VERSION
from app.core.db import get_engine
from app.entreprises.models import Entreprise, ModificationEntreprise
from app.main import app
from app.regles.chargement import charger_fichier
from tests.test_lot02_bulle_web import essai  # noqa: F401 (fixture)
from tests.test_lot03_onboarding import Visiteur, jusqu_au_recapitulatif, niu_unique

FICHIER_CM = Path(__file__).resolve().parent.parent / "app/regles/donnees/regles_cm.json"

# Ordre du menu de modification : celui du questionnaire, sans le NIU.
RAISON, FORME, SECTEUR, CA, CENTRE, REGIME, TVA, SALARIES, CNPS = (str(n) for n in range(1, 10))


def client_avec_profil(session, salaries="3", cnps="123-456-789"):
    """Visiteur qui a terminé l'onboarding : Boulangerie du Centre SARL, réel, TVA, 150 millions."""
    visiteur = Visiteur(session)
    visiteur.niu = niu_unique()
    jusqu_au_recapitulatif(visiteur, visiteur.niu, salaries=salaries, cnps=cnps)
    visiteur.dit("oui")
    return visiteur


def entreprise_de(visiteur) -> Entreprise:
    return visiteur.session.get(Entreprise, visiteur.conversation.entreprise_id)


def modification(visiteur) -> Parcours:
    """Le parcours de modification de la conversation (un seul par test)."""
    return visiteur.session.scalars(
        select(Parcours).where(
            Parcours.conversation_id == visiteur.conversation.id, Parcours.type == profil.TYPE
        )
    ).one()


def traces(session, entreprise) -> list[ModificationEntreprise]:
    return list(session.scalars(
        select(ModificationEntreprise)
        .where(ModificationEntreprise.entreprise_id == entreprise.id)
        .order_by(ModificationEntreprise.id)
    ))


# --- Menu ----------------------------------------------------------------------------------

def test_le_menu_propose_mon_entreprise():
    assert mf.MENU[-1] == ("5", "Mon entreprise")
    assert len(mf.MENU) == 5


def test_choix_5_sans_profil_lance_l_onboarding(session):
    assert traiter_message(session, CANAL_WEB, "sans-" + uuid.uuid4().hex, "5").texte == mf.PROPOSITION_ONBOARDING


def test_choix_5_reprend_l_onboarding_en_pause(session):
    visiteur = Visiteur(session)
    visiteur.dit("1")
    visiteur.dit("oui")
    visiteur.dit("menu")
    assert visiteur.parcours.statut == EN_PAUSE
    assert visiteur.dit("5").texte == mf.Q_RAISON_SOCIALE


def test_modifier_sans_profil_n_est_pas_compris(session):
    assert traiter_message(session, CANAL_WEB, "sans-" + uuid.uuid4().hex, "modifier").texte == mf.INCOMPRIS


# --- Voir le profil ------------------------------------------------------------------------

def test_voir_le_profil(session):
    visiteur = client_avec_profil(session)
    reponse = visiteur.dit("5")
    assert reponse.texte == "\n".join([
        mf.PROFIL_INTRO.format(raison_sociale="Boulangerie du Centre SARL"),
        "• Raison sociale : Boulangerie du Centre SARL",
        f"• NIU : {visiteur.niu} (non modifiable)",
        "• Forme juridique : SARL",
        "• Secteur : Services",
        "• Chiffre d'affaires annuel : 150 000 000 FCFA",
        "• Centre des impôts : CDI de Yaoundé 1",
        "• Régime d'imposition : Régime du réel",
        "• Assujetti à la TVA : Oui",
        "• Nombre de salariés : 3",
        "• N° employeur CNPS : 123456789",
        "",
        mf.PROFIL_NIU,
    ])
    assert reponse.choix == list(mf.CHOIX_PROFIL)
    # Voir le profil n'ouvre aucun parcours.
    assert visiteur.session.scalars(
        select(Parcours).where(Parcours.conversation_id == visiteur.conversation.id, Parcours.type == profil.TYPE)
    ).first() is None


def test_voir_un_profil_incomplet(session):
    e = Entreprise(
        juridiction_code="CM", niu=niu_unique(), raison_sociale="Ets Kamga", forme_juridique="entreprise_individuelle",
        secteur="commerce", chiffre_affaires_annuel=0, centre_impots="CDI Bafoussam", regime_declare="inconnu",
        assujetti_tva_declare=None, nombre_salaries=2,
    )
    session.add(e)
    session.flush()
    texte = profil.voir_profil(e).texte
    assert "• Régime d'imposition : Je ne sais pas" in texte
    assert "• Assujetti à la TVA : Je ne sais pas" in texte
    assert "• N° employeur CNPS : À compléter" in texte


def test_profil_sans_salarie_n_affiche_pas_la_cnps(session):
    visiteur = client_avec_profil(session, salaries="0")
    texte = visiteur.dit("5").texte
    assert "• Nombre de salariés : 0" in texte
    assert "CNPS" not in texte
    assert "• Assujetti à la TVA : Oui" in texte


def test_retour_au_menu_depuis_le_profil(session):
    visiteur = client_avec_profil(session)
    visiteur.dit("5")
    reponse = visiteur.dit("menu")
    assert reponse.texte == mf.ACCUEIL
    assert reponse.choix == list(mf.MENU)


# --- Modifier ------------------------------------------------------------------------------

@pytest.mark.parametrize("texte", ["modifier", "Modifier mon profil", " MODIFIER "])
def test_modifier_ouvre_le_choix_des_informations(session, texte):
    visiteur = client_avec_profil(session)
    visiteur.dit("5")
    reponse = visiteur.dit(texte)
    assert reponse.texte == mf.MODIFICATION_QUELLE
    assert [libelle for _, libelle in reponse.choix] == [
        "Raison sociale", "Forme juridique", "Secteur", "Chiffre d'affaires annuel", "Centre des impôts",
        "Régime d'imposition", "Assujetti à la TVA", "Nombre de salariés", "N° employeur CNPS",
    ]
    assert [valeur for valeur, _ in reponse.choix] == [str(n) for n in range(1, 10)]
    assert modification(visiteur).etape == "correction"


def test_modifier_le_chiffre_d_affaires(session):
    visiteur = client_avec_profil(session)
    avant = entreprise_de(visiteur)
    identifiant, niu = avant.id, avant.niu
    visiteur.dit("5")
    visiteur.dit("modifier")
    assert visiteur.dit(CA).texte == mf.Q_CHIFFRE_AFFAIRES
    recap = visiteur.dit("200 millions")
    assert recap.texte.startswith(mf.MODIFICATION_RECAP_INTRO + "\n")
    assert "• Chiffre d'affaires annuel : 200 000 000 FCFA" in recap.texte
    assert f"• NIU : {niu} (non modifiable)" in recap.texte
    assert recap.texte.endswith("\n\n" + mf.MODIFICATION_RECAP_QUESTION)
    assert recap.choix == list(mf.CHOIX_RECAP_MODIFICATION)
    # Rien n'est écrit avant la validation.
    assert entreprise_de(visiteur).chiffre_affaires_annuel == 150_000_000

    fin = visiteur.dit("oui")
    assert fin.texte == mf.PROFIL_A_JOUR
    assert fin.choix == list(mf.MENU)

    entreprise = entreprise_de(visiteur)
    assert entreprise.id == identifiant
    assert entreprise.chiffre_affaires_annuel == 200_000_000
    assert entreprise.niu == niu
    assert session.scalar(select(func.count()).select_from(Entreprise).where(Entreprise.niu == niu)) == 1
    [trace] = traces(session, entreprise)
    assert trace.champ == "chiffre_affaires_annuel"
    assert trace.ancienne_valeur == 150_000_000
    assert trace.nouvelle_valeur == 200_000_000
    assert trace.conversation_id == visiteur.conversation.id
    assert trace.cree_le is not None
    assert modification(visiteur).statut == TERMINE


def test_plusieurs_modifications_tracees_champ_par_champ(session):
    visiteur = client_avec_profil(session)
    visiteur.dit("modifier")
    visiteur.dit(REGIME)
    visiteur.dit("Impôt libératoire")
    visiteur.dit("corriger")
    visiteur.dit(TVA)
    recap = visiteur.dit("je ne sais pas")
    assert "• Régime d'imposition : Impôt libératoire" in recap.texte
    assert "• Assujetti à la TVA : Je ne sais pas" in recap.texte
    visiteur.dit("oui")
    entreprise = entreprise_de(visiteur)
    assert entreprise.regime_declare == "liberatoire"
    assert entreprise.assujetti_tva_declare is None
    assert [(t.champ, t.ancienne_valeur, t.nouvelle_valeur) for t in traces(session, entreprise)] == [
        ("regime_declare", "reel", "liberatoire"),
        ("assujetti_tva_declare", True, None),
    ]
    # « Je ne sais pas » est un vrai vide en base, pas le texte « null ».
    assert session.scalar(
        select(func.count()).select_from(ModificationEntreprise).where(
            ModificationEntreprise.entreprise_id == entreprise.id,
            ModificationEntreprise.nouvelle_valeur.is_(None),
        )
    ) == 1


def test_modifier_la_raison_sociale_et_la_tva(session):
    visiteur = client_avec_profil(session)
    visiteur.dit("modifier")
    visiteur.dit(RAISON)
    visiteur.dit("  Boulangerie   Moderne ")
    visiteur.dit("non")
    visiteur.dit(TVA)
    visiteur.dit("2")
    visiteur.dit("oui")
    entreprise = entreprise_de(visiteur)
    assert entreprise.raison_sociale == "Boulangerie Moderne"
    assert entreprise.assujetti_tva_declare is False
    assert visiteur.dit("5").texte.startswith(mf.PROFIL_INTRO.format(raison_sociale="Boulangerie Moderne"))


def test_valider_sans_rien_changer(session):
    visiteur = client_avec_profil(session)
    visiteur.dit("modifier")
    visiteur.dit(SECTEUR)
    visiteur.dit("Services")
    fin = visiteur.dit("oui")
    assert fin.texte == mf.PROFIL_INCHANGE
    assert fin.choix == list(mf.MENU)
    assert traces(session, entreprise_de(visiteur)) == []
    assert modification(visiteur).statut == TERMINE


def test_annuler_la_modification(session):
    visiteur = client_avec_profil(session)
    visiteur.dit("modifier")
    visiteur.dit(CA)
    visiteur.dit("999 millions")
    reponse = visiteur.dit("annuler")
    assert reponse.texte == mf.MODIFICATION_ANNULEE
    assert reponse.choix == list(mf.MENU)
    assert modification(visiteur).statut == ABANDONNE
    assert entreprise_de(visiteur).chiffre_affaires_annuel == 150_000_000
    assert traces(session, entreprise_de(visiteur)) == []
    # Une nouvelle modification repart du profil enregistré.
    visiteur.dit("modifier")
    visiteur.dit(CA)
    assert "150 000 000" in visiteur.dit("150 millions").texte


def test_annuler_l_onboarding_garde_son_message(session):
    visiteur = Visiteur(session)
    visiteur.dit("1")
    visiteur.dit("oui")
    assert visiteur.dit("annuler").texte == mf.ANNULE


def test_pause_puis_reprise_de_la_modification(session):
    charger_fichier(session, FICHIER_CM)
    visiteur = client_avec_profil(session)
    visiteur.dit("modifier")
    visiteur.dit(CA)
    pause = visiteur.dit("menu")
    assert pause.texte == mf.PAUSE
    assert modification(visiteur).statut == EN_PAUSE
    # Le menu reste utilisable pendant la pause, avec le profil enregistré.
    assert visiteur.dit("2").texte.startswith(mf.OBLIGATIONS_INTRO.format(raison_sociale="Boulangerie du Centre SARL"))
    assert "150 000 000" in visiteur.dit("5").texte
    assert visiteur.dit("reprendre").texte == mf.Q_CHIFFRE_AFFAIRES
    visiteur.dit("menu")
    # « Modifier » reprend la modification en pause au lieu d'en ouvrir une seconde.
    assert visiteur.dit("modifier").texte == mf.Q_CHIFFRE_AFFAIRES
    visiteur.dit("300 millions")
    assert visiteur.dit("oui").texte == mf.PROFIL_A_JOUR
    assert entreprise_de(visiteur).chiffre_affaires_annuel == 300_000_000


def test_reponses_invalides_pendant_la_modification(session):
    visiteur = client_avec_profil(session)
    visiteur.dit("modifier")
    assert visiteur.dit("10").texte == mf.ERR_CHOIX
    erreur = visiteur.dit("0")
    assert erreur.texte == mf.ERR_CHOIX
    assert len(erreur.choix) == 9
    visiteur.dit(CA)
    assert visiteur.dit("beaucoup").texte == mf.ERR_MONTANT
    visiteur.dit("180 millions")
    erreur = visiteur.dit("peut-être")
    assert erreur.texte == mf.ERR_CHOIX
    assert erreur.choix == list(mf.CHOIX_RECAP_MODIFICATION)
    assert visiteur.dit("corriger").texte == mf.MODIFICATION_QUELLE


def test_le_niu_n_est_jamais_propose(session):
    visiteur = client_avec_profil(session)
    niu = entreprise_de(visiteur).niu
    choix = visiteur.dit("modifier").choix
    assert "NIU" not in [libelle for _, libelle in choix]
    # Chaque information proposée se modifie, aucune n'amène à la question du NIU.
    for numero, _ in choix:
        assert visiteur.dit(numero).texte != mf.Q_NIU
        visiteur.dit("annuler")
        visiteur.dit("modifier")
    assert entreprise_de(visiteur).niu == niu


def test_salaries_de_zero_a_trois_demande_la_cnps(session):
    visiteur = client_avec_profil(session, salaries="0")
    choix = visiteur.dit("modifier").choix
    assert len(choix) == 8
    visiteur.dit(SALARIES)
    assert visiteur.dit("3").texte == mf.Q_CNPS
    recap = visiteur.dit("CN-445566")
    assert "• N° employeur CNPS : CN445566" in recap.texte
    visiteur.dit("oui")
    entreprise = entreprise_de(visiteur)
    assert [(t.champ, t.ancienne_valeur, t.nouvelle_valeur) for t in traces(session, entreprise)] == [
        ("nombre_salaries", 0, 3),
        ("numero_employeur_cnps", None, "CN445566"),
    ]
    # Ancienne valeur absente : un vrai vide en base, pas le texte « null ».
    assert session.scalar(
        select(func.count()).select_from(ModificationEntreprise).where(
            ModificationEntreprise.entreprise_id == entreprise.id,
            ModificationEntreprise.ancienne_valeur.is_(None),
        )
    ) == 1


def test_salaries_a_zero_conserve_le_numero_cnps(session):
    visiteur = client_avec_profil(session)
    visiteur.dit("modifier")
    visiteur.dit(SALARIES)
    recap = visiteur.dit("0")
    assert "CNPS" not in recap.texte
    visiteur.dit("oui")
    entreprise = entreprise_de(visiteur)
    assert entreprise.nombre_salaries == 0
    assert entreprise.numero_employeur_cnps == "123456789"
    assert [t.champ for t in traces(session, entreprise)] == ["nombre_salaries"]


def test_completer_le_numero_cnps(session):
    visiteur = client_avec_profil(session, cnps="plus tard")
    assert "• N° employeur CNPS : À compléter" in visiteur.dit("5").texte
    visiteur.dit("modifier")
    visiteur.dit(CNPS)
    visiteur.dit("998877")
    visiteur.dit("oui")
    assert entreprise_de(visiteur).numero_employeur_cnps == "998877"


def test_une_modification_d_un_autre_canal_n_est_pas_ecrasee(session):
    visiteur = client_avec_profil(session)
    visiteur.dit("modifier")
    visiteur.dit(CA)
    visiteur.dit("200 millions")
    # Pendant ce temps, la raison sociale change ailleurs (autre canal, équipe Jeff…).
    entreprise_de(visiteur).raison_sociale = "Nouvelle Raison"
    session.flush()
    visiteur.dit("oui")
    entreprise = entreprise_de(visiteur)
    assert entreprise.raison_sociale == "Nouvelle Raison"
    assert entreprise.chiffre_affaires_annuel == 200_000_000
    assert [t.champ for t in traces(session, entreprise)] == ["chiffre_affaires_annuel"]


def test_deja_change_ailleurs_a_la_meme_valeur(session):
    visiteur = client_avec_profil(session)
    visiteur.dit("modifier")
    visiteur.dit(CA)
    visiteur.dit("200 millions")
    entreprise_de(visiteur).chiffre_affaires_annuel = 200_000_000
    session.flush()
    assert visiteur.dit("oui").texte == mf.PROFIL_INCHANGE
    assert traces(session, entreprise_de(visiteur)) == []


def test_les_obligations_suivent_le_profil_modifie(session):
    charger_fichier(session, FICHIER_CM)
    visiteur = client_avec_profil(session)
    assert "TVA" in visiteur.dit("2").texte
    visiteur.dit("5")
    visiteur.dit("modifier")
    visiteur.dit(TVA)
    visiteur.dit("Non")
    visiteur.dit("oui")
    assert "Déclaration et paiement mensuels de la TVA" not in visiteur.dit("2").texte


def test_chaque_entreprise_garde_son_profil(session):
    alice = client_avec_profil(session)
    bruno = client_avec_profil(session)
    alice.dit("modifier")
    alice.dit(CA)
    alice.dit("1 milliard")
    alice.dit("oui")
    assert entreprise_de(alice).chiffre_affaires_annuel == 1_000_000_000
    assert entreprise_de(bruno).chiffre_affaires_annuel == 150_000_000
    assert traces(session, entreprise_de(bruno)) == []


# --- Base de données -----------------------------------------------------------------------

def test_table_des_modifications():
    inspecteur = inspect(get_engine())
    colonnes = {c["name"]: c for c in inspecteur.get_columns("modifications_entreprise")}
    assert set(colonnes) == {
        "id", "entreprise_id", "conversation_id", "champ", "ancienne_valeur", "nouvelle_valeur", "cree_le",
    }
    assert colonnes["entreprise_id"]["nullable"] is False
    assert colonnes["champ"]["nullable"] is False
    cles = {fk["referred_table"] for fk in inspecteur.get_foreign_keys("modifications_entreprise")}
    assert cles == {"entreprises", "conversations"}
    assert "ix_modifications_entreprise_entreprise_id" in {i["name"] for i in inspecteur.get_indexes("modifications_entreprise")}


def test_une_trace_exige_une_entreprise_existante(session):
    session.add(ModificationEntreprise(entreprise_id=uuid.uuid4(), champ="secteur"))
    with pytest.raises(IntegrityError):
        session.flush()


# --- Bulle web et version -----------------------------------------------------------------

def test_parcours_complet_dans_la_bulle(essai):
    client = TestClient(app)
    client.get("/essai")
    niu = niu_unique()
    for texte in ["1", "oui", "Ets Bulle", niu, "1", "1", "20 millions", "CDI Douala", "1", "2", "0"]:
        assert client.post("/essai/messages", json={"texte": texte}).status_code == 200, texte
    assert client.post("/essai/messages", json={"texte": "oui"}).json()["reponse"].startswith("C'est enregistré")
    profil_json = client.post("/essai/messages", json={"texte": "5"}).json()
    assert profil_json["reponse"].startswith(mf.PROFIL_INTRO.format(raison_sociale="Ets Bulle"))
    assert [c["valeur"] for c in profil_json["choix"]] == ["modifier", "menu"]
    client.post("/essai/messages", json={"texte": "modifier"})
    client.post("/essai/messages", json={"texte": SECTEUR})
    client.post("/essai/messages", json={"texte": "2"})
    assert client.post("/essai/messages", json={"texte": "oui"}).json()["reponse"] == mf.PROFIL_A_JOUR


def test_version():
    assert TestClient(app).get("/sante").json()["version"] == VERSION
