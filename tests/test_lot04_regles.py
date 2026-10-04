"""Lot 4 — conditions (oui / non / incertain), chargement des règles, moteur, affichage des obligations."""
import copy
import json
import uuid
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select

from app.conversation import messages_fixes as mf
from app.conversation.models import CANAL_WEB
from app.conversation.moteur import traiter_message, trouver_ou_creer_conversation
from app.conversation.obligations import voir_obligations
from app.entreprises.models import Entreprise
from app.regles import charger as commande
from app.regles.chargement import ReglesInvalides, charger, charger_fichier
from app.regles.conditions import INCERTAIN, NON, OUI, ConditionInvalide, evaluer, valider
from app.regles.models import A_VALIDER, PUBLIEE, Regle
from app.regles.moteur import evaluer_entreprise, profil_de, regles_en_vigueur

RACINE = Path(__file__).resolve().parent.parent
FICHIER_CM = RACINE / "app/regles/donnees/regles_cm.json"
JOUR = date(2026, 10, 4)


# --- Conditions ----------------------------------------------------------------------------

def comparer(champ, op, valeur):
    return {"champ": champ, "op": op, "valeur": valeur}


@pytest.mark.parametrize(
    "condition, profil, attendu",
    [
        ({"toujours": True}, {}, OUI),
        (comparer("nombre_salaries", "superieur", 0), {"nombre_salaries": 3}, OUI),
        (comparer("nombre_salaries", "superieur", 0), {"nombre_salaries": 0}, NON),
        (comparer("nombre_salaries", "superieur", 0), {"nombre_salaries": None}, INCERTAIN),
        (comparer("nombre_salaries", "superieur_ou_egal", 3), {"nombre_salaries": 3}, OUI),
        (comparer("nombre_salaries", "inferieur", 3), {"nombre_salaries": 3}, NON),
        (comparer("nombre_salaries", "inferieur_ou_egal", 3), {"nombre_salaries": 3}, OUI),
        (comparer("regime_declare", "egal", "reel"), {"regime_declare": "reel"}, OUI),
        (comparer("regime_declare", "different", "reel"), {"regime_declare": "reel"}, NON),
        (comparer("regime_declare", "dans", ["reel", "simplifie"]), {"regime_declare": "simplifie"}, OUI),
        (comparer("regime_declare", "dans", ["reel", "simplifie"]), {"regime_declare": "liberatoire"}, NON),
        (comparer("assujetti_tva_declare", "egal", True), {"assujetti_tva_declare": False}, NON),
        (comparer("assujetti_tva_declare", "egal", True), {"assujetti_tva_declare": None}, INCERTAIN),
        ({"champ": "numero_employeur_cnps", "op": "est_vide"}, {"numero_employeur_cnps": None}, OUI),
        ({"champ": "numero_employeur_cnps", "op": "est_vide"}, {"numero_employeur_cnps": "123"}, NON),
        ({"champ": "numero_employeur_cnps", "op": "est_renseigne"}, {"numero_employeur_cnps": None}, NON),
        ({"champ": "numero_employeur_cnps", "op": "est_renseigne"}, {"numero_employeur_cnps": "1"}, OUI),
    ],
)
def test_comparaisons(condition, profil, attendu):
    valider(condition)
    assert evaluer(condition, profil) == attendu


V, F, I = (
    comparer("nombre_salaries", "egal", 1),
    comparer("nombre_salaries", "egal", 2),
    comparer("regime_declare", "egal", "reel"),
)
PROFIL = {"nombre_salaries": 1, "regime_declare": None}  # V vraie, F fausse, I incertaine


