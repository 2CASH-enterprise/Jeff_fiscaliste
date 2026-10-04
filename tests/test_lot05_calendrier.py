"""Lot 5 — dates en français, calcul des échéances, jours fériés, « Voir mes échéances »."""
import json
import uuid
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select

from app.calendrier import feries
from app.calendrier.dates import (
    EcheanceInvalide,
    formater_date,
    formater_delai,
    prochaine_echeance,
    valider,
)
from app.conversation import echeances as module_echeances
from app.conversation import messages_fixes as mf
from app.conversation.echeances import avertissement, voir_echeances
from app.conversation.models import CANAL_WEB
from app.conversation.moteur import traiter_message, trouver_ou_creer_conversation
from app.entreprises.models import Entreprise
from app.regles.chargement import ReglesInvalides, charger, charger_fichier
from app.regles.models import Regle
from app.regles.moteur import regles_en_vigueur

RACINE = Path(__file__).resolve().parent.parent
FICHIER_CM = RACINE / "app/regles/donnees/regles_cm.json"
MENSUEL_15 = {"type": "jour_du_mois_suivant", "jour": 15}
TRIMESTRIEL_15 = {"type": "jour_du_mois_suivant_le_trimestre", "jour": 15}


# --- Dates en français ---------------------------------------------------------------------

@pytest.mark.parametrize(
    "jour, attendu",
    [
        (date(2026, 10, 15), "jeudi 15 octobre 2026"),
        (date(2026, 11, 1), "dimanche 1er novembre 2026"),
        (date(2026, 8, 15), "samedi 15 août 2026"),
        (date(2027, 2, 2), "mardi 2 février 2027"),
        (date(2026, 12, 7), "lundi 7 décembre 2026"),
    ],
)
def test_formater_date(jour, attendu):
    assert formater_date(jour) == attendu


@pytest.mark.parametrize(
    "limite, attendu",
    [(date(2026, 10, 4), "aujourd'hui"), (date(2026, 10, 5), "demain"), (date(2026, 10, 6), "dans 2 jours"),
     (date(2026, 10, 15), "dans 11 jours")],
)
def test_formater_delai(limite, attendu):
    assert formater_delai(limite, date(2026, 10, 4)) == attendu


# --- Calcul des échéances ------------------------------------------------------------------------

@pytest.mark.parametrize(
    "aujourd_hui, date_limite, periode",
    [
        (date(2026, 10, 4), date(2026, 10, 15), "septembre 2026"),
        (date(2026, 10, 15), date(2026, 10, 15), "septembre 2026"),  # le jour même : encore valable
        (date(2026, 10, 16), date(2026, 11, 15), "octobre 2026"),
        (date(2026, 12, 20), date(2027, 1, 15), "décembre 2026"),
        (date(2027, 1, 3), date(2027, 1, 15), "décembre 2026"),
        (date(2026, 1, 1), date(2026, 1, 15), "décembre 2025"),
    ],
)
def test_echeance_mensuelle(aujourd_hui, date_limite, periode):
    echeance = prochaine_echeance(MENSUEL_15, aujourd_hui)
    assert (echeance.date_limite, echeance.periode) == (date_limite, periode)


@pytest.mark.parametrize(
    "aujourd_hui, date_limite, periode",
    [
        (date(2026, 10, 4), date(2026, 10, 15), "3e trimestre 2026"),
        (date(2026, 10, 15), date(2026, 10, 15), "3e trimestre 2026"),
        (date(2026, 10, 16), date(2027, 1, 15), "4e trimestre 2026"),
        (date(2026, 2, 1), date(2026, 4, 15), "1er trimestre 2026"),
        (date(2026, 5, 20), date(2026, 7, 15), "2e trimestre 2026"),
        (date(2026, 1, 15), date(2026, 1, 15), "4e trimestre 2025"),
    ],
)
def test_echeance_trimestrielle(aujourd_hui, date_limite, periode):
    echeance = prochaine_echeance(TRIMESTRIEL_15, aujourd_hui)
    assert (echeance.date_limite, echeance.periode) == (date_limite, periode)


@pytest.mark.parametrize(
    "aujourd_hui, date_limite",
    [(date(2026, 3, 1), date(2026, 3, 15)), (date(2026, 3, 15), date(2026, 3, 15)), (date(2026, 3, 16), date(2027, 3, 15))],
)
def test_echeance_annuelle(aujourd_hui, date_limite):
    echeance = prochaine_echeance({"type": "date_annuelle", "mois": 3, "jour": 15}, aujourd_hui)
    assert echeance.date_limite == date_limite
    assert echeance.periode == f"année {date_limite.year}"


