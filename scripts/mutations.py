"""Contrôle par mutations : casse volontairement chaque règle et vérifie qu'un test échoue.

Usage : python scripts/mutations.py lot01
Chaque lot ajoute sa liste de mutations ci-dessous. Une mutation qui laisse tous les tests
verts signale un test manquant : le lot n'est pas livré tant qu'elle « survit ».
"""
import pathlib
import subprocess
import sys

RACINE = pathlib.Path(__file__).resolve().parent.parent

MUTATIONS = {
    "lot01": [
        ("app/core/sante.py", 'return {"statut": OK if tout_va_bien else INDISPONIBLE', 'return {"statut": OK'),
        ("app/core/sante.py", "all(valeur == OK", "any(valeur == OK"),
        ("app/core/sante.py", "        return OK\n    except Exception:\n        return INDISPONIBLE\n\n\ndef verifier_redis", "        return OK\n    except Exception:\n        return OK\n\n\ndef verifier_redis"),
        ("app/core/sante.py", "        client.ping()\n        return OK\n    except Exception:\n        return INDISPONIBLE", "        client.ping()\n        return OK\n    except Exception:\n        return OK"),
        ("app/main.py", "code = 200 if etat", "code = 200 or etat"),
        ("app/core/config.py", 'return self.environnement != "production"', "return True"),
        ("app/entreprises/niu.py", "if not niu:", "if False:"),
        ("app/entreprises/niu.py", "if len(niu) > LONGUEUR_MAX:", "if len(niu) > LONGUEUR_MAX + 1:"),
        ("app/entreprises/niu.py", ".upper()", ""),
        ("app/entreprises/niu.py", r're.sub(r"[\s\-]", "", valeur)', r're.sub(r"[\s]", "", valeur)'),
        ("app/entreprises/niu.py", "if not niu.isalnum():", "if False:"),
        ("app/entreprises/niu.py", "if valeur is None:", "if False:"),
        ("migrations/versions/0001_socle.py", '"active": True', '"active": False'),
        ("migrations/versions/0001_socle.py", 'sa.UniqueConstraint("juridiction_code", "niu", name="uq_entreprises_juridiction_niu"),', ""),
        ("migrations/versions/0001_socle.py", 'sa.UniqueConstraint("juridiction_code", "niu"', 'sa.UniqueConstraint("niu"'),
        ("migrations/versions/0001_socle.py", 'sa.ForeignKey("juridictions.code"), nullable=False', "nullable=False"),
    ],
}


def lancer_tests() -> bool:
    resultat = subprocess.run(
        [sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:warnings"],
        cwd=RACINE,
        capture_output=True,
    )
    return resultat.returncode == 0


def main(lot: str) -> int:
    survivantes = []
    for fichier, avant, apres in MUTATIONS[lot]:
        chemin = RACINE / fichier
        original = chemin.read_text()
        if original.count(avant) != 1:
            print(f"MUTATION INVALIDE ({fichier}) : texte introuvable ou ambigu : {avant!r}")
            return 2
        chemin.write_text(original.replace(avant, apres))
        try:
            tue = not lancer_tests()
        finally:
            chemin.write_text(original)
        print(f"{'tuée     ' if tue else 'SURVIVANTE'} {fichier} : {avant[:60]!r}")
        if not tue:
            survivantes.append((fichier, avant))
    total = len(MUTATIONS[lot])
    print(f"\n{total - len(survivantes)}/{total} mutations tuées.")
    return 1 if survivantes else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "lot01"))
