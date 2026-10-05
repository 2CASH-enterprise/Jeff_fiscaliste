"""Lot 16 — sauvegardes chiffrées de la base et des documents, état et essai de restauration.

Les scripts tournent pour de vrai (bash, pg_dump, age, tar) ; seul `docker compose exec` est remplacé
par un faux docker qui lance les mêmes commandes sur la base PostgreSQL de contrôle (jeff_migration).
"""
import io
import os
import shutil
import stat
import subprocess
import tarfile
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
DEPLOY = RACINE / "deploy"
BASE_DE_CONTROLE = "jeff_migration"
ESSAI = "jeff_restauration_essai"

FAUX_DOCKER = r'''#!/usr/bin/env python3
"""Faux docker : « compose exec -T <service> <commande> » lancé localement, et noté dans un journal."""
import os, sys
arguments = sys.argv[1:]
with open(os.environ["FAUX_JOURNAL"], "a") as journal:
    journal.write(" ".join(arguments) + "\n")
assert arguments[:3] == ["compose", "exec", "-T"], arguments
service, commande = arguments[3], arguments[4:]
if os.environ.get("FAUX_ECHEC") == commande[0]:
    sys.exit(1)
if os.environ.get("FAUX_VIDE") == commande[0]:
    sys.exit(0)
if service == "db":
    commande = [os.environ["FAUX_BASE"] if a == "jeff" and i > 0 and commande[i - 1] == "-d" else a
                for i, a in enumerate(commande)]
    os.execvpe(commande[0], commande, {**os.environ, "PGHOST": "localhost", "PGPASSWORD": "jeff"})
commande = [os.environ["FAUX_DOCUMENTS"] if a == "/data/documents" else a for a in commande]
os.execvp(commande[0], commande)
'''


def requis(*outils):
    manquants = [o for o in outils if shutil.which(o) is None]
    return pytest.mark.skipif(bool(manquants), reason=f"outils absents : {manquants}")


pytestmark = requis("age", "age-keygen", "pg_dump", "pg_restore", "flock")


@pytest.fixture
def banc(tmp_path):
    """Un /opt/jeff miniature : docker-compose.yml, faux docker, clé, documents."""
    racine = tmp_path / "jeff"
    racine.mkdir()
    (racine / "docker-compose.yml").write_text("# Jeff\nname: jeff\n")
    sauvegardes = racine / "sauvegardes"
    sauvegardes.mkdir()
    documents = tmp_path / "documents"
    (documents / "entreprise").mkdir(parents=True)
    docker = tmp_path / "docker"
    docker.write_text(FAUX_DOCKER)
    docker.chmod(0o755)
    cle = tmp_path / "cle.key"
    subprocess.run(["age-keygen", "-o", str(cle)], check=True, capture_output=True)
    publique = subprocess.run(["age-keygen", "-y", str(cle)], check=True, capture_output=True, text=True).stdout.strip()
    (sauvegardes / "cle-publique.txt").write_text(publique + "\n")
    env = {
        **os.environ,
        "JEFF_RACINE": str(racine), "JEFF_SAUVEGARDES": str(sauvegardes), "DOCKER": str(docker),
        "JEFF_MAINTENANT": "2026-10-05_0300", "JEFF_JOUR_SEMAINE": "1",
        "FAUX_JOURNAL": str(tmp_path / "docker.log"), "FAUX_BASE": BASE_DE_CONTROLE, "FAUX_DOCUMENTS": str(documents),
    }

    class Banc:
        pass

    b = Banc()
    b.racine, b.sauvegardes, b.documents, b.cle, b.publique, b.env, b.tmp = racine, sauvegardes, documents, cle, publique, env, tmp_path
    return b


def lancer(script, banc, *arguments, entree=None, **env):
    return subprocess.run(
        [str(DEPLOY / script), *arguments], env={**banc.env, **env}, capture_output=True, text=True,
        input=entree, timeout=120,
    )


def sauvegardes(banc) -> list[str]:
    return sorted(p.name for p in banc.sauvegardes.glob("jeff_*.tar.age"))


