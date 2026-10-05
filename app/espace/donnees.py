"""Données affichées par le coffre fiscal (lot 12) : accueil et fiche de l'entreprise.

Mêmes calculs que la conversation (« Voir mes échéances », « Mon entreprise ») : le coffre
n'invente rien, il présente autrement ce que Jeff sait déjà.
"""
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calendrier.dates import MOIS, formater_date, mois_suivant, prochaine_echeance
from app.conversation import messages_fixes as mf
from app.conversation import onboarding
from app.conversation.echeances import PONCTUELLE, avertissement
from app.conversation.models import CANAL_WHATSAPP, Conversation
from app.conversation.profil import donnees_depuis_entreprise
from app.core.temps import aujourd_hui
from app.entreprises.models import Entreprise
from app.referentiel.models import Juridiction
from app.rappels.preparation import PALIERS, date_prevue
from app.regles.conditions import INCERTAIN, PRESENCE
from app.regles.models import A_VALIDER, ALERTE, FISCAL, OBLIGATION, PERIODICITES, SOCIAL, Regle
from app.regles.moteur import evaluer_entreprise, profil_de

A_VENIR_MAX = 4
MOIS_COURTS = ("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc.")
CHIFFRES_VISIBLES = 4  # Numéro WhatsApp : seuls les derniers chiffres sont montrés.


@dataclass
class Echeance:
    titre: str
    periode: str
    date_limite: date
    date_texte: str
    mois_court: str
    jours: int
    alerte: str | None


@dataclass
class Tableau:
    prochaine: Echeance | None
    a_venir: list[Echeance] = field(default_factory=list)
    a_confirmer: list[str] = field(default_factory=list)
    sans_date: list[str] = field(default_factory=list)
    nombre_obligations: int = 0
    a_valider: bool = False


def ce_jour(session: Session, entreprise: Entreprise) -> date:
    return aujourd_hui(session.get(Juridiction, entreprise.juridiction_code).fuseau_horaire)


def tableau(session: Session, entreprise: Entreprise, jour: date | None = None) -> Tableau:
    jour = jour or ce_jour(session, entreprise)
    resultats = [r for r in evaluer_entreprise(session, entreprise, jour) if r.regle.type == OBLIGATION]
    certaines = [r.regle for r in resultats if r.applicabilite != INCERTAIN]
    datees = []
    for regle in certaines:
        if regle.echeance_calcul:
            echeance = prochaine_echeance(regle.echeance_calcul, jour)
            datees.append(Echeance(
                titre=regle.titre,
                periode=echeance.periode,
                date_limite=echeance.date_limite,
                date_texte=formater_date(echeance.date_limite),
                mois_court=MOIS_COURTS[echeance.date_limite.month - 1],
                jours=(echeance.date_limite - jour).days,
                alerte=avertissement(echeance.date_limite),
            ))
    datees.sort(key=lambda e: (e.date_limite, e.titre))
    return Tableau(
        prochaine=datees[0] if datees else None,
        a_venir=datees[1:1 + A_VENIR_MAX],
        a_confirmer=[r.regle.titre for r in resultats if r.applicabilite == INCERTAIN],
        sans_date=[r.titre for r in certaines if not r.echeance_calcul and r.periodicite != PONCTUELLE],
        nombre_obligations=len(resultats),
        a_valider=any(r.regle.statut == A_VALIDER for r in resultats),
    )


@dataclass
class Fiche:
    lignes: list[tuple[str, str, bool]]  # libellé, valeur, verrouillée
    email: str | None
    whatsapp: list[tuple[str, str, bool]]  # identifiant de la conversation, numéro masqué, rappels actifs
    rappels_email: bool = True


def masquer(numero: str) -> str:
    return "•••• " + numero[-CHIFFRES_VISIBLES:]


def valeur_affichee(cle: str, valeur) -> str:
    """Comme dans la conversation ; une information jamais donnée s'affiche « À compléter »."""
    return mf.A_COMPLETER if valeur is None else onboarding.afficher(cle, valeur)


