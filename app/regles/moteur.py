"""Moteur de règles : à partir du profil, les obligations et alertes qui s'appliquent à une date."""
from dataclasses import dataclass
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.entreprises.models import Entreprise
from app.regles.conditions import NON, evaluer
from app.regles.models import OBLIGATION, STATUTS_VISIBLES, Regle

INCONNU = "inconnu"


@dataclass
class Resultat:
    regle: Regle
    applicabilite: str  # oui ou incertain


def profil_de(entreprise: Entreprise) -> dict:
    """Le profil déclaré, avec « je ne sais pas » traduit en valeur absente."""
    regime = entreprise.regime_declare
    return {
        "forme_juridique": entreprise.forme_juridique,
        "secteur": entreprise.secteur,
        "chiffre_affaires_annuel": entreprise.chiffre_affaires_annuel,
        "regime_declare": None if regime == INCONNU else regime,
        "assujetti_tva_declare": entreprise.assujetti_tva_declare,
        "nombre_salaries": entreprise.nombre_salaries,
        "numero_employeur_cnps": entreprise.numero_employeur_cnps,
    }


def regles_en_vigueur(session: Session, juridiction: str, jour: date) -> list[Regle]:
    """Dernière version visible de chaque règle, applicable au jour donné."""
    regles = session.scalars(
        select(Regle).where(
            Regle.juridiction_code == juridiction,
            Regle.statut.in_(STATUTS_VISIBLES),
            Regle.applicable_du <= jour,
            or_(Regle.applicable_au.is_(None), Regle.applicable_au >= jour),
        )
    )
    dernieres: dict[str, Regle] = {}
    for regle in regles:
        if regle.code not in dernieres or regle.version > dernieres[regle.code].version:
            dernieres[regle.code] = regle
    return list(dernieres.values())


def evaluer_entreprise(session: Session, entreprise: Entreprise, jour: date) -> list[Resultat]:
    profil = profil_de(entreprise)
    resultats = []
    for regle in regles_en_vigueur(session, entreprise.juridiction_code, jour):
        applicabilite = evaluer(regle.condition, profil)
        if applicabilite != NON:
            resultats.append(Resultat(regle, applicabilite))
    return sorted(
        resultats,
        key=lambda r: (r.regle.type != OBLIGATION, r.regle.ordre, r.regle.code),
    )
