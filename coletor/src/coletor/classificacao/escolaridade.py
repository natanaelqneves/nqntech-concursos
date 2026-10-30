"""Escolaridade do cargo quando a fonte não a informou (regras conservadoras em config/escolaridade.yml)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from coletor.classificacao.regras import RegrasInvalidas, Termos, carregar_yaml, preparar

# Só a menção explícita ao nível conta. "Técnico Judiciário" não diz nada sobre escolaridade (hoje é superior).
_EXPLICITA = re.compile(r"\b(?:nivel|ensino|escolaridade)\s+(superior|medio|tecnico|fundamental)\b")
_CODIGOS = {"superior": "SUPERIOR", "medio": "MEDIO", "tecnico": "TECNICO", "fundamental": "FUNDAMENTAL"}


class InferidorEscolaridade:
    def __init__(self, superior: Termos) -> None:
        self._superior = superior

    @classmethod
    def padrao(cls) -> InferidorEscolaridade:
        return cls.de_dados(carregar_yaml("escolaridade.yml"))

    @classmethod
    def de_dados(cls, dados: Mapping[str, Any]) -> InferidorEscolaridade:
        superior = dados.get("superior")
        if not isinstance(superior, list) or not superior:
            raise RegrasInvalidas("escolaridade.yml: lista 'superior' ausente ou vazia")
        return cls(Termos.de(superior))

    def inferir(self, nome: str, especialidade: str | None = None) -> str | None:
        texto = preparar(f"{nome} {especialidade or ''}")
        if explicita := _EXPLICITA.search(texto):
            return _CODIGOS[explicita.group(1)]
        if self._superior.presente(texto):
            return "SUPERIOR"
        return None
