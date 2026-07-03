"""Paquete del bot de reglas (RAG)."""

from __future__ import annotations

# Import necesario para que discover_bots() (que importa el subpaquete) registre
# la subclase RulesBot.
from rpg_scribe.bots.rules.bot import RulesBot

__all__ = ["RulesBot"]