def ouvrir(banc, nom) -> dict[str, bytes]:
    clair = subprocess.run(["age", "-d", "-i", str(banc.cle), str(banc.sauvegardes / nom)], check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(clair)) as archive:
        return {m.name: archive.extractfile(m).read() for m in archive.getmembers() if m.isfile()}


def journal_docker(banc) -> list[str]:
    chemin = banc.tmp / "docker.log"
    return chemin.read_text().splitlines() if chemin.exists() else []


# --- Sauvegarde ---------------------------------------------------------------------------------

def test_sauvegarde_complete(banc):
    (banc.documents / "entreprise" / "facture.pdf").write_bytes(b"%PDF-1.4 test")
    (banc.documents / "entreprise" / "photo.jpg").write_bytes(b"\xff\xd8\xff photo")
    resultat = lancer("sauvegarde.sh", banc)
    assert resultat.returncode == 0, resultat.stderr
    assert sauvegardes(banc) == ["jeff_quotidienne_2026-10-05_0300.tar.age"]
    fichier = banc.sauvegardes / "jeff_quotidienne_2026-10-05_0300.tar.age"
    assert stat.S_IMODE(fichier.stat().st_mode) == 0o600 and stat.S_IMODE(banc.sauvegardes.stat().st_mode) == 0o700
    assert fichier.read_bytes().startswith(b"age-encryption.org/v1")
    contenu = ouvrir(banc, fichier.name)
    assert set(contenu) == {"jeff/base.dump", "jeff/documents.tar", "jeff/info.txt", "jeff/SHA256SUMS"}
    assert contenu["jeff/base.dump"].startswith(b"PGDMP")
    with tarfile.open(fileobj=io.BytesIO(contenu["jeff/documents.tar"])) as documents:
        assert sorted(n.lstrip("./") for n in documents.getnames() if n.endswith((".pdf", ".jpg"))) == [
            "entreprise/facture.pdf", "entreprise/photo.jpg"]
    info = contenu["jeff/info.txt"].decode()
    assert "horodatage=2026-10-05_0300" in info and "sorte=quotidienne" in info and "documents=2" in info
    assert "commit=inconnu" in info
    empreintes = contenu["jeff/SHA256SUMS"].decode()
    for nom in ("base.dump", "documents.tar", "info.txt"):
        assert nom in empreintes
    # Les empreintes correspondent au contenu.
    import hashlib

    for ligne in empreintes.splitlines():
        attendue, nom = ligne.split()
        assert hashlib.sha256(contenu[f"jeff/{nom}"]).hexdigest() == attendue
    journal = (banc.sauvegardes / "journal.log").read_text()
    assert "OK jeff_quotidienne_2026-10-05_0300.tar.age (" in journal
    assert [p.name for p in banc.sauvegardes.iterdir() if p.name.startswith(".") and p.name != ".verrou"] == []
    assert journal_docker(banc) == [
        "compose exec -T db pg_dump -U jeff -d jeff --format=custom",
        "compose exec -T api tar -C /data/documents -cf - .",
    ]


def test_sauvegarde_du_dimanche_hebdomadaire(banc):
    assert lancer("sauvegarde.sh", banc, JEFF_JOUR_SEMAINE="7").returncode == 0
    [nom] = sauvegardes(banc)
    assert nom == "jeff_hebdomadaire_2026-10-05_0300.tar.age"
    assert "sorte=hebdomadaire" in ouvrir(banc, nom)["jeff/info.txt"].decode()