@pytest.mark.parametrize(
    "calcul, periodicite",
    [
        (MENSUEL_15, "mensuelle"),
        (TRIMESTRIEL_15, "trimestrielle"),
        ({"type": "date_annuelle", "mois": 12, "jour": 28}, "annuelle"),
        ({"type": "jour_du_mois_suivant", "jour": 1}, "mensuelle"),
    ],
)
def test_echeances_valides(calcul, periodicite):
    valider(calcul, periodicite)


@pytest.mark.parametrize(
    "calcul, periodicite",
    [
        (None, "mensuelle"),
        ({"type": "chaque_lundi", "jour": 1}, "mensuelle"),
        (MENSUEL_15, "trimestrielle"),
        (TRIMESTRIEL_15, "mensuelle"),
        ({"type": "jour_du_mois_suivant", "jour": 29}, "mensuelle"),
        ({"type": "jour_du_mois_suivant", "jour": 0}, "mensuelle"),
        ({"type": "jour_du_mois_suivant", "jour": "15"}, "mensuelle"),
        ({"type": "jour_du_mois_suivant", "jour": True}, "mensuelle"),
        ({"type": "jour_du_mois_suivant"}, "mensuelle"),
        ({"type": "jour_du_mois_suivant", "jour": 15, "mois": 3}, "mensuelle"),
        ({"type": "date_annuelle", "jour": 15}, "annuelle"),
        ({"type": "date_annuelle", "mois": 13, "jour": 15}, "annuelle"),
        ({"type": "date_annuelle", "mois": 0, "jour": 15}, "annuelle"),
    ],
)
def test_echeances_invalides(calcul, periodicite):
    with pytest.raises(EcheanceInvalide):
        valider(calcul, periodicite)


# --- Jours fériés ---------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "annee, attendu",
    [(2024, date(2024, 3, 31)), (2025, date(2025, 4, 20)), (2026, date(2026, 4, 5)), (2027, date(2027, 3, 28)),
     (2030, date(2030, 4, 21)), (2022, date(2022, 4, 17)), (2032, date(2032, 3, 28)), (2038, date(2038, 4, 25))],
)
def test_paques(annee, attendu):
    assert feries.paques(annee) == attendu


@pytest.mark.parametrize(
    "jour, nom",
    [
        (date(2026, 1, 1), "Jour de l'An"),
        (date(2027, 2, 11), "Fête de la Jeunesse"),
        (date(2026, 4, 3), "Vendredi saint"),
        (date(2026, 5, 1), "Fête du Travail"),
        (date(2026, 5, 14), "Ascension"),
        (date(2026, 5, 20), "Fête nationale"),
        (date(2026, 8, 15), "Assomption"),
        (date(2026, 12, 25), "Noël"),
        (date(2027, 3, 26), "Vendredi saint"),
        (date(2027, 5, 6), "Ascension"),
        (date(2027, 3, 10), "Djouldé Soumaé (fin du ramadan)"),
    ],
)
def test_jours_feries(jour, nom):
    assert feries.jour_ferie(jour) == nom


@pytest.mark.parametrize("jour", [date(2026, 10, 15), date(2026, 4, 5), date(2026, 4, 6), date(2026, 5, 13)])
def test_jours_ordinaires(jour):
    assert feries.jour_ferie(jour) is None


def test_fichier_des_fetes_mobiles():
    donnees = json.loads(feries.FICHIER_MOBILES.read_text())
    for fete in donnees["feries"]:
        date.fromisoformat(fete["date"])
        assert fete["statut"] in {"estimee", "officielle"}


@pytest.mark.parametrize(
    "jour, attendu",
    [
        (date(2026, 10, 15), None),
        (date(2026, 11, 15), mf.ECHEANCES_WEEK_END.format(jour="dimanche")),
        (date(2026, 8, 15), mf.ECHEANCES_FERIE.format(nom="Assomption")),  # férié et samedi : le férié prime
        (date(2027, 5, 15), mf.ECHEANCES_WEEK_END.format(jour="samedi")),
        (date(2026, 5, 20), mf.ECHEANCES_FERIE.format(nom="Fête nationale")),
    ],
)
def test_avertissement_sans_report(jour, attendu):
    assert avertissement(jour) == attendu


