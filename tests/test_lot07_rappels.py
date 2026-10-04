"""Lot 7 — rappels d'échéances : préparation à J-7 et J-2, remise dans la bulle, tâche du matin."""
import os
import subprocess
import sys
import uuid
from datetime import date
from pathlib import Path

import pytest
from celery.schedules import crontab
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from app.conversation import messages_fixes as mf
from app.conversation.models import CANAL_WEB, ENTRANT, SORTANT, Message
from app.conversation.moteur import traiter_message, trouver_ou_creer_conversation
from app.core.config import VERSION
from app.core.db import get_engine
from app.entreprises.models import Entreprise
from app.main import app
from app.rappels import livraison, preparation, preparer
from app.rappels.canal import BULLE, choisir_canal
from app.rappels.models import A_ENVOYER, ENVOYE, EXPIRE, IGNORE, Rappel
from app.rappels.preparation import date_prevue, jour_ouvre, preparer_entreprise, preparer_rappels
from app.regles.chargement import charger_fichier
from app.regles.models import Regle
from app.worker import celery_app, tache_preparer_rappels
from tests.test_lot02_bulle_web import essai  # noqa: F401 (fixture)

FICHIER_CM = Path(__file__).resolve().parent.parent / "app/regles/donnees/regles_cm.json"
TVA = "TVA_DECLARATION_MENSUELLE"
TITRE_TVA = "Déclaration et paiement mensuels de la TVA"


def entreprise(session, **profil) -> Entreprise:
    valeurs = {"regime_declare": "reel", "assujetti_tva_declare": True, "nombre_salaries": 0, **profil}
    e = Entreprise(juridiction_code="CM", niu="R" + uuid.uuid4().hex[:12].upper(), raison_sociale="Ets Rappel", **valeurs)
    session.add(e)
    session.flush()
    return e


def rappels_de(session, e) -> list[Rappel]:
    return list(session.scalars(select(Rappel).where(Rappel.entreprise_id == e.id).order_by(Rappel.id)))


@pytest.fixture
def regles(session):
    charger_fichier(session, FICHIER_CM)


@pytest.fixture
def jour_de_remise(monkeypatch):
    """Fixe la date du jour vue au moment de la remise dans la bulle."""
    def fixer(jour):
        monkeypatch.setattr(livraison, "aujourd_hui", lambda fuseau: jour)
    return fixer


def client_de(session, e) -> str:
    identifiant = "rappel-" + uuid.uuid4().hex
    trouver_ou_creer_conversation(session, CANAL_WEB, identifiant).entreprise_id = e.id
    session.flush()
    return identifiant


# --- Jours ouvrés et date d'envoi --------------------------------------------------------------

@pytest.mark.parametrize(
    "jour, attendu",
    [
        (date(2026, 10, 15), True),   # jeudi
        (date(2026, 10, 17), False),  # samedi
        (date(2026, 10, 18), False),  # dimanche
        (date(2026, 5, 20), False),   # Fête nationale, un mercredi
        (date(2026, 5, 19), True),
    ],
)
def test_jour_ouvre(jour, attendu):
    assert jour_ouvre(jour) is attendu


@pytest.mark.parametrize(
    "date_limite, palier, attendu",
    [
        (date(2026, 10, 15), 7, date(2026, 10, 8)),
        (date(2026, 10, 15), 2, date(2026, 10, 13)),
        # Échéance un dimanche : J-2 tombe le vendredi, dernier jour ouvré.
        (date(2026, 11, 15), 2, date(2026, 11, 13)),
        (date(2026, 11, 15), 7, date(2026, 11, 8)),
        # Échéance un samedi : J-2 (jeudi) est déjà avant le dernier jour ouvré.
        (date(2026, 8, 15), 2, date(2026, 8, 13)),
        # Lundi 11 février 2030, Fête de la Jeunesse : J-2 serait un samedi → vendredi 8.
        (date(2030, 2, 11), 2, date(2030, 2, 8)),
        # Lundi 1er janvier 2029 : J-2 → vendredi 29 décembre ; J-7 (25 décembre) reste plus tôt.
        (date(2029, 1, 1), 2, date(2028, 12, 29)),
        (date(2029, 1, 1), 7, date(2028, 12, 25)),
        # Jeudi 20 mai 2027, Fête nationale : J-2 (mardi) est avant le dernier jour ouvré (mercredi).
        (date(2027, 5, 20), 2, date(2027, 5, 18)),
    ],
)
def test_date_prevue(date_limite, palier, attendu):
    assert date_prevue(date_limite, palier) == attendu