@pytest.mark.parametrize(
    "condition, attendu",
    [
        ({"tous": [V, V]}, OUI),
        ({"tous": [V, F]}, NON),
        ({"tous": [V, I]}, INCERTAIN),
        ({"tous": [F, I]}, NON),
        ({"un_parmi": [F, F]}, NON),
        ({"un_parmi": [F, V]}, OUI),
        ({"un_parmi": [F, I]}, INCERTAIN),
        ({"un_parmi": [V, I]}, OUI),
        ({"non": V}, NON),
        ({"non": F}, OUI),
        ({"non": I}, INCERTAIN),
        ({"tous": [V, {"un_parmi": [F, {"non": F}]}]}, OUI),
    ],
)
def test_logique_a_trois_valeurs(condition, attendu):
    valider(condition)
    assert evaluer(condition, PROFIL) == attendu


@pytest.mark.parametrize(
    "condition",
    [
        None, {}, [], {"toujours": False}, {"toujours": True, "x": 1},
        {"tous": []}, {"tous": V}, {"un_parmi": [V], "x": 1}, {"non": V, "x": 1},
        {"champ": "salaire_du_patron", "op": "egal", "valeur": 1},
        {"champ": "nombre_salaries", "op": "environ", "valeur": 1},
        {"champ": "nombre_salaries", "op": "egal"},
        {"champ": "nombre_salaries", "op": "egal", "valeur": 1, "x": 2},
        {"champ": "regime_declare", "op": "dans", "valeur": "reel"},
        {"champ": "numero_employeur_cnps", "op": "est_vide", "valeur": None},
        {"tous": [V, {"champ": "inconnu", "op": "egal", "valeur": 1}]},
        {"non": {}},
    ],
)
def test_conditions_invalides(condition):
    with pytest.raises(ConditionInvalide):
        valider(condition)


def test_comparaison_de_types_differents_refusee():
    with pytest.raises(ConditionInvalide):
        evaluer(comparer("nombre_salaries", "superieur", "beaucoup"), {"nombre_salaries": 3})


# --- Chargement ----------------------------------------------------------------------------

def regle_type(**champs):
    base = {
        "code": "REGLE_TEST_" + uuid.uuid4().hex[:8].upper(),
        "version": 1,
        "type": "obligation",
        "impot": "TVA",
        "titre": "Règle de test",
        "description": "Description de test.",
        "condition": {"toujours": True},
        "periodicite": "mensuelle",
        "applicable_du": "2026-01-01",
        "statut": "a_valider",
    }
    base.update(champs)
    return {k: v for k, v in base.items() if v is not ...}


def fichier(*regles):
    return {"juridiction": "CM", "regles": list(regles)}


def test_le_fichier_du_cameroun_se_charge(session):
    bilan = charger_fichier(session, FICHIER_CM)
    donnees = json.loads(FICHIER_CM.read_text())
    assert len(bilan.ajoutees) + len(bilan.inchangees) == len(donnees["regles"]) == 7
    # Rechargé une seconde fois : rien ne change.
    deuxieme = charger_fichier(session, FICHIER_CM)
    assert deuxieme.ajoutees == [] and deuxieme.statut_modifie == []
    assert len(deuxieme.inchangees) == 7


def test_toutes_les_regles_du_cameroun_sont_a_valider():
    donnees = json.loads(FICHIER_CM.read_text())
    assert {r["statut"] for r in donnees["regles"]} == {A_VALIDER}


def test_la_regle_tva_cite_la_fiche_officielle():
    donnees = json.loads(FICHIER_CM.read_text())
    tva = next(r for r in donnees["regles"] if r["code"] == "TVA_DECLARATION_MENSUELLE")
    assert tva["echeance"] == "avant le 15 du mois suivant"
    assert tva["source_url"].startswith("https://impots.cm/")


def test_chargement_tout_ou_rien(session):
    bonne = regle_type()
    mauvaise = regle_type(type="impot_magique")
    with pytest.raises(ReglesInvalides) as erreur:
        charger(session, fichier(bonne, mauvaise))
    assert any("type inconnu" in e for e in erreur.value.erreurs)
    assert session.scalars(select(Regle).where(Regle.code == bonne["code"])).first() is None


