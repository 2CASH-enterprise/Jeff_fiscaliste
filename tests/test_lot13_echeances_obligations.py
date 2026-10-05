"""Lot 13 — coffre fiscal : onglets Échéances (mois par mois) et Obligations (fiscales, sociales, à confirmer)."""
import importlib.util
import json
import uuid
from datetime import date
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from app.core.config import VERSION
from app.core.db import get_engine
from app.conversation.echeances import avertissement
from app.espace import donnees
from app.espace import textes as tx
from app.regles import charger as commande
from app.regles.chargement import ReglesInvalides, charger
from app.regles.models import DOMAINES, FISCAL, SOCIAL, Regle
from app.regles.moteur import Resultat
from tests.test_lot04_regles import fichier, regle_type
from tests.test_lot07_rappels import FICHIER_CM
from tests.test_lot12_espace import adresse_unique, connecter, creer, espace, texte_visible  # noqa: F401 (fixture)

RACINE = Path(__file__).resolve().parent.parent
JOUR = date(2026, 10, 5)  # lundi
MENSUEL_15 = {"type": "jour_du_mois_suivant", "jour": 15}


def faite(code=None, titre="Règle", domaine=FISCAL, periodicite="mensuelle", calcul=None, statut="publiee",
          type_="obligation", condition=None, **champs) -> Regle:
    return Regle(
        juridiction_code="CM", code=code or "R_" + uuid.uuid4().hex[:8].upper(), version=1, type=type_, impot="TVA",
        domaine=domaine, titre=titre, description=f"Description de {titre}.", condition=condition or {"toujours": True},
        periodicite=periodicite, echeance_calcul=calcul, statut=statut, applicable_du=date(2026, 1, 1), ordre=100,
        **champs,
    )


@pytest.fixture
def regles_simulees(monkeypatch):
    liste = []
    monkeypatch.setattr(donnees, "evaluer_entreprise", lambda *a: liste)
    return liste


def ajouter(liste, regle, applicabilite="oui"):
    liste.append(Resultat(regle, applicabilite))
    return regle


# --- Domaine des règles -------------------------------------------------------------------------

def test_domaines():
    assert DOMAINES == ("fiscal", "social") and (FISCAL, SOCIAL) == DOMAINES


def test_fichier_du_cameroun_classe():
    regles = json.loads(FICHIER_CM.read_text())["regles"]
    assert {r["code"] for r in regles if r["domaine"] == SOCIAL} == {"SALAIRES_RETENUES_DIPE", "CNPS_IMMATRICULATION_EMPLOYEUR"}
    assert all(r["domaine"] in DOMAINES for r in regles)


def test_domaine_obligatoire(session):
    regle = regle_type()
    del regle["domaine"]
    with pytest.raises(ReglesInvalides) as erreur:
        charger(session, fichier(regle))
    assert any("champs manquants : domaine" in e for e in erreur.value.erreurs)


def test_domaine_inconnu_refuse(session):
    with pytest.raises(ReglesInvalides) as erreur:
        charger(session, fichier(regle_type(domaine="fiscale")))
    assert any("domaine inconnu 'fiscale' (fiscal ou social)" in e for e in erreur.value.erreurs)


def test_domaine_enregistre(session):
    regle = regle_type(domaine=SOCIAL)
    charger(session, fichier(regle))
    assert session.scalars(select(Regle).where(Regle.code == regle["code"])).one().domaine == SOCIAL


def test_domaine_modifiable_sur_une_version_chargee(session):
    regle = regle_type(domaine=FISCAL)
    charger(session, fichier(regle))
    bilan = charger(session, fichier({**regle, "domaine": SOCIAL}))
    nom = f"{regle['code']} v1"
    assert bilan.domaine_modifie == [nom] and bilan.statut_modifie == [] and bilan.inchangees == []
    assert session.scalars(select(Regle).where(Regle.code == regle["code"])).one().domaine == SOCIAL
    bilan = charger(session, fichier({**regle, "domaine": SOCIAL}))
    assert bilan.inchangees == [nom] and bilan.domaine_modifie == []


def test_statut_et_domaine_modifies_ensemble(session):
    regle = regle_type(domaine=FISCAL)
    charger(session, fichier(regle))
    bilan = charger(session, fichier({**regle, "domaine": SOCIAL, "statut": "publiee"}))
    nom = f"{regle['code']} v1"
    assert bilan.statut_modifie == [nom] and bilan.domaine_modifie == [nom] and bilan.inchangees == []
    enregistree = session.scalars(select(Regle).where(Regle.code == regle["code"])).one()
    assert (enregistree.statut, enregistree.domaine) == ("publiee", SOCIAL)