def test_date_prevue_saute_plusieurs_jours_feries(monkeypatch):
    # Lundi 12 et mardi 13 octobre 2026 déclarés fériés : échéance mardi → dernier jour ouvré vendredi 9.
    feries = {date(2026, 10, 12): "Férié A", date(2026, 10, 13): "Férié B"}
    monkeypatch.setattr(preparation, "jour_ferie", lambda jour: feries.get(jour))
    assert date_prevue(date(2026, 10, 13), 2) == date(2026, 10, 9)


def test_le_canal_est_la_bulle(session):
    assert choisir_canal(entreprise(session)) == BULLE


# --- Préparation -------------------------------------------------------------------------------

def test_rien_avant_j_moins_7(session, regles):
    e = entreprise(session)
    assert preparer_entreprise(session, e, date(2026, 10, 7)) == []


def test_rappel_j_moins_7(session, regles):
    e = entreprise(session)
    [rappel] = preparer_entreprise(session, e, date(2026, 10, 8))
    tva_v2 = session.scalars(select(Regle).where(Regle.code == TVA, Regle.version == 2)).one()
    assert rappel.regle_id == tva_v2.id
    assert rappel.regle_code == TVA
    assert rappel.periode == "septembre 2026"
    assert rappel.date_limite == date(2026, 10, 15)
    assert rappel.palier == 7
    assert rappel.date_prevue == date(2026, 10, 8)
    assert rappel.canal == BULLE
    assert rappel.statut == A_ENVOYER
    assert rappel.conversation_id is None
    assert rappel.envoye_le is None


def test_jamais_deux_fois_le_meme_rappel(session, regles):
    e = entreprise(session)
    assert len(preparer_entreprise(session, e, date(2026, 10, 8))) == 1
    assert preparer_entreprise(session, e, date(2026, 10, 8)) == []
    assert preparer_entreprise(session, e, date(2026, 10, 10)) == []
    assert len(rappels_de(session, e)) == 1


def test_rappel_j_moins_2_remplace_le_j_moins_7_non_remis(session, regles):
    e = entreprise(session)
    preparer_entreprise(session, e, date(2026, 10, 8))
    [urgent] = preparer_entreprise(session, e, date(2026, 10, 13))
    assert urgent.palier == 2
    assert urgent.date_prevue == date(2026, 10, 13)
    assert [(r.palier, r.statut) for r in rappels_de(session, e)] == [(7, IGNORE), (2, A_ENVOYER)]
    assert preparer_entreprise(session, e, date(2026, 10, 14)) == []
    assert preparer_entreprise(session, e, date(2026, 10, 15)) == []


def test_un_j_moins_7_deja_remis_reste_remis(session, regles):
    e = entreprise(session)
    [premier] = preparer_entreprise(session, e, date(2026, 10, 8))
    premier.statut = ENVOYE
    preparer_entreprise(session, e, date(2026, 10, 13))
    assert [(r.palier, r.statut) for r in rappels_de(session, e)] == [(7, ENVOYE), (2, A_ENVOYER)]


def test_client_inscrit_tard_un_seul_rappel(session, regles):
    e = entreprise(session)
    [rappel] = preparer_entreprise(session, e, date(2026, 10, 14))
    assert rappel.palier == 2
    assert len(rappels_de(session, e)) == 1


