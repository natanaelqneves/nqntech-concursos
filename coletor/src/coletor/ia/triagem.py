"""Filtro barato antes de qualquer chamada de IA: o documento parece um edital de abertura?"""

from __future__ import annotations

import re
from dataclasses import dataclass

from coletor.texto import normalizar

_INICIO = 6000  # primeiras páginas (~2 a 3 no texto do PDF)
_TITULO = 700

# No título (topo do documento), estes termos indicam publicação de andamento, não edital de abertura.
_NAO_E_ABERTURA = re.compile(
    r"\b(gabarito|resultado|convocacao|homologacao|classificacao final|comunicado|aviso de|errata|"
    r"extrato de retificacao|relacao de|lista de)\b"
)
# Retificação só vale se o documento traz o edital inteiro ("consolidado", "retificado").
_RETIFICACAO = re.compile(r"\bretificacao\b")
_CONSOLIDADO = re.compile(r"\b(consolidad[oa]|retificad[oa] e consolidad|texto integral)\b")
_SINAIS_ABERTURA = (
    re.compile(r"torna(?:m)? public[oa]s? (?:a )?(?:abertura|realizacao|o edital)"),
    re.compile(r"abertura (?:das )?inscric"),
    re.compile(r"edital (?:de abertura|n[ºo°.]*\s*\d)"),
    re.compile(r"\b(?:concurso publico|processo seletivo|selecao publica)\b"),
)
_SINAIS_CONTEUDO = (
    re.compile(r"\binscric(?:ao|oes)\b"),
    re.compile(r"\bvagas?\b"),
    re.compile(r"\b(?:remuneracao|vencimento|salario)\b"),
    re.compile(r"\btaxa de inscricao\b"),
)


@dataclass(frozen=True)
class Triagem:
    valido: bool
    motivo: str


def triar(texto: str) -> Triagem:
    inicio = normalizar(texto[:_INICIO])
    if len(inicio) < 400:
        return Triagem(False, "texto curto demais (PDF escaneado ou vazio)")
    titulo = inicio[:_TITULO]
    if termo := _NAO_E_ABERTURA.search(titulo):
        return Triagem(False, f"publicação de andamento ({termo.group(1)})")
    if _RETIFICACAO.search(titulo) and not _CONSOLIDADO.search(titulo):
        return Triagem(False, "retificação parcial (não traz o edital inteiro)")
    abertura = sum(bool(p.search(inicio)) for p in _SINAIS_ABERTURA)
    conteudo = sum(bool(p.search(inicio)) for p in _SINAIS_CONTEUDO)
    if abertura >= 1 and conteudo >= 2:
        return Triagem(True, f"edital de abertura ({abertura} sinais de abertura, {conteudo} de conteúdo)")
    return Triagem(False, f"poucos sinais de edital de abertura ({abertura}/{conteudo})")
