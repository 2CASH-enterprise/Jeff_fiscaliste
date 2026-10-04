"""Réponse de Jeff : un texte et, éventuellement, des boutons de choix (valeur, libellé)."""
from dataclasses import dataclass, field


@dataclass
class Reponse:
    texte: str
    choix: list[tuple[str, str]] = field(default_factory=list)
    # Rappels remis avant la réponse (lot 7), chacun dans sa propre bulle.
    rappels: list[str] = field(default_factory=list)
