"""Deduplicação entre fontes: o mesmo concurso achado pela busca na web e pelo site da banca (ou por dois alvos da
busca) com páginas diferentes. A página igual já resolve sozinha (link_oficial é único); aqui entra a comparação
pelo órgão, conservadora: na dúvida (mais de um candidato) não junta e marca `possivel_duplicado`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from coletor.texto import normalizar

# Palavras que variam entre fontes sem mudar o órgão ("Prefeitura Municipal de X" = "Prefeitura de X").
_VAZIAS = frozenset({"a", "o", "de", "da", "do", "das", "dos", "e", "municipal", "municipio", "estado", "estadual"})


def chave_orgao(nome: str | None) -> str:
    palavras = re.sub(r"[^a-z0-9 ]", " ", normalizar(nome or "")).split()
    return " ".join(p for p in palavras if p not in _VAZIAS)


@dataclass(frozen=True)
class Candidato:
    id: int
    orgao: str | None
    uf: str | None
    banca_id: int | None
    ano: int | None
    so_busca: bool

    @classmethod
    def da_linha(cls, linha: Mapping[str, Any]) -> Candidato:
        return cls(linha["id"], linha["orgao"], linha["uf"], linha["banca_id"], linha["ano"], bool(linha["so_busca"]))


@dataclass(frozen=True)
class Equivalencia:
    concurso_id: int | None
    ambiguo: bool = False


def _compativel(a: object, b: object) -> bool:
    return a is None or b is None or a == b


def procurar_equivalente(
    orgao: str | None,
    uf: str | None,
    banca_id: int | None,
    ano: int | None,
    candidatos: Iterable[Candidato],
    somente_busca: bool = False,
    ignorar: int | None = None,
) -> Equivalencia:
    """Mesmo órgão (chave normalizada), UF, banca e ano compatíveis (nulo combina com tudo).

    `somente_busca`: só pré-cadastros vindos da busca (quando quem procura é uma fonte de banca, que é a referência).
    """
    chave = chave_orgao(orgao)
    if len(chave) < 4:  # nome curto demais ("TJ", "PM") junta concursos diferentes
        return Equivalencia(None)
    achados = [
        c
        for c in candidatos
        if c.id != ignorar
        and (c.so_busca or not somente_busca)
        and chave_orgao(c.orgao) == chave
        and _compativel(c.uf, uf)
        and _compativel(c.banca_id, banca_id)
        and _compativel(c.ano, ano)
    ]
    if len(achados) == 1:
        return Equivalencia(achados[0].id)
    return Equivalencia(None, ambiguo=len(achados) > 1)