# --- Règles : TVA version 2 ------------------------------------------------------------------------

def test_tva_version_2_dans_le_fichier():
    regles = json.loads(FICHIER_CM.read_text())["regles"]
    versions = {r["version"]: r for r in regles if r["code"] == "TVA_DECLARATION_MENSUELLE"}
    assert set(versions) == {1, 2}
    assert "echeance_calcul" not in versions[1]
    assert versions[2]["echeance_calcul"] == MENSUEL_15
    assert versions[2]["echeance"] == "au plus tard le 15 du mois suivant"
    autres = {k: v for k, v in versions[2].items() if k not in {"version", "echeance", "echeance_calcul"}}
    assert autres == {k: v for k, v in versions[1].items() if k not in {"version", "echeance"}}


def test_seule_la_tva_a_une_echeance_calculable():
    regles = json.loads(FICHIER_CM.read_text())["regles"]
    assert [(r["code"], r["version"]) for r in regles if r.get("echeance_calcul")] == [("TVA_DECLARATION_MENSUELLE", 2)]


def test_la_version_2_remplace_la_version_1(session):
    charger_fichier(session, FICHIER_CM)
    tva = [r for r in regles_en_vigueur(session, "CM", date(2026, 10, 4)) if r.code == "TVA_DECLARATION_MENSUELLE"]
    assert [(r.version, r.echeance_calcul) for r in tva] == [(2, MENSUEL_15)]


def regle(**champs):
    base = {
        "code": "ECH_" + uuid.uuid4().hex[:8].upper(), "version": 1, "type": "obligation", "impot": "TVA",
        "titre": "Test", "description": "Test.", "condition": {"toujours": True}, "periodicite": "mensuelle",
        "applicable_du": "2026-01-01", "statut": "a_valider",
    }
    base.update(champs)
    return base


def test_echeance_calculable_invalide_refusee_au_chargement(session):
    with pytest.raises(ReglesInvalides, match="échéance calculable invalide"):
        charger(session, {"juridiction": "CM", "regles": [regle(echeance_calcul=TRIMESTRIEL_15)]})


def test_echeance_calculable_enregistree(session):
    r = regle(periodicite="trimestrielle", echeance_calcul=TRIMESTRIEL_15)
    charger(session, {"juridiction": "CM", "regles": [r]})
    assert session.scalars(select(Regle).where(Regle.code == r["code"])).one().echeance_calcul == TRIMESTRIEL_15


def test_ajouter_une_echeance_exige_une_nouvelle_version(session):
    r = regle()
    charger(session, {"juridiction": "CM", "regles": [r]})
    with pytest.raises(ReglesInvalides, match="nouvelle version"):
        charger(session, {"juridiction": "CM", "regles": [{**r, "echeance_calcul": MENSUEL_15}]})


# --- « Voir mes échéances » ------------------------------------------------------------------------

AUJOURDHUI = date(2026, 10, 4)


@pytest.fixture
def jour_fixe(monkeypatch):
    monkeypatch.setattr(module_echeances, "aujourd_hui", lambda fuseau: AUJOURDHUI)


def entreprise(session, **profil) -> Entreprise:
    e = Entreprise(juridiction_code="CM", niu="E" + uuid.uuid4().hex[:12].upper(), raison_sociale="Ets BABA", **profil)
    session.add(e)
    session.flush()
    return e


def test_echeances_ets_baba(session, jour_fixe):
    """Le profil testé par le porteur au lot 4 : libératoire, TVA, salariés, sans n° CNPS."""
    charger_fichier(session, FICHIER_CM)
    e = entreprise(session, regime_declare="liberatoire", assujetti_tva_declare=True, nombre_salaries=2)
    reponse = voir_echeances(session, e)
    assert reponse.texte == "\n\n".join([
        mf.ECHEANCES_INTRO.format(raison_sociale="Ets BABA"),
        "• Déclaration et paiement mensuels de la TVA — septembre 2026\n"
        "  Au plus tard le jeudi 15 octobre 2026 (dans 11 jours)",
        mf.ECHEANCES_SANS_DATE + "\n"
        "• Paiement trimestriel de l'impôt libératoire (chaque trimestre)\n"
        "• Retenues sur salaires et déclaration mensuelle des salaires (DIPE) (chaque mois)",
        mf.ECHEANCES_PONCTUELLES + "\n• Immatriculation de l'employeur et des salariés à la CNPS",
        mf.OBLIGATIONS_AVERTISSEMENT,
    ])
    assert reponse.choix == list(mf.MENU)