def fiche(session: Session, entreprise: Entreprise) -> Fiche:
    donnees = donnees_depuis_entreprise(entreprise)
    lignes = [
        (e.libelle, valeur_affichee(e.cle, donnees.get(e.cle)), e.cle == "niu")
        for e in onboarding.etapes_visibles(donnees)
        if e.cle != "email"
    ]
    conversations = session.scalars(
        select(Conversation)
        .where(Conversation.entreprise_id == entreprise.id, Conversation.canal == CANAL_WHATSAPP)
        .order_by(Conversation.cree_le)
    )
    return Fiche(
        lignes=lignes,
        email=entreprise.email,
        whatsapp=[(str(c.id), masquer(c.identifiant_externe), c.rappels_whatsapp) for c in conversations],
        rappels_email=entreprise.rappels_email,
    )


# --- Échéances mois par mois (lot 13) -------------------------------------------------------------

HORIZON = 12  # Mois en cours et les 11 suivants.
MENSUELLE = "mensuelle"


@dataclass
class EcheanceDuMois:
    code: str
    titre: str
    domaine: str
    periode: str
    date_limite: date
    date_texte: str
    mois_court: str
    jours: int
    alerte: str | None
    rappels: list[tuple[int, str]]  # palier, date du rappel ; seulement ceux encore à venir


@dataclass
class Mois:
    cle: str  # « 2026-10 »
    libelle: str  # « octobre 2026 »
    datees: list[EcheanceDuMois]
    a_confirmer: list[tuple[str, str, str]]  # code, titre, domaine : mensuelles sans date connue
    precedent: str | None
    suivant: str | None
    sans_date: list[tuple[str, str, str]] = field(default_factory=list)  # trimestrielles et annuelles sans date
    incertaines: int = 0
    a_valider: bool = False


def cle_mois(annee: int, mois: int) -> str:
    return f"{annee:04d}-{mois:02d}"


def mois_possibles(jour: date) -> list[tuple[int, int]]:
    annee, mois, liste = jour.year, jour.month, []
    for _ in range(HORIZON):
        liste.append((annee, mois))
        annee, mois = mois_suivant(annee, mois)
    return liste


def echeance_dans_le_mois(regle: Regle, annee: int, mois: int, jour: date) -> EcheanceDuMois | None:
    """Chaque forme d'échéance tombe au plus une fois par mois : la première à partir du 1er."""
    echeance = prochaine_echeance(regle.echeance_calcul, date(annee, mois, 1))
    if (echeance.date_limite.year, echeance.date_limite.month) != (annee, mois):
        return None
    rappels = []
    for palier in sorted(PALIERS, reverse=True):
        prevue = date_prevue(echeance.date_limite, palier)
        if prevue >= jour:
            rappels.append((palier, formater_date(prevue)))
    return EcheanceDuMois(
        code=regle.code,
        titre=regle.titre,
        domaine=regle.domaine,
        periode=echeance.periode,
        date_limite=echeance.date_limite,
        date_texte=formater_date(echeance.date_limite),
        mois_court=MOIS_COURTS[echeance.date_limite.month - 1],
        jours=(echeance.date_limite - jour).days,
        alerte=avertissement(echeance.date_limite),
        rappels=rappels,
    )


def mois_affiche(session: Session, entreprise: Entreprise, cle: str | None, jour: date | None = None) -> Mois:
    jour = jour or ce_jour(session, entreprise)
    possibles = mois_possibles(jour)
    cles = [cle_mois(a, m) for a, m in possibles]
    position = cles.index(cle) if cle in cles else 0
    annee, mois = possibles[position]

    resultats = [r for r in evaluer_entreprise(session, entreprise, jour) if r.regle.type == OBLIGATION]
    certaines = [r.regle for r in resultats if r.applicabilite != INCERTAIN]
    datees = [e for e in (echeance_dans_le_mois(r, annee, mois, jour) for r in certaines if r.echeance_calcul) if e]
    datees.sort(key=lambda e: (e.date_limite, e.titre))
    sans_calcul = [r for r in certaines if not r.echeance_calcul]
    return Mois(
        cle=cles[position],
        libelle=f"{MOIS[mois - 1]} {annee}",
        datees=datees,
        a_confirmer=[(r.code, r.titre, r.domaine) for r in sans_calcul if r.periodicite == MENSUELLE],
        sans_date=[
            (r.code, r.titre, r.domaine) for r in sans_calcul if r.periodicite not in (MENSUELLE, PONCTUELLE)
        ],
        precedent=cles[position - 1] if position > 0 else None,
        suivant=cles[position + 1] if position + 1 < len(cles) else None,
        incertaines=sum(1 for r in resultats if r.applicabilite == INCERTAIN),
        a_valider=any(r.regle.statut == A_VALIDER for r in resultats),
    )