@pytest.mark.parametrize(
    "modification, message",
    [
        ({"code": "minuscules"}, "code invalide"),
        ({"version": 0}, "version"),
        ({"version": True}, "version"),
        ({"version": "1"}, "version"),
        ({"statut": "approuvee"}, "statut inconnu"),
        ({"periodicite": "hebdomadaire"}, "périodicité inconnue"),
        ({"periodicite": ...}, "doit avoir une périodicité"),
        ({"titre": "  "}, "ne peut pas être vide"),
        ({"description": ""}, "ne peut pas être vide"),
        ({"impot": None}, "ne peut pas être vide"),
        ({"condition": {"champ": "x", "op": "egal", "valeur": 1}}, "condition invalide"),
        ({"applicable_du": "01/01/2026"}, "date invalide"),
        ({"applicable_au": "2025-12-31"}, "antérieure"),
        ({"applicable_au": "fin 2026"}, "date invalide"),
        ({"titre": ...}, "champs manquants"),
        ({"commentaire_interne": "x"}, "champs inconnus"),
    ],
)
def test_regles_refusees(session, modification, message):
    with pytest.raises(ReglesInvalides) as erreur:
        charger(session, fichier(regle_type(**modification)))
    assert any(message in e for e in erreur.value.erreurs), erreur.value.erreurs


def test_une_alerte_n_a_pas_besoin_de_periodicite(session):
    charger(session, fichier(regle_type(type="alerte", periodicite=...)))


@pytest.mark.parametrize("donnees", [None, [], {"regles": []}, {"juridiction": "CM"}, {"juridiction": "CM", "regles": {}}])
def test_fichier_mal_forme(session, donnees):
    with pytest.raises(ReglesInvalides):
        charger(session, donnees)


def test_juridiction_inconnue(session):
    with pytest.raises(ReglesInvalides, match="Juridiction inconnue"):
        charger(session, {"juridiction": "ZZ", "regles": []})


def test_regle_en_double_dans_le_fichier(session):
    regle = regle_type()
    with pytest.raises(ReglesInvalides, match="deux fois"):
        charger(session, fichier(regle, dict(regle)))


def test_une_version_chargee_ne_change_jamais_de_contenu(session):
    regle = regle_type()
    charger(session, fichier(regle))
    modifiee = {**regle, "description": "Nouveau texte."}
    with pytest.raises(ReglesInvalides, match="nouvelle version"):
        charger(session, fichier(modifiee))
    bilan = charger(session, fichier({**modifiee, "version": 2}))
    assert bilan.ajoutees == [f"{regle['code']} v2"]


def test_seul_le_statut_change_sans_nouvelle_version(session):
    regle = regle_type()
    charger(session, fichier(regle))
    bilan = charger(session, fichier({**regle, "statut": "publiee"}))
    assert bilan.statut_modifie == [f"{regle['code']} v1"]
    enregistree = session.scalars(select(Regle).where(Regle.code == regle["code"])).one()
    assert enregistree.statut == PUBLIEE


def test_fichier_json_illisible(session, tmp_path):
    chemin = tmp_path / "regles.json"
    chemin.write_text("{ pas du json")
    with pytest.raises(ReglesInvalides, match="illisible"):
        charger_fichier(session, chemin)


def test_commande_de_chargement(tmp_path, capsys):
    chemin = tmp_path / "regles.json"
    # La commande valide en base pour de bon : règle en brouillon, donc jamais visible des autres tests.
    regle = regle_type(statut="brouillon")
    chemin.write_text(json.dumps(fichier(regle)))
    assert commande.main([str(chemin)]) == 0
    assert "Ajoutées : 1" in capsys.readouterr().out
    assert commande.main([str(chemin)]) == 0
    assert "Inchangées : 1" in capsys.readouterr().out
    chemin.write_text(json.dumps(fichier({**regle, "titre": "Autre"})))
    assert commande.main([str(chemin)]) == 1
    assert "Aucune règle n'a été chargée" in capsys.readouterr().out