def test_rotation_7_quotidiennes_4_hebdomadaires(banc):
    for jour in range(1, 10):
        (banc.sauvegardes / f"jeff_quotidienne_2026-09-{jour:02d}_0300.tar.age").write_text("ancienne")
    for jour in (6, 13, 20, 27, 28, 29):
        (banc.sauvegardes / f"jeff_hebdomadaire_2026-08-{jour:02d}_0300.tar.age").write_text("ancienne")
    (banc.sauvegardes / "autre_fichier.txt").write_text("gardé")
    assert lancer("sauvegarde.sh", banc).returncode == 0
    quotidiennes = [n for n in sauvegardes(banc) if "quotidienne" in n]
    hebdomadaires = [n for n in sauvegardes(banc) if "hebdomadaire" in n]
    assert quotidiennes == ["jeff_quotidienne_2026-09-04_0300.tar.age", "jeff_quotidienne_2026-09-05_0300.tar.age",
                            "jeff_quotidienne_2026-09-06_0300.tar.age", "jeff_quotidienne_2026-09-07_0300.tar.age",
                            "jeff_quotidienne_2026-09-08_0300.tar.age", "jeff_quotidienne_2026-09-09_0300.tar.age",
                            "jeff_quotidienne_2026-10-05_0300.tar.age"]
    assert hebdomadaires == ["jeff_hebdomadaire_2026-08-20_0300.tar.age", "jeff_hebdomadaire_2026-08-27_0300.tar.age",
                             "jeff_hebdomadaire_2026-08-28_0300.tar.age", "jeff_hebdomadaire_2026-08-29_0300.tar.age"]
    assert (banc.sauvegardes / "autre_fichier.txt").exists()


def test_sans_cle_publique(banc):
    (banc.sauvegardes / "cle-publique.txt").unlink()
    resultat = lancer("sauvegarde.sh", banc)
    assert resultat.returncode == 4 and sauvegardes(banc) == []
    assert "ECHEC : clé publique absente" in (banc.sauvegardes / "journal.log").read_text()
    assert journal_docker(banc) == []


@pytest.mark.parametrize("cle", ["pas-une-cle", "AGE-SECRET-KEY-1QQQ", "age1" + "b" * 58, "age1" + "q" * 57])
def test_cle_publique_invalide(banc, cle):
    (banc.sauvegardes / "cle-publique.txt").write_text(cle)
    resultat = lancer("sauvegarde.sh", banc)
    assert resultat.returncode == 4 and sauvegardes(banc) == []
    assert "ECHEC : clé publique invalide" in (banc.sauvegardes / "journal.log").read_text()


def test_cle_publique_avec_espaces(banc):
    (banc.sauvegardes / "cle-publique.txt").write_text(f"  {banc.publique} \n\n")
    assert lancer("sauvegarde.sh", banc).returncode == 0


def test_hors_du_dossier_de_jeff(banc):
    (banc.racine / "docker-compose.yml").write_text("name: bob\n")
    resultat = lancer("sauvegarde.sh", banc)
    assert resultat.returncode == 2 and "introuvable" in resultat.stderr and journal_docker(banc) == []


def test_echec_de_l_export(banc):
    resultat = lancer("sauvegarde.sh", banc, FAUX_ECHEC="pg_dump")
    assert resultat.returncode != 0 and sauvegardes(banc) == []
    assert "ECHEC ligne" in (banc.sauvegardes / "journal.log").read_text()
    assert [p.name for p in banc.sauvegardes.iterdir() if p.name.startswith(".") and p.name != ".verrou"] == []


def test_export_vide(banc):
    resultat = lancer("sauvegarde.sh", banc, FAUX_VIDE="pg_dump")
    assert resultat.returncode == 5 and sauvegardes(banc) == []
    assert "ECHEC : l'export de la base est vide ou illisible." in (banc.sauvegardes / "journal.log").read_text()


def test_echec_des_documents(banc):
    resultat = lancer("sauvegarde.sh", banc, FAUX_ECHEC="tar")
    assert resultat.returncode != 0 and sauvegardes(banc) == []


def test_une_seule_sauvegarde_a_la_fois(banc):
    with open(banc.sauvegardes / ".verrou", "w") as verrou:
        import fcntl

        fcntl.flock(verrou, fcntl.LOCK_EX)
        resultat = lancer("sauvegarde.sh", banc)
    assert resultat.returncode == 3 and "déjà en cours" in resultat.stderr and journal_docker(banc) == []


def test_dossier_cree_si_absent(banc):
    nouveau = banc.tmp / "ailleurs" / "sauvegardes"
    cle = nouveau / "cle.txt"
    resultat = lancer("sauvegarde.sh", banc, JEFF_SAUVEGARDES=str(nouveau), JEFF_CLE_PUBLIQUE=str(cle))
    assert resultat.returncode == 4 and nouveau.is_dir() and stat.S_IMODE(nouveau.stat().st_mode) == 0o700


