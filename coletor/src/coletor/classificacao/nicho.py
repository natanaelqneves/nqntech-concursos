"""Categoria do órgão no nicho do site (config/nicho.yml): tribunais, contas, fisco, segurança, militares etc."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from coletor.classificacao.regras import RegrasInvalidas, carregar_yaml
from coletor.texto import UFS, normalizar

CATEGORIA_CNU = "unificado"
MODOS = frozenset({"exclusivo", "destaque"})
_UFS = "(?:" + "|".join(sorted(sigla.lower() for sigla in UFS.values())) + ")"


@dataclass(frozen=True)
class ClassificadorNicho:
    modo: str
    categorias: tuple[tuple[str, re.Pattern[str]], ...]

    @classmethod
    def padrao(cls) -> ClassificadorNicho:
        return cls.de_dados(carregar_yaml("nicho.yml"))

    @classmethod
    def de_dados(cls, dados: Mapping[str, Any]) -> ClassificadorNicho:
        modo = dados.get("modo")
        if modo not in MODOS:
            raise RegrasInvalidas(f"nicho.yml: modo deve ser um de {sorted(MODOS)}, veio {modo!r}")
        bruto = dados.get("categorias")
        if not isinstance(bruto, Mapping) or not bruto:
            raise RegrasInvalidas("nicho.yml: mapa 'categorias' ausente ou vazio")
        categorias: list[tuple[str, re.Pattern[str]]] = []
        for codigo, padroes in bruto.items():
            if not isinstance(padroes, list) or not padroes:
                raise RegrasInvalidas(f"nicho.yml: categoria {codigo!r} sem padrões")
            try:
                juntos = "|".join(f"(?:{str(p).replace('{uf}', _UFS)})" for p in padroes)
                categorias.append((str(codigo), re.compile(juntos)))
            except re.error as erro:
                raise RegrasInvalidas(f"nicho.yml: expressão inválida em {codigo!r}: {erro}") from erro
        return cls(modo, tuple(categorias))

    @property
    def exclusivo(self) -> bool:
        return self.modo == "exclusivo"

    def categoria(self, *textos: str | None, unificado: bool = False) -> str | None:
        """Primeira categoria cujo padrão aparece no órgão/título; None = fora do nicho."""
        if unificado:
            return CATEGORIA_CNU
        texto = normalizar(" ".join(t for t in textos if t))
        if not texto:
            return None
        return next((codigo for codigo, padrao in self.categorias if padrao.search(texto)), None)