# --- Moteur ----------------------------------------------------------------------------------

def entreprise(session, **profil) -> Entreprise:
    e = Entreprise(juridiction_code="CM", niu="T" + uuid.uuid4().hex[:12].upper(), raison_sociale="Test SARL", **profil)
    session.add(e)
    session.flush()
    return e


def codes(resultats):
    return {r.regle.code: r.applicabilite for r in resultats}


def test_profil_je_ne_sais_pas_devient_absent(session):
    e = entreprise(session, regime_declare="inconnu", assujetti_tva_declare=None)
    assert profil_de(e)["regime_declare"] is None
    assert profil_de(e)["assujetti_tva_declare"] is None


def test_regles_en_vigueur_filtre_statut_dates_et_versions(session):
    prefixe = "VIG_" + uuid.uuid4().hex[:6].upper()
    charger(session, fichier(
        regle_type(code=prefixe + "_BROUILLON", statut="brouillon"),
        regle_type(code=prefixe + "_RETIREE", statut="retiree"),
        regle_type(code=prefixe + "_PUBLIEE", statut="publiee"),
        regle_type(code=prefixe + "_FUTURE", applicable_du="2027-01-01"),
        regle_type(code=prefixe + "_PASSEE", applicable_du="2025-01-01", applicable_au="2025-12-31"),
        regle_type(code=prefixe + "_JUSQUA_AUJOURDHUI", applicable_au="2026-10-04"),
        regle_type(code=prefixe + "_VERSIONS", titre="v1"),
        regle_type(code=prefixe + "_VERSIONS", version=2, titre="v2"),
    ))
    vues = {r.code: r for r in regles_en_vigueur(session, "CM", JOUR) if r.code.startswith(prefixe)}
    assert set(vues) == {prefixe + "_PUBLIEE", prefixe + "_JUSQUA_AUJOURDHUI", prefixe + "_VERSIONS"}
    assert vues[prefixe + "_VERSIONS"].titre == "v2"
    assert vues[prefixe + "_VERSIONS"].version == 2
    assert prefixe + "_JUSQUA_AUJOURDHUI" not in {r.code for r in regles_en_vigueur(session, "CM", date(2026, 10, 5))}
    assert prefixe + "_FUTURE" in {r.code for r in regles_en_vigueur(session, "CM", date(2027, 1, 1))}


def test_ets_boss(session):
    """Le profil enregistré par le porteur au lot 3 : simplifié, TVA déclarée, 2 salariés."""
    charger_fichier(session, FICHIER_CM)
    e = entreprise(
        session, forme_juridique="entreprise_individuelle", regime_declare="simplifie",
        assujetti_tva_declare=True, nombre_salaries=2, numero_employeur_cnps=None,
        chiffre_affaires_annuel=50_000_000,
    )
    resultat = codes(evaluer_entreprise(session, e, JOUR))
    assert resultat == {
        "TVA_DECLARATION_MENSUELLE": OUI,
        "ACOMPTE_MENSUEL_IMPOT": OUI,
        "PATENTE_ANNUELLE": OUI,
        "SALAIRES_RETENUES_DIPE": OUI,
        "CNPS_IMMATRICULATION_EMPLOYEUR": OUI,
        "ALERTE_SIMPLIFIE_ET_TVA": OUI,
    }


def test_profil_liberatoire_sans_salarie(session):
    charger_fichier(session, FICHIER_CM)
    e = entreprise(session, regime_declare="liberatoire", assujetti_tva_declare=False, nombre_salaries=0)
    assert codes(evaluer_entreprise(session, e, JOUR)) == {"IMPOT_LIBERATOIRE_TRIMESTRIEL": OUI}


