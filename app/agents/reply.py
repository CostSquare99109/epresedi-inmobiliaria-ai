"""Respuesta del agente: contrato único entre el loop LLM-first y el pipeline determinista."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.agents.intents import Intent


@dataclass
class AgentReply:
    text: str
    intent: Intent = Intent.UNKNOWN
    actions: list[tuple] = field(default_factory=list)  # (action, payload)
    images: list[str] = field(default_factory=list)     # file paths to send
    error: str | None = None