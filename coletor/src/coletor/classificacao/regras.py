"""Casamento de termos por palavra inteira sobre texto normalizado (minúsculas, sem acento)."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from coletor.config import resolver_caminho
from coletor.texto import normalizar

PASTA_CONFIG = "config"


class RegrasInvalidas(Exception):
    pass


def carregar_yaml(nome_arquivo: str) -> dict[str, Any]:
    """Lê um arquivo de config/ (na raiz do repositório). Erro de formato é falha de configuração: sobe alto."""
    caminho: Path = resolver_caminho(f"{PASTA_CONFIG}/{nome_arquivo}")
    try:
        dados = yaml.safe_load(caminho.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as erro:
        raise RegrasInvalidas(f"não foi possível ler {caminho}: {erro}") from erro
    if not isinstance(dados, dict):
        raise RegrasInvalidas(f"{caminho}: esperado um mapeamento no topo do arquivo")
    return dados


@dataclass(frozen=True)
class Termos:
    """Lista de termos já normalizados, compilada numa expressão só.

    Palavra inteira: "ti" casa com "área de ti", mas não com "ativo"; hífen conta como separador ("guarda-parque"
    casa com "guarda parque" porque os dois lados são normalizados do mesmo jeito).
    """

    termos: tuple[str, ...]
    _padrao: re.Pattern[str] | None

    @classmethod
    def de(cls, termos: Iterable[Any]) -> Termos:
        normalizados = sorted({_normalizar_termo(str(t)) for t in termos if str(t).strip()}, key=len, reverse=True)
        if not normalizados:
            return cls((), None)
        alternativas = "|".join(re.escape(t) for t in normalizados)
        return cls(tuple(normalizados), re.compile(rf"(?<![a-z0-9])(?:{alternativas})(?![a-z0-9])"))

    def maior(self, texto_normalizado: str) -> str | None:
        """O termo mais longo presente no texto (mais específico), ou None."""
        if self._padrao is None:
            return None
        achados = [m.group(0) for m in self._padrao.finditer(texto_normalizado)]
        return max(achados, key=len) if achados else None

    def presente(self, texto_normalizado: str) -> bool:
        return self._padrao is not None and self._padrao.search(texto_normalizado) is not None


def _normalizar_termo(termo: str) -> str:
    return normalizar(termo).replace("-", " ")


def preparar(texto: str | None) -> str:
    """Mesma normalização dos termos: hífens e travessões viram espaço (TI–Banco de Dados)."""
    return re.sub(r"\s+", " ", normalizar(texto or "").replace("-", " ")).strip()