def test_contenu_toujours_verrouille(session):
    regle = regle_type()
    charger(session, fichier(regle))
    with pytest.raises(ReglesInvalides, match="déjà chargée avec un autre contenu"):
        charger(session, fichier({**regle, "domaine": SOCIAL, "titre": "Autre"}))


def test_commande_affiche_les_domaines_modifies(tmp_path, capsys):
    chemin = tmp_path / "regles.json"
    regle = regle_type(statut="brouillon", domaine=FISCAL)
    chemin.write_text(json.dumps(fichier(regle)))
    assert commande.main([str(chemin)]) == 0
    capsys.readouterr()
    chemin.write_text(json.dumps(fichier({**regle, "domaine": SOCIAL})))
    assert commande.main([str(chemin)]) == 0
    sortie = capsys.readouterr().out
    assert f"Domaine modifié : 1 {regle['code']} v1" in sortie and "Inchangées : 0" in sortie


# --- Migration ----------------------------------------------------------------------------------

def migration_0013():
    chemin = RACINE / "migrations/versions/0013_domaine_regles.py"
    spec = importlib.util.spec_from_file_location("migration_0013", chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_colonne_et_contrainte():
    inspecteur = inspect(get_engine())
    colonne = {c["name"]: c for c in inspecteur.get_columns("regles")}["domaine"]
    assert colonne["nullable"] is False and "fiscal" in str(colonne["default"])
    [verif] = [c for c in inspecteur.get_check_constraints("regles") if c["name"] == "ck_regles_domaine"]
    assert "fiscal" in verif["sqltext"] and "social" in verif["sqltext"]


def test_domaine_inconnu_refuse_en_base(session):
    regle = faite()
    regle.domaine = "autre"
    session.add(regle)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_migration_classe_les_regles_deja_chargees():
    module = migration_0013()
    assert set(module.SOCIALES) == {"SALAIRES_RETENUES_DIPE", "CNPS_IMMATRICULATION_EMPLOYEUR"}
    connexion = get_engine().connect()
    transaction = connexion.begin()
    try:
        with Operations.context(MigrationContext.configure(connexion)):
            module.downgrade()
            assert "domaine" not in {c["name"] for c in inspect(connexion).get_columns("regles")}
            connexion.execute(text(
                "INSERT INTO juridictions (code, nom, devise, fuseau_horaire, langue, active) "
                "VALUES ('SN', 'Sénégal', 'XOF', 'Africa/Dakar', 'fr', false) ON CONFLICT DO NOTHING"
            ))
            for code, juridiction in (("SALAIRES_RETENUES_DIPE", "CM"), ("TVA_MIGRATION", "CM"), ("SALAIRES_RETENUES_DIPE", "SN")):
                connexion.execute(text(
                    "INSERT INTO regles (id, juridiction_code, code, version, type, impot, titre, description, condition, "
                    "applicable_du, statut, ordre) VALUES (gen_random_uuid(), :j, :c, 99, 'obligation', 'X', 'T', 'D', "
                    "'{\"toujours\": true}', '2026-01-01', 'brouillon', 1)"
                ), {"j": juridiction, "c": code})
            module.upgrade()
            lignes = connexion.execute(text(
                "SELECT juridiction_code, code, domaine FROM regles WHERE version = 99 ORDER BY juridiction_code, code"
            )).all()
            assert [tuple(l) for l in lignes] == [
                ("CM", "SALAIRES_RETENUES_DIPE", "social"), ("CM", "TVA_MIGRATION", "fiscal"), ("SN", "SALAIRES_RETENUES_DIPE", "fiscal"),
            ]
    finally:
        transaction.rollback()
        connexion.close()


# --- Échéances : calcul du mois -----------------------------------------------------------------

def test_douze_mois_du_mois_en_cours(session, regles_simulees):
    e = creer(session)
    mois = donnees.mois_affiche(session, e, None, JOUR)
    assert (mois.cle, mois.libelle, mois.precedent, mois.suivant) == ("2026-10", "octobre 2026", None, "2026-11")
    dernier = donnees.mois_affiche(session, e, "2027-09", JOUR)
    assert (dernier.cle, dernier.precedent, dernier.suivant) == ("2027-09", "2027-08", None)
    assert donnees.mois_affiche(session, e, "2027-01", JOUR).libelle == "janvier 2027"
    assert len(donnees.mois_possibles(JOUR)) == donnees.HORIZON == 12


@pytest.mark.parametrize("cle", ["2027-10", "2026-09", "2026-13", "n'importe", "", "2026-1"])
def test_mois_hors_limites_ramene_au_mois_en_cours(session, regles_simulees, cle):
    assert donnees.mois_affiche(session, creer(session), cle, JOUR).cle == "2026-10"


def test_jour_de_la_juridiction(session, regles_simulees, monkeypatch):
    monkeypatch.setattr(donnees, "aujourd_hui", lambda fuseau: date(2027, 3, 31) if fuseau == "Africa/Douala" else None)
    assert donnees.mois_affiche(session, creer(session), None).cle == "2027-03"


def test_echeance_mensuelle_du_mois(session, regles_simulees):
    ajouter(regles_simulees, faite("TVA", "TVA", calcul=MENSUEL_15))
    mois = donnees.mois_affiche(session, creer(session), "2026-11", JOUR)
    [e] = mois.datees
    assert (e.code, e.titre, e.domaine, e.periode, e.date_limite) == ("TVA", "TVA", FISCAL, "octobre 2026", date(2026, 11, 15))
    assert e.date_texte == "dimanche 15 novembre 2026" and e.mois_court == "nov." and e.jours == 41
    assert e.alerte == avertissement(date(2026, 11, 15)) and "dimanche" in e.alerte
    # Échéance un dimanche : les rappels arrivent au plus tard le vendredi.
    assert e.rappels == [(7, "dimanche 8 novembre 2026"), (2, "vendredi 13 novembre 2026")]


def test_rappels_deja_passes_masques(session, regles_simulees):
    ajouter(regles_simulees, faite(calcul=MENSUEL_15))
    [e] = donnees.mois_affiche(session, creer(session), None, date(2026, 10, 10)).datees
    assert e.rappels == [(2, "mardi 13 octobre 2026")]
    [e] = donnees.mois_affiche(session, creer(session), None, date(2026, 10, 8)).datees
    assert e.rappels == [(7, "jeudi 8 octobre 2026"), (2, "mardi 13 octobre 2026")]


def test_echeance_passee_du_mois_en_cours(session, regles_simulees):
    ajouter(regles_simulees, faite(calcul=MENSUEL_15))
    [e] = donnees.mois_affiche(session, creer(session), None, date(2026, 10, 20)).datees
    assert e.date_limite == date(2026, 10, 15) and e.jours == -5 and e.rappels == []


def test_jour_ferie_signale(session, regles_simulees):
    ajouter(regles_simulees, faite(calcul={"type": "date_annuelle", "mois": 5, "jour": 20}, periodicite="annuelle"))
    [e] = donnees.mois_affiche(session, creer(session), "2027-05", JOUR).datees
    assert "Fête nationale" in e.alerte


def test_trimestrielle_et_annuelle_seulement_leur_mois(session, regles_simulees):
    ajouter(regles_simulees, faite("TRIM", calcul={"type": "jour_du_mois_suivant_le_trimestre", "jour": 15}, periodicite="trimestrielle"))
    ajouter(regles_simulees, faite("AN", calcul={"type": "date_annuelle", "mois": 3, "jour": 15}, periodicite="annuelle"))
    e = creer(session)
    vus = {cle: [d.code for d in donnees.mois_affiche(session, e, cle, JOUR).datees] for cle in
           ("2026-10", "2026-11", "2026-12", "2027-01", "2027-03", "2027-04")}
    assert vus == {"2026-10": ["TRIM"], "2026-11": [], "2026-12": [], "2027-01": ["TRIM"], "2027-03": ["AN"], "2027-04": ["TRIM"]}
    [trimestre] = donnees.mois_affiche(session, e, "2027-01", JOUR).datees
    assert trimestre.periode == "4e trimestre 2026"


def test_ordre_des_dates(session, regles_simulees):
    ajouter(regles_simulees, faite("B", "B", calcul={"type": "jour_du_mois_suivant", "jour": 20}))
    ajouter(regles_simulees, faite("C", "C", calcul={"type": "jour_du_mois_suivant", "jour": 10}))
    ajouter(regles_simulees, faite("A", "A", calcul={"type": "jour_du_mois_suivant", "jour": 20}))
    assert [d.code for d in donnees.mois_affiche(session, creer(session), "2026-11", JOUR).datees] == ["C", "A", "B"]


def test_sans_date_incertaines_et_alertes(session, regles_simulees):
    ajouter(regles_simulees, faite("ACOMPTE", "Acompte"))
    ajouter(regles_simulees, faite("DIPE", "DIPE", domaine=SOCIAL))
    ajouter(regles_simulees, faite("PATENTE", "Patente", periodicite="annuelle"))
    ajouter(regles_simulees, faite("LIB", "Libératoire", periodicite="trimestrielle"))
    ajouter(regles_simulees, faite("CNPS", "CNPS", periodicite="ponctuelle", domaine=SOCIAL))
    ajouter(regles_simulees, faite("DOUTE", "Douteuse", calcul=MENSUEL_15), "incertain")
    ajouter(regles_simulees, faite("DOUTE2", "Douteuse 2"), "incertain")
    ajouter(regles_simulees, faite("ALERTE", "Alerte", type_="alerte", periodicite=None, statut="a_valider"))
    mois = donnees.mois_affiche(session, creer(session), "2026-12", JOUR)
    assert mois.datees == []
    assert mois.a_confirmer == [("ACOMPTE", "Acompte", FISCAL), ("DIPE", "DIPE", SOCIAL)]
    assert mois.sans_date == [("PATENTE", "Patente", FISCAL), ("LIB", "Libératoire", FISCAL)]
    assert mois.incertaines == 2 and mois.a_valider is False


def test_a_valider(session, regles_simulees):
    ajouter(regles_simulees, faite(statut="a_valider"))
    assert donnees.mois_affiche(session, creer(session), None, JOUR).a_valider is True


# --- Échéances : page ---------------------------------------------------------------------------

def test_page_echeances(espace, session, regles_simulees):
    ajouter(regles_simulees, faite("TVA_X", "Déclaration de TVA", calcul=MENSUEL_15, statut="a_valider"))
    ajouter(regles_simulees, faite("DIPE_X", "DIPE", domaine=SOCIAL))
    ajouter(regles_simulees, faite("PAT_X", "Patente", periodicite="annuelle"))
    ajouter(regles_simulees, faite("DOUTE_X", "Douteuse"), "incertain")
    adresse = adresse_unique()
    creer(session, "Ets Calendrier", adresse)
    client = connecter(session, adresse)
    html = client.get("/espace/echeances").text
    texte = texte_visible(html)
    assert tx.ECHEANCES_DATEES in texte and "Déclaration de TVA" in texte and "oct." in texte
    assert tx.DATE_A_CONFIRMER in texte and "DIPE" in texte and tx.DATE_A_CONFIRMER_AIDE in texte
    assert tx.SANS_DATE_CONNUE in texte and "Patente" in texte
    assert tx.INCERTAINES_LIEN.format(nombre=1) in texte and tx.AVERTISSEMENT_VALIDATION in texte
    assert 'href="http://testserver/espace/obligations?filtre=fiscales#TVA_X"' in html
    assert 'href="http://testserver/espace/obligations?filtre=sociales#DIPE_X"' in html
    assert 'href="http://testserver/espace/obligations?filtre=a_confirmer"' in html
    assert 'href="http://testserver/espace/echeances?mois=' in html and f'aria-label="{tx.MOIS_PRECEDENT}"' not in html
    assert 'class="esp-mois-fleche esp-inactif"' in html and f'aria-label="{tx.MOIS_SUIVANT}"' in html


def test_page_echeances_navigation(espace, session, regles_simulees):
    adresse = adresse_unique()
    e = creer(session, "Ets Navigation", adresse)
    client = connecter(session, adresse)
    debut = donnees.mois_affiche(session, e, None)
    html = client.get(f"/espace/echeances?mois={debut.suivant}").text
    assert f'href="http://testserver/espace/echeances?mois={debut.cle}"' in html
    dernier = donnees.mois_possibles(donnees.ce_jour(session, e))[-1]
    html = client.get(f"/espace/echeances?mois={donnees.cle_mois(*dernier)}").text
    assert f'aria-label="{tx.MOIS_SUIVANT}"' not in html and f'aria-label="{tx.MOIS_PRECEDENT}"' in html
    assert client.get("/espace/echeances?mois=" + "9" * 500).status_code == 200


def test_page_echeances_vide(espace, session, regles_simulees):
    adresse = adresse_unique()
    creer(session, "Ets Vide", adresse)
    texte = texte_visible(connecter(session, adresse).get("/espace/echeances").text)
    assert tx.AUCUNE_DATE_CE_MOIS in texte
    for absent in (tx.DATE_A_CONFIRMER, tx.SANS_DATE_CONNUE, tx.AVERTISSEMENT_VALIDATION, "à confirmer selon"):
        assert absent not in texte


@pytest.mark.parametrize("jours,attendu,classe", [
    (-3, tx.PASSEE, "esp-etiquette-gris"), (0, tx.AUJOURD_HUI, "esp-etiquette-orange"), (1, tx.DEMAIN, "esp-etiquette-orange"),
    (7, "7 j", "esp-etiquette-orange"), (8, "8 j", "esp-etiquette-bleu"),
])
def test_etiquettes_de_delai(espace, session, monkeypatch, jours, attendu, classe):
    echeance = donnees.EcheanceDuMois("C", "Titre", FISCAL, "septembre 2026", date(2026, 10, 15), "jeudi 15 octobre 2026",
                                      "oct.", jours, None, [(2, "mardi 13 octobre 2026")])
    monkeypatch.setattr(donnees, "mois_affiche", lambda *a: donnees.Mois("2026-10", "octobre 2026", [echeance], [], None, None))
    adresse = adresse_unique()
    creer(session, "Ets Délai", adresse)
    html = connecter(session, adresse).get("/espace/echeances").text
    assert f'<span class="esp-etiquette {classe}">{attendu}</span>'.replace("'", "&#39;") in html
    assert ("esp-passee" in html) == (jours < 0)
    assert tx.RAPPEL_PREVU.format(palier=2, date="mardi 13 octobre 2026") in texte_visible(html)


def test_echeances_cachees_si_profil_incertain(espace, session, regles):
    adresse = adresse_unique()
    creer(session, "Ets Inconnu", adresse, assujetti_tva_declare=None)
    texte = texte_visible(connecter(session, adresse).get("/espace/echeances").text)
    assert "Déclaration et paiement mensuels de la TVA" not in texte
    assert tx.INCERTAINES_LIEN.format(nombre=1) in texte


@pytest.fixture
def regles(session):
    from app.regles.chargement import charger_fichier

    charger_fichier(session, FICHIER_CM)


# --- Obligations : données ----------------------------------------------------------------------

def test_feuilles():
    a, b, c = ({"champ": x, "op": "est_vide"} for x in ("secteur", "nombre_salaries", "regime_declare"))
    assert donnees.feuilles({"tous": [a, {"un_parmi": [b, {"non": c}]}]}) == [a, b, c]
    assert donnees.feuilles({"toujours": True}) == []


def test_raisons_lues_et_manquantes(session):
    e = creer(session, regime_declare="inconnu", assujetti_tva_declare=True, nombre_salaries=None, numero_employeur_cnps=None)
    condition = {"tous": [
        {"champ": "assujetti_tva_declare", "op": "egal", "valeur": True},
        {"champ": "regime_declare", "op": "egal", "valeur": "reel"},
        {"champ": "assujetti_tva_declare", "op": "egal", "valeur": True},
        {"champ": "nombre_salaries", "op": "superieur", "valeur": 0},
        {"champ": "numero_employeur_cnps", "op": "est_vide"},
    ]}
    lues, manquantes = donnees.raisons(faite(condition=condition), e)
    assert lues == ["Assujetti à la TVA : Oui", "N° employeur CNPS : À compléter"]
    assert manquantes == ["Régime d'imposition", "Nombre de salariés"]


def test_raison_pour_toutes_les_entreprises(session):
    assert donnees.raisons(faite(), creer(session)) == ([tx.TOUTES_LES_ENTREPRISES], [])


@pytest.mark.parametrize("url,attendu", [
    ("https://impots.cm/fiche.pdf", "https://impots.cm/fiche.pdf"), ("http://impots.cm", None),
    ("javascript:alert(1)", None), ("", None), (None, None),
])
def test_source_sure(url, attendu):
    assert donnees.source_sure(url) == attendu


def test_fiche_d_obligation(session):
    regle = faite("TVA_F", "TVA", calcul=MENSUEL_15, statut="a_valider", echeance="au plus tard le 15",
                  source_texte="Fiche TVA", source_article="art. 149", source_url="https://impots.cm/tva.pdf")
    o = donnees.obligation(regle, "oui", creer(session), JOUR)
    assert (o.code, o.titre, o.description, o.domaine) == ("TVA_F", "TVA", "Description de TVA.", FISCAL)
    assert (o.frequence, o.echeance, o.prochaine) == ("Chaque mois", "au plus tard le 15", "jeudi 15 octobre 2026")
    assert (o.source_texte, o.source_article, o.source_url) == ("Fiche TVA", "art. 149", "https://impots.cm/tva.pdf")
    assert o.a_valider is True and o.incertaine is False
    incertaine = donnees.obligation(regle, "incertain", creer(session), JOUR)
    assert incertaine.incertaine is True and incertaine.prochaine is None
    alerte = donnees.obligation(faite(periodicite=None, statut="publiee"), "oui", creer(session), JOUR)
    assert alerte.frequence is None and alerte.prochaine is None and alerte.a_valider is False


def test_classement_des_obligations(session, regles_simulees):
    ajouter(regles_simulees, faite("F1", domaine=FISCAL))
    ajouter(regles_simulees, faite("S1", domaine=SOCIAL))
    ajouter(regles_simulees, faite("F2", domaine=FISCAL))
    ajouter(regles_simulees, faite("I_SOCIAL", domaine=SOCIAL), "incertain")
    ajouter(regles_simulees, faite("I_FISCAL"), "incertain")
    ajouter(regles_simulees, faite("AL", type_="alerte", periodicite=None))
    ajouter(regles_simulees, faite("AL_DOUTE", type_="alerte", periodicite=None), "incertain")
    o = donnees.obligations(session, creer(session), JOUR)
    assert [x.code for x in o.fiscales] == ["F1", "F2"] and [x.code for x in o.sociales] == ["S1"]
    assert [x.code for x in o.a_confirmer] == ["I_SOCIAL", "I_FISCAL"] and [x.code for x in o.alertes] == ["AL"]
    assert [x.code for x in o.liste("sociales")] == ["S1"] and o.liste("a_confirmer") == o.a_confirmer
    assert donnees.FILTRES == ("fiscales", "sociales", "a_confirmer")


def test_obligations_du_fichier_cm(session, regles):
    e = creer(session, regime_declare="simplifie", assujetti_tva_declare=True, nombre_salaries=3, numero_employeur_cnps=None)
    o = donnees.obligations(session, e, JOUR)
    assert {x.code for x in o.sociales} == {"SALAIRES_RETENUES_DIPE", "CNPS_IMMATRICULATION_EMPLOYEUR"}
    assert {"TVA_DECLARATION_MENSUELLE", "ACOMPTE_MENSUEL_IMPOT", "PATENTE_ANNUELLE"} <= {x.code for x in o.fiscales}
    assert [x.code for x in o.alertes] == ["ALERTE_SIMPLIFIE_ET_TVA"]
    tva = next(x for x in o.fiscales if x.code == "TVA_DECLARATION_MENSUELLE")
    assert tva.prochaine == "jeudi 15 octobre 2026" and tva.raisons == ["Assujetti à la TVA : Oui"]


# --- Obligations : page -------------------------------------------------------------------------

def test_page_obligations(espace, session, regles_simulees):
    ajouter(regles_simulees, faite("TVA_P", "TVA du mois", calcul=MENSUEL_15, statut="a_valider", echeance="le 15",
                                   source_texte="Fiche TVA", source_url="https://impots.cm/tva.pdf",
                                   condition={"champ": "assujetti_tva_declare", "op": "egal", "valeur": True}))
    ajouter(regles_simulees, faite("PAT_P", "Patente", periodicite="annuelle"))
    ajouter(regles_simulees, faite("DIPE_P", "DIPE", domaine=SOCIAL))
    ajouter(regles_simulees, faite("ALERTE_P", "Alerte régime", type_="alerte", periodicite=None))
    adresse = adresse_unique()
    creer(session, "Ets Obligations", adresse)
    client = connecter(session, adresse)
    html = client.get("/espace/obligations").text
    texte = texte_visible(html)
    assert '<details class="esp-carte esp-fiche-obligation" id="TVA_P">' in html and 'id="PAT_P"' in html
    assert 'id="DIPE_P"' not in html and 'id="ALERTE_P"' in html and tx.POINTS_ATTENTION in texte
    assert "Fiscales 2" in texte and "Sociales 1" in texte and "À confirmer 0" in texte
    assert 'href="http://testserver/espace/obligations?filtre=fiscales" class="actif" aria-current="true"' in html
    assert "Chaque mois · Prochaine date limite : jeudi 15 octobre 2026" in texte or "Prochaine date limite" in texte
    assert tx.EN_ATTENTE_VALIDATION in texte and tx.VALIDATION_DETAIL in texte
    assert "Assujetti à la TVA : Oui" in texte and tx.POURQUOI in texte and tx.D_APRES_PROFIL in texte
    assert 'href="https://impots.cm/tva.pdf" target="_blank" rel="noopener noreferrer"' in html
    assert "Fiche TVA" in texte and tx.SANS_SOURCE in texte  # La patente n'a pas de source.
    assert f"{tx.ECHEANCE} {tx.DATE_A_CONFIRMER}" in texte and f"{tx.ECHEANCE} le 15" in texte
    assert "location.hash" in html and 'cible.tagName === "DETAILS") { cible.open = true; }' in html
    html = client.get("/espace/obligations?filtre=sociales").text
    assert 'id="DIPE_P"' in html and 'id="TVA_P"' not in html and 'id="ALERTE_P"' in html


@pytest.mark.parametrize("filtre", ["", "toutes", "<script>"])
def test_filtre_inconnu(espace, session, regles_simulees, filtre):
    ajouter(regles_simulees, faite("F_INC"))
    adresse = adresse_unique()
    creer(session, "Ets Filtre", adresse)
    html = connecter(session, adresse).get(f"/espace/obligations?filtre={filtre}").text
    assert 'id="F_INC"' in html and "<script>alert" not in html


def test_page_a_confirmer(espace, session, regles_simulees):
    ajouter(regles_simulees, faite("DOUTE_P", "Obligation douteuse",
                                   condition={"champ": "nombre_salaries", "op": "superieur", "valeur": 0}), "incertain")
    adresse = adresse_unique()
    creer(session, "Ets Doute", adresse, nombre_salaries=None)
    texte = texte_visible(connecter(session, adresse).get("/espace/obligations?filtre=a_confirmer").text)
    assert "Obligation douteuse" in texte and tx.POURQUOI_A_CONFIRMER in texte
    assert tx.INFORMATIONS_MANQUANTES in texte and "Nombre de salariés" in texte and tx.A_CONFIRMER_AIDE in texte
    assert tx.D_APRES_PROFIL not in texte and tx.POINTS_ATTENTION not in texte


@pytest.mark.parametrize("filtre", ["fiscales", "sociales", "a_confirmer"])
def test_filtres_vides(espace, session, regles_simulees, filtre):
    adresse = adresse_unique()
    creer(session, "Ets Rien", adresse)
    texte = texte_visible(connecter(session, adresse).get(f"/espace/obligations?filtre={filtre}").text)
    assert tx.FILTRE_VIDE[filtre] in texte


def test_textes_du_coffre_echappes(espace, session, regles_simulees):
    ajouter(regles_simulees, faite("ECH", "<b>Gras</b>", source_texte="<i>x</i>"))
    adresse = adresse_unique()
    creer(session, "Ets Échappe", adresse)
    html = connecter(session, adresse).get("/espace/obligations").text
    assert "<b>Gras</b>" not in html and "&lt;b&gt;Gras&lt;/b&gt;" in html and "<i>x</i>" not in html


# --- Accueil : liens ----------------------------------------------------------------------------

def test_accueil_relie_aux_onglets(espace, session, regles):
    adresse = adresse_unique()
    creer(session, "Ets Liens", adresse, nombre_salaries=None)
    html = connecter(session, adresse).get("/espace/accueil").text
    assert f'<a class="esp-vedette-lien" href="http://testserver/espace/echeances">{tx.VOIR_CALENDRIER}' in html
    assert '<a class="esp-carte esp-chiffre" href="http://testserver/espace/obligations">' in html
    assert html.count('href="http://testserver/espace/obligations?filtre=a_confirmer"') == 2
    assert tx.VOIR_DETAIL in texte_visible(html)


def test_styles_du_lot():
    css = (RACINE / "app/static/css/espace.css").read_text()
    for classe in (".esp-mois", ".esp-filtres", ".esp-fiche-obligation", ".esp-etiquette-orange", ".esp-etiquette-sous"):
        assert classe in css


def test_version():
    assert VERSION.startswith("0.")