def test_profil_incertain(session):
    charger_fichier(session, FICHIER_CM)
    e = entreprise(session, regime_declare="inconnu", assujetti_tva_declare=None, nombre_salaries=1,
                   numero_employeur_cnps="C123")
    assert codes(evaluer_entreprise(session, e, JOUR)) == {
        "TVA_DECLARATION_MENSUELLE": INCERTAIN,
        "ACOMPTE_MENSUEL_IMPOT": INCERTAIN,
        "IMPOT_LIBERATOIRE_TRIMESTRIEL": INCERTAIN,
        "PATENTE_ANNUELLE": INCERTAIN,
        "SALAIRES_RETENUES_DIPE": OUI,
        "ALERTE_SIMPLIFIE_ET_TVA": INCERTAIN,
    }


def test_ordre_obligations_puis_alertes(session):
    charger_fichier(session, FICHIER_CM)
    e = entreprise(session, regime_declare="simplifie", assujetti_tva_declare=True, nombre_salaries=0)
    ordre = [r.regle.code for r in evaluer_entreprise(session, e, JOUR)]
    assert ordre == ["TVA_DECLARATION_MENSUELLE", "ACOMPTE_MENSUEL_IMPOT", "PATENTE_ANNUELLE", "ALERTE_SIMPLIFIE_ET_TVA"]


def test_regles_d_un_autre_pays_ignorees(session):
    from app.referentiel.models import Juridiction

    if session.get(Juridiction, "SN") is None:
        session.add(Juridiction(code="SN", nom="Sénégal", devise="XOF", langue="fr", fuseau_horaire="Africa/Dakar", active=False))
        session.flush()
    code = "SN_" + uuid.uuid4().hex[:6].upper()
    charger(session, {"juridiction": "SN", "regles": [regle_type(code=code)]})
    e = entreprise(session, regime_declare="reel")
    assert code not in codes(evaluer_entreprise(session, e, JOUR))


# --- Affichage dans la conversation ----------------------------------------------------------

def test_affichage_ets_boss(session):
    charger_fichier(session, FICHIER_CM)
    e = entreprise(session, regime_declare="simplifie", assujetti_tva_declare=True, nombre_salaries=2)
    reponse = voir_obligations(session, e)
    texte = reponse.texte
    assert texte.startswith(mf.OBLIGATIONS_INTRO.format(raison_sociale="Test SARL"))
    assert "• Déclaration et paiement mensuels de la TVA\n  Chaque mois · Échéance : avant le 15 du mois suivant" in texte
    assert "Source : Fiche TVA de la Direction générale des impôts" in texte
    assert "Source : Code général des impôts ; modalités de paiement revues par la loi de finances 2026, CGI art. 21 bis (à vérifier)" in texte
    assert "• Patente\n  Chaque année · Échéance : à confirmer" in texte
    assert "Source : à compléter" in texte
    assert mf.OBLIGATIONS_ALERTES + "\n• Régime simplifié et TVA :" in texte
    assert texte.endswith(mf.OBLIGATIONS_AVERTISSEMENT)
    assert mf.OBLIGATIONS_A_CONFIRMER not in texte
    assert reponse.choix == list(mf.MENU)


def test_affichage_des_obligations_a_confirmer(session):
    charger_fichier(session, FICHIER_CM)
    e = entreprise(session, regime_declare="inconnu", assujetti_tva_declare=None, nombre_salaries=0)
    texte = voir_obligations(session, e).texte
    intro, reste = texte.split(mf.OBLIGATIONS_A_CONFIRMER)
    assert "TVA" not in intro
    assert "• Déclaration et paiement mensuels de la TVA" in reste


def test_affichage_sans_obligation(session):
    charger_fichier(session, FICHIER_CM)
    e = entreprise(session, regime_declare="liberatoire", assujetti_tva_declare=False, nombre_salaries=0)
    session.execute(Regle.__table__.update().where(Regle.code == "IMPOT_LIBERATOIRE_TRIMESTRIEL").values(statut="retiree"))
    reponse = voir_obligations(session, e)
    assert reponse.texte == mf.OBLIGATIONS_AUCUNE