def test_echeance_suivante_apres_la_date_limite(session, regles):
    e = entreprise(session)
    preparer_entreprise(session, e, date(2026, 10, 13))
    assert preparer_entreprise(session, e, date(2026, 10, 16)) == []
    # Les rappels d'octobre n'empêchent pas ceux de novembre.
    [rappel] = preparer_entreprise(session, e, date(2026, 11, 8))
    assert rappel.date_limite == date(2026, 11, 15)
    assert rappel.periode == "octobre 2026"
    assert rappel.palier == 7


def test_pas_de_j_moins_7_apres_un_j_moins_2(session, regles):
    """Commande lancée à la main avec une date passée : pas de rappel moins urgent après coup."""
    e = entreprise(session)
    preparer_entreprise(session, e, date(2026, 10, 13))
    assert preparer_entreprise(session, e, date(2026, 10, 8)) == []
    assert [r.palier for r in rappels_de(session, e)] == [2]


@pytest.mark.parametrize(
    "profil",
    [
        {"assujetti_tva_declare": None},  # incertaine : pas de rappel
        {"assujetti_tva_declare": False},  # ne s'applique pas
        {"regime_declare": "liberatoire", "assujetti_tva_declare": False, "nombre_salaries": 3},  # sans date
    ],
)
def test_pas_de_rappel_sans_obligation_datee_et_certaine(session, regles, profil):
    e = entreprise(session, **profil)
    assert preparer_entreprise(session, e, date(2026, 10, 13)) == []


def test_pas_de_rappel_pour_une_regle_retiree(session, regles):
    session.execute(Regle.__table__.update().where(Regle.code == TVA).values(statut="retiree"))
    assert preparer_entreprise(session, entreprise(session), date(2026, 10, 13)) == []


def test_pas_de_rappel_pour_une_alerte_datee(session):
    regle = Regle(
        juridiction_code="CM", code="ALERTE_DATEE_" + uuid.uuid4().hex[:6].upper(), version=1, type="alerte",
        impot="Test", titre="Alerte", description="Alerte de test.",
        condition={"champ": "regime_declare", "op": "egal", "valeur": "reel"}, periodicite="mensuelle",
        echeance_calcul={"type": "jour_du_mois_suivant", "jour": 15}, applicable_du=date(2026, 1, 1),
        statut="a_valider", ordre=1,
    )
    session.add(regle)
    session.flush()
    e = entreprise(session, assujetti_tva_declare=False)
    assert preparer_entreprise(session, e, date(2026, 10, 13)) == []


def test_preparer_toutes_les_entreprises(session, regles):
    a, b = entreprise(session), entreprise(session)
    sans_tva = entreprise(session, assujetti_tva_declare=False)
    assert preparer_rappels(session, date(2026, 10, 8)) >= 2
    assert len(rappels_de(session, a)) == len(rappels_de(session, b)) == 1
    assert rappels_de(session, sans_tva) == []


def test_preparer_au_jour_de_la_juridiction(session, regles, monkeypatch):
    vus = []
    monkeypatch.setattr(preparation, "aujourd_hui", lambda fuseau: vus.append(fuseau) or date(2026, 10, 8))
    e = entreprise(session)
    preparer_rappels(session)
    assert vus == ["Africa/Douala"]
    assert rappels_de(session, e)[0].palier == 7


def test_juridiction_inactive_ignoree(session, regles):
    from app.referentiel.models import Juridiction

    session.get(Juridiction, "CM").active = False
    session.flush()
    e = entreprise(session)
    assert preparer_rappels(session, date(2026, 10, 8)) == 0
    assert rappels_de(session, e) == []


# --- Remise dans la bulle ----------------------------------------------------------------------

def texte_attendu(date_texte, delai, *suite):
    return "\n".join([
        f"Rappel : « {TITRE_TVA} » — septembre 2026.",
        f"Au plus tard le {date_texte} ({delai}).",
        *suite,
    ])