# --- État ---------------------------------------------------------------------------------------

def test_etat_sans_sauvegarde(banc):
    resultat = lancer("sauvegarde_etat.sh", banc)
    assert resultat.returncode == 1 and resultat.stdout.startswith("ATTENTION : aucune sauvegarde")


def test_etat_recent(banc):
    lancer("sauvegarde.sh", banc)
    (banc.sauvegardes / "jeff_quotidienne_2026-10-01_0300.tar.age").write_text("x")
    os.utime(banc.sauvegardes / "jeff_quotidienne_2026-10-01_0300.tar.age", (time.time() - 4 * 86400,) * 2)
    resultat = lancer("sauvegarde_etat.sh", banc)
    assert resultat.returncode == 0
    assert resultat.stdout.startswith("OK : dernière sauvegarde jeff_quotidienne_2026-10-05_0300.tar.age, il y a 0 h")
    assert "2 copies gardées." in resultat.stdout


@pytest.mark.parametrize("heures,code", [(25, 0), (26, 1), (40, 1)])
def test_etat_trop_ancien(banc, heures, code):
    fichier = banc.sauvegardes / "jeff_quotidienne_2026-10-04_0300.tar.age"
    fichier.write_text("x")
    os.utime(fichier, (time.time() - heures * 3600 - 60,) * 2)
    resultat = lancer("sauvegarde_etat.sh", banc)
    assert resultat.returncode == code
    assert resultat.stdout.startswith("ATTENTION" if code else "OK") and f"{heures} h" in resultat.stdout


# --- Essai de restauration ----------------------------------------------------------------------

def nettoyer_essai():
    subprocess.run(["dropdb", "--if-exists", ESSAI], env={**os.environ, "PGHOST": "localhost", "PGUSER": "jeff", "PGPASSWORD": "jeff"},
                   capture_output=True)


def base_essai_existe() -> bool:
    sortie = subprocess.run(
        ["psql", "-tAc", f"SELECT 1 FROM pg_database WHERE datname = '{ESSAI}'", "postgres"],
        env={**os.environ, "PGHOST": "localhost", "PGUSER": "jeff", "PGPASSWORD": "jeff"}, capture_output=True, text=True,
    ).stdout.strip()
    return sortie == "1"


def documents_en_base() -> int:
    return int(subprocess.run(
        ["psql", "-tAc", "SELECT count(*) FROM documents", BASE_DE_CONTROLE],
        env={**os.environ, "PGHOST": "localhost", "PGUSER": "jeff", "PGPASSWORD": "jeff"}, capture_output=True, text=True,
    ).stdout.strip())


@pytest.fixture
def sauvegarde(banc):
    nettoyer_essai()
    for numero in range(documents_en_base()):
        (banc.documents / "entreprise" / f"doc{numero}.pdf").write_bytes(b"%PDF-1.4")
    assert lancer("sauvegarde.sh", banc).returncode == 0
    yield banc.sauvegardes / sauvegardes(banc)[0]
    nettoyer_essai()


def test_restauration_d_essai(banc, sauvegarde):
    (banc.tmp / "docker.log").unlink()
    resultat = lancer("restauration_essai.sh", banc, str(sauvegarde), entree=banc.cle.read_text())
    assert resultat.returncode == 0, resultat.stdout + resultat.stderr
    sortie = resultat.stdout
    assert "Empreintes : OK" in sortie and "Base : migration 0015_documents" in sortie
    assert f"{documents_en_base()} document(s) enregistrés" in sortie
    assert sortie.rstrip().endswith("Restauration d'essai : OK (base d'essai effacée, la vraie base n'a pas été touchée).")
    assert not base_essai_existe()
    appels = journal_docker(banc)
    assert appels and all(service in a for a in appels for service in ["compose exec -T db"])
    # La vraie base n'est jamais visée : toutes les commandes portent sur la base d'essai.
    assert all(ESSAI in a for a in appels) and not any(" -d jeff " in a + " " for a in appels)


