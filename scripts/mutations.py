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
    "lot02": [
        ("app/conversation/moteur.py", "return len(texte) > LONGUEUR_MAX", "return len(texte) > LONGUEUR_MAX + 1"),
        ("app/conversation/moteur.py", "if premier_mot in SALUTATIONS:", "if mots in SALUTATIONS:"),
        ("app/conversation/moteur.py", "if mots == valeur:", "if valeur in mots:"),
        ("app/conversation/normalisation.py", 'encode("ascii", "ignore")', 'encode("utf-8", "ignore")'),
        ("app/conversation/normalisation.py", ".lower()", ""),
        ("app/conversation/moteur.py", "if texte is None or not texte.strip():", "if texte is None:"),
        ("app/conversation/moteur.py", "texte=texte[:LONGUEUR_MAX]", "texte=texte"),
        ("app/conversation/moteur.py", "            Conversation.canal == canal, Conversation.identifiant_externe == identifiant\n        )", "            Conversation.identifiant_externe == identifiant\n        )"),
        ("app/conversation/moteur.py", ".where(Conversation.canal == canal, Conversation.identifiant_externe == identifiant)\n            .order_by", ".where(Conversation.canal == canal)\n            .order_by"),
        ("app/conversation/moteur.py", ".order_by(Message.id)", ".order_by(Message.id.desc())"),
        ("app/conversation/moteur.py", "return Reponse(mf.ACCUEIL, list(mf.MENU))", "return Reponse(mf.ACCUEIL)"),
        ("app/conversation/messages_fixes.py", "Tapez « menu » pour voir ce que je peux faire pour vous.", "Tape « menu » pour voir ce que je peux faire pour toi."),
        ("app/canaux/web.py", "if not get_settings().essai_actif:", "if False:"),
        ("app/canaux/web.py", "jeton = jeton_valide(request) or secrets.token_urlsafe(32)", "jeton = secrets.token_urlsafe(32)"),
        ("app/canaux/web.py", "if jeton and 20 <= len(jeton)", "if jeton and 0 <= len(jeton)"),
        ("app/canaux/web.py", 'jeton.replace("-", "").replace("_", "").isalnum()', "True"),
        ("app/canaux/web.py", "httponly=True", "httponly=False"),
        ("app/canaux/web.py", 'samesite="strict"', 'samesite="lax"'),
        ("app/canaux/web.py", "    if jeton is None:\n        raise HTTPException(status_code=401", "    if False:\n        raise HTTPException(status_code=401"),
        ("app/canaux/web.py", "raise HTTPException(status_code=422", "raise HTTPException(status_code=400"),
        ("app/static/js/essai.js", "bulle.textContent = texte;", "bulle.innerHTML = texte;"),
        ("docker-compose.yml", "${JEFF_PORT:-8020}", "${JEFF_PORT:-8010}"),
        ("app/main.py", "from app import models as _modeles  # noqa: F401", "# from app import models"),
        ("migrations/versions/0002_conversations.py", 'sa.UniqueConstraint("canal", "identifiant_externe", name="uq_conversations_canal_identifiant"),', ""),
    ],
    "lot03": [
        ("app/conversation/montants.py", 'brut = re.sub(UNITES_MONETAIRES, " ", brut)', "brut = brut"),
        ("app/conversation/montants.py", 'brut = re.sub(r"\\bde\\b", " ", brut).strip()', "brut = brut.strip()"),
        ("app/conversation/montants.py", "if unite not in MULTIPLICATEURS:", "if False:"),
        ("app/conversation/montants.py", "if valeur != valeur.to_integral_value():", "if False:"),
        ("app/conversation/montants.py", 'chiffres.replace(",", ".")', "chiffres"),
        ("app/conversation/montants.py", r're.fullmatch(r"\d{1,3}(\.\d{3})+", chiffres)', r're.fullmatch(r"[\d.]+", chiffres)'),
        ("app/conversation/montants.py", "if montant > MONTANT_MAX:", "if montant > MONTANT_MAX * 10:"),
        ("app/conversation/montants.py", '"million": 10**6, "millions": 10**6, "m": 10**6', '"million": 10**6, "millions": 10**3, "m": 10**6'),
        ("app/conversation/montants.py", "if normaliser(texte) in MOTS_ZERO:", "if False:"),
        ("app/conversation/montants.py", "chiffres = re.sub(ESPACES, \"\", texte)", "chiffres = re.sub(ESPACES, \"\", normaliser(texte))"),
        ("app/conversation/montants.py", "if nombre > maximum:", "if nombre > maximum + 1:"),
        ("app/conversation/montants.py", 'return f"{montant:,}".replace(",", ESPACE_INSECABLE)', 'return f"{montant:,}".replace(",", " ")'),
        ("app/conversation/onboarding.py", "if len(valeur) < minimum:", "if len(valeur) < minimum - 1:"),
        ("app/conversation/onboarding.py", "if len(valeur) > maximum:", "if len(valeur) > maximum + 1:"),
        ("app/conversation/onboarding.py", "    if niu_deja_connu(session, niu):\n        raise ReponseInvalide(mf.NIU_DEJA_CONNU)", "    if False:\n        raise ReponseInvalide(mf.NIU_DEJA_CONNU)"),
        ("app/conversation/onboarding.py", "Entreprise.juridiction_code == get_settings().juridiction, Entreprise.niu == niu", "Entreprise.niu == niu"),
        ("app/conversation/onboarding.py", "if mots in {str(numero), normaliser(libelle), *synonymes}:", "if mots in {str(numero), *synonymes}:"),
        ("app/conversation/onboarding.py", "if not numero.isalnum() or not 3 <= len(numero) <= 30:", "if not 3 <= len(numero) <= 30:"),
        ("app/conversation/onboarding.py", 'if mots in {"plus tard", "je ne sais pas", "je ne l ai pas", "inconnu"}:', "if False:"),
        ("app/conversation/onboarding.py", 'condition=lambda donnees: (donnees.get("nombre_salaries") or 0) > 0,', "condition=lambda donnees: True,"),
        ("app/conversation/onboarding.py", "        if cle == \"nombre_salaries\" and cnps.condition(donnees) and cnps.cle not in donnees:", "        if False:"),
        ("app/conversation/onboarding.py", "    if donnees.get(RETOUR_RECAP):", "    if False:"),
        ("app/conversation/onboarding.py", '        donnees.pop("numero_employeur_cnps", None)', "        pass"),
        ("app/conversation/onboarding.py", "            parcours.statut = ABANDONNE\n            return Reponse(mf.PLUS_TARD", "            return Reponse(mf.PLUS_TARD"),
        ("app/conversation/onboarding.py", "if mots.isdigit() and 1 <= int(mots) <= len(visibles):", "if mots.isdigit() and 0 <= int(mots) <= len(visibles):"),
        ("app/conversation/onboarding.py", "    if niu_deja_connu(session, donnees[\"niu\"]):", "    if False:"),
        ("app/conversation/onboarding.py", "assujetti_tva_declare=None if tva == INCONNU else tva == \"oui\",", "assujetti_tva_declare=tva == \"oui\","),
        ("app/conversation/onboarding.py", "    conversation.entreprise_id = entreprise.id\n", ""),
        ("app/conversation/onboarding.py", "    parcours.statut = TERMINE\n", ""),
        ("app/conversation/onboarding.py", "juridiction_code=get_settings().juridiction,", 'juridiction_code="CI",'),
        ("app/conversation/moteur.py", "            parcours.statut = EN_PAUSE\n", ""),
        ("app/conversation/moteur.py", "            parcours.statut = ABANDONNE\n            return Reponse(mf.ANNULE", "            return Reponse(mf.ANNULE"),
        ("app/conversation/moteur.py", 'if mots == "reprendre" or (sans_profil and mots in CHOIX_AVEC_PROFIL):', 'if mots == "reprendre":'),
        ("app/conversation/moteur.py", "if sans_profil and mots in CHOIX_AVEC_PROFIL and parcours is None:", "if mots in CHOIX_AVEC_PROFIL and parcours is None:"),
        ("app/conversation/moteur.py", 'CHOIX_AVEC_PROFIL = {"1", "2", "3"}', 'CHOIX_AVEC_PROFIL = {"1", "2", "3", "4"}'),
        ("app/conversation/models.py", "postgresql_where=text(\"statut IN ('en_cours', 'en_pause')\"),", "postgresql_where=text(\"statut IN ('en_cours')\"),"),
        ("migrations/versions/0003_onboarding.py", "postgresql_where=sa.text(\"statut IN ('en_cours', 'en_pause')\"),", "postgresql_where=sa.text(\"statut IN ('en_cours')\"),"),
        ("migrations/versions/0003_onboarding.py", "        unique=True,\n", ""),
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
