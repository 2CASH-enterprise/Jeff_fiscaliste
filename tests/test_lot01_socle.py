"""Lot 1 — socle : page /sante, juridiction Cameroun, entreprises, NIU."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core import sante as module_sante
from app.core.config import Settings
from app.entreprises.models import Entreprise
from app.entreprises.niu import LONGUEUR_MAX, NiuInvalide, normaliser_niu
from app.main import app
from app.referentiel.models import Juridiction

client = TestClient(app)


# --- Page /sante -------------------------------------------------------------

def test_sante_repond_ok_quand_tout_fonctionne():
    reponse = client.get("/sante")
    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["statut"] == "ok"
    assert corps["base"] == "ok"
    assert corps["redis"] == "ok"
    assert corps["version"]


def test_sante_repond_503_si_la_base_ne_repond_pas(monkeypatch):
    monkeypatch.setattr(module_sante, "verifier_base", lambda: module_sante.INDISPONIBLE)
    reponse = client.get("/sante")
    assert reponse.status_code == 503
    assert reponse.json()["statut"] == "indisponible"
    assert reponse.json()["base"] == "indisponible"


def test_sante_repond_503_si_redis_ne_repond_pas(monkeypatch):
    monkeypatch.setattr(module_sante, "verifier_redis", lambda: module_sante.INDISPONIBLE)
    reponse = client.get("/sante")
    assert reponse.status_code == 503
    assert reponse.json()["redis"] == "indisponible"


def test_verifier_base_signale_une_base_injoignable(monkeypatch):
    def moteur_en_panne():
        raise RuntimeError("base injoignable")

    monkeypatch.setattr(module_sante, "get_engine", moteur_en_panne)
    assert module_sante.verifier_base() == module_sante.INDISPONIBLE


def test_verifier_redis_signale_un_redis_injoignable(monkeypatch):
    monkeypatch.setattr(
        module_sante, "get_settings", lambda: Settings(redis_url="redis://127.0.0.1:1/0")
    )
    assert module_sante.verifier_redis() == module_sante.INDISPONIBLE


# --- Configuration ----------------------------------------------------------

def test_debug_coupe_en_production():
    assert Settings(environnement="production").debug is False
    assert Settings(environnement="developpement").debug is True


# --- Juridictions -----------------------------------------------------------

def test_migration_cree_le_cameroun_actif(session):
    cameroun = session.get(Juridiction, "CM")
    assert cameroun is not None
    assert cameroun.nom == "Cameroun"
    assert cameroun.devise == "XAF"
    assert cameroun.fuseau_horaire == "Africa/Douala"
    assert cameroun.active is True


# --- Entreprises -------------------------------------------------------------

def test_une_entreprise_est_rattachee_a_une_juridiction(session):
    session.add(Entreprise(juridiction_code="CM", niu="M012345678901A", raison_sociale="Test SARL"))
    session.flush()
    entreprise = session.scalars(select(Entreprise).where(Entreprise.niu == "M012345678901A")).one()
    assert entreprise.juridiction_code == "CM"
    assert entreprise.distributeur_id is None
    assert entreprise.cree_le is not None


def test_niu_unique_dans_une_meme_juridiction(session):
    session.add(Entreprise(juridiction_code="CM", niu="DOUBLON1", raison_sociale="A"))
    session.flush()
    session.add(Entreprise(juridiction_code="CM", niu="DOUBLON1", raison_sociale="B"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_meme_niu_autorise_dans_deux_juridictions(session):
    session.add(
        Juridiction(code="SN", nom="Sénégal", devise="XOF", langue="fr", fuseau_horaire="Africa/Dakar", active=False)
    )
    session.flush()
    session.add(Entreprise(juridiction_code="CM", niu="COMMUN1", raison_sociale="A"))
    session.add(Entreprise(juridiction_code="SN", niu="COMMUN1", raison_sociale="B"))
    session.flush()


def test_entreprise_refusee_si_juridiction_inconnue(session):
    session.add(Entreprise(juridiction_code="ZZ", niu="X1", raison_sociale="Inconnue"))
    with pytest.raises(IntegrityError):
        session.flush()


# --- NIU ---------------------------------------------------------------------

@pytest.mark.parametrize(
    "saisie, attendu",
    [
        ("m012345678901a", "M012345678901A"),
        (" M0123 4567-8901A ", "M012345678901A"),
        ("P0" * 10, "P0" * 10),
    ],
)
def test_normaliser_niu(saisie, attendu):
    assert normaliser_niu(saisie) == attendu


@pytest.mark.parametrize("saisie", [None, "", "   ", " - "])
def test_niu_vide_signale_comme_obligatoire(saisie):
    with pytest.raises(NiuInvalide, match="obligatoire"):
        normaliser_niu(saisie)


@pytest.mark.parametrize("saisie", [None, "", "   ", " - ", "A" * (LONGUEUR_MAX + 1), "M0123/45", "NIU_1"])
def test_normaliser_niu_refuse_les_valeurs_invalides(saisie):
    with pytest.raises(NiuInvalide):
        normaliser_niu(saisie)