def test_rappel_remis_avant_la_reponse(session, regles, jour_de_remise):
    e = entreprise(session)
    identifiant = client_de(session, e)
    preparer_entreprise(session, e, date(2026, 10, 8))
    jour_de_remise(date(2026, 10, 8))

    reponse = traiter_message(session, CANAL_WEB, identifiant, "bonjour")
    assert reponse.texte == mf.ACCUEIL
    assert reponse.rappels == [
        texte_attendu("jeudi 15 octobre 2026", "dans 7 jours", mf.OBLIGATIONS_AVERTISSEMENT)
    ]
    conversation = trouver_ou_creer_conversation(session, CANAL_WEB, identifiant)
    messages = list(session.scalars(
        select(Message).where(Message.conversation_id == conversation.id).order_by(Message.id)
    ))
    assert [(m.sens, m.texte) for m in messages] == [
        (ENTRANT, "bonjour"), (SORTANT, reponse.rappels[0]), (SORTANT, mf.ACCUEIL),
    ]
    [rappel] = rappels_de(session, e)
    assert rappel.statut == ENVOYE
    assert rappel.conversation_id == conversation.id
    assert rappel.envoye_le is not None
    # Remis une seule fois.
    assert traiter_message(session, CANAL_WEB, identifiant, "2").rappels == []


def test_rappel_d_une_echeance_un_dimanche(session, regles, jour_de_remise):
    e = entreprise(session)
    identifiant = client_de(session, e)
    preparer_entreprise(session, e, date(2026, 11, 13))
    jour_de_remise(date(2026, 11, 13))
    [texte] = traiter_message(session, CANAL_WEB, identifiant, "bonjour").rappels
    assert texte == "\n".join([
        f"Rappel : « {TITRE_TVA} » — octobre 2026.",
        "Au plus tard le dimanche 15 novembre 2026 (dans 2 jours).",
        mf.ECHEANCES_WEEK_END.format(jour="dimanche"),
        mf.OBLIGATIONS_AVERTISSEMENT,
    ])


def test_rappel_d_une_regle_publiee_sans_avertissement(session, regles, jour_de_remise):
    session.execute(Regle.__table__.update().values(statut="publiee"))
    e = entreprise(session)
    identifiant = client_de(session, e)
    preparer_entreprise(session, e, date(2026, 10, 13))
    jour_de_remise(date(2026, 10, 15))
    assert traiter_message(session, CANAL_WEB, identifiant, "bonjour").rappels == [
        texte_attendu("jeudi 15 octobre 2026", "aujourd'hui")
    ]


def test_rappel_expire_non_remis(session, regles, jour_de_remise):
    e = entreprise(session)
    identifiant = client_de(session, e)
    preparer_entreprise(session, e, date(2026, 10, 13))
    jour_de_remise(date(2026, 10, 16))
    assert traiter_message(session, CANAL_WEB, identifiant, "bonjour").rappels == []
    assert [r.statut for r in rappels_de(session, e)] == [EXPIRE]


def test_rappels_tries_par_date(session, jour_de_remise):
    def regle(code, jour):
        session.add(Regle(
            juridiction_code="CM", code=code, version=1, type="obligation", impot="Test", titre=code,
            description="Test.", condition={"champ": "regime_declare", "op": "egal", "valeur": "reel"},
            periodicite="mensuelle", echeance_calcul={"type": "jour_du_mois_suivant", "jour": jour},
            applicable_du=date(2026, 1, 1), statut="publiee", ordre=1,
        ))
    suffixe = uuid.uuid4().hex[:6].upper()
    regle("TARDIVE_" + suffixe, 20)
    regle("PROCHE_" + suffixe, 14)
    session.flush()
    e = entreprise(session, assujetti_tva_declare=False)
    identifiant = client_de(session, e)
    # Le 13 octobre : PROCHE (14 octobre) est à J-1 et TARDIVE (20 octobre) à J-7.
    assert len(preparer_entreprise(session, e, date(2026, 10, 13))) == 2
    jour_de_remise(date(2026, 10, 13))
    textes = traiter_message(session, CANAL_WEB, identifiant, "bonjour").rappels
    assert [t.split("»")[0] for t in textes] == [f"Rappel : « PROCHE_{suffixe} ", f"Rappel : « TARDIVE_{suffixe} "]