# --- Obligations (lot 13) -------------------------------------------------------------------------

FISCALES = "fiscales"
SOCIALES = "sociales"
A_CONFIRMER = "a_confirmer"
FILTRES = (FISCALES, SOCIALES, A_CONFIRMER)
FILTRE_DU_DOMAINE = {FISCAL: FISCALES, SOCIAL: SOCIALES}


@dataclass
class Obligation:
    code: str
    titre: str
    description: str
    domaine: str
    frequence: str | None
    echeance: str | None
    prochaine: str | None
    source_texte: str | None
    source_article: str | None
    source_url: str | None
    a_valider: bool
    incertaine: bool
    raisons: list[str]
    manquants: list[str]


@dataclass
class Obligations:
    fiscales: list[Obligation]
    sociales: list[Obligation]
    a_confirmer: list[Obligation]
    alertes: list[Obligation]

    def liste(self, filtre: str) -> list[Obligation]:
        return {FISCALES: self.fiscales, SOCIALES: self.sociales, A_CONFIRMER: self.a_confirmer}[filtre]


def feuilles(condition: dict) -> list[dict]:
    """Comparaisons d'une condition, dans l'ordre d'écriture."""
    for cle in ("tous", "un_parmi"):
        if cle in condition:
            return [f for sous in condition[cle] for f in feuilles(sous)]
    if "non" in condition:
        return feuilles(condition["non"])
    if "champ" in condition:
        return [condition]
    return []


def raisons(regle: Regle, entreprise: Entreprise) -> tuple[list[str], list[str]]:
    """Ce que Jeff a lu dans le profil pour cette règle, et ce qui lui manque encore."""
    from app.espace import textes as tx

    profil = profil_de(entreprise)
    donnees = donnees_depuis_entreprise(entreprise)
    lues, manquantes, vus = [], [], set()
    for feuille in feuilles(regle.condition):
        champ = feuille["champ"]
        if champ in vus:
            continue
        vus.add(champ)
        libelle = onboarding.PAR_CLE[champ].libelle
        if profil.get(champ) is None and feuille["op"] not in PRESENCE:
            manquantes.append(libelle)
        else:
            lues.append(f"{libelle} : {valeur_affichee(champ, donnees.get(champ))}")
    if not lues and not manquantes:
        lues.append(tx.TOUTES_LES_ENTREPRISES)
    return lues, manquantes


def source_sure(url: str | None) -> str | None:
    return url if url and url.startswith("https://") else None


def obligation(regle: Regle, applicabilite: str, entreprise: Entreprise, jour: date) -> Obligation:
    lues, manquantes = raisons(regle, entreprise)
    prochaine = None
    if regle.echeance_calcul and applicabilite != INCERTAIN:
        prochaine = formater_date(prochaine_echeance(regle.echeance_calcul, jour).date_limite)
    return Obligation(
        code=regle.code,
        titre=regle.titre,
        description=regle.description,
        domaine=regle.domaine,
        frequence=PERIODICITES.get(regle.periodicite) if regle.periodicite else None,
        echeance=regle.echeance,
        prochaine=prochaine,
        source_texte=regle.source_texte,
        source_article=regle.source_article,
        source_url=source_sure(regle.source_url),
        a_valider=regle.statut == A_VALIDER,
        incertaine=applicabilite == INCERTAIN,
        raisons=lues,
        manquants=manquantes,
    )


