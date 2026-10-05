#!/usr/bin/env bash
# Jeff — essai de restauration (lot 16), sans jamais toucher à la vraie base.
#
# Usage, depuis le Mac (la clé privée passe par la connexion SSH et n'est jamais écrite sur le serveur) :
#   ssh root@SERVEUR 'cd /opt/jeff && deploy/restauration_essai.sh sauvegardes/jeff_quotidienne_….tar.age' < ~/jeff-sauvegarde.key
#
# Déchiffre la sauvegarde dans un dossier temporaire, vérifie les empreintes, recharge la base
# dans une base d'essai séparée (jeff_restauration_essai), compte les lignes et les fichiers,
# puis efface la base d'essai et le dossier temporaire.
set -Eeuo pipefail
umask 077

RACINE="${JEFF_RACINE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
DOCKER="${DOCKER:-docker}"
ESSAI="jeff_restauration_essai"
FICHIER="${1:-}"

if [ -z "$FICHIER" ] || [ ! -f "$FICHIER" ]; then
    echo "Usage : deploy/restauration_essai.sh sauvegardes/jeff_….tar.age < cle-privee" >&2
    exit 2
fi
if [ -t 0 ]; then
    echo "La clé privée doit arriver par l'entrée standard (… < ~/jeff-sauvegarde.key depuis le Mac)." >&2
    exit 2
fi
cd "$RACINE"
TRAVAIL="$(mktemp -d)"
base_essai() { "$DOCKER" compose exec -T db "$@"; }
nettoyer() {
    base_essai dropdb -U jeff --if-exists "$ESSAI" > /dev/null 2>&1 || true
    rm -rf "$TRAVAIL"
}
trap nettoyer EXIT

age -d -i - "$FICHIER" | tar -x -C "$TRAVAIL"
(cd "$TRAVAIL/jeff" && sha256sum --quiet -c SHA256SUMS)
echo "Empreintes : OK"

base_essai dropdb -U jeff --if-exists "$ESSAI"
base_essai createdb -U jeff "$ESSAI"
base_essai pg_restore -U jeff -d "$ESSAI" --no-owner --exit-on-error < "$TRAVAIL/jeff/base.dump"
compter() { base_essai psql -U jeff -d "$ESSAI" -tAc "SELECT count(*) FROM $1" | tr -d '[:space:]'; }
VERSION_BASE="$(base_essai psql -U jeff -d "$ESSAI" -tAc 'SELECT version_num FROM alembic_version' | tr -d '[:space:]')"
ENTREPRISES="$(compter entreprises)"
DOCUMENTS_BASE="$(compter documents)"
DOCUMENTS_FICHIERS="$(tar -tf "$TRAVAIL/jeff/documents.tar" | grep -cE '\.(pdf|jpg|png)$' || true)"

echo "Base : migration $VERSION_BASE, $ENTREPRISES entreprise(s), $DOCUMENTS_BASE document(s) enregistrés."
echo "Fichiers : $DOCUMENTS_FICHIERS document(s) dans l'archive."
if [ "$DOCUMENTS_BASE" != "$DOCUMENTS_FICHIERS" ]; then
    echo "ATTENTION : le nombre de documents en base et de fichiers diffère."
    exit 1
fi
echo "Restauration d'essai : OK (base d'essai effacée, la vraie base n'a pas été touchée)."