def test_un_rappel_n_est_remis_qu_a_une_conversation(session, regles, jour_de_remise):
    e = entreprise(session)
    premiere, seconde = client_de(session, e), client_de(session, e)
    preparer_entreprise(session, e, date(2026, 10, 8))
    jour_de_remise(date(2026, 10, 8))
    assert len(traiter_message(session, CANAL_WEB, premiere, "bonjour").rappels) == 1
    assert traiter_message(session, CANAL_WEB, seconde, "bonjour").rappels == []


def test_chaque_entreprise_ne_recoit_que_ses_rappels(session, regles, jour_de_remise):
    a, b = entreprise(session), entreprise(session)
    client_a, client_b = client_de(session, a), client_de(session, b)
    preparer_entreprise(session, a, date(2026, 10, 8))
    jour_de_remise(date(2026, 10, 8))
    assert traiter_message(session, CANAL_WEB, client_b, "bonjour").rappels == []
    assert len(traiter_message(session, CANAL_WEB, client_a, "bonjour").rappels) == 1


def test_pas_de_rappel_sans_profil(session):
    assert traiter_message(session, CANAL_WEB, "sans-" + uuid.uuid4().hex, "bonjour").rappels == []


def test_rappel_remis_pendant_une_modification(session, regles, jour_de_remise):
    e = entreprise(session)
    identifiant = client_de(session, e)
    traiter_message(session, CANAL_WEB, identifiant, "modifier")
    preparer_entreprise(session, e, date(2026, 10, 8))
    jour_de_remise(date(2026, 10, 8))
    reponse = traiter_message(session, CANAL_WEB, identifiant, "4")
    assert len(reponse.rappels) == 1
    assert reponse.texte == mf.Q_CHIFFRE_AFFAIRES


def test_la_bulle_renvoie_les_rappels(essai):
    client = TestClient(app)
    client.get("/essai")
    corps = client.post("/essai/messages", json={"texte": "bonjour"}).json()
    assert corps["rappels"] == []
    assert corps["reponse"] == mf.ACCUEIL


def test_le_script_affiche_les_rappels_avant_la_reponse():
    script = (Path(__file__).resolve().parent.parent / "app/static/js/essai.js").read_text()
    assert script.index('ajouterBulle(r, "sortant", "jeff-rappel")') < script.index('ajouterBulle(donnees.reponse, "sortant")')


# --- Tâche du matin et commande ----------------------------------------------------------------

def test_tache_planifiee_a_7h30_heure_de_douala():
    assert celery_app.conf.timezone == "Africa/Douala"
    entree = celery_app.conf.beat_schedule["preparer-rappels"]
    assert entree["task"] == "jeff.preparer_rappels"
    assert entree["schedule"] == crontab(hour=7, minute=30)
    assert "jeff.preparer_rappels" in celery_app.tasks


class SessionFactice:
    def __init__(self):
        self.actions = []

    def commit(self):
        self.actions.append("commit")

    def rollback(self):
        self.actions.append("rollback")

    def close(self):
        self.actions.append("close")


@pytest.fixture
def session_factice(monkeypatch):
    factice = SessionFactice()
    monkeypatch.setattr("app.core.db.get_session", lambda: factice)
    monkeypatch.setattr(preparer, "get_session", lambda: factice)
    return factice


def test_la_tache_valide_le_travail(monkeypatch, session_factice):
    monkeypatch.setattr(preparation, "preparer_rappels", lambda s, jour=None: 3)
    assert tache_preparer_rappels() == 3
    assert session_factice.actions == ["commit", "close"]


