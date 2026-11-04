"""Conferência do pré-cadastro (busca na web) com o edital lido: o edital sempre vence; a busca só preenche o que o
edital não trouxe, e cada campo preenchido assim ganha o aviso "confira o edital". Divergências são registradas no
log (o valor do edital fica)."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import replace
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from coletor.extratores.base import CargoExtraido, EditalExtraido

log = logging.getLogger(__name__)

# Avisos de lacuna do extrator que deixam de valer quando a busca preenche o campo.
_LACUNAS = {
    "inscricao_fim": "período de inscrição não encontrado",
    "data_prova": "data da prova não encontrada",
    "taxa_max": "taxa de inscrição não encontrada",
    "cargos": "quadro de cargos/vagas não encontrado",
}
_NOMES = {
    "inscricao_inicio": "início das inscrições",
    "inscricao_fim": "fim das inscrições",
    "data_prova": "data da prova",
    "taxa_max": "taxa de inscrição",
    "cargos": "cargos",
    "isencao_fim": "prazo para pedir isenção",
}


def _data(valor: Any) -> date | None:
    try:
        return date.fromisoformat(valor) if valor else None
    except (TypeError, ValueError):
        return None


def _decimal(valor: Any) -> Decimal | None:
    try:
        return Decimal(str(valor)) if valor not in (None, "") else None
    except InvalidOperation:
        return None


def completar_com_busca(
    edital: EditalExtraido, dados: Mapping[str, Any] | None, concurso_id: int | None = None
) -> EditalExtraido:
    if not dados:
        return edital
    busca = {
        "inscricao_inicio": _data(dados.get("inscricoes_inicio")),
        "inscricao_fim": _data(dados.get("inscricoes_fim")),
        "data_prova": _data(dados.get("data_prova")),
        "taxa_max": _decimal(dados.get("taxa_max")),
        "isencao_inicio": _data(dados.get("isencao_inicio")),
        "isencao_fim": _data(dados.get("isencao_fim")),
    }
    for campo in ("inscricao_fim", "data_prova", "taxa_max"):
        lido, sugerido = getattr(edital, campo), busca[campo]
        if lido is not None and sugerido is not None and lido != sugerido:
            log.info("concurso %s: %s diverge (edital %s, busca %s); vale o edital", concurso_id, campo, lido, sugerido)

    preenchidos: list[str] = []
    mudancas: dict[str, Any] = {}
    for campo in ("inscricao_inicio", "inscricao_fim", "data_prova", "taxa_max"):
        if getattr(edital, campo) is None and busca[campo] is not None:
            mudancas[campo] = busca[campo]
            preenchidos.append(campo)
    # Prazo de isenção só se o edital prevê isenção e não deu o prazo (a busca não diz quem tem direito).
    if edital.isencoes and edital.isencao_fim is None and busca["isencao_fim"] is not None:
        mudancas["isencao_inicio"] = edital.isencao_inicio or busca["isencao_inicio"]
        mudancas["isencao_fim"] = busca["isencao_fim"]
        preenchidos.append("isencao_fim")
    nomes_cargos = [str(c) for c in dados.get("cargos") or () if c]
    if not edital.cargos and nomes_cargos:
        mudancas["cargos"] = tuple(CargoExtraido(nome=nome) for nome in nomes_cargos)
        preenchidos.append("cargos")
    for campo, valor in (("orgao", dados.get("orgao")), ("esfera", dados.get("esfera")), ("ano", dados.get("ano"))):
        if getattr(edital, campo) is None and valor:
            mudancas[campo] = valor
    if edital.uf is None and dados.get("uf") and dados.get("esfera") != "FEDERAL":
        mudancas["uf"] = dados["uf"]
    if not mudancas:
        return edital

    resolvidas = {_LACUNAS[c] for c in preenchidos if c in _LACUNAS}
    avisos = [a for a in edital.avisos if not any(a.startswith(r) for r in resolvidas)]
    if preenchidos:
        nomes = ", ".join(_NOMES[c] for c in preenchidos)
        avisos.append(f"{nomes}: informado pela busca na web, não encontrado no edital (confira o edital)")
    return replace(edital, **mudancas, avisos=tuple(dict.fromkeys(avisos)))