def test_pas_d_avertissement_si_tout_est_publie(session):
    charger_fichier(session, FICHIER_CM)
    session.execute(Regle.__table__.update().values(statut="publiee"))
    e = entreprise(session, regime_declare="reel", assujetti_tva_declare=True, nombre_salaries=0)
    assert mf.OBLIGATIONS_AVERTISSEMENT not in voir_obligations(session, e).texte


def test_choix_2_du_menu_avec_profil(session):
    charger_fichier(session, FICHIER_CM)
    e = entreprise(session, regime_declare="reel", assujetti_tva_declare=True, nombre_salaries=0)
    identifiant = "obligations-" + uuid.uuid4().hex
    conversation = trouver_ou_creer_conversation(session, CANAL_WEB, identifiant)
    conversation.entreprise_id = e.id
    session.flush()
    reponse = traiter_message(session, CANAL_WEB, identifiant, "2")
    assert reponse.texte.startswith(mf.OBLIGATIONS_INTRO.format(raison_sociale="Test SARL"))
    # Les autres choix restent « bientôt disponibles ».
    assert traiter_message(session, CANAL_WEB, identifiant, "3").texte == mf.BIENTOT.format(libelle="Voir mes échéances")


def test_choix_2_sans_profil_lance_toujours_l_onboarding(session):
    identifiant = "sans-profil-" + uuid.uuid4().hex
    assert traiter_message(session, CANAL_WEB, identifiant, "2").texte == mf.PROPOSITION_ONBOARDING


def test_bienvenue_oriente_vers_les_obligations():
    assert "Voir mes obligations" in mf.BIENVENUE


def test_fuseau_horaire_de_la_juridiction(monkeypatch, session):
    from app.conversation import obligations as module

    vus = []
    monkeypatch.setattr(module, "aujourd_hui", lambda fuseau: vus.append(fuseau) or JOUR)
    e = entreprise(session, regime_declare="reel")
    module.voir_obligations(session, e)
    assert vus == ["Africa/Douala"]


def test_textes_des_regles_au_vouvoiement():
    from tests.test_lot02_bulle_web import TUTOIEMENT

    for regle in json.loads(FICHIER_CM.read_text())["regles"]:
        for texte in (regle["titre"], regle["description"], regle.get("echeance") or ""):
            assert not TUTOIEMENT.search(texte), (regle["code"], texte)


def test_date_du_jour_dans_le_fuseau_de_la_juridiction(monkeypatch):
    from datetime import datetime, timezone

    from app.core import temps

    instant = datetime(2026, 10, 4, 23, 30, tzinfo=timezone.utc)  # 0 h 30 le 5 octobre à Douala

    class HorlogeFigee(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    monkeypatch.setattr(temps, "datetime", HorlogeFigee)
    assert temps.aujourd_hui("Africa/Douala") == date(2026, 10, 5)
    assert temps.aujourd_hui("UTC") == date(2026, 10, 4)


def test_une_seule_regle_par_code_et_version_en_base(session):
    from sqlalchemy.exc import IntegrityError

    regle = regle_type()
    charger(session, fichier(regle))
    session.add(Regle(juridiction_code="CM", **{**charger_regle_brute(regle)}))
    with pytest.raises(IntegrityError):
        session.flush()


def charger_regle_brute(regle):
    from app.regles.chargement import verifier_regle

    propre, erreurs = verifier_regle(regle, 1)
    assert erreurs == []
    return propre


def test_source_reduite_a_un_lien(session):
    charger_fichier(session, FICHIER_CM)
    e = entreprise(session, regime_declare="reel", assujetti_tva_declare=False, nombre_salaries=1)
    texte = voir_obligations(session, e).texte
    assert "• Immatriculation de l'employeur et des salariés à la CNPS\n  Une fois · Échéance : à confirmer\n  Source : https://www.cnps.cm" in texte