def obligations(session: Session, entreprise: Entreprise, jour: date | None = None) -> Obligations:
    jour = jour or ce_jour(session, entreprise)
    resultats = evaluer_entreprise(session, entreprise, jour)
    fiches = [(r.regle, obligation(r.regle, r.applicabilite, entreprise, jour)) for r in resultats]
    certaines = [(regle, o) for regle, o in fiches if regle.type == OBLIGATION and not o.incertaine]
    return Obligations(
        fiscales=[o for regle, o in certaines if regle.domaine == FISCAL],
        sociales=[o for regle, o in certaines if regle.domaine == SOCIAL],
        a_confirmer=[o for regle, o in fiches if regle.type == OBLIGATION and o.incertaine],
        alertes=[o for regle, o in fiches if regle.type == ALERTE and not o.incertaine],
    )


# --- Historique des modifications (lot 14) --------------------------------------------------------

HISTORIQUE_MAX = 50


@dataclass
class Changement:
    quand: str  # « lundi 5 octobre 2026 à 18 h 40 », heure de la juridiction
    libelle: str
    avant: str
    apres: str
    origine: str


def libelle_du_champ(champ: str) -> str:
    from app.espace import textes as tx

    if champ in onboarding.PAR_CLE:
        return onboarding.PAR_CLE[champ].libelle
    return {**tx.CHAMPS_PREFERENCES, **tx.CHAMPS_DOCUMENTS}.get(champ, champ)


def valeur_historique(champ: str, valeur) -> str:
    """Valeur telle qu'enregistrée en base, affichée comme dans le profil."""
    from app.espace import textes as tx

    if champ in tx.CHAMPS_PREFERENCES:
        return tx.ACTIFS if valeur else tx.ARRETES
    if champ in tx.CHAMPS_DOCUMENTS:
        if not isinstance(valeur, dict):
            return tx.AUCUN
        annee, mois = (int(x) for x in valeur["mois"].split("-"))
        return tx.DOCUMENT_DECRIT.format(
            nom=valeur["nom"], type=dict(tx.TYPES_DOCUMENT).get(valeur["type"], valeur["type"]),
            mois=libelle_mois(date(annee, mois, 1)),
        )
    if champ == "assujetti_tva_declare":
        valeur = "inconnu" if valeur is None else ("oui" if valeur else "non")
    return valeur_affichee(champ, valeur)


def origine_du_changement(modification, canaux: dict) -> str:
    from app.entreprises.models import COFFRE
    from app.espace import textes as tx

    if modification.origine == COFFRE:
        return tx.ORIGINE_COFFRE
    canal = canaux.get(modification.conversation_id)
    if canal == CANAL_WHATSAPP:
        return tx.ORIGINE_WHATSAPP
    return tx.ORIGINE_CONVERSATION if canal else tx.ORIGINE_INCONNUE


def quand(instant, fuseau: str) -> str:
    from zoneinfo import ZoneInfo

    local = instant.astimezone(ZoneInfo(fuseau))
    return f"{formater_date(local.date())} à {local.hour} h {local.minute:02d}"


def historique(session: Session, entreprise: Entreprise) -> list[Changement]:
    from app.entreprises.models import ModificationEntreprise
    from app.espace import textes as tx

    modifications = list(session.scalars(
        select(ModificationEntreprise)
        .where(ModificationEntreprise.entreprise_id == entreprise.id)
        .order_by(ModificationEntreprise.cree_le.desc(), ModificationEntreprise.id.desc())
        .limit(HISTORIQUE_MAX)
    ))
    identifiants = {m.conversation_id for m in modifications if m.conversation_id}
    conversations = {
        c.id: c for c in session.scalars(select(Conversation).where(Conversation.id.in_(identifiants)))
    } if identifiants else {}
    canaux = {i: c.canal for i, c in conversations.items()}
    fuseau = session.get(Juridiction, entreprise.juridiction_code).fuseau_horaire
    changements = []
    for m in modifications:
        libelle = libelle_du_champ(m.champ)
        conversation = conversations.get(m.conversation_id)
        if m.champ == "rappels_whatsapp" and conversation is not None:
            libelle = tx.LIBELLE_RAPPELS_NUMERO.format(numero=masquer(conversation.identifiant_externe))
        changements.append(Changement(
            quand=quand(m.cree_le, fuseau),
            libelle=libelle,
            avant=valeur_historique(m.champ, m.ancienne_valeur),
            apres=valeur_historique(m.champ, m.nouvelle_valeur),
            origine=origine_du_changement(m, canaux),
        ))
    return changements