def test_la_tache_annule_en_cas_d_erreur(monkeypatch, session_factice):
    def echec(s, jour=None):
        raise RuntimeError("panne")
    monkeypatch.setattr(preparation, "preparer_rappels", echec)
    with pytest.raises(RuntimeError):
        tache_preparer_rappels()
    assert session_factice.actions == ["rollback", "close"]


def test_commande_preparer(monkeypatch, session_factice, capsys):
    jours = []
    monkeypatch.setattr(preparer, "preparer_rappels", lambda s, jour=None: jours.append(jour) or 2)
    assert preparer.main(["2026-10-08"]) == 0
    assert preparer.main([]) == 0
    assert jours == [date(2026, 10, 8), None]
    assert session_factice.actions == ["commit", "close", "commit", "close"]
    assert "Rappels préparés : 2" in capsys.readouterr().out


RESOUDRE_CLES = "from app.core.db import Base; [fk.column for t in Base.metadata.tables.values() for fk in t.foreign_keys]"


def lancer_python(code: str):
    racine = Path(__file__).resolve().parent.parent
    return subprocess.run([sys.executable, "-c", code], cwd=racine, env=os.environ.copy(), capture_output=True, text=True)


def test_la_commande_connait_toutes_les_tables():
    """Le bug du lot 1 : sans tous les modèles chargés, l'écriture d'un rappel échoue (clé étrangère)."""
    resultat = lancer_python("import app.rappels.preparer; " + RESOUDRE_CLES)
    assert resultat.returncode == 0, resultat.stderr


def test_la_tache_connait_toutes_les_tables():
    resultat = lancer_python(
        "import app.worker as w, app.rappels.preparation as p, app.core.db as db\n"
        "class S:\n    def commit(self): pass\n    def rollback(self): pass\n    def close(self): pass\n"
        "def verifier(session, jour=None):\n    " + RESOUDRE_CLES.replace("; ", "\n    ") + "\n    return 0\n"
        "p.preparer_rappels = verifier\ndb.get_session = lambda: S()\nw.tache_preparer_rappels()\n"
    )
    assert resultat.returncode == 0, resultat.stderr


def test_commande_preparer_date_invalide(capsys):
    assert preparer.main(["08/10/2026"]) == 1
    assert "AAAA-MM-JJ" in capsys.readouterr().out


# --- Base de données et version --------------------------------------------------------------

def test_table_des_rappels():
    inspecteur = inspect(get_engine())
    colonnes = {c["name"]: c for c in inspecteur.get_columns("rappels")}
    assert set(colonnes) == {
        "id", "entreprise_id", "regle_id", "regle_code", "periode", "date_limite", "palier", "date_prevue",
        "canal", "statut", "conversation_id", "cree_le", "envoye_le",
    }
    assert colonnes["conversation_id"]["nullable"] is True
    assert colonnes["envoye_le"]["nullable"] is True
    assert colonnes["statut"]["nullable"] is False
    uniques = {u["name"]: u["column_names"] for u in inspecteur.get_unique_constraints("rappels")}
    assert uniques == {"uq_rappels_entreprise_regle_date_palier": ["entreprise_id", "regle_code", "date_limite", "palier"]}
    assert {fk["referred_table"] for fk in inspecteur.get_foreign_keys("rappels")} == {"entreprises", "regles", "conversations"}


def test_contrainte_d_unicite(session, regles):
    e = entreprise(session)
    [rappel] = preparer_entreprise(session, e, date(2026, 10, 8))
    session.add(Rappel(
        entreprise_id=e.id, regle_id=rappel.regle_id, regle_code=TVA, periode="x", date_limite=rappel.date_limite,
        palier=7, date_prevue=rappel.date_prevue, canal=BULLE,
    ))
    with pytest.raises(IntegrityError):
        session.flush()


def test_version():
    assert VERSION == "0.7.0"
