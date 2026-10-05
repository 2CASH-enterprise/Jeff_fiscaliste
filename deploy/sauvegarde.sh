#!/usr/bin/env bash
# Jeff — sauvegarde nocturne (lot 16) : base PostgreSQL + documents du coffre, chiffrées avec age.
#
# Lancé par le cron de root (deploy/cron/jeff-sauvegarde), depuis /opt/jeff uniquement.
# Le serveur n'a que la clé PUBLIQUE ; la clé privée reste chez le porteur. Sans elle,
# une sauvegarde ne peut pas être relue, même sur le serveur.
#
# Rotation : 7 sauvegardes quotidiennes et 4 hebdomadaires (celle du dimanche, heure de Douala).
set -Eeuo pipefail
umask 077

RACINE="${JEFF_RACINE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
DESTINATION="${JEFF_SAUVEGARDES:-$RACINE/sauvegardes}"
CLE_PUBLIQUE="${JEFF_CLE_PUBLIQUE:-$DESTINATION/cle-publique.txt}"
DOCKER="${DOCKER:-docker}"
QUOTIDIENNES=7
HEBDOMADAIRES=4
FUSEAU="Africa/Douala"

journal() {
    echo "$(TZ="$FUSEAU" date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$DESTINATION/journal.log"
}

cd "$RACINE"
if ! grep -qx 'name: jeff' docker-compose.yml 2>/dev/null; then
    echo "Le docker-compose.yml de Jeff est introuvable dans $RACINE : rien n'est fait." >&2
    exit 2
fi
mkdir -p "$DESTINATION"
chmod 700 "$DESTINATION"

exec 9>"$DESTINATION/.verrou"
if ! flock -n 9; then
    echo "Une sauvegarde est déjà en cours." >&2
    exit 3
fi

if [ ! -s "$CLE_PUBLIQUE" ]; then
    journal "ECHEC : clé publique absente ($CLE_PUBLIQUE)."
    exit 4
fi
DESTINATAIRE="$(tr -d '[:space:]' < "$CLE_PUBLIQUE")"
if [[ ! "$DESTINATAIRE" =~ ^age1[02-9ac-hj-np-z]{58}$ ]]; then
    journal "ECHEC : clé publique invalide (une clé age commence par age1)."
    exit 4
fi

HORODATAGE="${JEFF_MAINTENANT:-$(TZ="$FUSEAU" date +%Y-%m-%d_%H%M)}"
JOUR_SEMAINE="${JEFF_JOUR_SEMAINE:-$(TZ="$FUSEAU" date +%u)}"
SORTE="quotidienne"
if [ "$JOUR_SEMAINE" = "7" ]; then
    SORTE="hebdomadaire"
fi
NOM="jeff_${SORTE}_${HORODATAGE}.tar.age"
PARTIEL="$DESTINATION/.$NOM.partiel"
TRAVAIL="$(mktemp -d "$DESTINATION/.travail.XXXXXX")"
trap 'rm -rf "$TRAVAIL" "$PARTIEL"' EXIT
trap 'journal "ECHEC ligne $LINENO : la sauvegarde $NOM n'"'"'a pas été faite."' ERR

mkdir "$TRAVAIL/jeff"
"$DOCKER" compose exec -T db pg_dump -U jeff -d jeff --format=custom > "$TRAVAIL/jeff/base.dump"
if [ "$(head -c 5 "$TRAVAIL/jeff/base.dump")" != "PGDMP" ]; then
    journal "ECHEC : l'export de la base est vide ou illisible."
    exit 5
fi
"$DOCKER" compose exec -T api tar -C /data/documents -cf - . > "$TRAVAIL/jeff/documents.tar"
tar -tf "$TRAVAIL/jeff/documents.tar" > /dev/null

{
    echo "horodatage=$HORODATAGE"
    echo "sorte=$SORTE"
    echo "commit=$(git -C "$RACINE" rev-parse --short HEAD 2>/dev/null || echo inconnu)"
    echo "documents=$(tar -tf "$TRAVAIL/jeff/documents.tar" | grep -cE '\.(pdf|jpg|png)$' || true)"
} > "$TRAVAIL/jeff/info.txt"
(cd "$TRAVAIL/jeff" && sha256sum base.dump documents.tar info.txt > SHA256SUMS)

tar -C "$TRAVAIL" -cf - jeff | age -r "$DESTINATAIRE" -o "$PARTIEL"
mv "$PARTIEL" "$DESTINATION/$NOM"

# Rotation : les plus récentes d'abord (le nom contient la date), on garde les N premières.
find "$DESTINATION" -maxdepth 1 -name 'jeff_quotidienne_*.tar.age' -printf '%f\n' | sort -r \
    | tail -n +$((QUOTIDIENNES + 1)) | while read -r ancien; do rm -f "$DESTINATION/$ancien"; done
find "$DESTINATION" -maxdepth 1 -name 'jeff_hebdomadaire_*.tar.age' -printf '%f\n' | sort -r \
    | tail -n +$((HEBDOMADAIRES + 1)) | while read -r ancien; do rm -f "$DESTINATION/$ancien"; done

journal "OK $NOM ($(du -h "$DESTINATION/$NOM" | cut -f1))"