def test_echeance_avec_avertissement_week_end(session, monkeypatch):
    monkeypatch.setattr(module_echeances, "aujourd_hui", lambda fuseau: date(2026, 10, 20))
    charger_fichier(session, FICHIER_CM)
    e = entreprise(session, regime_declare="reel", assujetti_tva_declare=True, nombre_salaries=0)
    texte = voir_echeances(session, e).texte
    assert "• Déclaration et paiement mensuels de la TVA — octobre 2026\n  Au plus tard le dimanche 15 novembre 2026 (dans 26 jours)\n  " + mf.ECHEANCES_WEEK_END.format(jour="dimanche") in texte


def test_echeances_triees_par_date(session, jour_fixe):
    charger(session, {"juridiction": "CM", "regles": [
        # Titres choisis à l'inverse de l'ordre alphabétique : seul l'ordre des dates doit compter.
        regle(code="ECH_TARDIVE_" + uuid.uuid4().hex[:4].upper(), titre="A tardive", periodicite="annuelle",
              echeance_calcul={"type": "date_annuelle", "mois": 12, "jour": 1}),
        regle(code="ECH_PROCHE_" + uuid.uuid4().hex[:4].upper(), titre="Z proche",
              echeance_calcul={"type": "jour_du_mois_suivant", "jour": 10}),
    ]})
    e = entreprise(session, regime_declare="reel")
    texte = voir_echeances(session, e).texte
    assert texte.index("• Z proche") < texte.index("• A tardive")


def test_echeances_incertaines(session, jour_fixe):
    charger_fichier(session, FICHIER_CM)
    e = entreprise(session, regime_declare="inconnu", assujetti_tva_declare=None, nombre_salaries=0)
    texte = voir_echeances(session, e).texte
    debut, fin = texte.split(mf.ECHEANCES_A_CONFIRMER)
    assert "TVA" not in debut
    assert "• Déclaration et paiement mensuels de la TVA (chaque mois)" in fin


def test_aucune_echeance(session, jour_fixe):
    e = entreprise(session, regime_declare="liberatoire", assujetti_tva_declare=False, nombre_salaries=0)
    session.execute(Regle.__table__.update().values(statut="retiree"))
    assert voir_echeances(session, e).texte == mf.ECHEANCES_AUCUNE


def test_pas_d_avertissement_de_validation_si_tout_est_publie(session, jour_fixe):
    charger_fichier(session, FICHIER_CM)
    session.execute(Regle.__table__.update().values(statut="publiee"))
    e = entreprise(session, regime_declare="reel", assujetti_tva_declare=True, nombre_salaries=0)
    assert mf.OBLIGATIONS_AVERTISSEMENT not in voir_echeances(session, e).texte


def test_les_alertes_ne_sont_pas_des_echeances(session, jour_fixe):
    charger_fichier(session, FICHIER_CM)
    e = entreprise(session, regime_declare="simplifie", assujetti_tva_declare=True, nombre_salaries=0)
    assert "Régime simplifié et TVA" not in voir_echeances(session, e).texte


def test_fuseau_horaire_de_la_juridiction(monkeypatch, session):
    vus = []
    monkeypatch.setattr(module_echeances, "aujourd_hui", lambda fuseau: vus.append(fuseau) or AUJOURDHUI)
    voir_echeances(session, entreprise(session, regime_declare="reel"))
    assert vus == ["Africa/Douala"]


def test_choix_3_du_menu(session, jour_fixe):
    charger_fichier(session, FICHIER_CM)
    e = entreprise(session, regime_declare="reel", assujetti_tva_declare=True, nombre_salaries=0)
    identifiant = "echeances-" + uuid.uuid4().hex
    trouver_ou_creer_conversation(session, CANAL_WEB, identifiant).entreprise_id = e.id
    session.flush()
    assert traiter_message(session, CANAL_WEB, identifiant, "3").texte.startswith(
        mf.ECHEANCES_INTRO.format(raison_sociale="Ets BABA")
    )


def test_choix_3_sans_profil_lance_l_onboarding(session):
    assert traiter_message(session, CANAL_WEB, "sans-" + uuid.uuid4().hex, "3").texte == mf.PROPOSITION_ONBOARDING
