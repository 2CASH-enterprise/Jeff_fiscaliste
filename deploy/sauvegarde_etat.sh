#!/usr/bin/env bash
# Jeff — état des sauvegardes (lot 16) : une ligne, code de sortie 0 si la dernière a moins de 26 h.
set -euo pipefail

RACINE="${JEFF_RACINE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
DESTINATION="${JEFF_SAUVEGARDES:-$RACINE/sauvegardes}"
LIMITE_HEURES=26

DERNIERE="$(find "$DESTINATION" -maxdepth 1 -name 'jeff_*.tar.age' -printf '%T@ %f\n' 2>/dev/null | sort -rn | head -n 1 | cut -d' ' -f2-)"
if [ -z "$DERNIERE" ]; then
    echo "ATTENTION : aucune sauvegarde dans $DESTINATION."
    exit 1
fi
HEURES=$(( ($(date +%s) - $(stat -c %Y "$DESTINATION/$DERNIERE")) / 3600 ))
TAILLE="$(du -h "$DESTINATION/$DERNIERE" | cut -f1)"
NOMBRE="$(find "$DESTINATION" -maxdepth 1 -name 'jeff_*.tar.age' | wc -l)"
if [ "$HEURES" -ge "$LIMITE_HEURES" ]; then
    echo "ATTENTION : la dernière sauvegarde ($DERNIERE) date de $HEURES h."
    exit 1
fi
echo "OK : dernière sauvegarde $DERNIERE, il y a $HEURES h, $TAILLE ; $NOMBRE copies gardées."