def test_restauration_documents_manquants(banc, sauvegarde):
    (banc.documents / "entreprise" / "en_trop.pdf").write_bytes(b"%PDF")
    autre = lancer("sauvegarde.sh", banc, JEFF_MAINTENANT="2026-10-06_0300")
    assert autre.returncode == 0
    resultat = lancer("restauration_essai.sh", banc, str(banc.sauvegardes / "jeff_quotidienne_2026-10-06_0300.tar.age"),
                      entree=banc.cle.read_text())
    assert resultat.returncode == 1 and "ATTENTION : le nombre de documents en base et de fichiers diffère." in resultat.stdout
    assert not base_essai_existe()


def test_restauration_avec_une_autre_cle(banc, sauvegarde):
    autre = subprocess.run(["age-keygen"], check=True, capture_output=True, text=True).stdout
    resultat = lancer("restauration_essai.sh", banc, str(sauvegarde), entree=autre)
    assert resultat.returncode != 0 and "Empreintes : OK" not in resultat.stdout


def test_restauration_empreinte_fausse(banc, sauvegarde):
    clair = subprocess.run(["age", "-d", "-i", str(banc.cle), str(sauvegarde)], check=True, capture_output=True).stdout
    dossier = banc.tmp / "falsifie"
    dossier.mkdir()
    with tarfile.open(fileobj=io.BytesIO(clair)) as archive:
        archive.extractall(dossier, filter="data")
    with open(dossier / "jeff" / "base.dump", "ab") as dump:
        dump.write(b"modifie")
    falsifie = banc.tmp / "falsifie.tar"
    with tarfile.open(falsifie, "w") as archive:
        archive.add(dossier / "jeff", arcname="jeff")
    chiffre = banc.sauvegardes / "jeff_quotidienne_2026-10-07_0300.tar.age"
    subprocess.run(["age", "-r", banc.publique, "-o", str(chiffre), str(falsifie)], check=True)
    resultat = lancer("restauration_essai.sh", banc, str(chiffre), entree=banc.cle.read_text())
    assert resultat.returncode != 0 and "Empreintes : OK" not in resultat.stdout and not base_essai_existe()


@pytest.mark.parametrize("arguments", [(), ("sauvegardes/absente.tar.age",)])
def test_restauration_usage(banc, arguments):
    resultat = lancer("restauration_essai.sh", banc, *arguments, entree="")
    assert resultat.returncode == 2 and resultat.stderr.startswith("Usage")


# --- Fichiers de déploiement ---------------------------------------------------------------------

def test_scripts_executables():
    for script in ("sauvegarde.sh", "sauvegarde_etat.sh", "restauration_essai.sh"):
        chemin = DEPLOY / script
        assert os.access(chemin, os.X_OK), script
        assert chemin.read_text().startswith("#!/usr/bin/env bash\n")


@requis("shellcheck")
def test_shellcheck():
    resultat = subprocess.run(["shellcheck", *(str(DEPLOY / s) for s in ("sauvegarde.sh", "sauvegarde_etat.sh", "restauration_essai.sh"))],
                              capture_output=True, text=True)
    assert resultat.returncode == 0, resultat.stdout


def test_cron_a_3_h_de_douala():
    cron = (DEPLOY / "cron" / "jeff-sauvegarde").read_text()
    lignes = [l for l in cron.splitlines() if l and not l.startswith("#") and "=" not in l]
    assert lignes == ["0 2 * * * root /opt/jeff/deploy/sauvegarde.sh >> /opt/jeff/sauvegardes/cron.log 2>&1"]
    assert "UTC+1" in cron and cron.endswith("\n")


def test_sauvegardes_jamais_versionnees_ni_dans_l_image():
    assert "sauvegardes/" in (RACINE / ".gitignore").read_text().split()
    assert "sauvegardes" in (RACINE / ".dockerignore").read_text().split()


def test_procedure_de_restauration_documentee():
    texte = (DEPLOY / "RESTAURATION.md").read_text()
    for attendu in ("deploy/restauration_essai.sh", "< ~/jeff-sauvegarde.key", "pg_restore", "--clean", "sha256sum -c",
                    "docker compose stop api worker beat", "rm -rf /root/restauration"):
        assert attendu in texte, attendu
    assert "AGE-SECRET-KEY" not in texte


def test_version():
    from app.core.config import VERSION

    assert VERSION == "0.16.0"