# --- Documents (lot 15) ---------------------------------------------------------------------------

MOIS_EN_ARRIERE = 24  # Un document peut être classé jusqu'à deux ans en arrière.


@dataclass
class LigneDocument:
    id: str
    nom: str
    type_document: str
    type_libelle: str
    format: str
    taille: str
    depose: str
    mois_cle: str


@dataclass
class GroupeDeMois:
    cle: str
    libelle: str
    documents: list[LigneDocument]


@dataclass
class Documents:
    groupes: list[GroupeDeMois]
    compteurs: dict[str, int]
    total: int
    utilise: str
    quota: str
    pourcentage: int
    filtre: str
    mois_choisissables: list[tuple[str, str]]
    mois_defaut: str


def taille_lisible(octets: int) -> str:
    if octets < 1024 * 1024:
        return f"{max(1, -(-octets // 1024))} Ko"
    return f"{octets / (1024 * 1024):.1f} Mo".replace(".", ",")


def libelle_mois(jour: date) -> str:
    return f"{MOIS[jour.month - 1]} {jour.year}"


def mois_choisissables(jour: date) -> list[tuple[str, str]]:
    """Du mois en cours à 24 mois en arrière, le plus récent d'abord."""
    from app.calendrier.dates import mois_precedent

    annee, mois, liste = jour.year, jour.month, []
    for _ in range(MOIS_EN_ARRIERE + 1):
        liste.append((cle_mois(annee, mois), libelle_mois(date(annee, mois, 1))))
        annee, mois = mois_precedent(annee, mois)
    return liste


def lire_mois(cle: str, jour: date) -> date | None:
    if cle not in {c for c, _ in mois_choisissables(jour)}:
        return None
    annee, mois = cle.split("-")
    return date(int(annee), int(mois), 1)


def documents(session: Session, entreprise: Entreprise, filtre: str = "", jour: date | None = None) -> Documents:
    from app.documents.models import TYPES, Document
    from app.documents.stockage import QUOTA, utilise
    from app.espace import textes as tx

    jour = jour or ce_jour(session, entreprise)
    fuseau = session.get(Juridiction, entreprise.juridiction_code).fuseau_horaire
    tous = list(session.scalars(
        select(Document).where(Document.entreprise_id == entreprise.id)
        .order_by(Document.mois.desc(), Document.depose_le.desc(), Document.nom)
    ))
    compteurs = {t: sum(1 for d in tous if d.type_document == t) for t in TYPES}
    filtre = filtre if filtre in TYPES else ""
    groupes: list[GroupeDeMois] = []
    for d in tous:
        if filtre and d.type_document != filtre:
            continue
        cle = d.mois.strftime("%Y-%m")
        if not groupes or groupes[-1].cle != cle:
            groupes.append(GroupeDeMois(cle, libelle_mois(d.mois), []))
        groupes[-1].documents.append(LigneDocument(
            id=str(d.id),
            nom=d.nom,
            type_document=d.type_document,
            type_libelle=dict(tx.TYPES_DOCUMENT)[d.type_document],
            format=d.format,
            taille=taille_lisible(d.taille),
            depose=quand(d.depose_le, fuseau),
            mois_cle=cle,
        ))
    octets = utilise(session, entreprise.id)
    return Documents(
        groupes=groupes,
        compteurs=compteurs,
        total=len(tous),
        utilise=taille_lisible(octets) if octets else "0 Mo",
        quota=taille_lisible(QUOTA),
        pourcentage=min(100, round(100 * octets / QUOTA)),
        filtre=filtre,
        mois_choisissables=mois_choisissables(jour),
        mois_defaut=cle_mois(jour.year, jour.month),
    )
