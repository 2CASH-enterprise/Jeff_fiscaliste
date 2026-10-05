# Jeff — sauvegardes et restauration (lot 16)

## Ce qui est sauvegardé

Chaque nuit à 3 h (heure de Douala), `deploy/sauvegarde.sh` crée dans `/opt/jeff/sauvegardes/`
un fichier `jeff_quotidienne_AAAA-MM-JJ_HHMM.tar.age` (le dimanche : `jeff_hebdomadaire_…`). Il contient :

- `base.dump` : la base PostgreSQL complète (`pg_dump`, format personnalisé) ;
- `documents.tar` : tous les documents déposés dans le coffre (volume `jeff_documents`) ;
- `info.txt` : date, commit, nombre de documents ;
- `SHA256SUMS` : les empreintes des trois fichiers.

Le tout est chiffré avec **age** pour la clé publique `sauvegardes/cle-publique.txt`. Seule la clé
privée du porteur (gardée hors du serveur) permet de le relire. On garde 7 quotidiennes et 4 hebdomadaires.

Les copies restent sur le serveur : elles protègent contre une erreur ou une donnée abîmée, **pas
contre la perte du serveur**. Une copie hors serveur est prévue dans un lot ultérieur.

## Vérifier

- État : `cd /opt/jeff && deploy/sauvegarde_etat.sh` (code 0 si la dernière a moins de 26 h).
- Journal : `tail -n 20 /opt/jeff/sauvegardes/journal.log`.
- Essai de restauration, **depuis le Mac** (la clé passe par SSH, jamais écrite sur le serveur) :

  ```bash
  ssh root@178.104.56.200 'cd /opt/jeff && deploy/restauration_essai.sh sauvegardes/NOM_DU_FICHIER' < ~/jeff-sauvegarde.key
  ```

  Recharge la base dans une base d'essai séparée (`jeff_restauration_essai`), compte les lignes et
  les fichiers, puis efface tout. La vraie base n'est jamais touchée. À faire au moins une fois par mois.

## Restaurer pour de vrai (perte de données)

À ne faire qu'en cas de besoin réel, en arrêtant d'abord Jeff. Chaque étape se lance **sur le serveur**,
dans `/opt/jeff`, sauf la première.

1. **Sur le Mac** : déchiffrer la sauvegarde choisie et la renvoyer, déchiffrée, dans un dossier temporaire
   du serveur, sans écrire la clé sur le serveur :

   ```bash
   ssh root@178.104.56.200 'mkdir -m 700 -p /root/restauration && cd /root/restauration && age -d -i - /opt/jeff/sauvegardes/NOM_DU_FICHIER | tar -x' < ~/jeff-sauvegarde.key
   ```

2. Vérifier les empreintes : `cd /root/restauration/jeff && sha256sum -c SHA256SUMS`.
3. Arrêter l'application (la base reste allumée) : `cd /opt/jeff && docker compose stop api worker beat`.
4. Recharger la base (remplace son contenu) :

   ```bash
   cd /opt/jeff
   docker compose exec -T db pg_restore -U jeff -d jeff --clean --if-exists --no-owner < /root/restauration/jeff/base.dump
   ```

5. Recharger les documents (remplace le contenu du volume) :

   ```bash
   cd /opt/jeff
   docker compose run --rm -T --no-deps --entrypoint sh api -c 'rm -rf /data/documents/* && tar -x -C /data/documents' < /root/restauration/jeff/documents.tar
   ```

6. Redémarrer : `docker compose up -d`, puis `curl -s http://127.0.0.1:8020/sante`.
7. Effacer la copie déchiffrée : `rm -rf /root/restauration`.
