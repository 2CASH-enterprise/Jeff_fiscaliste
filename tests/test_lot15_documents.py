"""Lot 15 — coffre fiscal : dépôt, classement, consultation et suppression des documents."""
import hashlib
import io
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from app.core.config import VERSION, get_settings
from app.core.db import get_engine
from app.documents import stockage
from app.documents.models import FORMATS, TYPES, Document
from app.entreprises.models import COFFRE, ModificationEntreprise
from app.espace import donnees
from app.espace import textes as tx
from app.espace.models import SessionEspace
from tests.test_lot12_espace import adresse_unique, connecter, creer, espace, texte_visible  # noqa: F401

RACINE = Path(__file__).resolve().parent.parent
PDF = b"%PDF-1.4\n%contenu de test\n%%EOF\n"
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"x" * 100
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
OCTOBRE = date(2026, 10, 1)
JOUR = date(2026, 10, 5)


@pytest.fixture
def dossier(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCUMENTS_DOSSIER", str(tmp_path / "documents"))
    get_settings.cache_clear()
    yield tmp_path / "documents"
    get_settings.cache_clear()


@pytest.fixture
def jour_fixe(monkeypatch):
    monkeypatch.setattr(donnees, "ce_jour", lambda session, entreprise: JOUR)


def deposer(session, e, contenu=PDF, nom="facture.pdf", type_document="facture", mois=OCTOBRE, session_espace_id=None):
    return stockage.deposer(session, e, io.BytesIO(contenu), nom, type_document, mois, session_espace_id)


def traces(session, e) -> list[ModificationEntreprise]:
    return list(session.scalars(
        select(ModificationEntreprise).where(ModificationEntreprise.entreprise_id == e.id).order_by(ModificationEntreprise.id)
    ))


def connecte(session, nom="Ets Documents"):
    adresse = adresse_unique()
    e = creer(session, nom, adresse)
    return e, connecter(session, adresse), adresse


def envoyer(client, contenu=PDF, nom="facture.pdf", type_document="facture", mois="2026-10", type_mime="application/pdf"):
    return client.post(
        "/espace/documents", data={"type_document": type_document, "mois": mois},
        files={"fichier": (nom, contenu, type_mime)}, follow_redirects=False,
    )


def info(reponse) -> str:
    return reponse.headers["location"].split("?info=")[1] if "?info=" in reponse.headers["location"] else ""


# --- Décisions et formats -----------------------------------------------------------------------

def test_decisions_du_porteur():
    assert stockage.TAILLE_MAX == 10 * 1024 * 1024 and stockage.QUOTA == 500 * 1024 * 1024
    assert FORMATS == ("pdf", "jpeg", "png")
    assert TYPES == ("facture", "paie", "declaration", "attestation", "autre")
    assert [c for c, _ in tx.TYPES_DOCUMENT] == list(TYPES)


@pytest.mark.parametrize("debut,attendu", [
    (PDF, "pdf"), (JPEG, "jpeg"), (PNG, "png"), (b"PK\x03\x04docx", None), (b"<html>", None),
    (b"%PDF", None), (b"\x89PNG\r\n\x1a", None), (b"\xff\xd8", None), (b"", None),
])
def test_format_reconnu_au_contenu(debut, attendu):
    assert stockage.detecter_format(debut) == attendu


@pytest.mark.parametrize("nom,attendu", [
    ("facture.pdf", "facture.pdf"),
    ("../../etc/passwd.pdf", "passwd.pdf"),
    ("C:\\Users\\Moi\\scan.jpg", "scan.jpg"),
    ("  rapport \n final\t.pdf  ", "rapport final.pdf"),
    ("", "document.pdf"),
    (None, "document.pdf"),
    ("...", "document.pdf"),
    ("re\u0301sume\u0301.pdf", "résumé.pdf"),
    ("a" * 200 + ".pdf", "a" * 146 + ".pdf"),
    ("b" * 200, "b" * 150),
    ("c" * 200 + ".extensiontroplongue", ("c" * 200 + ".extensiontroplongue")[:150]),
])
def test_nom_nettoye(nom, attendu):
    assert stockage.nettoyer_nom(nom, "pdf") == attendu
    assert len(stockage.nettoyer_nom(nom, "pdf")) <= stockage.NOM_MAX == 150


def test_nom_par_defaut_selon_le_format():
    assert stockage.nettoyer_nom("", "jpeg") == "document.jpg" and stockage.nettoyer_nom("", "png") == "document.png"


# --- Dépôt --------------------------------------------------------------------------------------

def test_depot(session, dossier):
    e = creer(session)
    document = deposer(session, e, nom="Facture Octobre.pdf", session_espace_id=None)
    assert (document.type_document, document.mois, document.nom, document.format) == ("facture", OCTOBRE, "Facture Octobre.pdf", "pdf")
    assert document.taille == len(PDF) and document.empreinte == hashlib.sha256(PDF).hexdigest()
    fichier = stockage.chemin(document)
    assert fichier == dossier / str(e.id) / f"{document.id}.pdf" and fichier.read_bytes() == PDF
    assert [p.name for p in fichier.parent.iterdir()] == [fichier.name]  # Aucun fichier temporaire restant.
    [trace] = traces(session, e)
    assert (trace.champ, trace.ancienne_valeur, trace.origine) == (stockage.DEPOSE, None, COFFRE)
    assert trace.nouvelle_valeur == {"nom": "Facture Octobre.pdf", "type": "facture", "mois": "2026-10"}


@pytest.mark.parametrize("contenu,extension", [(JPEG, "jpg"), (PNG, "png")])
def test_depot_photo(session, dossier, contenu, extension):
    document = deposer(session, creer(session), contenu=contenu, nom="photo")
    assert stockage.chemin(document).name == f"{document.id}.{extension}"


class LecteurLent:
    """Un flux qui ne rend que quelques octets à la fois : le format doit quand même être reconnu."""

    def __init__(self, contenu: bytes, pas: int = 2):
        self.flux, self.pas = io.BytesIO(contenu), pas

    def read(self, _taille=-1):
        return self.flux.read(self.pas)


def test_format_reconnu_sur_un_flux_lent(session, dossier):
    document = stockage.deposer(session, creer(session), LecteurLent(PNG), "lent.png", "autre", OCTOBRE, None)
    assert document.format == "png" and stockage.chemin(document).read_bytes() == PNG


def test_fichier_lu_par_blocs(session, dossier):
    gros = PDF + b"0" * (3 * stockage.BLOC)
    document = deposer(session, creer(session), contenu=gros)
    assert document.taille == len(gros) and stockage.chemin(document).read_bytes() == gros


@pytest.mark.parametrize("contenu,raison", [
    (b"", stockage.VIDE), (b"PK\x03\x04 un docx", stockage.FORMAT), (b"<script>alert(1)</script>", stockage.FORMAT),
])
def test_depot_refuse(session, dossier, contenu, raison):
    e = creer(session)
    with pytest.raises(stockage.DepotRefuse) as refus:
        deposer(session, e, contenu=contenu)
    assert refus.value.raison == raison
    assert session.scalars(select(Document).where(Document.entreprise_id == e.id)).all() == [] and traces(session, e) == []
    assert list((dossier / str(e.id)).iterdir()) == []


def test_dix_mo_au_plus(session, dossier):
    e = creer(session)
    juste = PDF + b"0" * (stockage.TAILLE_MAX - len(PDF))
    assert deposer(session, e, contenu=juste).taille == stockage.TAILLE_MAX
    with pytest.raises(stockage.DepotRefuse) as refus:
        deposer(session, e, contenu=juste + b"0")
    assert refus.value.raison == stockage.TAILLE
    assert len(list((dossier / str(e.id)).iterdir())) == 1


def test_quota_de_500_mo(session, dossier, monkeypatch):
    e, voisine = creer(session), creer(session, "Ets Voisine")
    deposer(session, e, contenu=PDF)
    monkeypatch.setattr(stockage, "QUOTA", 2 * len(PDF))
    assert stockage.utilise(session, e.id) == len(PDF)
    deposer(session, e, contenu=PDF)  # Exactement le quota.
    with pytest.raises(stockage.DepotRefuse) as refus:
        deposer(session, e, contenu=PDF)
    assert refus.value.raison == stockage.QUOTA_ATTEINT
    deposer(session, voisine, contenu=PDF)  # Le quota est par entreprise.
    assert stockage.utilise(session, creer(session, "Ets Vide").id) == 0


@pytest.mark.parametrize("type_document,mois", [("inconnu", OCTOBRE), ("facture", date(2026, 10, 2))])
def test_classement_invalide(session, dossier, type_document, mois):
    with pytest.raises(ValueError):
        deposer(session, creer(session), type_document=type_document, mois=mois)


# --- Classement et suppression ------------------------------------------------------------------

def test_reclasser(session, dossier):
    e = creer(session)
    document = deposer(session, e)
    assert stockage.reclasser(session, document, "facture", OCTOBRE, None) is False
    assert stockage.reclasser(session, document, "paie", date(2026, 9, 1), None) is True
    assert (document.type_document, document.mois) == ("paie", date(2026, 9, 1))
    trace = traces(session, e)[-1]
    assert trace.champ == stockage.RECLASSE and trace.origine == COFFRE
    assert (trace.ancienne_valeur["type"], trace.nouvelle_valeur["type"], trace.nouvelle_valeur["mois"]) == ("facture", "paie", "2026-09")
    assert len(traces(session, e)) == 2
    with pytest.raises(ValueError):
        stockage.reclasser(session, document, "rien", OCTOBRE, None)
    with pytest.raises(ValueError):
        stockage.reclasser(session, document, "paie", date(2026, 9, 3), None)


def test_supprimer(session, dossier):
    e = creer(session)
    document = deposer(session, e)
    fichier = stockage.chemin(document)
    stockage.supprimer(session, document, None)
    assert not fichier.exists() and session.get(Document, document.id) is None
    trace = traces(session, e)[-1]
    assert (trace.champ, trace.nouvelle_valeur, trace.origine) == (stockage.SUPPRIME, None, COFFRE)
    assert trace.ancienne_valeur == {"nom": "facture.pdf", "type": "facture", "mois": "2026-10"}


def test_supprimer_fichier_deja_absent(session, dossier):
    document = deposer(session, creer(session))
    stockage.chemin(document).unlink()
    stockage.supprimer(session, document, None)
    assert session.get(Document, document.id) is None


# --- Données de la page -------------------------------------------------------------------------

@pytest.mark.parametrize("octets,attendu", [
    (1, "1 Ko"), (1024, "1 Ko"), (1025, "2 Ko"), (1024 * 1024 - 1, "1024 Ko"), (1024 * 1024, "1,0 Mo"),
    (int(12.34 * 1024 * 1024), "12,3 Mo"), (500 * 1024 * 1024, "500,0 Mo"),
])
def test_taille_lisible(octets, attendu):
    assert donnees.taille_lisible(octets) == attendu


def test_mois_choisissables():
    mois = donnees.mois_choisissables(JOUR)
    assert len(mois) == 25 and mois[0] == ("2026-10", "octobre 2026") and mois[-1] == ("2024-10", "octobre 2024")
    assert donnees.lire_mois("2026-10", JOUR) == OCTOBRE and donnees.lire_mois("2024-10", JOUR) == date(2024, 10, 1)
    for invalide in ("2026-11", "2024-09", "2026-1", "", "x-y"):
        assert donnees.lire_mois(invalide, JOUR) is None


def test_liste_groupee_par_mois(session, dossier):
    e = creer(session)
    a = deposer(session, e, nom="a.pdf", mois=date(2026, 9, 1))
    b = deposer(session, e, nom="b.pdf", type_document="paie")
    c = deposer(session, e, contenu=PNG, nom="c.png", type_document="paie")
    session.execute(Document.__table__.update().where(Document.id == b.id).values(depose_le=datetime(2026, 10, 1, tzinfo=timezone.utc)))
    session.execute(Document.__table__.update().where(Document.id == c.id).values(depose_le=datetime(2026, 10, 2, 9, 5, tzinfo=timezone.utc)))
    session.expire_all()
    liste = donnees.documents(session, e, "", JOUR)
    assert [(g.cle, g.libelle, [d.nom for d in g.documents]) for g in liste.groupes] == [
        ("2026-10", "octobre 2026", ["c.png", "b.pdf"]), ("2026-09", "septembre 2026", ["a.pdf"]),
    ]
    ligne = liste.groupes[0].documents[0]
    assert (ligne.id, ligne.type_document, ligne.type_libelle, ligne.format) == (str(c.id), "paie", "Bulletins de paie", "png")
    assert ligne.taille == "1 Ko" and ligne.depose == "vendredi 2 octobre 2026 à 10 h 05" and ligne.mois_cle == "2026-10"
    assert liste.compteurs == {"facture": 1, "paie": 2, "declaration": 0, "attestation": 0, "autre": 0} and liste.total == 3
    assert liste.mois_defaut == "2026-10" and len(liste.mois_choisissables) == 25
    assert liste.quota == "500,0 Mo" and liste.utilise == "1 Ko" and liste.pourcentage == 0
    filtree = donnees.documents(session, e, "paie", JOUR)
    assert filtree.filtre == "paie" and [d.nom for g in filtree.groupes for d in g.documents] == ["c.png", "b.pdf"]
    assert donnees.documents(session, e, "n'importe", JOUR).filtre == ""
    assert a.id


def test_liste_vide_et_jauge(session, dossier, monkeypatch):
    e = creer(session)
    vide = donnees.documents(session, e, "", JOUR)
    assert vide.groupes == [] and vide.utilise == "0 Mo" and vide.total == 0
    deposer(session, e)
    monkeypatch.setattr(stockage, "QUOTA", len(PDF) * 2)
    assert donnees.documents(session, e, "", JOUR).pourcentage == 50


def test_jour_de_la_juridiction(session, dossier, monkeypatch):
    monkeypatch.setattr(donnees, "aujourd_hui", lambda fuseau: date(2027, 1, 31) if fuseau == "Africa/Douala" else None)
    assert donnees.documents(session, creer(session)).mois_defaut == "2027-01"


def test_liste_d_une_seule_entreprise(session, dossier):
    e, autre = creer(session), creer(session, "Ets Autre")
    deposer(session, autre)
    assert donnees.documents(session, e, "", JOUR).total == 0


# --- Historique ---------------------------------------------------------------------------------

def test_historique_des_documents(session, dossier):
    e = creer(session)
    document = deposer(session, e, nom="releve.pdf")
    stockage.reclasser(session, document, "declaration", date(2026, 9, 1), None)
    stockage.supprimer(session, document, None)
    lignes = [(c.libelle, c.avant, c.apres, c.origine) for c in donnees.historique(session, e)]
    assert lignes == [
        ("Document supprimé", "releve.pdf (Déclarations, septembre 2026)", tx.AUCUN, tx.ORIGINE_COFFRE),
        ("Classement d'un document", "releve.pdf (Factures, octobre 2026)", "releve.pdf (Déclarations, septembre 2026)", tx.ORIGINE_COFFRE),
        ("Document déposé", tx.AUCUN, "releve.pdf (Factures, octobre 2026)", tx.ORIGINE_COFFRE),
    ]


def test_type_inconnu_dans_l_historique():
    assert donnees.valeur_historique("document_depose", {"nom": "x", "type": "ancien", "mois": "2026-01"}) == "x (ancien, janvier 2026)"


# --- Pages --------------------------------------------------------------------------------------

def test_page_documents_vide(espace, session, dossier, jour_fixe):
    e, client, _ = connecte(session)
    html = client.get("/espace/documents").text
    texte = texte_visible(html)
    assert tx.DEPOSER_TITRE in texte and tx.DEPOSER_AIDE in texte and tx.AUCUN_DOCUMENT in texte
    assert 'enctype="multipart/form-data"' in html and 'action="http://testserver/espace/documents"' in html
    assert 'accept="application/pdf,image/jpeg,image/png,.pdf,.jpg,.jpeg,.png"' in html
    assert '<option value="autre" selected>' in html and '<option value="2026-10" selected>' in html
    assert html.count("<option value=") == 5 + 25
    assert tx.ESPACE_UTILISE.format(utilise="0 Mo", quota="500,0 Mo") in texte
    assert f"{tx.TOUS_LES_DOCUMENTS} 0" in texte and "Factures 0" in texte


def test_depot_depuis_le_coffre(espace, session, dossier, jour_fixe):
    e, client, adresse = connecte(session)
    reponse = envoyer(client, nom="Facture Octobre.pdf")
    assert reponse.status_code == 303 and info(reponse) == "depose"
    [document] = session.scalars(select(Document).where(Document.entreprise_id == e.id)).all()
    ouverte = session.scalars(select(SessionEspace).where(SessionEspace.email == adresse)).one()
    assert document.session_espace_id == ouverte.id and traces(session, e)[0].session_espace_id == ouverte.id
    html = client.get("/espace/documents?info=depose").text
    texte = texte_visible(html)
    assert tx.DOCUMENT_DEPOSE in texte and "Facture Octobre.pdf" in texte and "Factures · PDF · 1 Ko" in texte
    assert "octobre 2026" in texte and f"{tx.TOUS_LES_DOCUMENTS} 1" in texte and "Factures 1" in texte
    assert f'href="http://testserver/espace/documents/{document.id}/fichier"' in html
    assert f'href="http://testserver/espace/documents/{document.id}/fichier?telecharger=1"' in html
    assert f'action="http://testserver/espace/documents/{document.id}/classement"' in html
    assert f'action="http://testserver/espace/documents/{document.id}/supprimer"' in html
    assert tx.SUPPRIMER_CONFIRMATION in texte and tx.SUPPRIMER_CONFIRMER in texte


@pytest.mark.parametrize("contenu,attendu", [(b"", "vide"), (b"MZ executable", "format")])
def test_depot_refuse_depuis_le_coffre(espace, session, dossier, jour_fixe, contenu, attendu):
    e, client, _ = connecte(session)
    reponse = envoyer(client, contenu=contenu)
    assert info(reponse) == attendu
    assert tx.REFUS_DOCUMENT[attendu] in texte_visible(client.get(f"/espace/documents?info={attendu}").text)
    assert session.scalars(select(Document).where(Document.entreprise_id == e.id)).all() == []


def test_depot_trop_lourd_depuis_le_coffre(espace, session, dossier, jour_fixe, monkeypatch):
    monkeypatch.setattr(stockage, "TAILLE_MAX", 10)
    _, client, _ = connecte(session)
    assert info(envoyer(client)) == "taille"


def test_depot_quota_depuis_le_coffre(espace, session, dossier, jour_fixe, monkeypatch):
    monkeypatch.setattr(stockage, "QUOTA", 10)
    _, client, _ = connecte(session)
    assert info(envoyer(client)) == "quota"


def test_depot_sans_fichier(espace, session, dossier, jour_fixe):
    _, client, _ = connecte(session)
    reponse = client.post("/espace/documents", data={"type_document": "facture", "mois": "2026-10"}, follow_redirects=False)
    assert info(reponse) == "vide"


@pytest.mark.parametrize("type_document,mois", [("inconnu", "2026-10"), ("facture", "2026-11"), ("facture", ""), ("", "2026-10")])
def test_depot_mal_classe(espace, session, dossier, jour_fixe, type_document, mois):
    e, client, _ = connecte(session)
    assert info(envoyer(client, type_document=type_document, mois=mois)) == "impossible"
    assert session.scalars(select(Document).where(Document.entreprise_id == e.id)).all() == []


def test_le_navigateur_ne_decide_pas_du_format(espace, session, dossier, jour_fixe):
    e, client, _ = connecte(session)
    envoyer(client, contenu=PNG, nom="facture.pdf", type_mime="application/pdf")
    [document] = session.scalars(select(Document).where(Document.entreprise_id == e.id)).all()
    assert document.format == "png" and stockage.chemin(document).suffix == ".png"


@pytest.mark.parametrize("format_,contenu,type_mime", [("pdf", PDF, "application/pdf"), ("png", PNG, "image/png"), ("jpeg", JPEG, "image/jpeg")])
def test_ouvrir_et_telecharger(espace, session, dossier, jour_fixe, format_, contenu, type_mime):
    e, client, _ = connecte(session)
    document = deposer(session, e, contenu=contenu, nom=f"Relevé {format_}")
    reponse = client.get(f"/espace/documents/{document.id}/fichier")
    assert reponse.status_code == 200 and reponse.content == contenu
    assert reponse.headers["content-type"].startswith(type_mime)
    assert reponse.headers["content-disposition"].startswith("inline;") and "Relev%C3%A9" in reponse.headers["content-disposition"]
    assert reponse.headers["x-content-type-options"] == "nosniff" and reponse.headers["cache-control"] == "private, no-store"
    assert ("content-security-policy" in reponse.headers) == (format_ != "pdf")
    if format_ != "pdf":
        assert reponse.headers["content-security-policy"] == "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"
    telecharge = client.get(f"/espace/documents/{document.id}/fichier?telecharger=1")
    assert telecharge.headers["content-disposition"].startswith("attachment;")


@pytest.mark.parametrize("cas", ["autre_entreprise", "inconnu", "pas_un_uuid", "fichier_absent"])
def test_fichier_introuvable(espace, session, dossier, jour_fixe, cas):
    e, client, _ = connecte(session)
    autre = creer(session, "Ets Étrangère")
    if cas == "autre_entreprise":
        identifiant = deposer(session, autre).id
    elif cas == "fichier_absent":
        document = deposer(session, e)
        stockage.chemin(document).unlink()
        identifiant = document.id
    else:
        identifiant = uuid.uuid4() if cas == "inconnu" else "abc"
    assert client.get(f"/espace/documents/{identifiant}/fichier").status_code == 404


def test_fichier_sans_session(espace, session, dossier):
    from fastapi.testclient import TestClient

    from app.main import app

    document = deposer(session, creer(session))
    reponse = TestClient(app, follow_redirects=False).get(f"/espace/documents/{document.id}/fichier")
    assert reponse.status_code == 303 and reponse.headers["location"].endswith("/espace/connexion")


def test_reclasser_depuis_le_coffre(espace, session, dossier, jour_fixe):
    e, client, _ = connecte(session)
    document = deposer(session, e)
    reponse = client.post(f"/espace/documents/{document.id}/classement", data={"type_document": "paie", "mois": "2026-08"},
                          follow_redirects=False)
    assert info(reponse) == "classe" and (document.type_document, document.mois) == ("paie", date(2026, 8, 1))
    assert traces(session, e)[-1].session_espace_id is not None
    assert tx.DOCUMENT_RECLASSE in texte_visible(client.get("/espace/documents?info=classe").text)


@pytest.mark.parametrize("cas", ["type", "mois", "autre_entreprise", "inconnu"])
def test_reclasser_refuse(espace, session, dossier, jour_fixe, cas):
    e, client, _ = connecte(session)
    document = deposer(session, e if cas != "autre_entreprise" else creer(session, "Ets Autre"))
    identifiant = uuid.uuid4() if cas == "inconnu" else document.id
    donnees_envoyees = {"type_document": "rien" if cas == "type" else "paie", "mois": "2030-01" if cas == "mois" else "2026-10"}
    reponse = client.post(f"/espace/documents/{identifiant}/classement", data=donnees_envoyees, follow_redirects=False)
    assert info(reponse) == "impossible" and document.type_document == "facture"


def test_supprimer_depuis_le_coffre(espace, session, dossier, jour_fixe):
    e, client, _ = connecte(session)
    document = deposer(session, e)
    fichier = stockage.chemin(document)
    reponse = client.post(f"/espace/documents/{document.id}/supprimer", follow_redirects=False)
    assert info(reponse) == "supprime" and not fichier.exists()
    assert session.get(Document, document.id) is None and traces(session, e)[-1].session_espace_id is not None
    assert tx.DOCUMENT_SUPPRIME in texte_visible(client.get("/espace/documents?info=supprime").text)


def test_supprimer_le_document_d_une_autre_entreprise(espace, session, dossier, jour_fixe):
    _, client, _ = connecte(session)
    document = deposer(session, creer(session, "Ets Autre"))
    assert info(client.post(f"/espace/documents/{document.id}/supprimer", follow_redirects=False)) == "impossible"
    assert session.get(Document, document.id) is not None and stockage.chemin(document).exists()


def test_actions_seulement_en_post(espace, session, dossier, jour_fixe):
    e, client, _ = connecte(session)
    document = deposer(session, e)
    assert client.get(f"/espace/documents/{document.id}/supprimer").status_code == 405
    assert client.get(f"/espace/documents/{document.id}/classement").status_code == 405


def test_filtre_par_type(espace, session, dossier, jour_fixe):
    e, client, _ = connecte(session)
    deposer(session, e, nom="paie.pdf", type_document="paie")
    deposer(session, e, nom="facture.pdf")
    html = client.get("/espace/documents?type=paie").text
    assert "paie.pdf" in html and "facture.pdf" not in html
    assert 'href="http://testserver/espace/documents?type=paie" class="actif" aria-current="true"' in html
    assert tx.AUCUN_DOCUMENT_TYPE in texte_visible(client.get("/espace/documents?type=attestation").text)


def test_messages_inconnus_ignores(espace, session, dossier, jour_fixe):
    _, client, _ = connecte(session)
    assert "esp-message" not in client.get("/espace/documents?info=autre").text


def test_nom_de_fichier_echappe(espace, session, dossier, jour_fixe):
    e, client, _ = connecte(session)
    deposer(session, e, nom="<img src=x onerror=alert(1)>.pdf")
    html = client.get("/espace/documents").text
    assert "<img src=x" not in html and "&lt;img src=x onerror=alert(1)&gt;.pdf" in html


def test_textes_sans_tutoiement_des_documents(espace, session, dossier, jour_fixe):
    from tests.test_lot02_bulle_web import TUTOIEMENT

    e, client, _ = connecte(session)
    deposer(session, e)
    for adresse in ("/espace/documents", "/espace/documents?info=quota", "/espace/documents?info=depose"):
        texte = texte_visible(client.get(adresse).text)
        assert not TUTOIEMENT.search(texte), texte


# --- Base, déploiement, version -----------------------------------------------------------------

def test_table_documents():
    inspecteur = inspect(get_engine())
    colonnes = {c["name"]: c for c in inspecteur.get_columns("documents")}
    assert set(colonnes) == {"id", "entreprise_id", "type_document", "mois", "nom", "format", "taille", "empreinte",
                             "session_espace_id", "depose_le"}
    assert all(not colonnes[c]["nullable"] for c in colonnes if c != "session_espace_id")
    assert {fk["referred_table"] for fk in inspecteur.get_foreign_keys("documents")} == {"entreprises", "sessions_espace"}
    assert {i["name"] for i in inspecteur.get_indexes("documents")} == {"ix_documents_entreprise_id"}
    contraintes = {c["name"]: c["sqltext"] for c in inspecteur.get_check_constraints("documents")}
    assert set(contraintes) == {"ck_documents_type", "ck_documents_format", "ck_documents_taille", "ck_documents_mois"}
    import re

    assert set(re.findall(r"'(\w+)'", contraintes["ck_documents_type"])) == set(TYPES)
    assert set(re.findall(r"'(\w+)'", contraintes["ck_documents_format"])) == set(FORMATS)


@pytest.mark.parametrize("champs", [
    {"type_document": "autre_type"}, {"format": "gif"}, {"taille": 0}, {"mois": date(2026, 10, 2)},
])
def test_contraintes_de_la_table(session, champs):
    e = creer(session)
    valeurs = {"id": uuid.uuid4(), "entreprise_id": e.id, "type_document": "facture", "mois": OCTOBRE, "nom": "x.pdf",
               "format": "pdf", "taille": 10, "empreinte": "0" * 64, **champs}
    session.add(Document(**valeurs))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_depose_le_par_defaut(session):
    e = creer(session)
    identifiant = uuid.uuid4()
    session.execute(text(
        "INSERT INTO documents (id, entreprise_id, type_document, mois, nom, format, taille, empreinte) "
        "VALUES (:i, :e, 'autre', '2026-10-01', 'x.pdf', 'pdf', 1, :h)"), {"i": identifiant, "e": e.id, "h": "0" * 64})
    assert session.execute(text("SELECT depose_le FROM documents WHERE id = :i"), {"i": identifiant}).scalar() is not None


def test_volume_docker_et_dossier():
    compose = (RACINE / "docker-compose.yml").read_text()
    assert "DOCUMENTS_DOSSIER: /data/documents" in compose and "- jeff_documents:/data/documents" in compose
    assert "\n  jeff_documents:\n" in compose
    dockerfile = (RACINE / "Dockerfile").read_text()
    assert "mkdir -p /data/documents" in dockerfile and "chown jeff:jeff /data/documents" in dockerfile
    assert dockerfile.index("chown jeff:jeff /data/documents") < dockerfile.index("USER jeff")
    assert "uploads/" in (RACINE / ".gitignore").read_text()


def test_dossier_par_defaut(monkeypatch):
    monkeypatch.delenv("DOCUMENTS_DOSSIER", raising=False)
    get_settings.cache_clear()
    try:
        assert get_settings().documents_dossier == "uploads/documents"
    finally:
        get_settings.cache_clear()


def test_onglet_documents_dans_le_modele():
    import app.models as modeles

    assert "Document" in modeles.__all__


def test_version():
    assert VERSION.startswith("0.")
