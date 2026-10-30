"""Concursos com destaque próprio na tela inicial: hoje, o CNU (config/destaques.yml)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from coletor.classificacao.regras import RegrasInvalidas, carregar_yaml
from coletor.texto import normalizar


class DetectorCNU:
    def __init__(self, padroes: tuple[re.Pattern[str], ...]) -> None:
        self._padroes = padroes

    @classmethod
    def padrao(cls) -> DetectorCNU:
        return cls.de_dados(carregar_yaml("destaques.yml"))

    @classmethod
    def de_dados(cls, dados: Mapping[str, Any]) -> DetectorCNU:
        padroes = dados.get("cnu")
        if not isinstance(padroes, list) or not padroes:
            raise RegrasInvalidas("destaques.yml: lista 'cnu' ausente ou vazia")
        try:
            return cls(tuple(re.compile(str(p)) for p in padroes))
        except re.error as erro:
            raise RegrasInvalidas(f"destaques.yml: expressão inválida: {erro}") from erro

    def eh_cnu(self, titulo: str, link_oficial: str | None = None) -> bool:
        caminho = urlsplit(link_oficial).path.replace("/", " ") if link_oficial else ""
        texto = normalizar(f"{titulo} {caminho}")
        return any(p.search(texto) for p in self._padroes)
